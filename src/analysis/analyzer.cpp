#include "csrd/analyzer.hpp"
#include "clang/AST/ASTContext.h"
#include "clang/AST/Decl.h"
#include "clang/AST/Expr.h"
#include "clang/AST/Stmt.h"
#include "clang/AST/RecordLayout.h"
#include "clang/Basic/TargetInfo.h"
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
  const CallContracts &contracts;
  const clang::FunctionDecl *currentFunction = nullptr;
  unsigned callCount = 0;
  std::unordered_set<const clang::ValueDecl *> initialized;
  std::unordered_set<const clang::ValueDecl *> loopIndices;
  std::unordered_set<std::string> names;
  std::unordered_map<const clang::ValueDecl *, std::vector<uint32_t>> arrays;
  std::unordered_map<std::string, uint32_t> loopBounds;
  std::unordered_set<const clang::ValueDecl *> pointers;
  std::unordered_set<const clang::ValueDecl *> persistent;
  // Local pointers capture an offset into one original parameter. Their
  // offsets are scalar IR declarations, frozen when the pointer is initialized.
  std::unordered_map<const clang::ValueDecl *, std::string> pointerOrigins;
  unsigned memoryExpressions = 0;

  bool fail(clang::SourceLocation loc, const std::string &why) {
    if (result.reason.empty()) { result.reason = why; result.location = loc; }
    return false;
  }
  bool u32(clang::QualType t) const {
    return !t.hasQualifiers() && ctx.hasSameType(t, ctx.UnsignedIntTy) && ctx.getTypeSize(t) == 32;
  }
  bool byte(clang::QualType t) const {
    return !t.hasQualifiers() && t->isAnyCharacterType() && ctx.getTypeSize(t) == 8 &&
           (ctx.hasSameType(t, ctx.CharTy) || ctx.hasSameType(t, ctx.SignedCharTy) ||
            ctx.hasSameType(t, ctx.UnsignedCharTy));
  }
  bool record(clang::QualType type, Region::Buffer &buffer, clang::SourceLocation loc) {
    const auto *rt = type->getAs<clang::RecordType>();
    const auto *decl = rt ? rt->getDecl()->getDefinition() : nullptr;
    if (!decl || decl->getName().empty() || decl->hasAttrs() || !decl->getDeclContext()->isFileContext())
      return fail(loc, "records require a complete named file-scope struct/union without attributes");
    const auto &layout = ctx.getASTRecordLayout(decl);
    unsigned count = 0;
    for (const auto *field : decl->fields()) {
      if (field->getName().empty() || field->isBitField() || field->hasAttrs() || !u32(field->getType()) || count >= 16)
        return fail(loc, "records require 1..16 named, unqualified uint32_t fields; no bitfields, arrays or nested records");
      const auto expected = decl->isUnion() ? 0u : count * 32u;
      if (layout.getFieldOffset(count) != expected)
        return fail(loc, "record layout contains unsupported padding or field alignment");
      buffer.fields.emplace(field->getNameAsString(), expected / 8);
      ++count;
    }
    if (!count || layout.getSize().getQuantity() != (decl->isUnion() ? 4 : count * 4) ||
        layout.getAlignment().getQuantity() != 4)
      return fail(loc, "records require padding-free uint32_t layouts with 4-byte alignment");
    buffer.recordTag = decl->getNameAsString(); buffer.isUnion = decl->isUnion();
    buffer.recordBytes = unsigned(layout.getSize().getQuantity()); buffer.recordAlignment = 4;
    buffer.elementType = "record";
    region.extendedMemory = true;
    return true;
  }
  bool collectPersistent(const clang::Stmt *s) {
    if (!s) return true;
    if (const auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(s)) {
      const auto *v = llvm::dyn_cast<clang::VarDecl>(ref->getDecl());
      if (v && v->hasGlobalStorage()) {
        if (persistent.count(v)) return true;
        if (!v->isFileVarDecl() || v->getTLSKind() != clang::VarDecl::TLS_None ||
            v->getType().hasQualifiers() || v->getName().empty())
          return fail(ref->getExprLoc(), "persistent objects require file-scope mutable uint32_t or admitted records; no local statics or TLS");
        for (const auto *d : v->redecls()) if (d->hasAttrs())
          return fail(ref->getExprLoc(), "persistent object attributes are unsupported");
        Region::Buffer buffer; buffer.persistent = true; buffer.minimumElements = 1;
        if (!u32(v->getType()) && !record(v->getType(), buffer, ref->getExprLoc())) return false;
        const auto name = v->getNameAsString();
        if (!names.insert(name).second) return fail(ref->getExprLoc(), "persistent object names cannot shadow parameters or locals");
        region.buffers.emplace(name, std::move(buffer)); persistent.insert(v);
        region.extendedMemory = true;
      }
    }
    for (const auto *child : s->children()) if (!collectPersistent(child)) return false;
    return true;
  }
  static std::unique_ptr<Expr> constant(uint32_t value) {
    auto e = std::make_unique<Expr>(Expr::Kind::Constant); e->value = value; return e;
  }
  std::unique_ptr<Expr> pointerOffset(const clang::Expr *e, std::string &name) {
    e = e->IgnoreParens();
    if (e->getBeginLoc().isMacroID() || e->getEndLoc().isMacroID()) {
      fail(e->getExprLoc(), "macro expansions are not transformed"); return nullptr;
    }
    if (const auto *cast = llvm::dyn_cast<clang::ImplicitCastExpr>(e)) {
      if (cast->getCastKind() == clang::CK_LValueToRValue || cast->getCastKind() == clang::CK_NoOp)
        return pointerOffset(cast->getSubExpr(), name);
      fail(e->getExprLoc(), "pointer reinterpretation is unsupported"); return nullptr;
    }
    if (const auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(e)) {
      if (pointers.count(ref->getDecl())) {
        name = ref->getDecl()->getNameAsString(); return constant(0);
      }
      auto found = pointerOrigins.find(ref->getDecl());
      if (found != pointerOrigins.end()) {
        name = found->second;
        auto offset = std::make_unique<Expr>(Expr::Kind::Reference);
        offset->name = ref->getDecl()->getNameAsString(); return offset;
      }
    }
    if (const auto *add = llvm::dyn_cast<clang::BinaryOperator>(e)) {
      if (add->getOpcode() == clang::BO_Add && add->getType()->isPointerType()) {
        const auto *base = add->getLHS()->getType()->isPointerType() ? add->getLHS() : add->getRHS();
        const auto *index = base == add->getLHS() ? add->getRHS() : add->getLHS();
        auto offset = pointerOffset(base, name), step = expression(index);
        if (!offset || !step) return nullptr;
        auto sum = std::make_unique<Expr>(Expr::Kind::Add);
        sum->left = std::move(offset); sum->right = std::move(step);
        if (upperBound(*sum) >= 256) {
          fail(e->getExprLoc(), "pointer offset must be statically bounded in 0..255"); return nullptr;
        }
        region.extendedMemory = true; return sum;
      }
    }
    fail(e->getExprLoc(), "pointer must derive from a buffer parameter using bounded nonnegative offsets");
    return nullptr;
  }
  bool boolean(const clang::Expr *e) const {
    const auto *b = llvm::dyn_cast<clang::BinaryOperator>(e->IgnoreParens());
    return b && b->isComparisonOp();
  }
  std::unique_ptr<Expr> access(const clang::Expr *e, bool write = false) {
    e = e->IgnoreParens();
    const clang::Expr *base = nullptr;
    auto index = constant(0);
    std::string member, name;
    if (const auto *field = llvm::dyn_cast<clang::MemberExpr>(e)) {
      if (!u32(field->getType().getUnqualifiedType()) || field->getType().isVolatileQualified()) {
        fail(e->getExprLoc(), "record access requires an ordinary uint32_t field"); return nullptr;
      }
      member = field->getMemberDecl()->getNameAsString();
      if (field->isArrow()) base = field->getBase();
      else {
        const auto *object = field->getBase()->IgnoreParens();
        if (const auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(object)) {
          if (persistent.count(ref->getDecl())) name = ref->getDecl()->getNameAsString();
        } else if (const auto *subscript = llvm::dyn_cast<clang::ArraySubscriptExpr>(object)) {
          base = subscript->getBase(); index = expression(subscript->getIdx());
        } else if (const auto *deref = llvm::dyn_cast<clang::UnaryOperator>(object)) {
          if (deref->getOpcode() == clang::UO_Deref) base = deref->getSubExpr();
        }
      }
    } else if (const auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(e)) {
      if (persistent.count(ref->getDecl()) && u32(ref->getType())) name = ref->getDecl()->getNameAsString();
    } else if (const auto *subscript = llvm::dyn_cast<clang::ArraySubscriptExpr>(e)) {
      base = subscript->getBase();
      index = expression(subscript->getIdx());
    } else if (const auto *unary = llvm::dyn_cast<clang::UnaryOperator>(e)) {
      if (unary->getOpcode() == clang::UO_Deref) base = unary->getSubExpr();
    }
    if (!base && name.empty()) { fail(e->getExprLoc(), "memory access requires a buffer subscript, record field or file-scope object"); return nullptr; }
    auto offset = base ? pointerOffset(base, name) : constant(0);
    if (!index || !offset) return nullptr;
    if (offset->kind != Expr::Kind::Constant || offset->value) {
      auto sum = std::make_unique<Expr>(Expr::Kind::Add);
      sum->left = std::move(offset); sum->right = std::move(index); index = std::move(sum);
    }
    const auto bound = upperBound(*index);
    if (bound >= 256) {
      fail(e->getExprLoc(), "buffer index must be statically bounded in 0..255"); return nullptr;
    }
    auto &buffer = region.buffers.at(name);
    if ((buffer.recordBytes && !buffer.fields.count(member)) || (!buffer.recordBytes && !member.empty())) {
      fail(e->getExprLoc(), "whole-record loads/stores and unknown fields are unsupported"); return nullptr;
    }
    if (write && buffer.readOnly) {
      fail(e->getExprLoc(), "cannot store through a const buffer parameter"); return nullptr;
    }
    buffer.minimumElements = std::max(buffer.minimumElements, unsigned(bound + 1));
    if (write) ++buffer.stores; else ++buffer.loads;
    auto out = std::make_unique<Expr>(Expr::Kind::Load);
    out->name = name; out->value = bound; out->member = member;
    if (index->kind != Expr::Kind::Constant) { out->left = std::move(index); region.extendedMemory = true; }
    if (bound >= 16) region.extendedMemory = true;
    return out;
  }
  uint32_t upperBound(const Expr &e) const {
    if (e.kind == Expr::Kind::Constant) return e.value;
    if (e.kind == Expr::Kind::Load) {
      const auto &b = region.buffers.at(e.name);
      return b.elementBits == 8 && !b.elementSigned ? 255 : UINT32_MAX;
    }
    if (e.kind == Expr::Kind::ByteCast) return e.value ? UINT32_MAX : 255;
    if (e.kind == Expr::Kind::Reference) {
      auto found = loopBounds.find(e.name);
      return found == loopBounds.end() ? UINT32_MAX : found->second;
    }
    if (e.kind == Expr::Kind::BitAnd) return std::min(upperBound(*e.left), upperBound(*e.right));
    if (e.kind == Expr::Kind::ShiftRight) return upperBound(*e.left) >> e.value;
    if (e.kind == Expr::Kind::ShiftLeft) {
      const auto bound = uint64_t(upperBound(*e.left)) << e.value;
      return bound <= UINT32_MAX ? uint32_t(bound) : UINT32_MAX;
    }
    if (e.kind == Expr::Kind::BitOr || e.kind == Expr::Kind::BitXor) {
      uint32_t bound = std::max(upperBound(*e.left), upperBound(*e.right));
      bound |= bound >> 1; bound |= bound >> 2; bound |= bound >> 4;
      bound |= bound >> 8; bound |= bound >> 16; return bound;
    }
    if (e.kind >= Expr::Kind::Equal && e.kind <= Expr::Kind::GreaterEqual) return 1;
    if (e.kind == Expr::Kind::Select) {
      // Expose a checked unsigned clamp's bound after decoding an index.
      // Translation validation still checks that the clamp preserves its value.
      if (e.left->kind == Expr::Kind::LessEqual && e.left->left->kind == Expr::Kind::Reference &&
          e.right->kind == Expr::Kind::Reference && e.left->left->name == e.right->name &&
          e.left->right->kind == Expr::Kind::Constant)
        return std::max(e.left->right->value, upperBound(*e.third));
      return std::max(upperBound(*e.right), upperBound(*e.third));
    }
    if (e.kind == Expr::Kind::Table) return *std::max_element(e.table.begin(), e.table.end());
    if (e.kind == Expr::Kind::Add || e.kind == Expr::Kind::Scale) {
      const uint64_t bound = e.kind == Expr::Kind::Add ? uint64_t(upperBound(*e.left)) + upperBound(*e.right) : uint64_t(upperBound(*e.left)) * e.value;
      if (bound <= UINT32_MAX) return uint32_t(bound);
    }
    return UINT32_MAX;
  }
  std::unique_ptr<Expr> expression(const clang::Expr *e) {
    if (region.ordered() && ++memoryExpressions > 4096) {
      fail(e->getExprLoc(), "buffer region exceeds 4096 expression visits"); return nullptr;
    }
    if (e->getBeginLoc().isMacroID() || e->getEndLoc().isMacroID()) {
      fail(e->getExprLoc(), "macro expansions are not transformed"); return nullptr;
    }
    if (auto *p = llvm::dyn_cast<clang::ParenExpr>(e)) return expression(p->getSubExpr());
    if (!region.buffers.empty()) if (auto *c = llvm::dyn_cast<clang::CastExpr>(e)) {
      const auto to = c->getType(), from = c->getSubExpr()->getType().getUnqualifiedType();
      const bool integral = c->getCastKind() == clang::CK_IntegralCast || c->getCastKind() == clang::CK_NoOp;
      const bool load = c->getCastKind() == clang::CK_LValueToRValue &&
                        !c->getSubExpr()->getType().isVolatileQualified();
      if ((integral || load) && (byte(to) || u32(to) || ctx.hasSameType(to, ctx.IntTy)) &&
          (byte(from) || u32(from) || ctx.hasSameType(from, ctx.IntTy))) {
        if (ctx.hasSameType(to, ctx.IntTy) && u32(from)) {
          fail(e->getExprLoc(), "uint32_t to signed int conversion is unsupported in memory regions"); return nullptr;
        }
        auto value = expression(c->getSubExpr());
        if (!value) return nullptr;
        if (byte(to) && !load) {
          auto out = std::make_unique<Expr>(Expr::Kind::ByteCast);
          out->value = to->isSignedIntegerType(); out->left = std::move(value);
          region.extendedMemory = true; return out;
        }
        return value;
      }
    }
    if (auto *c = llvm::dyn_cast<clang::ImplicitCastExpr>(e)) {
      bool allowed = c->getCastKind() == clang::CK_LValueToRValue && u32(c->getType()) && u32(c->getSubExpr()->getType());
      const auto *lit = llvm::dyn_cast<clang::IntegerLiteral>(c->getSubExpr()->IgnoreParens());
      if (c->getCastKind() == clang::CK_IntegralCast && u32(c->getType()) && lit &&
          ctx.hasSameType(lit->getType(), ctx.IntTy) && lit->getValue().getActiveBits() <= 31) allowed = true;
      if (c->getCastKind() == clang::CK_IntegralCast && u32(c->getType()) && boolean(c->getSubExpr())) allowed = true;
      if (c->getCastKind() == clang::CK_LValueToRValue && u32(c->getType()) &&
          llvm::isa<clang::ArraySubscriptExpr>(c->getSubExpr()->IgnoreParens()) &&
          u32(c->getSubExpr()->getType().getUnqualifiedType()) && !c->getSubExpr()->getType().isVolatileQualified()) allowed = true;
      if (!region.buffers.empty() && c->getCastKind() == clang::CK_LValueToRValue && u32(c->getType()) &&
          u32(c->getSubExpr()->getType().getUnqualifiedType()) &&
          !c->getSubExpr()->getType().isVolatileQualified() &&
          llvm::isa<clang::UnaryOperator>(c->getSubExpr()->IgnoreParens())) allowed = true;
      if (!allowed) { fail(e->getExprLoc(), "unsupported integer conversion or promotion"); return nullptr; }
      return expression(c->getSubExpr());
    }
    if (auto *table = llvm::dyn_cast<clang::ArraySubscriptExpr>(e)) {
      if (!region.buffers.empty()) return access(table);
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
    if (llvm::isa<clang::MemberExpr>(e) && !region.buffers.empty()) return access(e);
    if (auto *unary = llvm::dyn_cast<clang::UnaryOperator>(e)) {
      if (!region.buffers.empty()) {
        if (unary->getOpcode() == clang::UO_Deref) return access(unary);
        region.extendedMemory = true;
      }
      if (unary->getOpcode() != clang::UO_Not || !u32(unary->getType())) {
        fail(e->getExprLoc(), "only unsigned bitwise complement is supported as a unary expression"); return nullptr;
      }
      auto out = std::make_unique<Expr>(Expr::Kind::BitNot);
      out->left = expression(unary->getSubExpr());
      if (!out->left) return nullptr;
      ++region.operations; return out;
    }
    if (auto *conditional = llvm::dyn_cast<clang::ConditionalOperator>(e)) {
      if (!region.buffers.empty()) region.extendedMemory = true;
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
      if (persistent.count(ref->getDecl())) return access(ref);
      if (!u32(ref->getType()) || !initialized.count(ref->getDecl())) {
        fail(e->getExprLoc(), "reference must read an initialized local uint32_t object or parameter"); return nullptr;
      }
      auto out = std::make_unique<Expr>(Expr::Kind::Reference);
      out->name = ref->getDecl()->getNameAsString();
      return out;
    }
    if (auto *b = llvm::dyn_cast<clang::BinaryOperator>(e)) {
      const bool promotedBytes = !region.buffers.empty() && ctx.hasSameType(b->getType(), ctx.IntTy) &&
        ctx.hasSameType(b->getLHS()->getType(), ctx.IntTy) && ctx.hasSameType(b->getRHS()->getType(), ctx.IntTy);
      if (!promotedBytes && ((!b->isComparisonOp() && !u32(b->getType())) ||
          (b->isComparisonOp() && (!u32(b->getLHS()->getType()) || !u32(b->getRHS()->getType()))))) {
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
      if (promotedBytes) {
        const auto a = upperBound(*out->left), c = out->right ? upperBound(*out->right) : out->value;
        bool safe = a <= INT32_MAX && c <= INT32_MAX;
        if (kind == Expr::Kind::Add) safe &= uint64_t(a) + c <= INT32_MAX;
        else if (kind == Expr::Kind::Scale) safe &= uint64_t(a) * c <= INT32_MAX;
        else if (kind == Expr::Kind::ShiftLeft) safe &= (uint64_t(a) << out->value) <= INT32_MAX;
        else if (kind == Expr::Kind::Subtract) safe = false;
        if (!safe) { fail(e->getExprLoc(), "promoted byte arithmetic must stay nonnegative and within INT_MAX; cast to uint32_t for modular arithmetic"); return nullptr; }
      }
      if (!region.buffers.empty() && (promotedBytes || (kind != Expr::Kind::Add &&
          kind != Expr::Kind::Subtract && kind != Expr::Kind::Scale))) region.extendedMemory = true;
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
  static bool containsCall(const clang::Stmt *s) {
    if (!s) return false;
    if (llvm::isa<clang::CallExpr>(s)) return true;
    for (const auto *child : s->children()) if (containsCall(child)) return true;
    return false;
  }
  const clang::CallExpr *directCall(const clang::Expr *e) const {
    return llvm::dyn_cast<clang::CallExpr>(e->IgnoreParens());
  }
  bool call(const clang::CallExpr *e, const std::string &target, bool declare,
            std::vector<Statement> &output) {
    const auto *callee = e->getDirectCallee();
    const auto *reference = llvm::dyn_cast<clang::DeclRefExpr>(e->getCallee()->IgnoreParenImpCasts());
    if (!callee || !reference || reference->getDecl() != callee || callee->getBuiltinID() ||
        callee->getCanonicalDecl() == currentFunction->getCanonicalDecl())
      return fail(e->getExprLoc(), "calls require a direct nonrecursive function name (no builtins or function pointers)");
    if (e->getBeginLoc().isMacroID() || e->getEndLoc().isMacroID())
      return fail(e->getExprLoc(), "macro calls are unsupported");
    const auto name = callee->getNameAsString();
    auto contract = contracts.find(name);
    if (contract == contracts.end()) return fail(e->getExprLoc(), "direct call requires an explicit --call-contracts entry: " + name);
    const auto &spec = contract->second;
    if (++callCount > 64) return fail(e->getExprLoc(), "ordered call regions are limited to 64 calls");
    if (callee->isVariadic() || !callee->hasPrototype() || callee->getNumParams() != spec.parameters.size() ||
        e->getNumArgs() != spec.parameters.size() ||
        (spec.returnsVoid ? !callee->getReturnType()->isVoidType() : !u32(callee->getReturnType())) ||
        (spec.returnsVoid && !target.empty()))
      return fail(e->getExprLoc(), "callee signature does not match its call contract");
    for (const auto *decl : callee->redecls()) if (decl->hasAttrs())
      return fail(e->getExprLoc(), "callee attributes are unsupported by the synchronous call contract");
    Statement out(Statement::Kind::Call, target, nullptr);
    out.callee = name; out.declaresCallResult = declare;
    for (unsigned i = 0; i < e->getNumArgs(); ++i) {
      const auto &expected = spec.parameters[i];
      const auto *parameter = callee->getParamDecl(i);
      const auto type = parameter->getType();
      if (parameter->hasAttrs() || parameter->getOriginalType()->isArrayType() || type.hasQualifiers())
        return fail(e->getArg(i)->getExprLoc(), "call parameter attributes, qualifiers and array declarators are unsupported");
      Statement::Argument arg;
      if (expected.kind == "uint32") {
        if (!u32(type)) return fail(e->getExprLoc(), "call scalar parameter must be uint32_t");
        arg.value = expression(e->getArg(i));
      } else {
        if (!type->isPointerType()) return fail(e->getExprLoc(), "call contract requires a buffer pointer");
        const auto element = type->getPointeeType(), unqualified = element.getUnqualifiedType();
        const bool valid = expected.kind == "uint32-buffer" ? u32(unqualified) :
          expected.kind == "char-buffer" ? ctx.hasSameType(unqualified, ctx.CharTy) :
          expected.kind == "signed-char-buffer" ? ctx.hasSameType(unqualified, ctx.SignedCharTy) :
          ctx.hasSameType(unqualified, ctx.UnsignedCharTy);
        if (!valid || element.isConstQualified() != expected.readOnly ||
            (element.hasQualifiers() && element.getQualifiers() != clang::Qualifiers::fromCVRMask(clang::Qualifiers::Const)))
          return fail(e->getExprLoc(), "call buffer type/constness does not match its contract");
        arg.value = pointerOffset(e->getArg(i), arg.buffer);
        if (!arg.value) return false;
        auto &buffer = region.buffers.at(arg.buffer);
        if (buffer.elementType + "-buffer" != expected.kind || (buffer.readOnly && !expected.readOnly))
          return fail(e->getExprLoc(), "call cannot reinterpret or remove constness from a buffer");
        arg.bound = upperBound(*arg.value);
        const auto needed = uint64_t(arg.bound) + std::max(expected.minimumElements,
          unsigned(arg.value->kind != Expr::Kind::Constant || arg.value->value != 0));
        if (needed > 256) return fail(e->getExprLoc(), "call buffer footprint exceeds 256 elements");
        buffer.minimumElements = std::max(buffer.minimumElements, unsigned(needed));
      }
      if (!arg.value) return false;
      out.arguments.push_back(std::move(arg));
    }
    region.calls.emplace(name, spec);
    output.push_back(std::move(out));
    if (!target.empty()) loopBounds[target] = UINT32_MAX;
    return true;
  }
  bool statement(const clang::Stmt *s, bool final, std::vector<Statement> &output, bool nested = false) {
    if (const auto *e = llvm::dyn_cast<clang::Expr>(s))
      if (const auto *invoke = directCall(e)) return call(invoke, "", false, output);
    if (const auto *discard = llvm::dyn_cast<clang::CStyleCastExpr>(s)) {
      if (discard->getCastKind() == clang::CK_ToVoid)
        if (const auto *invoke = directCall(discard->getSubExpr())) return call(invoke, "", false, output);
      const auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(discard->getSubExpr()->IgnoreParenImpCasts());
      if (discard->getCastKind() == clang::CK_ToVoid && ref &&
          (pointers.count(ref->getDecl()) || pointerOrigins.count(ref->getDecl()))) return true;
      if (discard->getCastKind() == clang::CK_ToVoid &&
          llvm::isa<clang::DeclRefExpr>(discard->getSubExpr()->IgnoreParenImpCasts()) &&
          expression(discard->getSubExpr())) return true;
      return fail(s->getBeginLoc(), "only a discarded pure uint32_t reference is accepted as a void cast statement");
    }
    if (auto *branch = llvm::dyn_cast<clang::IfStmt>(s)) {
      if (region.ordered()) return fail(s->getBeginLoc(), "buffer/call regions currently require straight-line statements");
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
      if (region.ordered()) return fail(s->getBeginLoc(), "buffer/call regions currently require straight-line statements");
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
      if (v && region.buffers.count(v->getNameAsString()) && region.buffers.at(v->getNameAsString()).persistent)
        return fail(v->getLocation(), "local declarations cannot shadow referenced persistent objects");
      if (v && v->getType()->isPointerType() && !region.buffers.empty()) {
        const auto type = v->getType(), element = type->getPointeeType();
        if (type.hasQualifiers() || (!u32(element.getUnqualifiedType()) && !byte(element.getUnqualifiedType()) && !element->isRecordType()) ||
            (element.hasQualifiers() && element.getQualifiers() != clang::Qualifiers::fromCVRMask(clang::Qualifiers::Const)) ||
            !v->hasLocalStorage() || v->getStorageClass() != clang::SC_None || v->hasAttrs() || !v->hasInit())
          return fail(v->getLocation(), "local pointers require a simple initialized automatic buffer view");
        std::string origin;
        auto offset = pointerOffset(v->getInit(), origin);
        if (!offset) return false;
        const auto name = v->getNameAsString();
        pointerOrigins.emplace(v, origin); names.insert(name);
        loopBounds[name] = upperBound(*offset);
        // Even unused pointer arithmetic requires a live source object under
        // the footprint contract. One-past formation is intentionally excluded.
        auto &buffer = region.buffers.at(origin);
        if (offset->kind != Expr::Kind::Constant || offset->value)
          buffer.minimumElements = std::max(buffer.minimumElements, unsigned(loopBounds[name] + 1));
        output.push_back({Statement::Kind::Declare, name, std::move(offset)});
        region.extendedMemory = true; return true;
      }
      if (v && ctx.getAsConstantArrayType(v->getType())) {
        if (region.ordered()) return fail(s->getBeginLoc(), "local arrays are not supported inside buffer/call regions");
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
      if (const auto *invoke = directCall(v->getInit())) {
        if (!call(invoke, v->getNameAsString(), true, output)) return false;
        initialized.insert(v); names.insert(v->getNameAsString()); return true;
      }
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
      if (!region.buffers.empty() && (!ref || persistent.count(ref->getDecl()))) {
        auto location = access(a->getLHS(), true);
        auto value = expression(a->getRHS());
        if (!location || !value) return false;
        Statement store(Statement::Kind::Store, location->name, std::move(value));
        store.index = location->value; store.dynamicIndex = std::move(location->left); store.member = location->member;
        output.push_back(std::move(store)); return true;
      }
      if (!ref || !u32(ref->getType()) || !initialized.count(ref->getDecl()))
        return fail(a->getExprLoc(), "assignment must target an initialized local uint32_t object or parameter");
      if (loopIndices.count(ref->getDecl())) return fail(a->getExprLoc(), "loop indices cannot be modified in the body");
      if (const auto *invoke = directCall(a->getRHS())) return call(invoke, ref->getDecl()->getNameAsString(), false, output);
      auto expr = expression(a->getRHS());
      if (!expr) return false;
      loopBounds[ref->getDecl()->getNameAsString()] = upperBound(*expr);
      output.push_back({Statement::Kind::Assign, ref->getDecl()->getNameAsString(), std::move(expr)});
      return true;
    }
    if (auto *r = llvm::dyn_cast<clang::ReturnStmt>(s)) {
      if (!final || !r->getRetValue()) return fail(s->getBeginLoc(), "require a single final return with a value");
      if (const auto *invoke = directCall(r->getRetValue())) {
        std::string name = "csrd_call_return";
        while (!names.insert(name).second) name += "_";
        if (!call(invoke, name, true, output)) return false;
        auto value = std::make_unique<Expr>(Expr::Kind::Reference); value->name = name;
        output.push_back({Statement::Kind::Return, "", std::move(value)}); return true;
      }
      auto expr = expression(r->getRetValue());
      if (!expr) return false;
      output.push_back({Statement::Kind::Return, "", std::move(expr)});
      return true;
    }
    return fail(s->getBeginLoc(), "unsupported statement: " + std::string(s->getStmtClassName()));
  }
public:
  explicit Analyzer(clang::ASTContext &context, const CallContracts &specs) : ctx(context), contracts(specs) {}
  Analysis run(const clang::FunctionDecl &f) {
    currentFunction = &f;
    region.orderedCalls = containsCall(f.getBody());
    region.extendedMemory = region.orderedCalls;
    region.name = f.getNameAsString();
    region.littleEndian = ctx.getTargetInfo().isLittleEndian();
    if (ctx.getTypeSize(ctx.IntTy) != 32 || ctx.getTypeSize(ctx.UnsignedIntTy) != 32 || !u32(f.getReturnType()) ||
        f.isVariadic() || !f.hasWrittenPrototype()) {
      fail(f.getLocation(), "require a prototyped uint32_t function on a target with 32-bit int/unsigned int");
      return std::move(result);
    }
    for (auto *decl : f.redecls()) {
      if (decl->hasAttrs()) { fail(f.getLocation(), "function attributes are unsupported"); return std::move(result); }
    }
    for (const auto *p : f.parameters()) {
      if (p->getType()->isPointerType()) {
        const auto element = p->getType()->getPointeeType();
        if (ctx.getTypeSize(ctx.CharTy) != 8 || p->getType().hasQualifiers() ||
            (!u32(element.getUnqualifiedType()) && !byte(element.getUnqualifiedType()) && !element->isRecordType()) ||
            (element.hasQualifiers() && element.getQualifiers() != clang::Qualifiers::fromCVRMask(clang::Qualifiers::Const)) ||
            p->getOriginalType()->isArrayType() || p->hasAttrs() || p->getName().empty() || p->getStorageClass() != clang::SC_None) {
          fail(p->getLocation(), "buffer parameters require unqualified pointers to uint32_t, 8-bit characters or admitted records (optionally const); array declarators are unsupported");
          return std::move(result);
        }
        const auto name = p->getNameAsString();
        pointers.insert(p); names.insert(name); region.parameters.push_back(name);
        Region::Buffer buffer; buffer.readOnly = element.isConstQualified();
        if (element->isRecordType()) {
          if (!record(element, buffer, p->getLocation())) return std::move(result);
        } else buffer.elementBits = unsigned(ctx.getTypeSize(element));
        buffer.elementSigned = element->isSignedIntegerType();
        if (buffer.elementBits == 8) {
          region.extendedMemory = true;
          buffer.elementType = ctx.hasSameType(element.getUnqualifiedType(), ctx.CharTy) ? "char" :
            buffer.elementSigned ? "signed-char" : "unsigned-char";
        }
        region.buffers.emplace(name, buffer); continue;
      }
      if (!u32(p->getType()) || p->hasAttrs() || p->getName().empty() || p->getStorageClass() != clang::SC_None) {
        fail(p->getLocation(), "parameters must be named, unqualified uint32_t objects without attributes"); return std::move(result);
      }
      initialized.insert(p); names.insert(p->getNameAsString()); loopBounds[p->getNameAsString()] = UINT32_MAX; region.parameters.push_back(p->getNameAsString());
    }
    auto *body = llvm::dyn_cast<clang::CompoundStmt>(f.getBody());
    if (!body || body->body_empty() || !llvm::isa<clang::ReturnStmt>(body->body_back())) {
      fail(f.getLocation(), "require a supported compound body ending in a return statement"); return std::move(result);
    }
    if (!collectPersistent(body)) return std::move(result);
    for (auto *s : body->body()) if (!statement(s, s == body->body_back(), region.statements)) return std::move(result);
    result.region = std::move(region);
    return std::move(result);
  }
};
}
Analysis analyze(clang::ASTContext &context, const clang::FunctionDecl &function, const CallContracts &contracts) {
  return Analyzer(context, contracts).run(function);
}
} // namespace csrd
