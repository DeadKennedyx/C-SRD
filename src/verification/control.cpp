#include "csrd/control_regions.hpp"
#include "clang/AST/ASTContext.h"
#include "clang/AST/Decl.h"
#include "clang/AST/Expr.h"
#include "clang/AST/Stmt.h"
#include "clang/Basic/SourceManager.h"
#include "clang/Lex/Lexer.h"
#include <algorithm>
#include <functional>
#include <map>
#include <stdexcept>

namespace csrd {
namespace {
void require(bool condition, const char *reason) { if (!condition) throw std::invalid_argument(reason); }
void walk(const clang::Stmt *s, const std::function<void(const clang::Stmt *)> &visit) {
  if (!s) return;
  visit(s); for (const auto *child : s->children()) walk(child, visit);
}
const clang::Expr *clean(const clang::Expr *e) { return e ? e->IgnoreParenImpCasts() : nullptr; }
uint64_t literal(const clang::Expr *e) {
  const auto *value = llvm::dyn_cast_or_null<clang::IntegerLiteral>(clean(e));
  require(value && value->getValue().getActiveBits() <= 32, "dispatcher requires a literal state within 32 bits");
  return value->getValue().getZExtValue();
}
bool refers(const clang::Expr *e, const clang::VarDecl *state) {
  const auto *ref = llvm::dyn_cast_or_null<clang::DeclRefExpr>(clean(e));
  return ref && ref->getDecl() == state;
}
std::vector<const clang::Stmt *> body(const clang::Stmt *s) {
  const auto *block = llvm::dyn_cast_or_null<clang::CompoundStmt>(s);
  require(block, "dispatcher requires an explicit compound scope");
  return {block->body_begin(), block->body_end()};
}
void assignment(const clang::Stmt *s, const clang::VarDecl *state, uint64_t expected) {
  const auto *a = llvm::dyn_cast_or_null<clang::BinaryOperator>(s);
  require(a && a->getOpcode() == clang::BO_Assign && refers(a->getLHS(), state), "invalid dispatcher assignment");
  require(literal(a->getRHS()) == expected, "dispatcher edge differs from source control graph");
}
void comparison(const clang::Expr *e, const clang::VarDecl *state, clang::BinaryOperatorKind op, uint64_t value) {
  const auto *b = llvm::dyn_cast_or_null<clang::BinaryOperator>(clean(e));
  require(b && b->getOpcode() == op && refers(b->getLHS(), state) && literal(b->getRHS()) == value,
          "dispatcher guard differs from its contract");
}
void exitGuard(const clang::Stmt *s, const clang::VarDecl *state, clang::BinaryOperatorKind op, uint64_t value, bool continuation) {
  const auto *i = llvm::dyn_cast_or_null<clang::IfStmt>(s);
  require(i && !i->getInit() && !i->getConditionVariable() && !i->getElse(), "invalid dispatcher exit guard");
  comparison(i->getCond(), state, op, value);
  const auto statements = body(i->getThen());
  require(statements.size() == 1 && (continuation ? llvm::isa<clang::ContinueStmt>(statements[0]) : llvm::isa<clang::BreakStmt>(statements[0])),
          "dispatcher exit changes its enclosing control target");
}
unsigned tokenEnd(clang::ASTContext &ctx, clang::SourceLocation loc) {
  const auto end = clang::Lexer::getLocForEndOfToken(loc, 0, ctx.getSourceManager(), ctx.getLangOpts());
  require(end.isValid() && !end.isMacroID(), "invalid candidate token boundary");
  return ctx.getSourceManager().getFileOffset(end);
}
void payload(clang::ASTContext &ctx, const ControlFrame &frame, const ControlNode &node, const clang::Stmt *s) {
  require(s && !s->getBeginLoc().isMacroID() && !s->getEndLoc().isMacroID(), "payload crossed a macro boundary");
  auto &sm = ctx.getSourceManager();
  const auto begin = sm.getFileOffset(s->getBeginLoc()), end = tokenEnd(ctx, s->getEndLoc());
  require(begin == frame.candidateBegin + node.emittedOffset, "payload moved outside its bound case");
  require(sm.getBufferData(sm.getMainFileID()).substr(begin, end-begin) == node.text, "payload expression/return was modified");
}
unsigned mapOffset(unsigned pos, const std::vector<const ControlFrame *> &frames) {
  int64_t mapped = pos;
  for (const auto *frame : frames) {
    if (pos >= frame->begin && pos < frame->end) {
      for (const auto &node : frame->nodes) if (!node.text.empty() && pos >= node.begin && pos < node.end)
        return frame->candidateBegin + node.emittedOffset + pos-node.begin;
      throw std::invalid_argument("source reference is not bound to a control payload");
    }
    if (pos >= frame->end) mapped += int64_t(frame->emitted.size()) - int64_t(frame->end-frame->begin);
  }
  require(mapped >= 0 && uint64_t(mapped) <= UINT32_MAX, "control reference offset overflow");
  return unsigned(mapped);
}
} // namespace

Verification validateControlFrame(clang::ASTContext &ctx, const clang::FunctionDecl &f, const ControlFrame &frame) {
  Verification proof;
  try {
    const auto &sm = ctx.getSourceManager();
    const clang::CompoundStmt *wrapper = nullptr, *parent = nullptr;
    walk(f.getBody(), [&](const clang::Stmt *s) {
      if (const auto *b = llvm::dyn_cast<clang::CompoundStmt>(s)) {
        if (sm.getFileOffset(b->getBeginLoc()) == frame.candidateBegin) wrapper = b;
        if (sm.getFileOffset(b->getBeginLoc()) == frame.candidateParentBegin) parent = b;
      }
    });
    require(wrapper && parent, "dispatcher or original enclosing scope missing");
    require(std::find(parent->body_begin(), parent->body_end(), wrapper) != parent->body_end(), "dispatcher changed enclosing scope");
    require(tokenEnd(ctx, wrapper->getEndLoc()) == frame.candidateEnd, "dispatcher extent mismatch");
    auto statements = body(wrapper);
    require(statements.size() == 2u + unsigned(frame.outerBreak) + unsigned(frame.outerContinue), "extra/missing dispatcher statement");
    const auto *declaration = llvm::dyn_cast<clang::DeclStmt>(statements[0]);
    require(declaration && declaration->isSingleDecl(), "dispatcher state declaration missing");
    const auto *state = llvm::dyn_cast<clang::VarDecl>(declaration->getSingleDecl());
    require(state && state->getName() == frame.stateName && state->getType() == ctx.UnsignedLongTy && !state->hasAttrs() &&
            state->getStorageClass() == clang::SC_None && state->hasLocalStorage(), "state is not a private unsigned long object");
    require(sm.getFileOffset(state->getLocation()) == frame.candidateBegin + frame.stateDeclarationOffset, "state declaration binding moved");
    auto value = [&](int edge) -> uint64_t {
      if (edge < 0) { require(edge >= ControlContinue, "invalid exit edge"); return unsigned(-edge-1); }
      require(unsigned(edge) < frame.nodes.size(), "source graph edge outside region");
      return frame.nodes[edge].state;
    };
    require(literal(state->getInit()) == value(frame.entry), "dispatcher entry differs from source graph");
    const auto *loop = llvm::dyn_cast<clang::WhileStmt>(statements[1]);
    require(loop && !loop->getConditionVariable() && literal(loop->getCond()) == 1, "dispatcher must use constant while(1)");
    const auto loopBody = body(loop->getBody());
    const auto exits = controlExits(frame);
    require(frame.outerBreak == bool(exits.count(ControlBreak)) && frame.outerContinue == bool(exits.count(ControlContinue)), "exit certificate differs from reachable source graph");
    const bool hasExits = !exits.empty();
    require(loopBody.size() == (hasExits ? 2u : 1u), "extra/missing dispatcher loop statement");
    if (hasExits) exitGuard(loopBody[0], state, clang::BO_LE, 2, false);
    const auto *dispatch = llvm::dyn_cast<clang::SwitchStmt>(loopBody.back());
    require(dispatch && !dispatch->getInit() && !dispatch->getConditionVariable() && refers(dispatch->getCond(), state), "invalid dispatch selector");
    std::map<uint64_t, const ControlNode *> expected;
    for (const auto &node : frame.nodes) {
      require(node.state > 2 && expected.emplace(node.state, &node).second, "nonunique/reserved state in source graph certificate");
      if (node.kind != ControlKind::Return) { (void)value(node.yes); if (node.kind == ControlKind::Branch) (void)value(node.no); }
    }
    bool seenDefault = false;
    for (const auto *s : body(dispatch->getBody())) {
      if (const auto *fallback = llvm::dyn_cast<clang::DefaultStmt>(s)) {
        require(!seenDefault, "duplicate default case"); seenDefault = true;
        const auto statements = body(fallback->getSubStmt());
        require(statements.size() == 2 && llvm::isa<clang::BreakStmt>(statements.back()), "invalid default case");
        assignment(statements[0], state, 0); continue;
      }
      const auto *label = llvm::dyn_cast<clang::CaseStmt>(s);
      require(label && !label->getRHS(), "nonliteral/range/fallthrough case");
      const auto found = expected.find(literal(label->getLHS()));
      require(found != expected.end(), "unknown or duplicate state case");
      const auto &node = *found->second;
      const auto statements = body(label->getSubStmt());
      if (node.kind == ControlKind::Return) {
        require(statements.size() == 1 && llvm::isa<clang::ReturnStmt>(statements[0]), "return case modified");
        payload(ctx, frame, node, statements[0]);
      } else {
        require(statements.size() == (node.kind == ControlKind::Effect ? 3u : 2u) && llvm::isa<clang::BreakStmt>(statements.back()),
                "case has extra effects or can fall through");
        if (node.kind == ControlKind::Branch) {
          const auto *branch = llvm::dyn_cast<clang::IfStmt>(statements[0]);
          require(branch && !branch->getInit() && !branch->getConditionVariable() && branch->getElse(), "branch case modified");
          payload(ctx, frame, node, branch->getCond());
          const auto yes = body(branch->getThen()), no = body(branch->getElse());
          require(yes.size() == 1 && no.size() == 1, "branch adds effects");
          assignment(yes[0], state, value(node.yes)); assignment(no[0], state, value(node.no));
        } else {
          if (node.kind == ControlKind::Effect) {
            require(llvm::isa<clang::Expr>(statements[0]), "effect case changed statement kind");
            payload(ctx, frame, node, statements[0]);
          }
          assignment(statements[statements.size()-2], state, value(node.yes));
        }
      }
      expected.erase(found);
    }
    require(seenDefault && expected.empty(), "dispatcher missing source states or default case");
    unsigned index = 2;
    if (frame.outerBreak) {
      if (exits.size() == 1) require(llvm::isa<clang::BreakStmt>(statements[index++]), "unconditional outer break missing");
      else exitGuard(statements[index++], state, clang::BO_EQ, 1, false);
    }
    if (frame.outerContinue) {
      if (!exits.count(ControlEnd)) require(llvm::isa<clang::ContinueStmt>(statements[index++]), "unconditional outer continue missing");
      else exitGuard(statements[index++], state, clang::BO_EQ, 2, true);
    }
    proof.status = "proved-under-model";
    proof.strategy = "control-graph-isomorphism";
    proof.reason = "reparsed dispatcher has identical payloads and source graph transitions; private control steps terminate; declaration bindings and surrounding source checked separately";
  } catch (const std::exception &e) {
    proof.status = "rejected"; proof.reason = e.what();
  }
  return proof;
}

bool controlContextMatches(const std::vector<PrivateReference> &original, const std::vector<PrivateReference> &candidate,
                           const std::vector<const ControlFrame *> &frames, std::string &reason) {
  try {
    std::map<unsigned, const PrivateReference *> actual;
    for (const auto &ref : candidate) {
      bool control = false;
      for (const auto *frame : frames)
        if (ref.declaration == frame->candidateBegin + frame->stateDeclarationOffset && ref.name == frame->stateName) control = true;
      if (!control) require(actual.emplace(ref.position, &ref).second, "ambiguous candidate reference");
    }
    for (const auto &ref : original) {
      const auto found = actual.find(mapOffset(ref.position, frames));
      require(found != actual.end(), "source reference missing from control payload/context");
      const auto &other = *found->second;
      require(ref.name == other.name && ref.kind == other.kind && ref.mainFile == other.mainFile &&
              (ref.mainFile || ref.file == other.file) && other.declaration == (ref.mainFile ? mapOffset(ref.declaration, frames) : ref.declaration),
              "control payload/context reference changed declaration binding");
      actual.erase(found);
    }
    require(actual.empty(), "additional non-control references in candidate");
    return true;
  } catch (const std::exception &e) { reason = e.what(); return false; }
}
} // namespace csrd
