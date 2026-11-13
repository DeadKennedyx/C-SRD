#include "csrd/control_regions.hpp"
#include "clang/AST/ASTContext.h"
#include "clang/AST/Decl.h"
#include "clang/Frontend/ASTUnit.h"
#include "clang/Tooling/Tooling.h"
#include <iostream>
#include <stdexcept>

namespace {
void check(bool b, const std::string &why) { if (!b) throw std::runtime_error(why); }
std::unique_ptr<clang::ASTUnit> parse(const std::string &text) {
  const auto input = text.empty() || text.back() != '\n' ? text + "\n" : text;
  auto ast = clang::tooling::buildASTFromCodeWithArgs(input, {"-std=c11", "-pedantic-errors", "-Wno-return-type"}, "control.c");
  check(ast && !ast->getDiagnostics().hasErrorOccurred(), "test candidate must parse"); return ast;
}
const clang::FunctionDecl &function(clang::ASTUnit &ast) {
  for (const auto *decl : ast.getASTContext().getTranslationUnitDecl()->decls())
    if (const auto *f = llvm::dyn_cast<clang::FunctionDecl>(decl)) if (f->getName() == "f" && f->doesThisDeclarationHaveABody()) return *f;
  throw std::runtime_error("missing test function");
}
bool grade(const std::string &original, csrd::ControlFrame frame, const std::string &body) {
  frame.emitted = body; csrd::prepareControlFrames({&frame});
  auto before = parse(original);
  auto after = parse(original.substr(0,frame.begin) + body + original.substr(frame.end));
  auto proof = csrd::validateControlFrame(after->getASTContext(), function(*after), frame);
  std::string reason;
  return proof.status == "proved-under-model" && csrd::controlContextMatches(
    csrd::privateReferences(before->getASTContext(), function(*before)),
    csrd::privateReferences(after->getASTContext(), function(*after)), {&frame}, reason);
}
std::string replace(std::string text, const std::string &from, const std::string &to) {
  const auto pos = text.find(from); check(pos != std::string::npos, "mutation site missing: " + from);
  text.replace(pos,from.size(),to); return text;
}
}
int main() {
  try {
    const std::string source = "extern void sink(unsigned); unsigned f(unsigned x,unsigned n){unsigned i=0;"
      "while(i<n){if(x&1u){x+=3u;++i;continue;}if(x==17u)break;x^=i;sink(x);++i;}"
      "do{x+=7u;n>>=1u;}while(n);return x;}\n";
    auto ast = parse(source);
    auto discovery = csrd::discoverControlRegions(ast->getASTContext(),function(*ast));
    check(discovery.frames.size()==1,"one control region expected");
    auto frame = discovery.frames.front();
    check(frame.loops==2 && frame.branches==4,"source CFG coverage");
    for (const auto seed : {UINT64_C(0), UINT64_C(42), UINT64_MAX}) {
      const auto reserved = "csrd_control_"+std::to_string(frame.begin)+"_0";
      csrd::emitControlFrame(frame,seed,"f",{reserved});
      check(frame.stateName != reserved,"identifier collision");
      check(grade(source,frame,frame.emitted),"valid emitted control graph rejected");
      check(grade(source,frame,replace(frame.emitted,"while (1)","while(01)")),"validator compared template text instead of actual C semantics");
      check(!grade(source,frame,replace(frame.emitted,"while (1)","while (0)")),"nonexecuting dispatcher admitted");
      check(!grade(source,frame,replace(frame.emitted,"x+=3u","x+=4u")),"changed effect admitted");
      check(!grade(source,frame,replace(frame.emitted,"x==17u","x!=17u")),"changed condition admitted");
      check(!grade(source,frame,replace(frame.emitted,"return x","return n")),"changed return admitted");
      const auto entry = frame.stateName+" = "+std::to_string(frame.nodes.at(unsigned(frame.entry)).state)+"UL";
      check(!grade(source,frame,replace(frame.emitted,entry,frame.stateName+" = 0UL")),"wrong entry admitted");
      bool testedEdge=false;
      for (const auto &node : frame.nodes) {
        if (node.yes < 0 || node.kind==csrd::ControlKind::Return) continue;
        const auto current=std::to_string(frame.nodes.at(unsigned(node.yes)).state);
        for (const auto &other : frame.nodes) {
          const auto alternate=std::to_string(other.state);
          if(alternate==current || alternate.size()!=current.size())continue;
          auto changed=frame.emitted;
          auto pos=changed.find("case ");
          pos=changed.find(frame.stateName+" = "+current+"UL",pos);
          if(pos==std::string::npos)continue;
          changed.replace(pos+frame.stateName.size()+3,current.size(),alternate);
          check(!grade(source,frame,changed),"wrong same-width CFG edge admitted");testedEdge=true;break;
        }
        if(testedEdge)break;
      }
      check(testedEdge,"edge corruption control did not run");
    }
    const std::string exiting="void f(unsigned x){x+=3u;sink(x);}";
    auto exitAst=parse("extern void sink(unsigned);"+exiting);
    auto exitFrames=csrd::discoverControlRegions(exitAst->getASTContext(),function(*exitAst));
    auto exitFrame=exitFrames.frames.at(0);csrd::emitControlFrame(exitFrame,42,"f",{});
    check(!grade("extern void sink(unsigned);"+exiting,exitFrame,replace(exitFrame.emitted," <= 2UL"," <= 3UL")),"wrong exit guard admitted");
    for (const auto &bad : {
        "unsigned f(unsigned x){again: x++;if(x)goto again;return x;}",
        "unsigned f(volatile unsigned *p){*p+=1u;return *p;}",
        "unsigned long f(void *p){unsigned long x=(unsigned long)p;x+=1;return x;}",
        "_Thread_local unsigned value;unsigned f(unsigned x){value+=x;return value;}",
        "extern int setjmp(void*);unsigned f(void*p){if(setjmp(p))return 1;return 0;}",
        "unsigned f(unsigned x){return __builtin_constant_p(x)+x;}"}) {
      auto tree=parse(bad);check(csrd::discoverControlRegions(tree->getASTContext(),function(*tree)).frames.empty(),"unsupported context transformed");
    }
    std::cout<<"PASS source-CFG/actual-dispatch validation, binding and mutation controls\n";
  } catch (const std::exception &e) { std::cerr<<e.what()<<'\n';return 1; }
}
