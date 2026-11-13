#include "csrd/outline.hpp"
#include "clang/AST/ASTContext.h"
#include "clang/AST/Attr.h"
#include "clang/AST/Expr.h"
#include "clang/AST/Stmt.h"
#include "clang/Basic/SourceManager.h"
#include "clang/Lex/Lexer.h"
#include <algorithm>
#include <functional>
#include <map>
#include <numeric>
#include <stdexcept>
#include <tuple>

namespace csrd {
namespace {
void walk(const clang::Stmt *s, const std::function<void(const clang::Stmt *)> &visit) {
  if (!s) return;
  visit(s);
  for (const auto *child:s->children()) walk(child,visit);
}
unsigned offset(clang::ASTContext &ctx, clang::SourceLocation loc) {
  if (loc.isInvalid() || loc.isMacroID() || !ctx.getSourceManager().isWrittenInMainFile(loc))
    throw std::invalid_argument("outlining requires rewritable main-file source");
  return ctx.getSourceManager().getFileOffset(loc);
}
unsigned endOf(clang::ASTContext &ctx, clang::SourceLocation loc) {
  return offset(ctx,clang::Lexer::getLocForEndOfToken(loc,0,ctx.getSourceManager(),ctx.getLangOpts()));
}
std::string integerType(clang::ASTContext &ctx, clang::QualType type) {
  if (type.hasQualifiers() || type->isAtomicType() || !type->isIntegerType() ||
      !type->isBuiltinType() || ctx.getTypeSize(type)>64)
    throw std::invalid_argument("outlining supports unqualified standard integer values through 64 bits");
  const auto *builtin=type->getAs<clang::BuiltinType>();
  switch (builtin->getKind()) {
  case clang::BuiltinType::Bool: case clang::BuiltinType::Char_S: case clang::BuiltinType::Char_U:
  case clang::BuiltinType::SChar: case clang::BuiltinType::UChar:
  case clang::BuiltinType::Short: case clang::BuiltinType::UShort:
  case clang::BuiltinType::Int: case clang::BuiltinType::UInt:
  case clang::BuiltinType::Long: case clang::BuiltinType::ULong:
  case clang::BuiltinType::LongLong: case clang::BuiltinType::ULongLong: break;
  default: throw std::invalid_argument("nonstandard integer type in outline expression");
  }
  return type.getCanonicalType().getAsString();
}
struct Tree { std::string signature; std::set<unsigned> required; };
class Expression {
  clang::ASTContext &ctx;
  const clang::FunctionDecl &function;
  const std::set<const clang::ValueDecl *> &escaped;
  OutlineFrame &frame;
  bool discover;
public:
  std::map<const clang::ValueDecl *,unsigned> bindings;
  std::map<unsigned,unsigned> references;
  Expression(clang::ASTContext &c,const clang::FunctionDecl &f,
             const std::set<const clang::ValueDecl *> &e,OutlineFrame &r,bool d)
    :ctx(c),function(f),escaped(e),frame(r),discover(d) {}
  Tree read(const clang::Expr *e,unsigned depth=0) {
    if (depth>128) throw std::invalid_argument("outline expression depth limit exceeded");
    if (const auto *p=llvm::dyn_cast<clang::ParenExpr>(e)) return read(p->getSubExpr(),depth+1);
    offset(ctx,e->getBeginLoc()); offset(ctx,e->getEndLoc());
    const auto type=integerType(ctx,e->getType());
    auto child=[&](const clang::Expr *x) { return read(x,depth+1); };
    auto combine=[&](std::string kind,std::vector<Tree> parts) {
      Tree tree{kind+":"+type+"(",{}};
      for (const auto &part:parts) { tree.signature+=part.signature+";";tree.required.insert(part.required.begin(),part.required.end()); }
      tree.signature+=")"; return tree;
    };
    if (const auto *literal=llvm::dyn_cast<clang::IntegerLiteral>(e)) {
      if (literal->getValue().getActiveBits()>64) throw std::invalid_argument("outline literal exceeds 64 bits");
      return {"literal:"+type+":"+std::to_string(literal->getValue().getZExtValue()),{}};
    }
    if (const auto *literal=llvm::dyn_cast<clang::CharacterLiteral>(e))
      return {"character:"+type+":"+std::to_string(unsigned(literal->getKind()))+":"+std::to_string(literal->getValue()),{}};
    if (const auto *ref=llvm::dyn_cast<clang::DeclRefExpr>(e)) {
      const auto *v=llvm::dyn_cast<clang::VarDecl>(ref->getDecl());
      if (!v || !v->hasLocalStorage() || v->getDeclContext()!=&function || v->hasAttrs() || escaped.count(v) ||
          (v->getStorageClass()!=clang::SC_None && v->getStorageClass()!=clang::SC_Register))
        throw std::invalid_argument("outline capture is not a private automatic integer object");
      integerType(ctx,v->getType());
      if (!bindings.count(v)) {
        if (!discover) throw std::invalid_argument("helper expression reads an uncaptured object");
        if (frame.captures.size()>=16) throw std::invalid_argument("outline capture limit exceeded");
        const auto id=unsigned(frame.captures.size()); bindings.emplace(v,id);
        frame.captures.push_back({v->getNameAsString(),type,"",offset(ctx,v->getLocation()),0});
      }
      const auto id=bindings.at(v);
      references.emplace(offset(ctx,ref->getLocation()),id);
      return {"reference:"+type+":"+std::to_string(id),{id}};
    }
    if (const auto *cast=llvm::dyn_cast<clang::CastExpr>(e)) {
      switch(cast->getCastKind()) {
      case clang::CK_LValueToRValue: case clang::CK_IntegralCast: case clang::CK_IntegralToBoolean: case clang::CK_NoOp: break;
      default:throw std::invalid_argument("outline cast is not an integer value conversion");
      }
      return combine(std::string("cast:")+cast->getCastKindName(),{child(cast->getSubExpr())});
    }
    if (++frame.operations>256) throw std::invalid_argument("outline operator limit exceeded");
    if (const auto *u=llvm::dyn_cast<clang::UnaryOperator>(e)) {
      if (u->getOpcode()!=clang::UO_Plus && u->getOpcode()!=clang::UO_Minus &&
          u->getOpcode()!=clang::UO_Not && u->getOpcode()!=clang::UO_LNot)
        throw std::invalid_argument("effect, address or memory operation in outline expression");
      return combine("unary:"+std::to_string(u->getOpcode()),{child(u->getSubExpr())});
    }
    if (const auto *b=llvm::dyn_cast<clang::BinaryOperator>(e)) {
      if (b->isAssignmentOp() || b->getOpcode()==clang::BO_Comma)
        throw std::invalid_argument("assignment/comma is outside outline expressions");
      auto left=child(b->getLHS()),right=child(b->getRHS());
      auto tree=combine("binary:"+std::to_string(b->getOpcode()),{left,right});
      if (b->getOpcode()==clang::BO_LAnd || b->getOpcode()==clang::BO_LOr) tree.required=left.required;
      return tree;
    }
    if (const auto *select=llvm::dyn_cast<clang::ConditionalOperator>(e)) {
      auto condition=child(select->getCond()),yes=child(select->getTrueExpr()),no=child(select->getFalseExpr());
      auto tree=combine("select",{condition,yes,no});tree.required=condition.required;
      for (const auto id:yes.required) if (no.required.count(id)) tree.required.insert(id);
      return tree;
    }
    throw std::invalid_argument("calls, memory and noninteger expressions are outline boundaries");
  }
};
unsigned mapped(unsigned position,const std::vector<const OutlineEdit *> &edits) {
  int64_t result=position;
  for (const auto *edit:edits) {
    if (edit->begin<edit->end && position>=edit->begin && position<edit->end)
      throw std::invalid_argument("declaration unexpectedly lies inside an outlined expression");
    if (position>=edit->end) result+=int64_t(edit->emitted.size())-int64_t(edit->end-edit->begin);
  }
  if (result<0 || uint64_t(result)>UINT32_MAX) throw std::invalid_argument("outline source offset overflow");
  return unsigned(result);
}
bool inside(unsigned p,const std::vector<const OutlineFunction *> &functions,bool candidate) {
  for (const auto *function:functions) for (const auto &frame:function->frames)
    if (p>=(candidate ? frame.candidateBegin:frame.begin) && p<(candidate ? frame.candidateEnd:frame.end)) return true;
  return false;
}
} // namespace

OutlineFunction discoverOutline(clang::ASTContext &ctx,const clang::FunctionDecl &f) {
  OutlineFunction result;
  for (const auto *decl:f.redecls()) if (decl->hasAttrs()) result.reason="function attributes are outside the outline contract";
  std::set<const clang::ValueDecl *> escaped;
  walk(f.getBody(),[&](const clang::Stmt *s) {
    if (llvm::isa<clang::AsmStmt,clang::GotoStmt,clang::IndirectGotoStmt,clang::SourceLocExpr>(s))
      result.reason="assembly, jumps and source-location observations are outside outlining";
    if (const auto *call=llvm::dyn_cast<clang::CallExpr>(s)) if (const auto *callee=call->getDirectCallee()) {
      const auto name=callee->getNameAsString();
      if (callee->hasAttr<clang::ReturnsTwiceAttr>() || name=="setjmp" || name=="_setjmp" || name=="sigsetjmp" ||
          name=="longjmp" || name=="siglongjmp" || name.rfind("__builtin_",0)==0)
        result.reason="nonlocal control and explicit compiler builtins are outside outlining";
    }
    if (const auto *u=llvm::dyn_cast<clang::UnaryOperator>(s)) if (u->getOpcode()==clang::UO_AddrOf)
      if (const auto *ref=llvm::dyn_cast<clang::DeclRefExpr>(u->getSubExpr()->IgnoreParenImpCasts())) escaped.insert(ref->getDecl());
  });
  if (!result.reason.empty()) return result;
  result.insertion.begin=result.insertion.end=offset(ctx,f.getBeginLoc());
  auto &sm=ctx.getSourceManager();const auto source=sm.getBufferData(sm.getMainFileID());
  // Only move assignment RHSs that are full expression statements. Capturing
  // an otherwise initialized parameter from a nested conditional assignment
  // could add an unsequenced read beside an enclosing write to that parameter.
  std::set<const clang::Stmt *> expressionStatements;
  walk(f.getBody(),[&](const clang::Stmt *s) {
    if (const auto *block=llvm::dyn_cast<clang::CompoundStmt>(s))
      for (const auto *statement:block->body()) expressionStatements.insert(statement);
  });
  walk(f.getBody(),[&](const clang::Stmt *s) {
    const clang::Expr *e=nullptr;
    if (const auto *r=llvm::dyn_cast<clang::ReturnStmt>(s)) e=r->getRetValue();
    if (const auto *d=llvm::dyn_cast<clang::DeclStmt>(s)) if (d->isSingleDecl())
      if (const auto *v=llvm::dyn_cast<clang::VarDecl>(d->getSingleDecl())) if (v->hasLocalStorage()) e=v->getInit();
    if (const auto *b=llvm::dyn_cast<clang::BinaryOperator>(s)) if (b->getOpcode()==clang::BO_Assign && expressionStatements.count(s))
      if (llvm::isa<clang::DeclRefExpr>(b->getLHS()->IgnoreParens())) e=b->getRHS();
    if (!e) return;
    try {
      OutlineFrame frame;
      frame.begin=offset(ctx,e->getBeginLoc());frame.end=endOf(ctx,e->getEndLoc());frame.type=integerType(ctx,e->getType());
      frame.line=sm.getSpellingLineNumber(e->getBeginLoc());frame.column=sm.getSpellingColumnNumber(e->getBeginLoc());
      Expression parser(ctx,f,escaped,frame,true);const auto tree=parser.read(e);
      if (frame.operations<2 || frame.captures.empty()) throw std::invalid_argument("outlining requires two operators and a captured value");
      if (result.frames.size()>=64) throw std::invalid_argument("outline region count limit exceeded");
      for (const auto &[decl,id]:parser.bindings) if (!llvm::isa<clang::ParmVarDecl>(decl) && !tree.required.count(id))
        throw std::invalid_argument("helper arguments could eagerly read a conditionally used local; initialization is not established");
      frame.signature=tree.signature;frame.original=source.substr(frame.begin,frame.end-frame.begin).str();
      clang::Lexer lexer(sm.getLocForStartOfFile(sm.getMainFileID()),ctx.getLangOpts(),source.begin(),source.begin()+frame.begin,source.end());
      clang::Token token;
      do {
        lexer.LexFromRawLexer(token);
        const auto pos=offset(ctx,token.getLocation());
        if (pos>=frame.end || token.is(clang::tok::eof)) break;
        if (token.is(clang::tok::hash)) throw std::invalid_argument("preprocessor line marker inside outline expression");
        if (!token.is(clang::tok::comment)) frame.tokens.push_back({clang::Lexer::getSpelling(token,sm,ctx.getLangOpts()),
          parser.references.count(pos) ? int(parser.references.at(pos)):-1});
      } while (!token.is(clang::tok::eof));
      result.frames.push_back(std::move(frame));
    } catch (const std::exception &error) {
      result.boundaries.push_back({sm.getSpellingLineNumber(e->getBeginLoc()),sm.getSpellingColumnNumber(e->getBeginLoc()),
        e->getStmtClassName(),error.what()});
    }
  });
  std::sort(result.frames.begin(),result.frames.end(),[](const auto &a,const auto &b){return a.begin<b.begin;});
  if (result.frames.empty()) result.reason="no eligible pure integer outline expressions";
  return result;
}

void emitOutline(OutlineFunction &function,uint64_t seed,std::set<std::string> &reserved) {
  unsigned serial=0;
  auto fresh=[&](unsigned begin) {
    std::string name;
    do {name="csrd_outline_"+std::to_string(seed)+"_"+std::to_string(begin)+"_"+std::to_string(serial++);} while (!reserved.insert(name).second);
    return name;
  };
  function.insertion.emitted.clear();
  for (auto &frame:function.frames) {
    frame.helper=fresh(frame.begin);
    for (auto &capture:frame.captures) capture.parameter=fresh(frame.begin);
    frame.argumentOrder.resize(frame.captures.size());std::iota(frame.argumentOrder.begin(),frame.argumentOrder.end(),0);
    uint64_t state=seed^uint64_t(frame.begin)*UINT64_C(1099511628211);
    for (auto n=frame.argumentOrder.size();n>1;--n) {state^=state<<13;state^=state>>7;state^=state<<17;std::swap(frame.argumentOrder[n-1],frame.argumentOrder[state%n]);}
    std::string helper="static "+frame.type+" "+frame.helper+"(",call=frame.helper+"(";
    for (unsigned index=0;index<frame.argumentOrder.size();++index) {
      const auto &capture=frame.captures[frame.argumentOrder[index]];
      if (index) {helper+=", ";call+=", ";}
      helper+=capture.type+" "+capture.parameter;call+=capture.name;
    }
    helper+="){ return ";
    for (const auto &token:frame.tokens) helper+=(token.capture<0 ? token.text:frame.captures.at(unsigned(token.capture)).parameter)+" ";
    helper+="; } ";call+=")";
    function.insertion.emitted+=helper;
    frame.callBytes=unsigned(call.size());frame.emitted=call+std::string(std::count(frame.original.begin(),frame.original.end(),'\n'),'\n');
  }
}

std::vector<const OutlineEdit *> outlineEdits(const std::vector<const OutlineFunction *> &functions) {
  std::vector<const OutlineEdit *> edits;
  for (const auto *function:functions) if (!function->frames.empty()) {
    edits.push_back(&function->insertion);for (const auto &frame:function->frames) edits.push_back(&frame);
  }
  std::sort(edits.begin(),edits.end(),[](const auto *a,const auto *b){return std::tie(a->begin,a->end)<std::tie(b->begin,b->end);});
  return edits;
}
void prepareOutline(std::vector<OutlineFunction *> functions) {
  const std::vector<const OutlineFunction *> readonly(functions.begin(),functions.end());
  const auto edits=outlineEdits(readonly);
  int64_t delta=0;unsigned previous=0;
  for (const auto *view:edits) {
    auto *edit=const_cast<OutlineEdit *>(view);
    if (edit->begin<previous) throw std::invalid_argument("overlapping outline source edits");
    edit->candidateBegin=unsigned(int64_t(edit->begin)+delta);edit->candidateEnd=edit->candidateBegin+unsigned(edit->emitted.size());
    delta+=int64_t(edit->emitted.size())-int64_t(edit->end-edit->begin);previous=edit->end;
  }
  for (auto *function:functions) for (auto &frame:function->frames) for (auto &capture:frame.captures)
    capture.candidateDeclaration=mapped(capture.declaration,edits);
}
bool outlineContextMatches(const std::vector<PrivateReference> &original,const std::vector<PrivateReference> &candidate,
                           const std::vector<const OutlineFunction *> &functions,std::string &reason) {
  const auto edits=outlineEdits(functions);std::vector<PrivateReference> expected,observed;
  try {
    for (auto ref:original) if (!inside(ref.position,functions,false)) {
      ref.position=mapped(ref.position,edits);if (ref.mainFile) ref.declaration=mapped(ref.declaration,edits);expected.push_back(ref);
    }
    for (const auto &ref:candidate) if (!inside(ref.position,functions,true)) observed.push_back(ref);
    if (expected.size()!=observed.size()) throw std::invalid_argument("outline context reference count changed");
    for (unsigned i=0;i<expected.size();++i) {
      const auto &a=expected[i],&b=observed[i];
      if (std::tie(a.position,a.declaration,a.mainFile,a.file,a.name,a.kind)!=std::tie(b.position,b.declaration,b.mainFile,b.file,b.name,b.kind))
        throw std::invalid_argument("outline changed a surrounding declaration binding");
    }
    return true;
  } catch (const std::exception &error) {reason=error.what();return false;}
}

Verification validateOutline(clang::ASTContext &ctx,const clang::FunctionDecl &caller,OutlineFunction &function) {
  Verification proof;proof.status="unsupported";proof.strategy="typed-expression-alpha-equivalence";
  try {
    std::map<std::string,const clang::FunctionDecl *> helpers;
    for (const auto *decl:ctx.getTranslationUnitDecl()->decls()) {
      const auto loc=decl->getBeginLoc();if (loc.isInvalid() || !ctx.getSourceManager().isWrittenInMainFile(loc)) continue;
      const auto begin=offset(ctx,loc);
      if (begin<function.insertion.candidateBegin || begin>=function.insertion.candidateEnd) continue;
      const auto *f=llvm::dyn_cast<clang::FunctionDecl>(decl);
      if (!f || !f->doesThisDeclarationHaveABody() || f->getStorageClass()!=clang::SC_Static || f->hasAttrs() ||
          f->isVariadic() || f->isInlineSpecified() || endOf(ctx,f->getEndLoc())>function.insertion.candidateEnd ||
          !helpers.emplace(f->getNameAsString(),f).second)
        throw std::invalid_argument("outline insertion contains an unexpected declaration");
    }
    if (helpers.size()!=function.frames.size()) throw std::invalid_argument("outline helper set changed");
    for (auto &frame:function.frames) {
      const auto found=helpers.find(frame.helper);
      if (found==helpers.end()) throw std::invalid_argument("missing outline helper");
      const auto &helper=*found->second;
      if (integerType(ctx,helper.getReturnType())!=frame.type || helper.getNumParams()!=frame.captures.size())
        throw std::invalid_argument("outline helper signature changed");
      const auto *body=llvm::dyn_cast<clang::CompoundStmt>(helper.getBody());
      const auto *ret=body && body->size()==1 ? llvm::dyn_cast<clang::ReturnStmt>(*body->body_begin()):nullptr;
      if (!ret || !ret->getRetValue()) throw std::invalid_argument("outline helper must return only its pure expression");
      OutlineFrame actual;const std::set<const clang::ValueDecl *> escaped;
      Expression parser(ctx,helper,escaped,actual,false);
      for (unsigned n=0;n<helper.getNumParams();++n) {
        const auto id=frame.argumentOrder.at(n);const auto *parameter=helper.getParamDecl(n);
        if (parameter->hasAttrs() || integerType(ctx,parameter->getType())!=frame.captures[id].type)
          throw std::invalid_argument("outline parameter type changed");
        parser.bindings.emplace(parameter,id);
      }
      if (parser.read(ret->getRetValue()).signature!=frame.signature) throw std::invalid_argument("outline helper expression or types changed");
      const clang::CallExpr *call=nullptr;unsigned matches=0;
      walk(caller.getBody(),[&](const clang::Stmt *s) {
        if (const auto *c=llvm::dyn_cast<clang::CallExpr>(s)) if (offset(ctx,c->getBeginLoc())==frame.candidateBegin) {call=c;++matches;}
      });
      if (matches!=1 || endOf(ctx,call->getEndLoc())!=frame.candidateBegin+frame.callBytes ||
          call->getDirectCallee()!=&helper || call->getNumArgs()!=frame.captures.size() || integerType(ctx,call->getType())!=frame.type)
        throw std::invalid_argument("outline call target, extent or signature changed");
      for (unsigned n=0;n<call->getNumArgs();++n) {
        const auto &capture=frame.captures[frame.argumentOrder[n]];
        const auto *ref=llvm::dyn_cast<clang::DeclRefExpr>(call->getArg(n)->IgnoreParenImpCasts());
        if (!ref || offset(ctx,ref->getDecl()->getLocation())!=capture.candidateDeclaration ||
            ref->getDecl()->getNameAsString()!=capture.name || integerType(ctx,ref->getDecl()->getType())!=capture.type)
          throw std::invalid_argument("outline argument changed its source binding");
      }
      frame.verification.status="proved-under-model";frame.verification.strategy=proof.strategy;
      frame.verification.reason="actual helper has the same typed pure expression under verified parameter substitution";
    }
    proof.status="proved-under-model";
    proof.reason="typed expression alpha-equivalence, initialized entry captures and matching calls; compiler and sequential contextual assumptions remain trusted";
  } catch (const std::exception &error) {proof.reason=error.what();}
  return proof;
}
} // namespace csrd
