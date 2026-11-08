#include "csrd/analyzer.hpp"
#include "clang/AST/ASTContext.h"
#include "clang/AST/Decl.h"
#include "clang/AST/Expr.h"
#include "clang/AST/Stmt.h"
#include <unordered_set>
#include <unordered_map>
#include <algorithm>
#include <limits>

namespace csrd {
namespace {
class Analyzer {
  clang::ASTContext &ctx;
  Analysis result;
  Region region;
  std::unordered_set<const clang::ValueDecl *> initialized;
  std::unordered_set<const clang::ValueDecl *> loopIndices;
  std::unordered_set<std::string> names;
  std::unordered_map<const clang::ValueDecl *, std::vector<uint32_t>> arrays;
  std::unordered_map<std::string, uint32_t> loopBounds;

  bool fail(clang::SourceLocation loc, const std::string &why) {
    if (result.reason.empty()) { result.reason = why; result.location = loc; }
    return false;
  }
  bool u32(clang::QualType t) const {
    return !t.hasQualifiers() && ctx.hasSameType(t, ctx.UnsignedIntTy) && ctx.getTypeSize(t) == 32;
  }
  bool boolean(const clang::Expr *e) const {
    const auto *b = llvm::dyn_cast<clang::BinaryOperator>(e->IgnoreParens());
    return b && b->isComparisonOp();
  }
  uint32_t upperBound(const Expr &e) const {
    if (e.kind == Expr::Kind::Constant) return e.value;
    if (e.kind == Expr::Kind::Reference) {
      auto found = loopBounds.find(e.name);
      return found == loopBounds.end() ? UINT32_MAX : found->second;
    }
    if (e.kind == Expr::Kind::BitAnd) return std::min(upperBound(*e.left), upperBound(*e.right));
    if (e.kind == Expr::Kind::ShiftRight) return upperBound(*e.left) >> e.value;
    if (e.kind >= Expr::Kind::Equal && e.kind <= Expr::Kind::GreaterEqual) return 1;
    if (e.kind == Expr::Kind::Select) return std::max(upperBound(*e.right), upperBound(*e.third));
    if (e.kind == Expr::Kind::Table) return *std::max_element(e.table.begin(), e.table.end());
    if (e.kind == Expr::Kind::Add || e.kind == Expr::Kind::Scale) {
      const uint64_t bound = e.kind == Expr::Kind::Add ? uint64_t(upperBound(*e.left)) + upperBound(*e.right) : uint64_t(upperBound(*e.left)) * e.value;
      if (bound <= UINT32_MAX) return uint32_t(bound);
    }
    return UINT32_MAX;
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
      if (c->getCastKind() == clang::CK_IntegralCast && u32(c->getType()) && boolean(c->getSubExpr())) allowed = true;
      if (c->getCastKind() == clang::CK_LValueToRValue && u32(c->getType()) &&
          llvm::isa<clang::ArraySubscriptExpr>(c->getSubExpr()->IgnoreParens()) &&
          u32(c->getSubExpr()->getType().getUnqualifiedType()) && !c->getSubExpr()->getType().isVolatileQualified()) allowed = true;
      if (!allowed) { fail(e->getExprLoc(), "unsupported integer conversion or promotion"); return nullptr; }
      return expression(c->getSubExpr());
    }
    if (auto *table = llvm::dyn_cast<clang::ArraySubscriptExpr>(e)) {
      const auto *reference = llvm::dyn_cast<clang::DeclRefExpr>(table->getBase()->IgnoreParenImpCasts());
      if (!reference || !arrays.count(reference->getDecl())) {
        fail(e->getExprLoc(), "only nonescaping initialized local lookup arrays can be indexed"); return nullptr;
      }
      auto index = expression(table->getIdx());
      if (!index) return nullptr;
      const auto &values = arrays.at(reference->getDecl());
      if (upperBound(*index) >= values.size()) {
        fail(e->getExprLoc(), "array index is not statically bounded within the local table"); return nullptr;
      }
      auto out = std::make_unique<Expr>(Expr::Kind::Table);
      out->table = values; out->left = std::move(index); ++region.operations; return out;
    }
    if (auto *unary = llvm::dyn_cast<clang::UnaryOperator>(e)) {
      if (unary->getOpcode() != clang::UO_Not || !u32(unary->getType())) {
        fail(e->getExprLoc(), "only unsigned bitwise complement is supported as a unary expression"); return nullptr;
      }
      auto out = std::make_unique<Expr>(Expr::Kind::BitNot);
      out->left = expression(unary->getSubExpr());
      if (!out->left) return nullptr;
      ++region.operations; return out;
    }
    if (auto *conditional = llvm::dyn_cast<clang::ConditionalOperator>(e)) {
      if (!u32(e->getType())) { fail(e->getExprLoc(), "conditional values must have unsigned 32-bit type"); return nullptr; }
      auto out = std::make_unique<Expr>(Expr::Kind::Select);
      out->left = expression(conditional->getCond());
      out->right = expression(conditional->getTrueExpr());
      out->third = expression(conditional->getFalseExpr());
      if (!out->left || !out->right || !out->third) return nullptr;
      ++region.operations; return out;
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
      if ((!b->isComparisonOp() && !u32(b->getType())) ||
          (b->isComparisonOp() && (!u32(b->getLHS()->getType()) || !u32(b->getRHS()->getType())))) {
        fail(e->getExprLoc(), "operations require unsigned 32-bit operands and semantics"); return nullptr;
      }
      Expr::Kind kind;
      switch (b->getOpcode()) {
      case clang::BO_Add: kind = Expr::Kind::Add; break;
      case clang::BO_Sub: kind = Expr::Kind::Subtract; break;
      case clang::BO_Mul: kind = Expr::Kind::Scale; break;
      case clang::BO_And: kind = Expr::Kind::BitAnd; break;
      case clang::BO_Or: kind = Expr::Kind::BitOr; break;
      case clang::BO_Xor: kind = Expr::Kind::BitXor; break;
      case clang::BO_Shl: kind = Expr::Kind::ShiftLeft; break;
      case clang::BO_Shr: kind = Expr::Kind::ShiftRight; break;
      case clang::BO_EQ: kind = Expr::Kind::Equal; break;
      case clang::BO_NE: kind = Expr::Kind::NotEqual; break;
      case clang::BO_LT: kind = Expr::Kind::Less; break;
      case clang::BO_LE: kind = Expr::Kind::LessEqual; break;
      case clang::BO_GT: kind = Expr::Kind::Greater; break;
      case clang::BO_GE: kind = Expr::Kind::GreaterEqual; break;
      default: fail(e->getExprLoc(), "unsupported binary operator"); return nullptr;
      }
      auto left = expression(b->getLHS());
      auto right = expression(b->getRHS());
      if (!left || !right) return nullptr;
      auto out = std::make_unique<Expr>(kind);
      if (b->getOpcode() == clang::BO_Mul) {
        if (left->kind == Expr::Kind::Constant) std::swap(left, right);
        if (right->kind != Expr::Kind::Constant) {
          fail(e->getExprLoc(), "general multiplication is unsupported; one operand must be an integer literal"); return nullptr;
        }
        out->kind = Expr::Kind::Scale;
        out->value = right->value;
        right.reset();
      }
      if (kind == Expr::Kind::ShiftLeft || kind == Expr::Kind::ShiftRight) {
        if (right->kind != Expr::Kind::Constant || right->value >= 32) {
          fail(e->getExprLoc(), "shift count must be a literal in 0..31"); return nullptr;
        }
        out->value = right->value; right.reset();
      }
      out->left = std::move(left); out->right = std::move(right);
      ++region.operations;
      return out;
    }
    fail(e->getExprLoc(), "unsupported expression: " + std::string(e->getStmtClassName()));
    return nullptr;
  }
  bool block(const clang::Stmt *s, std::vector<Statement> &output) {
    if (auto *body = llvm::dyn_cast<clang::CompoundStmt>(s)) {
      for (const auto *child : body->body()) if (!statement(child, false, output, true)) return false;
      return true;
    }
    return statement(s, false, output, true);
  }
  bool statement(const clang::Stmt *s, bool final, std::vector<Statement> &output, bool nested = false) {
    if (const auto *discard = llvm::dyn_cast<clang::CStyleCastExpr>(s)) {
      if (discard->getCastKind() == clang::CK_ToVoid &&
          llvm::isa<clang::DeclRefExpr>(discard->getSubExpr()->IgnoreParenImpCasts()) &&
          expression(discard->getSubExpr())) return true;
      return fail(s->getBeginLoc(), "only a discarded pure uint32_t reference is accepted as a void cast statement");
    }
    if (auto *branch = llvm::dyn_cast<clang::IfStmt>(s)) {
      auto condition = expression(branch->getCond());
      if (!condition) return false;
      const auto before = loopBounds;
      Statement out(Statement::Kind::If, "", std::move(condition));
      if (!block(branch->getThen(), out.thenBranch)) return false;
      const auto afterThen = loopBounds; loopBounds = before;
      if (branch->getElse() && !block(branch->getElse(), out.elseBranch)) return false;
      for (auto &[name, bound] : loopBounds) bound = std::max(bound, afterThen.at(name));
      output.push_back(std::move(out)); return true;
    }
    if (auto *loop = llvm::dyn_cast<clang::ForStmt>(s)) {
      const auto *decl = llvm::dyn_cast_or_null<clang::DeclStmt>(loop->getInit());
      const auto *index = decl && decl->isSingleDecl() ? llvm::dyn_cast<clang::VarDecl>(decl->getSingleDecl()) : nullptr;
      if (!index || !u32(index->getType()) || !index->hasInit() || index->hasAttrs() || index->getStorageClass() != clang::SC_None)
        return fail(s->getBeginLoc(), "bounded for loops require a fresh uint32_t index initialized to zero");
      auto initial = expression(index->getInit());
      const auto *condition = llvm::dyn_cast_or_null<clang::BinaryOperator>(loop->getCond());
      const auto *left = condition ? llvm::dyn_cast<clang::DeclRefExpr>(condition->getLHS()->IgnoreParenImpCasts()) : nullptr;
      const auto *increment = llvm::dyn_cast_or_null<clang::UnaryOperator>(loop->getInc());
      const auto *incrementRef = increment ? llvm::dyn_cast<clang::DeclRefExpr>(increment->getSubExpr()->IgnoreParens()) : nullptr;
      if (!initial || initial->kind != Expr::Kind::Constant || initial->value != 0 || !condition ||
          condition->getOpcode() != clang::BO_LT || !left || left->getDecl() != index || !increment ||
          !increment->isIncrementOp() || !incrementRef || incrementRef->getDecl() != index)
        return fail(s->getBeginLoc(), "require for(uint32_t i=0; i<N; ++i), with literal N in 0..32");
      auto limit = expression(condition->getRHS());
      if (!limit || limit->kind != Expr::Kind::Constant || limit->value > 32)
        return fail(s->getBeginLoc(), "loop bound must be a literal in 0..32");
      const auto name = index->getNameAsString();
      if (!names.insert(name).second) return fail(index->getLocation(), "loop index must have a fresh function-wide name");
      const auto before = loopBounds;
      // A prior iteration may change every ordinary local. Only induction
      // variables are immutable throughout the body.
      for (auto &[variable, bound] : loopBounds) {
        bool invariantIndex = false;
        for (const auto *active : loopIndices) if (active->getNameAsString() == variable) invariantIndex = true;
        if (!invariantIndex) bound = UINT32_MAX;
      }
      initialized.insert(index); loopIndices.insert(index); loopBounds[name] = limit->value ? limit->value - 1 : 0;
      Statement out(Statement::Kind::Repeat, name, nullptr); out.repetitions = limit->value;
      const bool valid = block(loop->getBody(), out.thenBranch);
      initialized.erase(index); loopIndices.erase(index); loopBounds.erase(name);
      if (limit->value == 0) loopBounds = before;
      if (!valid) return false;
      output.push_back(std::move(out)); return true;
    }
    if (auto *d = llvm::dyn_cast<clang::DeclStmt>(s)) {
      if (nested) return fail(s->getBeginLoc(), "declarations inside control-flow bodies are unsupported");
      if (!d->isSingleDecl()) return fail(s->getBeginLoc(), "use a single initialized variable per declaration");
      auto *v = llvm::dyn_cast<clang::VarDecl>(d->getSingleDecl());
      if (v && ctx.getAsConstantArrayType(v->getType())) {
        const auto *type = ctx.getAsConstantArrayType(v->getType());
        const auto count = type->getSize().getLimitedValue(17);
        const auto *init = llvm::dyn_cast_or_null<clang::InitListExpr>(v->getInit());
        if (count == 0 || count > 16 || !u32(type->getElementType().getUnqualifiedType()) ||
            type->getElementType().isVolatileQualified() || !v->hasLocalStorage() ||
            v->getStorageClass() != clang::SC_None || v->hasAttrs() || !init)
          return fail(s->getBeginLoc(), "lookup arrays require 1..16 local uint32_t elements and literal initialization");
        const auto *syntactic = init->getSyntacticForm() ? init->getSyntacticForm() : init;
        for (const auto *item : syntactic->inits()) if (llvm::isa<clang::DesignatedInitExpr>(item))
          return fail(item->getBeginLoc(), "designated array initializers are unsupported");
        std::vector<uint32_t> values(size_t(count), 0);
        for (unsigned i = 0; i < init->getNumInits(); ++i) {
          if (llvm::isa<clang::ImplicitValueInitExpr>(init->getInit(i))) continue;
          auto value = expression(init->getInit(i));
          if (!value || value->kind != Expr::Kind::Constant || i >= count)
            return fail(s->getBeginLoc(), "lookup table initializers must be integer literals");
          values[i] = value->value;
        }
        arrays.emplace(v, std::move(values)); names.insert(v->getNameAsString()); return true;
      }
      if (!v || !u32(v->getType()) || !v->hasLocalStorage() || v->getStorageClass() != clang::SC_None ||
          v->hasAttrs() || v->isImplicit() || v->getName().empty())
        return fail(s->getBeginLoc(), "locals must be unqualified automatic uint32_t objects without attributes");
      if (!v->hasInit()) return fail(v->getLocation(), "local declarations require an initializer");
      auto expr = expression(v->getInit());
      if (!expr) return false;
      initialized.insert(v);
      names.insert(v->getNameAsString());
      loopBounds[v->getNameAsString()] = upperBound(*expr);
      output.push_back({Statement::Kind::Declare, v->getNameAsString(), std::move(expr)});
      return true;
    }
    if (auto *a = llvm::dyn_cast<clang::BinaryOperator>(s)) {
      if (a->getOpcode() != clang::BO_Assign) return fail(a->getExprLoc(), "only simple assignment statements are supported");
      auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(a->getLHS()->IgnoreParens());
      if (!ref || !u32(ref->getType()) || !initialized.count(ref->getDecl()))
        return fail(a->getExprLoc(), "assignment must target an initialized local uint32_t object or parameter");
      if (loopIndices.count(ref->getDecl())) return fail(a->getExprLoc(), "loop indices cannot be modified in the body");
      auto expr = expression(a->getRHS());
      if (!expr) return false;
      loopBounds[ref->getDecl()->getNameAsString()] = upperBound(*expr);
      output.push_back({Statement::Kind::Assign, ref->getDecl()->getNameAsString(), std::move(expr)});
      return true;
    }
    if (auto *r = llvm::dyn_cast<clang::ReturnStmt>(s)) {
      if (!final || !r->getRetValue()) return fail(s->getBeginLoc(), "require a single final return with a value");
      auto expr = expression(r->getRetValue());
      if (!expr) return false;
      output.push_back({Statement::Kind::Return, "", std::move(expr)});
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
      initialized.insert(p); names.insert(p->getNameAsString()); loopBounds[p->getNameAsString()] = UINT32_MAX; region.parameters.push_back(p->getNameAsString());
    }
    auto *body = llvm::dyn_cast<clang::CompoundStmt>(f.getBody());
    if (!body || body->body_empty() || !llvm::isa<clang::ReturnStmt>(body->body_back())) {
      fail(f.getLocation(), "require a supported compound body ending in a return statement"); return std::move(result);
    }
    for (auto *s : body->body()) if (!statement(s, s == body->body_back(), region.statements)) return std::move(result);
    result.region = std::move(region);
    return std::move(result);
  }
};
}
Analysis analyze(clang::ASTContext &context, const clang::FunctionDecl &function) {
  return Analyzer(context).run(function);
}
} // namespace csrd
