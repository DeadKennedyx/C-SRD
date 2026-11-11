#include "csrd/private_regions.hpp"
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
#include <unordered_set>

namespace csrd {
namespace {
using Decl = const clang::ValueDecl *;
using DeclSet = std::unordered_set<Decl>;
bool u32(clang::ASTContext &ctx, clang::QualType t) {
  return !t.hasQualifiers() && ctx.hasSameType(t, ctx.UnsignedIntTy) && ctx.getTypeSize(t) == 32;
}
void walk(const clang::Stmt *s, const std::function<void(const clang::Stmt *)> &visit) {
  if (!s) return;
  visit(s);
  for (const auto *child : s->children()) walk(child, visit);
}
struct PrivateObjects {
  DeclSet objects;
  std::string reason;
  PrivateObjects(clang::ASTContext &ctx, const clang::FunctionDecl &f) {
    if (ctx.getTypeSize(ctx.IntTy) != 32 || ctx.getTypeSize(ctx.UnsignedIntTy) != 32) {
      reason = "private frames require 32-bit int/unsigned int"; return;
    }
    for (const auto *decl : f.redecls()) if (decl->hasAttrs()) {
      reason = "function attributes are outside the private-frame contract"; return;
    }
    std::map<std::string, unsigned> counts;
    auto add = [&](const clang::VarDecl *v) {
      if (!v || v->getName().empty()) return;
      ++counts[v->getNameAsString()];
      if (v->hasLocalStorage() && u32(ctx, v->getType()) && !v->hasAttrs() &&
          (v->getStorageClass() == clang::SC_None || v->getStorageClass() == clang::SC_Register)) objects.insert(v);
    };
    for (const auto *p : f.parameters()) add(p);
    DeclSet escaped;
    walk(f.getBody(), [&](const clang::Stmt *s) {
      if (const auto *d = llvm::dyn_cast<clang::DeclStmt>(s))
        for (const auto *decl : d->decls()) add(llvm::dyn_cast<clang::VarDecl>(decl));
      if (llvm::isa<clang::AsmStmt>(s)) reason = "inline assembly prevents private-object reasoning";
      if (const auto *u = llvm::dyn_cast<clang::UnaryOperator>(s))
        if (u->getOpcode() == clang::UO_AddrOf)
          if (const auto *r = llvm::dyn_cast<clang::DeclRefExpr>(u->getSubExpr()->IgnoreParenImpCasts())) escaped.insert(r->getDecl());
    });
    for (const auto *decl : escaped) objects.erase(decl);
    for (const auto &[name, count] : counts) if (count != 1) {
      reason = "shadowed local names are outside the first private-frame contract: " + name; break;
    }
  }
};
std::unique_ptr<Expr> expression(clang::ASTContext &ctx, const clang::Expr *e, const DeclSet &allowed,
                                 unsigned &operations, unsigned depth = 0) {
  if (depth > 128) throw std::invalid_argument("private expression depth budget exceeded");
  if (e->getBeginLoc().isMacroID() || e->getEndLoc().isMacroID()) throw std::invalid_argument("macro expression boundary");
  if (const auto *p = llvm::dyn_cast<clang::ParenExpr>(e)) return expression(ctx, p->getSubExpr(), allowed, operations, depth+1);
  if (const auto *c = llvm::dyn_cast<clang::ImplicitCastExpr>(e)) {
    bool ok = c->getCastKind() == clang::CK_LValueToRValue && u32(ctx, c->getType()) && u32(ctx, c->getSubExpr()->getType());
    const auto *literal = llvm::dyn_cast<clang::IntegerLiteral>(c->getSubExpr()->IgnoreParens());
    ok |= c->getCastKind() == clang::CK_IntegralCast && u32(ctx, c->getType()) && literal &&
          ctx.hasSameType(literal->getType(), ctx.IntTy) && literal->getValue().getActiveBits() <= 31;
    if (!ok) throw std::invalid_argument("unsupported private integer conversion");
    return expression(ctx, c->getSubExpr(), allowed, operations, depth+1);
  }
  if (const auto *literal = llvm::dyn_cast<clang::IntegerLiteral>(e)) {
    if ((!u32(ctx, e->getType()) && !ctx.hasSameType(e->getType(), ctx.IntTy)) || literal->getValue().getActiveBits() > 32)
      throw std::invalid_argument("private constants require int/unsigned int literals");
    auto out = std::make_unique<Expr>(Expr::Kind::Constant);
    out->value = uint32_t(literal->getValue().getZExtValue()); return out;
  }
  if (const auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(e)) {
    if (!allowed.count(ref->getDecl()) || !u32(ctx, e->getType()))
      throw std::invalid_argument("reference is not a private unqualified uint32 object");
    auto out = std::make_unique<Expr>(Expr::Kind::Reference);
    out->name = ref->getDecl()->getNameAsString(); return out;
  }
  if (const auto *b = llvm::dyn_cast<clang::BinaryOperator>(e)) {
    if (!u32(ctx, b->getType()) || (b->getOpcode() != clang::BO_Add && b->getOpcode() != clang::BO_Sub && b->getOpcode() != clang::BO_Mul))
      throw std::invalid_argument("private arithmetic initially supports unsigned addition, subtraction and literal scaling");
    auto left = expression(ctx, b->getLHS(), allowed, operations, depth+1);
    auto right = expression(ctx, b->getRHS(), allowed, operations, depth+1);
    auto out = std::make_unique<Expr>(b->getOpcode() == clang::BO_Add ? Expr::Kind::Add : Expr::Kind::Subtract);
    if (b->getOpcode() == clang::BO_Mul) {
      if (left->kind == Expr::Kind::Constant) std::swap(left, right);
      if (right->kind != Expr::Kind::Constant) throw std::invalid_argument("general multiplication is outside private regions");
      out->kind = Expr::Kind::Scale; out->value = right->value; right.reset();
    }
    out->left = std::move(left); out->right = std::move(right); ++operations; return out;
  }
  throw std::invalid_argument("effect, memory access or unsupported expression forms a private-region boundary");
}
Statement assignment(clang::ASTContext &ctx, const clang::Stmt *s, const DeclSet &allowed, unsigned &operations) {
  const auto *a = llvm::dyn_cast<clang::BinaryOperator>(s);
  if (!a || a->getOpcode() != clang::BO_Assign) throw std::invalid_argument("only plain assignments enter the first private-region prototype");
  const auto *lhs = llvm::dyn_cast<clang::DeclRefExpr>(a->getLHS()->IgnoreParens());
  if (!lhs || !allowed.count(lhs->getDecl()) || !u32(ctx, lhs->getType()))
    throw std::invalid_argument("assignment target is not a private unqualified uint32 object");
  return {Statement::Kind::Assign, lhs->getDecl()->getNameAsString(), expression(ctx, a->getRHS(), allowed, operations)};
}
void references(const Expr &e, const std::function<void(const std::string &)> &visit) {
  if (e.kind == Expr::Kind::Reference) visit(e.name);
  if (e.left) references(*e.left, visit);
  if (e.right) references(*e.right, visit);
}
void appendFrameOutputs(Region &region, const PrivateFrame &frame) {
  // The synthetic pointer is distinct from all source variables. Its contents
  // encode observable scalar state for the already-tested memory verifier.
  std::string memory = "csrd_frame_output_vector";
  while (std::find(frame.inputs.begin(), frame.inputs.end(), memory) != frame.inputs.end() ||
         std::find(frame.outputs.begin(), frame.outputs.end(), memory) != frame.outputs.end()) memory += "_";
  region.parameters = frame.inputs; region.parameters.push_back(memory);
  Region::Buffer buffer; buffer.minimumElements = unsigned(frame.outputs.size()); buffer.stores = unsigned(frame.outputs.size());
  region.buffers.emplace(memory, buffer);
  for (unsigned i = 0; i < frame.outputs.size(); ++i) {
    auto ref = std::make_unique<Expr>(Expr::Kind::Reference); ref->name = frame.outputs[i];
    Statement store(Statement::Kind::Store, memory, std::move(ref)); store.index = i;
    region.statements.push_back(std::move(store));
  }
  region.statements.emplace_back(Statement::Kind::Return, "", std::make_unique<Expr>(Expr::Kind::Constant));
}
unsigned tokenEnd(clang::ASTContext &ctx, clang::SourceLocation loc) {
  const auto end = clang::Lexer::getLocForEndOfToken(loc, 0, ctx.getSourceManager(), ctx.getLangOpts());
  if (end.isInvalid() || end.isMacroID()) throw std::invalid_argument("unrewritable private source range");
  return ctx.getSourceManager().getFileOffset(end);
}
} // namespace

PrivateDiscovery discoverPrivateRegions(clang::ASTContext &ctx, const clang::FunctionDecl &f) {
  PrivateDiscovery result;
  const PrivateObjects privateObjects(ctx, f);
  if (!privateObjects.reason.empty()) { result.reason = privateObjects.reason; return result; }
  auto &sm = ctx.getSourceManager();
  const auto source = sm.getBufferData(sm.getMainFileID());
  walk(f.getBody(), [&](const clang::Stmt *node) {
    const auto *block = llvm::dyn_cast<clang::CompoundStmt>(node);
    if (!block) return;
    PrivateFrame pending;
    std::set<std::string> written;
    auto flush = [&]() {
      if (pending.original && pending.original->operations) {
        pending.originalText = source.substr(pending.begin, pending.end-pending.begin).str();
        appendFrameOutputs(*pending.original, pending);
        result.frames.push_back(std::move(pending));
      }
      pending = PrivateFrame{}; written.clear();
    };
    for (const auto *s : block->body()) {
      try {
        unsigned operations = 0;
        auto statement = assignment(ctx, s, privateObjects.objects, operations);
        // Bounded proof workload; splitting preserves all scalar boundaries.
        if (pending.original && (pending.original->statements.size() >= 32 ||
            pending.original->operations + operations > 256 ||
            (pending.outputs.size() == 16 && !written.count(statement.name)))) flush();
        const auto next = clang::Lexer::findNextToken(s->getEndLoc(), sm, ctx.getLangOpts());
        if (!next || !next->is(clang::tok::semi)) throw std::invalid_argument("cannot locate assignment semicolon");
        if (!pending.original) {
          pending.original = std::make_shared<Region>(); pending.original->name = f.getNameAsString();
          pending.begin = sm.getFileOffset(s->getBeginLoc());
          pending.line = sm.getSpellingLineNumber(s->getBeginLoc()); pending.column = sm.getSpellingColumnNumber(s->getBeginLoc());
        }
        pending.end = tokenEnd(ctx, next->getLocation());
        references(*statement.expression, [&](const std::string &name) {
          if (!written.count(name) && std::find(pending.inputs.begin(), pending.inputs.end(), name) == pending.inputs.end())
            pending.inputs.push_back(name);
        });
        if (written.insert(statement.name).second) pending.outputs.push_back(statement.name);
        pending.original->operations += operations;
        pending.original->statements.push_back(std::move(statement));
      } catch (const std::exception &e) {
        flush();
        result.boundaries.push_back({sm.getSpellingLineNumber(s->getBeginLoc()), sm.getSpellingColumnNumber(s->getBeginLoc()),
                                     s->getStmtClassName(), e.what()});
      }
    }
    flush();
  });
  std::sort(result.frames.begin(), result.frames.end(), [](const PrivateFrame &a, const PrivateFrame &b) { return a.begin < b.begin; });
  if (result.frames.empty()) result.reason = "no eligible private uint32 assignment regions";
  return result;
}

Verification validatePrivateFrame(clang::ASTContext &ctx, const clang::FunctionDecl &f, const PrivateFrame &frame, unsigned timeoutMs) {
  Verification proof;
  try {
    auto &sm = ctx.getSourceManager();
    const PrivateObjects privateObjects(ctx, f);
    if (!privateObjects.reason.empty()) throw std::invalid_argument(privateObjects.reason);
    const clang::CompoundStmt *body = nullptr;
    walk(f.getBody(), [&](const clang::Stmt *s) {
      const auto *block = llvm::dyn_cast<clang::CompoundStmt>(s);
      if (block && !block->getBeginLoc().isMacroID() && sm.getFileOffset(block->getBeginLoc()) == frame.candidateBegin &&
          tokenEnd(ctx, block->getEndLoc()) == frame.candidateEnd) body = block;
    });
    if (!body) throw std::invalid_argument("emitted private block boundary is missing or changed");
    DeclSet initialized;
    std::set<std::string> externalOutputs(frame.outputs.begin(), frame.outputs.end()), actualOutputs;
    std::set<std::string> inputNames(frame.inputs.begin(), frame.inputs.end());
    for (const auto *decl : privateObjects.objects) {
      const auto pos = sm.getFileOffset(decl->getLocation());
      if (pos < frame.candidateBegin && inputNames.count(decl->getNameAsString())) initialized.insert(decl);
    }
    if (initialized.size() != frame.inputs.size()) throw std::invalid_argument("private input bindings changed");
    Region candidate; candidate.name = f.getNameAsString();
    DeclSet locals;
    for (const auto *s : body->body()) {
      if (const auto *d = llvm::dyn_cast<clang::DeclStmt>(s)) {
        const auto *v = d->isSingleDecl() ? llvm::dyn_cast<clang::VarDecl>(d->getSingleDecl()) : nullptr;
        if (!v || !privateObjects.objects.count(v) || !v->hasInit() || v->getStorageClass() != clang::SC_None)
          throw std::invalid_argument("emitted private local has unsupported type, storage or initialization");
        auto value = expression(ctx, v->getInit(), initialized, candidate.operations);
        candidate.statements.emplace_back(Statement::Kind::Declare, v->getNameAsString(), std::move(value));
        initialized.insert(v); locals.insert(v);
      } else {
        // Writes may initialize an output without reading its old value.
        auto writable = initialized;
        for (const auto *decl : privateObjects.objects)
          if (sm.getFileOffset(decl->getLocation()) < frame.candidateBegin && externalOutputs.count(decl->getNameAsString())) writable.insert(decl);
        unsigned unused = 0;
        const auto *a = llvm::dyn_cast<clang::BinaryOperator>(s);
        if (!a || a->getOpcode() != clang::BO_Assign) throw std::invalid_argument("emitted region contains an unsupported statement or effect");
        const auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(a->getLHS()->IgnoreParens());
        if (!ref || !writable.count(ref->getDecl())) throw std::invalid_argument("emitted assignment escapes its scalar frame");
        if (!locals.count(ref->getDecl()) && !externalOutputs.count(ref->getDecl()->getNameAsString()))
          throw std::invalid_argument("emitted region writes a non-output object");
        auto value = expression(ctx, a->getRHS(), initialized, unused); candidate.operations += unused;
        candidate.statements.emplace_back(Statement::Kind::Assign, ref->getDecl()->getNameAsString(), std::move(value));
        initialized.insert(ref->getDecl());
        if (!locals.count(ref->getDecl())) actualOutputs.insert(ref->getDecl()->getNameAsString());
      }
    }
    if (actualOutputs != externalOutputs) throw std::invalid_argument("emitted region omits a required output");
    appendFrameOutputs(candidate, frame);
    proof = verifyMemory(*frame.original, candidate, timeoutMs);
    proof.strategy = "private-scalar-frame/" + proof.strategy;
    if (proof.status == "proved-under-model") proof.reason = "all written scalar outputs equal for every uint32 input; surrounding effects are unchanged under private-object assumptions";
  } catch (const std::exception &e) { proof.status = "unsupported"; proof.reason = e.what(); }
  return proof;
}
} // namespace csrd
