#include "csrd/control_regions.hpp"
#include "clang/AST/ASTContext.h"
#include "clang/AST/Attr.h"
#include "clang/AST/Decl.h"
#include "clang/AST/Expr.h"
#include "clang/AST/Stmt.h"
#include "clang/Basic/SourceManager.h"
#include "clang/Lex/Lexer.h"
#include <algorithm>
#include <functional>
#include <stdexcept>

namespace csrd {
namespace {
void walk(const clang::Stmt *s, const std::function<void(const clang::Stmt *)> &visit) {
  if (!s) return;
  visit(s);
  for (const auto *child : s->children()) walk(child, visit);
}
unsigned tokenEnd(clang::ASTContext &ctx, clang::SourceLocation loc) {
  const auto end = clang::Lexer::getLocForEndOfToken(loc, 0, ctx.getSourceManager(), ctx.getLangOpts());
  if (end.isInvalid() || end.isMacroID()) throw std::invalid_argument("unrewritable control token");
  return ctx.getSourceManager().getFileOffset(end);
}
unsigned statementEnd(clang::ASTContext &ctx, const clang::Stmt *s) {
  if (const auto *i = llvm::dyn_cast<clang::IfStmt>(s)) return statementEnd(ctx, i->getElse() ? i->getElse() : i->getThen());
  if (const auto *w = llvm::dyn_cast<clang::WhileStmt>(s)) return statementEnd(ctx, w->getBody());
  if (const auto *f = llvm::dyn_cast<clang::ForStmt>(s)) return statementEnd(ctx, f->getBody());
  if (llvm::isa<clang::CompoundStmt, clang::NullStmt, clang::DeclStmt>(s)) return tokenEnd(ctx, s->getEndLoc());
  const auto next = clang::Lexer::findNextToken(s->getEndLoc(), ctx.getSourceManager(), ctx.getLangOpts());
  if (!next || !next->is(clang::tok::semi)) throw std::invalid_argument("cannot locate control statement terminator");
  return tokenEnd(ctx, next->getLocation());
}
bool expressionSafe(const clang::Expr *e) {
  bool safe = true;
  walk(e, [&](const clang::Stmt *s) {
    if (llvm::isa<clang::CompoundLiteralExpr, clang::StmtExpr, clang::SourceLocExpr>(s)) safe = false;
  });
  return safe;
}
// Declarations are boundaries, never hoisted. A nested scope containing one is
// visited separately; this preserves object scope and storage duration.
bool canLower(const clang::Stmt *s) {
  if (!s) return true;
  if (const auto *e = llvm::dyn_cast<clang::Expr>(s)) return expressionSafe(e);
  if (const auto *r = llvm::dyn_cast<clang::ReturnStmt>(s)) return !r->getRetValue() || expressionSafe(r->getRetValue());
  if (llvm::isa<clang::NullStmt, clang::BreakStmt, clang::ContinueStmt>(s)) return true;
  if (const auto *b = llvm::dyn_cast<clang::CompoundStmt>(s)) {
    for (const auto *child : b->body()) if (!canLower(child)) return false;
    return true;
  }
  if (const auto *i = llvm::dyn_cast<clang::IfStmt>(s))
    return !i->getInit() && !i->getConditionVariable() && expressionSafe(i->getCond()) && canLower(i->getThen()) && canLower(i->getElse());
  if (const auto *w = llvm::dyn_cast<clang::WhileStmt>(s))
    return !w->getConditionVariable() && expressionSafe(w->getCond()) && canLower(w->getBody());
  if (const auto *d = llvm::dyn_cast<clang::DoStmt>(s)) return expressionSafe(d->getCond()) && canLower(d->getBody());
  if (const auto *f = llvm::dyn_cast<clang::ForStmt>(s))
    return !f->getConditionVariable() && canLower(f->getInit()) && (!f->getCond() || expressionSafe(f->getCond())) &&
           (!f->getInc() || expressionSafe(f->getInc())) && canLower(f->getBody());
  return false;
}
class GraphBuilder {
  clang::ASTContext &ctx;
  ControlFrame &frame;
  llvm::StringRef source;
  unsigned depth = 0;
  int add(ControlKind kind, const clang::Stmt *s, int yes, int no = ControlEnd) {
    if (frame.nodes.size() >= 512) throw std::invalid_argument("control region exceeds 512 graph nodes");
    ControlNode node; node.kind = kind; node.yes = yes; node.no = no;
    if (s) {
      node.begin = ctx.getSourceManager().getFileOffset(s->getBeginLoc());
      node.end = tokenEnd(ctx, s->getEndLoc());
      node.text = source.substr(node.begin, node.end-node.begin).str();
    }
    frame.nodes.push_back(std::move(node));
    return int(frame.nodes.size()-1);
  }
public:
  GraphBuilder(clang::ASTContext &c, ControlFrame &f) : ctx(c), frame(f),
    source(c.getSourceManager().getBufferData(c.getSourceManager().getMainFileID())) {}
  int lower(const clang::Stmt *s, int next, int onBreak, int onContinue) {
    if (!s) return next;
    if (++depth > 128) throw std::invalid_argument("control nesting exceeds 128 levels");
    struct Exit { unsigned &d; ~Exit() { --d; } } exit{depth};
    if (const auto *e = llvm::dyn_cast<clang::Expr>(s)) return add(ControlKind::Effect, e, next);
    if (llvm::isa<clang::ReturnStmt>(s)) return add(ControlKind::Return, s, ControlEnd);
    if (llvm::isa<clang::NullStmt>(s)) return add(ControlKind::Jump, nullptr, next);
    if (llvm::isa<clang::BreakStmt>(s)) { frame.outerBreak |= onBreak == ControlBreak; return add(ControlKind::Jump, nullptr, onBreak); }
    if (llvm::isa<clang::ContinueStmt>(s)) { frame.outerContinue |= onContinue == ControlContinue; return add(ControlKind::Jump, nullptr, onContinue); }
    if (const auto *b = llvm::dyn_cast<clang::CompoundStmt>(s)) {
      for (auto it = b->body_rbegin(); it != b->body_rend(); ++it) next = lower(*it, next, onBreak, onContinue);
      return next;
    }
    if (const auto *i = llvm::dyn_cast<clang::IfStmt>(s)) {
      ++frame.branches;
      const auto yes = lower(i->getThen(), next, onBreak, onContinue);
      const auto no = lower(i->getElse(), next, onBreak, onContinue);
      return add(ControlKind::Branch, i->getCond(), yes, no);
    }
    if (const auto *w = llvm::dyn_cast<clang::WhileStmt>(s)) {
      ++frame.branches; ++frame.loops;
      const auto guard = add(ControlKind::Branch, w->getCond(), next, next);
      const auto body = lower(w->getBody(), guard, next, guard);
      frame.nodes[guard].yes = body;
      return guard;
    }
    if (const auto *d = llvm::dyn_cast<clang::DoStmt>(s)) {
      ++frame.branches; ++frame.loops;
      const auto guard = add(ControlKind::Branch, d->getCond(), next, next);
      const auto body = lower(d->getBody(), guard, next, guard);
      frame.nodes[guard].yes = body;
      return body;
    }
    if (const auto *f = llvm::dyn_cast<clang::ForStmt>(s)) {
      ++frame.loops;
      const auto guard = add(f->getCond() ? ControlKind::Branch : ControlKind::Jump, f->getCond(), next, next);
      frame.branches += f->getCond() != nullptr;
      const auto advance = f->getInc() ? add(ControlKind::Effect, f->getInc(), guard) : guard;
      const auto body = lower(f->getBody(), advance, next, advance);
      frame.nodes[guard].yes = body;
      return lower(f->getInit(), guard, onBreak, onContinue);
    }
    throw std::invalid_argument("unmodeled control statement");
  }
};
} // namespace

const char *controlKindName(ControlKind kind) {
  switch (kind) {
  case ControlKind::Effect: return "effect";
  case ControlKind::Branch: return "branch";
  case ControlKind::Return: return "return";
  case ControlKind::Jump: return "jump";
  }
  return "invalid";
}
ControlDiscovery discoverControlRegions(clang::ASTContext &ctx, const clang::FunctionDecl &f) {
  ControlDiscovery result;
  for (const auto *decl : f.redecls()) if (decl->hasAttrs()) result.reason = "function attributes are outside the control-region contract";
  walk(f.getBody(), [&](const clang::Stmt *s) {
    if (llvm::isa<clang::GotoStmt, clang::IndirectGotoStmt, clang::LabelStmt, clang::AddrLabelExpr, clang::AsmStmt, clang::StmtExpr>(s))
      result.reason = "labels, goto, statement expressions and assembly are outside control regions";
    if (llvm::isa<clang::AtomicExpr>(s)) result.reason = "atomic accesses need a separate control contract";
    if (const auto *e = llvm::dyn_cast<clang::Expr>(s))
      if (e->getType().isVolatileQualified() || e->getType()->isAtomicType()) result.reason = "volatile/atomic accesses need a separate control contract";
    if (const auto *cast = llvm::dyn_cast<clang::CastExpr>(s))
      if (cast->getCastKind() == clang::CK_PointerToIntegral)
        result.reason = "numeric address observations are outside the control-region contract";
    if (const auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(s))
      if (const auto *var = llvm::dyn_cast<clang::VarDecl>(ref->getDecl()))
        if (var->getTLSKind() != clang::VarDecl::TLS_None)
          result.reason = "thread-local accesses need a separate concurrency contract";
    if (const auto *d = llvm::dyn_cast<clang::DeclStmt>(s)) for (const auto *decl : d->decls())
      if (decl->hasAttrs()) result.reason = "local declaration attributes are outside control regions";
    if (const auto *call = llvm::dyn_cast<clang::CallExpr>(s)) if (const auto *callee = call->getDirectCallee()) {
      const auto name = callee->getNameAsString();
      if (callee->hasAttr<clang::ReturnsTwiceAttr>() || name == "setjmp" || name == "_setjmp" || name == "sigsetjmp" ||
          name == "__sigsetjmp" || name == "longjmp" || name == "siglongjmp" || name.rfind("__builtin_", 0) == 0 ||
          name.rfind("__atomic_", 0) == 0 || name.rfind("__sync_", 0) == 0)
        result.reason = "nonlocal jumps and explicit compiler builtins are outside control regions";
    }
  });
  if (!result.reason.empty()) return result;
  auto &sm = ctx.getSourceManager();
  const auto source = sm.getBufferData(sm.getMainFileID());
  std::function<void(const clang::Stmt *)> visit = [&](const clang::Stmt *s) {
    if (!s) return;
    const auto *block = llvm::dyn_cast<clang::CompoundStmt>(s);
    if (!block) { for (const auto *child : s->children()) visit(child); return; }
    std::vector<const clang::Stmt *> pending;
    auto flush = [&]() {
      if (pending.empty()) return;
      try {
        ControlFrame frame;
        frame.begin = sm.getFileOffset(pending.front()->getBeginLoc());
        frame.end = statementEnd(ctx, pending.back());
        frame.parentBegin = sm.getFileOffset(block->getBeginLoc());
        frame.line = sm.getSpellingLineNumber(pending.front()->getBeginLoc());
        frame.column = sm.getSpellingColumnNumber(pending.front()->getBeginLoc());
        GraphBuilder builder(ctx, frame);
        for (auto it = pending.rbegin(); it != pending.rend(); ++it)
          frame.entry = builder.lower(*it, frame.entry, ControlBreak, ControlContinue);
        if (frame.nodes.size() >= 2 || frame.loops) {
          frame.originalText = source.substr(frame.begin, frame.end-frame.begin).str();
          result.frames.push_back(std::move(frame));
        }
      } catch (const std::exception &e) {
        result.boundaries.push_back({sm.getSpellingLineNumber(pending.front()->getBeginLoc()), 0, "control region", e.what()});
      }
      pending.clear();
    };
    for (const auto *child : block->body()) {
      if (canLower(child)) {
        if (pending.size() == 64) flush();
        pending.push_back(child);
      } else {
        flush();
        result.boundaries.push_back({sm.getSpellingLineNumber(child->getBeginLoc()), sm.getSpellingColumnNumber(child->getBeginLoc()),
          child->getStmtClassName(), "declaration/switch/unsupported scope boundary; nested blocks considered separately"});
        visit(child);
      }
    }
    flush();
  };
  visit(f.getBody());
  std::sort(result.frames.begin(), result.frames.end(), [](const auto &a, const auto &b) { return a.begin < b.begin; });
  if (result.frames.empty()) result.reason = "no eligible control regions";
  return result;
}
} // namespace csrd
