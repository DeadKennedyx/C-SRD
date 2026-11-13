#include "csrd/outline.hpp"
#include "clang/AST/ASTContext.h"
#include "clang/AST/Decl.h"
#include "clang/Frontend/ASTUnit.h"
#include "clang/Tooling/Tooling.h"
#include <algorithm>
#include <iostream>
#include <stdexcept>

namespace {
void check(bool value,const std::string &why) { if (!value) throw std::runtime_error(why); }
std::unique_ptr<clang::ASTUnit> parse(std::string source) {
  if (source.empty() || source.back()!='\n') source+='\n';
  auto ast=clang::tooling::buildASTFromCodeWithArgs(source,{"-std=c11","-pedantic-errors"},"outline.c");
  check(ast && !ast->getDiagnostics().hasErrorOccurred(),"candidate must parse");return ast;
}
const clang::FunctionDecl &function(clang::ASTUnit &ast) {
  for (const auto *decl:ast.getASTContext().getTranslationUnitDecl()->decls())
    if (const auto *f=llvm::dyn_cast<clang::FunctionDecl>(decl))
      if (f->getName()=="f" && f->doesThisDeclarationHaveABody()) return *f;
  throw std::runtime_error("missing f");
}
std::string replace(std::string value,const std::string &from,const std::string &to) {
  const auto pos=value.find(from);check(pos!=std::string::npos,"mutation not found: "+from);
  value.replace(pos,from.size(),to);return value;
}
bool grade(const std::string &source,csrd::OutlineFunction outline) {
  csrd::prepareOutline({&outline});
  const auto edits=csrd::outlineEdits({&outline});auto candidate=source;
  for (auto it=edits.rbegin();it!=edits.rend();++it) candidate.replace((*it)->begin,(*it)->end-(*it)->begin,(*it)->emitted);
  auto before=parse(source),after=parse(candidate);std::string reason;
  const auto proof=csrd::validateOutline(after->getASTContext(),function(*after),outline);
  return proof.status=="proved-under-model" && csrd::outlineContextMatches(
    csrd::privateReferences(before->getASTContext(),function(*before)),
    csrd::privateReferences(after->getASTContext(),function(*after)),{&outline},reason);
}
csrd::OutlineFunction discover(const std::string &source) {
  auto ast=parse(source);return csrd::discoverOutline(ast->getASTContext(),function(*ast));
}
}
int main() {
  try {
    const std::string source="unsigned f(unsigned x,unsigned y){return (x+y)*3u+11u;}\n";
    for (const auto seed:{UINT64_C(0),UINT64_C(42),UINT64_MAX}) {
      auto outline=discover(source);check(outline.frames.size()==1,"expected one expression");
      auto &frame=outline.frames[0];std::set<std::string> reserved;
      const auto collision="csrd_outline_"+std::to_string(seed)+"_"+std::to_string(frame.begin)+"_0";
      reserved.insert(collision);csrd::emitOutline(outline,seed,reserved);
      check(frame.helper!=collision,"helper identifier collision");
      check(grade(source,outline),"valid expression rejected");
      for (const auto &mutation:std::vector<std::pair<std::string,std::string>>{
          {"3u","4u"},{"+","-"},{"static unsigned int","static int"},
          {"return ","unsigned extra=0; return "}}) {
        auto changed=outline;changed.insertion.emitted=replace(changed.insertion.emitted,mutation.first,mutation.second);
        check(!grade(source,changed),"changed helper admitted: "+mutation.first);
      }
      auto extra=outline;extra.insertion.emitted+="static unsigned extra; ";
      check(!grade(source,extra),"extra inserted declaration admitted");
      auto wrong=outline;
      const auto &first=frame.captures[frame.argumentOrder[0]].name,&second=frame.captures[frame.argumentOrder[1]].name;
      wrong.frames[0].emitted=replace(wrong.frames[0].emitted,"("+first+", "+second+")","("+second+", "+first+")");
      check(!grade(source,wrong),"wrong argument binding admitted");
      auto equivalent=outline;equivalent.insertion.emitted=replace(equivalent.insertion.emitted,"3u","03u");
      check(grade(source,equivalent),"equivalent literal spelling rejected");
    }
    for (const std::string source:{
        "typedef unsigned U;U f(U x,U y){U z=x+2u*y;{U x=z+1u;z=x*3u+7u;}return z-x+y;}\n",
        "long long f(signed char x,unsigned short y,long long z){return ((long long)x+y)*z;}\n",
        "unsigned f(unsigned x,unsigned y){return x ? y/x+1u : y*3u;}\n",
        "int f(int x,int y){return x && y/x>1;}\n",
        "unsigned char f(unsigned char x,unsigned char y){return (unsigned char)((x+y)*3);}\n",
        "unsigned f(unsigned x){unsigned a; a=x+1u; return a*3u+7u;}\n",
        "unsigned f(unsigned x){return (x\n + 2u)\n*3u;}\n"}) {
      auto outline=discover(source);check(!outline.frames.empty(),"supported type/expression rejected");
      std::set<std::string> reserved;csrd::emitOutline(outline,42,reserved);
      check(grade(source,outline),"typed substitution or surrounding binding rejected");
      for (const auto &frame:outline.frames)
        check(std::count(frame.original.begin(),frame.original.end(),'\n')==std::count(frame.emitted.begin(),frame.emitted.end(),'\n'),"line count changed");
    }
    for (const std::string source:{
        "unsigned f(unsigned c){unsigned x;return c ? x+1u :0u;}",
        "unsigned f(unsigned c){unsigned x;return c && x+1u;}",
        "unsigned f(unsigned c,unsigned x){unsigned y=0;return (y=c?x*3u+1u:0u)+(x=5u);}",
        "unsigned f(unsigned x){unsigned *p=&x;return x*3u+1u;}",
        "unsigned f(volatile unsigned x){return x*3u+1u;}",
        "unsigned f(_Atomic unsigned x){return x*3u+1u;}",
        "extern unsigned g(unsigned);unsigned f(unsigned x){return g(x)*3u+1u;}",
        "unsigned f(unsigned x){again:x++;if(x)goto again;return x*3u+1u;}",
        "unsigned f(unsigned x){return __builtin_constant_p(x)+x*3u;}"})
      check(discover(source).frames.empty(),"unsafe context/capture admitted");
    std::cout<<"PASS typed outlining, binding, capture and mutation controls\n";
  } catch (const std::exception &error) { std::cerr<<error.what()<<'\n';return 1; }
}
