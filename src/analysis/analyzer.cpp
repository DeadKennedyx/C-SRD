#include "csrd/analyzer.hpp"
#include "clang/AST/ASTContext.h"
#include "clang/AST/Decl.h"
#include "clang/AST/Expr.h"
#include "clang/AST/Stmt.h"
#include <unordered_set>

namespace csrd {
namespace {
class Analyzer {
  clang::ASTContext &ctx;
  Analysis result;
  Region region;
  std::unordered_set<const clang::ValueDecl *> initialized;

  bool fail(clang::SourceLocation loc, const std::string &why) {
    if (result.reason.empty()) { result.reason = why; result.location = loc; }
    return false;
  }
  bool u32(clang::QualType t) const {
    return !t.hasQualifiers() && ctx.hasSameType(t, ctx.UnsignedIntTy) && ctx.getTypeSize(t) == 32;
  }
  std::unique_ptr<Expr> expression(const clang::Expr *e) {
    if (e->getBeginLoc().isMacroID() || e->getEndLoc().isMacroID()) {
      fail(e->getExprLoc(), "macro expansions are not transformed"); return nullptr;
    }
    if (auto *p = llvm::dyn_cast<clang::ParenExpr>(e)) return expression(p->getSubExpr());
    if (auto *c = llvm::dyn_cast<clang::ImplicitCastExpr>(e)) {
      bool allowed = c->getCastKind() == clang::CK_LValueToRValue && u32(c->getType()) && u32(c->getSubExpr()->getType());
      const auto *lit = llvm::dyn_cast<clang::IntegerLiteral>(c->getSubExpr()->IgnoreParens());
      if (c->getCastKind() == clang::CK_IntegralCast && u32(c->getType()) && lit &&
          ctx.hasSameType(lit->getType(), ctx.IntTy) && lit->getValue().getActiveBits() <= 31) allowed = true;
      if (!allowed) { fail(e->getExprLoc(), "unsupported integer conversion or promotion"); return nullptr; }
      return expression(c->getSubExpr());
    }
    if (auto *lit = llvm::dyn_cast<clang::IntegerLiteral>(e)) {
      if ((!u32(lit->getType()) && !ctx.hasSameType(lit->getType(), ctx.IntTy)) || lit->getValue().getActiveBits() > 32) {
        fail(e->getExprLoc(), "only nonnegative int or unsigned-int literals are supported"); return nullptr;
      }
      auto out = std::make_unique<Expr>(Expr::Kind::Constant);
      out->value = uint32_t(lit->getValue().getZExtValue());
      return out;
    }
    if (auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(e)) {
      if (!u32(ref->getType()) || !initialized.count(ref->getDecl())) {
        fail(e->getExprLoc(), "reference must read an initialized local uint32_t object or parameter"); return nullptr;
      }
      auto out = std::make_unique<Expr>(Expr::Kind::Reference);
      out->name = ref->getDecl()->getNameAsString();
      return out;
    }
    if (auto *b = llvm::dyn_cast<clang::BinaryOperator>(e)) {
      if (!u32(b->getType())) { fail(e->getExprLoc(), "arithmetic must have 32-bit unsigned-int semantics"); return nullptr; }
      if (b->getOpcode() != clang::BO_Add && b->getOpcode() != clang::BO_Sub && b->getOpcode() != clang::BO_Mul) {
        fail(e->getExprLoc(), "only addition, subtraction, and literal multiplication are supported in expressions"); return nullptr;
      }
      auto left = expression(b->getLHS());
      auto right = expression(b->getRHS());
      if (!left || !right) return nullptr;
      auto out = std::make_unique<Expr>(b->getOpcode() == clang::BO_Add ? Expr::Kind::Add : Expr::Kind::Subtract);
      if (b->getOpcode() == clang::BO_Mul) {
        if (left->kind == Expr::Kind::Constant) std::swap(left, right);
        if (right->kind != Expr::Kind::Constant) {
          fail(e->getExprLoc(), "general multiplication is unsupported; one operand must be an integer literal"); return nullptr;
        }
        out->kind = Expr::Kind::Scale;
        out->value = right->value;
        right.reset();
      }
      out->left = std::move(left); out->right = std::move(right);
      ++region.operations;
      return out;
    }
    fail(e->getExprLoc(), "unsupported expression: " + std::string(e->getStmtClassName()));
    return nullptr;
  }
  bool statement(const clang::Stmt *s, bool final) {
    if (auto *d = llvm::dyn_cast<clang::DeclStmt>(s)) {
      if (!d->isSingleDecl()) return fail(s->getBeginLoc(), "use a single initialized variable per declaration");
      auto *v = llvm::dyn_cast<clang::VarDecl>(d->getSingleDecl());
      if (!v || !u32(v->getType()) || !v->hasLocalStorage() || v->getStorageClass() != clang::SC_None ||
          v->hasAttrs() || v->isImplicit() || v->getName().empty())
        return fail(s->getBeginLoc(), "locals must be unqualified automatic uint32_t objects without attributes");
      if (!v->hasInit()) return fail(v->getLocation(), "local declarations require an initializer");
      auto expr = expression(v->getInit());
      if (!expr) return false;
      initialized.insert(v);
      region.statements.push_back({Statement::Kind::Declare, v->getNameAsString(), std::move(expr)});
      return true;
    }
    if (auto *a = llvm::dyn_cast<clang::BinaryOperator>(s)) {
      if (a->getOpcode() != clang::BO_Assign) return fail(a->getExprLoc(), "only simple assignment statements are supported");
      auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(a->getLHS()->IgnoreParens());
      if (!ref || !u32(ref->getType()) || !initialized.count(ref->getDecl()))
        return fail(a->getExprLoc(), "assignment must target an initialized local uint32_t object or parameter");
      auto expr = expression(a->getRHS());
      if (!expr) return false;
      region.statements.push_back({Statement::Kind::Assign, ref->getDecl()->getNameAsString(), std::move(expr)});
      return true;
    }
    if (auto *r = llvm::dyn_cast<clang::ReturnStmt>(s)) {
      if (!final || !r->getRetValue()) return fail(s->getBeginLoc(), "require a single final return with a value");
      auto expr = expression(r->getRetValue());
      if (!expr) return false;
      region.statements.push_back({Statement::Kind::Return, "", std::move(expr)});
      return true;
    }
    return fail(s->getBeginLoc(), "unsupported statement: " + std::string(s->getStmtClassName()));
  }
public:
  explicit Analyzer(clang::ASTContext &context) : ctx(context) {}
  Analysis run(const clang::FunctionDecl &f) {
    region.name = f.getNameAsString();
    if (ctx.getTypeSize(ctx.IntTy) != 32 || ctx.getTypeSize(ctx.UnsignedIntTy) != 32 || !u32(f.getReturnType()) ||
        f.isVariadic() || !f.hasWrittenPrototype()) {
      fail(f.getLocation(), "require a prototyped uint32_t function on a target with 32-bit int/unsigned int");
      return std::move(result);
    }
    for (auto *decl : f.redecls()) {
      if (decl->hasAttrs()) { fail(f.getLocation(), "function attributes are unsupported"); return std::move(result); }
    }
    for (const auto *p : f.parameters()) {
      if (!u32(p->getType()) || p->hasAttrs() || p->getName().empty() || p->getStorageClass() != clang::SC_None) {
        fail(p->getLocation(), "parameters must be named, unqualified uint32_t objects without attributes"); return std::move(result);
      }
      initialized.insert(p); region.parameters.push_back(p->getNameAsString());
    }
    auto *body = llvm::dyn_cast<clang::CompoundStmt>(f.getBody());
    if (!body || body->body_empty() || !llvm::isa<clang::ReturnStmt>(body->body_back())) {
      fail(f.getLocation(), "require a straight-line body ending in a return statement"); return std::move(result);
    }
    for (auto *s : body->body()) if (!statement(s, s == body->body_back())) return std::move(result);
    result.region = std::move(region);
    return std::move(result);
  }
};
}
Analysis analyze(clang::ASTContext &context, const clang::FunctionDecl &function) {
  return Analyzer(context).run(function);
}
} // namespace csrd
