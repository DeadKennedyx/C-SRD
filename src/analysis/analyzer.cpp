#include "csrd/analyzer.hpp"
#include "clang/AST/ASTContext.h"
#include "clang/AST/Decl.h"
#include "clang/AST/Attr.h"
#include "clang/AST/Expr.h"
#include "clang/AST/Stmt.h"
#include "clang/AST/RecordLayout.h"
#include "clang/Basic/TargetInfo.h"
#include "clang/Basic/SourceManager.h"
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
  std::unordered_set<const clang::ValueDecl *> heapPointers;
  std::unordered_set<const clang::ValueDecl *> functionPointers;
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
  static bool allocatorName(const std::string &name) {
    return name == "malloc" || name == "calloc" || name == "realloc" || name == "free";
  }
  static const clang::CallExpr *allocatorCall(const clang::Expr *e) {
    e = e->IgnoreParens();
    if (const auto *cast = llvm::dyn_cast<clang::ImplicitCastExpr>(e)) {
      if (cast->getCastKind() == clang::CK_BitCast || cast->getCastKind() == clang::CK_NoOp)
        e = cast->getSubExpr()->IgnoreParens();
    }
    const auto *call = llvm::dyn_cast<clang::CallExpr>(e);
    return call && call->getDirectCallee() && allocatorName(call->getDirectCallee()->getNameAsString()) ? call : nullptr;
  }
  bool heapExpression(const clang::Expr *e) const {
    e = e->IgnoreParenImpCasts();
    if (const auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(e)) return heapPointers.count(ref->getDecl());
    if (const auto *lit = llvm::dyn_cast<clang::IntegerLiteral>(e)) return lit->getValue() == 0;
    if (const auto *add = llvm::dyn_cast<clang::BinaryOperator>(e))
      return add->getOpcode() == clang::BO_Add && add->getType()->isPointerType() &&
        heapExpression(add->getLHS()->getType()->isPointerType() ? add->getLHS() : add->getRHS());
    return allocatorCall(e);
  }
  std::unique_ptr<Expr> heapPointer(const clang::Expr *e, std::string &name, bool &arithmetic) {
    if (e->getBeginLoc().isMacroID() || e->getEndLoc().isMacroID()) {
      fail(e->getExprLoc(), "macro expansions are not transformed"); return nullptr;
    }
    e = e->IgnoreParens();
    if (const auto *cast = llvm::dyn_cast<clang::ImplicitCastExpr>(e)) {
      if (cast->getCastKind() == clang::CK_LValueToRValue || cast->getCastKind() == clang::CK_NoOp ||
          cast->getCastKind() == clang::CK_NullToPointer ||
          (cast->getCastKind() == clang::CK_BitCast && cast->getType()->isVoidPointerType()))
        return heapPointer(cast->getSubExpr(), name, arithmetic);
    }
    if (const auto *lit = llvm::dyn_cast<clang::IntegerLiteral>(e)) {
      if (lit->getValue() == 0) { name.clear(); return constant(0); }
    }
    if (const auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(e)) if (heapPointers.count(ref->getDecl())) {
      name = ref->getDecl()->getNameAsString(); return constant(0);
    }
    if (const auto *add = llvm::dyn_cast<clang::BinaryOperator>(e)) {
      if (add->getOpcode() == clang::BO_Add && add->getType()->isPointerType()) {
        const auto *base = add->getLHS()->getType()->isPointerType() ? add->getLHS() : add->getRHS();
        auto out = std::make_unique<Expr>(Expr::Kind::Add);
        out->left = heapPointer(base, name, arithmetic);
        out->right = expression(base == add->getLHS() ? add->getRHS() : add->getLHS());
        arithmetic = true;
        if (out->left && out->right && upperBound(*out) <= 32) return out;
      }
    }
    fail(e->getExprLoc(), "owned pointer must be null, a live owned handle, or a bounded view of it"); return nullptr;
  }
  bool integerConstant(const clang::Expr *e, uint64_t &value) const {
    if (e->getBeginLoc().isMacroID() || e->getEndLoc().isMacroID() || e->HasSideEffects(ctx)) return false;
    clang::Expr::EvalResult evaluated;
    if (!e->EvaluateAsInt(evaluated, ctx) || evaluated.HasUndefinedBehavior) return false;
    const auto &n = evaluated.Val.getInt();
    if ((n.isSigned() && n.isNegative()) || n.getActiveBits() > 32) return false;
    value = n.getZExtValue(); return true;
  }
  std::unique_ptr<Expr> allocationCount(const clang::Expr *e, bool bytes) {
    uint64_t fixed;
    if (integerConstant(e, fixed)) {
      if ((!bytes || fixed % 4 == 0) && fixed / (bytes ? 4 : 1) <= 32)
        return constant(uint32_t(fixed / (bytes ? 4 : 1)));
    } else {
      e = e->IgnoreParens();
      if (const auto *cast = llvm::dyn_cast<clang::ImplicitCastExpr>(e))
        if (cast->getCastKind() == clang::CK_IntegralCast &&
            ctx.hasSameType(cast->getType(), ctx.getSizeType()) && u32(cast->getSubExpr()->getType()))
          e = cast->getSubExpr()->IgnoreParens();
      if (bytes) {
        if (const auto *mul = llvm::dyn_cast<clang::BinaryOperator>(e)) if (mul->getOpcode() == clang::BO_Mul) {
          const clang::Expr *count = nullptr;
          if (integerConstant(mul->getRHS(), fixed) && fixed == 4) count = mul->getLHS();
          else if (integerConstant(mul->getLHS(), fixed) && fixed == 4) count = mul->getRHS();
          if (count) return allocationCount(count, false);
        }
      } else {
        auto out = expression(e);
        if (out && upperBound(*out) <= 32) return out;
      }
    }
    fail(e->getExprLoc(), "allocation requires 0..32 uint32_t elements and an exact multiple of sizeof(uint32_t)"); return nullptr;
  }
  bool allocate(const clang::CallExpr *e, const std::string &target, bool declare,
                std::vector<Statement> &output) {
    const auto *f = e->getDirectCallee();
    const auto name = f->getNameAsString();
    const bool release = name == "free", resize = name == "realloc", zero = name == "calloc";
    const unsigned arity = resize || zero ? 2 : 1;
    const auto *reference = llvm::dyn_cast<clang::DeclRefExpr>(e->getCallee()->IgnoreParenImpCasts());
    if (e->getBeginLoc().isMacroID() || e->getEndLoc().isMacroID() || !reference || reference->getDecl() != f ||
        f->hasBody() || f->getStorageClass() == clang::SC_Static || f->isVariadic() || !f->hasPrototype() ||
        f->getNumParams() != arity || e->getNumArgs() != arity ||
        !(release ? f->getReturnType()->isVoidType() : ctx.hasSameType(f->getReturnType(), ctx.VoidPtrTy)))
      return fail(e->getExprLoc(), "allocation requires direct standard-library declarations, with no local definition or macro expansion");
    for (unsigned i = 0; i < arity; ++i) {
      const auto expected = i == 0 && (release || resize) ? ctx.VoidPtrTy : ctx.getSizeType();
      if (!ctx.hasSameType(f->getParamDecl(i)->getType(), expected))
        return fail(e->getExprLoc(), "allocator prototype does not match the C11 library signature");
    }
    // Preprocessed inputs no longer retain system-header source locations.
    // Admit only metadata consistent with these standard allocator contracts.
    for (const auto *decl : f->redecls()) for (const auto *attr : decl->attrs()) {
      if (llvm::isa<clang::BuiltinAttr,clang::NoThrowAttr,clang::LeafAttr,clang::WarnUnusedResultAttr>(attr)) continue;
      if (llvm::isa<clang::RestrictAttr>(attr) && !release && !resize) continue;
      if (const auto *size=llvm::dyn_cast<clang::AllocSizeAttr>(attr)) {
        const auto first=size->getElemSizeParam(), second=size->getNumElemsParam();
        if (!release && first.getASTIndex()==(resize ? 1u : 0u) &&
            (zero ? second.isValid() && second.getASTIndex()==1u : !second.isValid())) continue;
      }
      return fail(e->getExprLoc(), "allocator attribute is outside the standard allocation contract");
    }
    if ((release && !target.empty()) || (!release && target.empty()))
      return fail(e->getExprLoc(), "allocation results require an owned uint32_t pointer binding");
    Statement out(release ? Statement::Kind::Release : Statement::Kind::Allocate, target, nullptr);
    out.callee = name; out.declaresCallResult = declare;
    if (release || resize) {
      bool arithmetic = false;
      auto offset = heapPointer(e->getArg(0), out.pointer, arithmetic);
      if (!offset || arithmetic) return fail(e->getExprLoc(), "free/realloc require an owned base handle or null");
    }
    if (!release) {
      if (zero) {
        uint64_t width;
        const bool ordinary = integerConstant(e->getArg(1), width) && width == 4;
        const bool swapped = !ordinary && integerConstant(e->getArg(0), width) && width == 4;
        if (!ordinary && !swapped) return fail(e->getExprLoc(), "calloc requires a uint32_t element size");
        out.callocSwapped = swapped;
        out.expression = allocationCount(e->getArg(swapped ? 1 : 0), false);
      } else out.expression = allocationCount(e->getArg(resize ? 1 : 0), true);
      if (!out.expression) return false;
      out.index = upperBound(*out.expression);
    }
    output.push_back(std::move(out)); return true;
  }
  bool bindHeap(const clang::Expr *e, const std::string &target, bool declare,
                std::vector<Statement> &output) {
    if (const auto *invoke = allocatorCall(e)) return allocate(invoke, target, declare, output);
    Statement out(Statement::Kind::PointerBind, target, nullptr);
    out.declaresCallResult = declare;
    out.expression = heapPointer(e, out.pointer, out.pointerArithmetic);
    if (!out.expression) return false;
    out.index = upperBound(*out.expression);
    output.push_back(std::move(out)); return true;
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
      if (heapPointers.count(ref->getDecl())) {
        name = ref->getDecl()->getNameAsString(); return constant(0);
      }
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
    if (e.kind == Expr::Kind::PointerNonNull) return 1;
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
    if (region.ownedHeap) {
      if (e->getType()->isPointerType() && heapExpression(e)) {
        std::string pointer; bool arithmetic = false;
        auto offset = heapPointer(e, pointer, arithmetic);
        if (!offset || arithmetic) { fail(e->getExprLoc(), "pointer conditions require a captured owned handle"); return nullptr; }
        if (pointer.empty()) return constant(0);
        auto out = std::make_unique<Expr>(Expr::Kind::PointerNonNull); out->name = pointer; return out;
      }
      if (const auto *unary = llvm::dyn_cast<clang::UnaryOperator>(e))
        if (unary->getOpcode() == clang::UO_LNot && unary->getSubExpr()->getType()->isPointerType()) {
          auto out = std::make_unique<Expr>(Expr::Kind::Equal);
          out->left = expression(unary->getSubExpr()); out->right = constant(0);
          if (!out->left) return nullptr;
          return out;
        }
      if (const auto *binary = llvm::dyn_cast<clang::BinaryOperator>(e))
        if ((binary->getOpcode() == clang::BO_EQ || binary->getOpcode() == clang::BO_NE) &&
            binary->getLHS()->getType()->isPointerType() && binary->getRHS()->getType()->isPointerType()) {
          const auto null = [&](const clang::Expr *p) {
            const auto *lit = llvm::dyn_cast<clang::IntegerLiteral>(p->IgnoreParenImpCasts());
            return lit && lit->getValue() == 0;
          };
          if (!null(binary->getLHS()) && !null(binary->getRHS())) {
            fail(e->getExprLoc(), "owned pointers can only be compared with null"); return nullptr;
          }
          auto out = std::make_unique<Expr>(binary->getOpcode() == clang::BO_EQ ? Expr::Kind::Equal : Expr::Kind::NotEqual);
          out->left = expression(null(binary->getLHS()) ? binary->getRHS() : binary->getLHS());
          out->right = constant(0);
          if (!out->left) return nullptr;
          return out;
        }
    }
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
    const auto before = initialized;
    const auto bounds = loopBounds;
    bool valid = true;
    if (auto *body = llvm::dyn_cast<clang::CompoundStmt>(s)) {
      for (const auto *child : body->body()) if (!statement(child, false, output, true)) { valid = false; break; }
    } else valid = statement(s, false, output, true);
    initialized = before;
    for (auto i = loopBounds.begin(); i != loopBounds.end();) {
      if (!bounds.count(i->first)) i = loopBounds.erase(i); else ++i;
    }
    return valid;
  }
  static bool limitReferences(const Expr &e, std::unordered_set<std::string> &references) {
    if (e.kind == Expr::Kind::Load || e.kind == Expr::Kind::PointerNonNull) return false;
    if (e.kind == Expr::Kind::Reference) references.insert(e.name);
    for (const auto *child : {e.left.get(), e.right.get(), e.third.get()})
      if (child && !limitReferences(*child, references)) return false;
    return true;
  }
  static bool changesLimit(const clang::Stmt *s, const std::unordered_set<std::string> &references) {
    if (!s) return false;
    const clang::Expr *target = nullptr;
    if (const auto *a = llvm::dyn_cast<clang::BinaryOperator>(s)) if (a->isAssignmentOp()) target = a->getLHS();
    if (const auto *a = llvm::dyn_cast<clang::UnaryOperator>(s)) if (a->isIncrementDecrementOp()) target = a->getSubExpr();
    if (target) if (const auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(target->IgnoreParenImpCasts()))
      if (references.count(ref->getDecl()->getNameAsString())) return true;
    for (const auto *child : s->children()) if (changesLimit(child, references)) return true;
    return false;
  }
  static bool containsCall(const clang::Stmt *s, bool allocation = false) {
    if (!s) return false;
    if (const auto *call = llvm::dyn_cast<clang::CallExpr>(s)) {
      const bool allocator = call->getDirectCallee() && allocatorName(call->getDirectCallee()->getNameAsString());
      if (allocator == allocation) return true;
    }
    for (const auto *child : s->children()) if (containsCall(child, allocation)) return true;
    return false;
  }
  const clang::CallExpr *directCall(const clang::Expr *e) const {
    return llvm::dyn_cast<clang::CallExpr>(e->IgnoreParens());
  }
  bool callSignature(const clang::FunctionProtoType *type, const CallContract &spec, clang::SourceLocation loc) {
    if (!type || type->isVariadic() || type->getNumParams()!=spec.parameters.size() ||
        type->getExtInfo()!=clang::FunctionType::ExtInfo() || type->hasExtParameterInfos() ||
        (spec.returnsVoid ? !type->getReturnType()->isVoidType() : !u32(type->getReturnType())))
      return fail(loc,"callee signature or calling convention does not match its contract");
    for (unsigned i=0;i<spec.parameters.size();++i) {
      const auto parameter=type->getParamType(i); const auto &expected=spec.parameters[i];
      if (parameter.hasQualifiers()) return fail(loc,"qualified call parameter types are unsupported");
      if (expected.kind=="uint32") {
        if (!u32(parameter)) return fail(loc,"call scalar parameter must be uint32_t");
      } else {
        if (!parameter->isPointerType()) return fail(loc,"call contract requires a buffer pointer");
        const auto element=parameter->getPointeeType(), plain=element.getUnqualifiedType();
        const bool valid=expected.kind=="uint32-buffer" ? u32(plain) :
          expected.kind=="char-buffer" ? ctx.hasSameType(plain,ctx.CharTy) :
          expected.kind=="signed-char-buffer" ? ctx.hasSameType(plain,ctx.SignedCharTy) : ctx.hasSameType(plain,ctx.UnsignedCharTy);
        if (!valid || element.isConstQualified()!=expected.readOnly ||
            (element.hasQualifiers() && element.getQualifiers()!=clang::Qualifiers::fromCVRMask(clang::Qualifiers::Const)))
          return fail(loc,"call buffer type/constness does not match its contract");
      }
    }
    return true;
  }
  bool call(const clang::CallExpr *e, const std::string &target, bool declare,
            std::vector<Statement> &output) {
    const auto *callee = e->getDirectCallee();
    const auto *reference = llvm::dyn_cast<clang::DeclRefExpr>(e->getCallee()->IgnoreParenImpCasts());
    const bool indirect=!callee && reference && functionPointers.count(reference->getDecl());
    const bool recursive=callee && callee->getCanonicalDecl()==currentFunction->getCanonicalDecl();
    if (!reference || (!indirect && (!callee || reference->getDecl()!=callee || callee->getBuiltinID())))
      return fail(e->getExprLoc(),"calls require a declared function or a contracted function-pointer parameter");
    if (e->getBeginLoc().isMacroID() || e->getEndLoc().isMacroID())
      return fail(e->getExprLoc(), "macro calls are unsupported");
    const auto indirectName=indirect ? reference->getDecl()->getNameAsString() : "";
    const auto name = indirect ? region.functionPointers.at(indirectName) : callee->getNameAsString();
    auto contract = contracts.find(name);
    if (contract == contracts.end()) return fail(e->getExprLoc(), "direct call requires an explicit --call-contracts entry: " + name);
    const auto &spec = contract->second;
    if (recursive && (!spec.recursive || !spec.guarded))
      return fail(e->getExprLoc(),"self-recursion requires its own explicit guarded decreasing-rank contract");
    if (indirect && (!spec.guarded || spec.indirectParameter!=indirectName))
      return fail(e->getExprLoc(),"indirect call does not match its function-scoped parameter contract");
    if (++callCount > 64) return fail(e->getExprLoc(), "ordered call regions are limited to 64 calls");
    const auto type=indirect ? reference->getDecl()->getType()->getPointeeType() : callee->getType();
    const auto *prototype=type->getAs<clang::FunctionProtoType>();
    if (!callSignature(prototype,spec,e->getExprLoc()) || e->getNumArgs()!=spec.parameters.size() || (spec.returnsVoid && !target.empty()))
      return fail(e->getExprLoc(), "callee signature does not match its call contract");
    if (callee) for (const auto *decl : callee->redecls()) if (decl->hasAttrs())
      return fail(e->getExprLoc(), "callee attributes are unsupported by the synchronous call contract");
    Statement out(Statement::Kind::Call, target, nullptr);
    out.callee = name; out.declaresCallResult = declare; out.indirectTarget=indirectName; out.recursiveCall=recursive;
    for (unsigned i = 0; i < e->getNumArgs(); ++i) {
      const auto &expected = spec.parameters[i];
      const auto *parameter = callee ? callee->getParamDecl(i) : nullptr;
      const auto type = prototype->getParamType(i);
      if (parameter && (parameter->hasAttrs() || parameter->getOriginalType()->isArrayType() || type.hasQualifiers()))
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
    if (recursive) region.recursiveContract=name;
    output.push_back(std::move(out));
    if (!target.empty()) loopBounds[target] = UINT32_MAX;
    return true;
  }
  bool statement(const clang::Stmt *s, bool final, std::vector<Statement> &output, bool nested = false) {
    if (const auto *e = llvm::dyn_cast<clang::Expr>(s)) {
      if (const auto *invoke = allocatorCall(e)) return allocate(invoke, "", false, output);
      if (const auto *invoke = directCall(e)) return call(invoke, "", false, output);
    }
    if (const auto *discard = llvm::dyn_cast<clang::CStyleCastExpr>(s)) {
      if (discard->getCastKind() == clang::CK_ToVoid)
        if (const auto *invoke = directCall(discard->getSubExpr())) return call(invoke, "", false, output);
      const auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(discard->getSubExpr()->IgnoreParenImpCasts());
      if (ref && heapPointers.count(ref->getDecl()))
        return fail(s->getBeginLoc(), "discarded owned pointer reads require an explicit lifetime-checked use");
      if (discard->getCastKind() == clang::CK_ToVoid && ref &&
          (pointers.count(ref->getDecl()) || pointerOrigins.count(ref->getDecl()) || functionPointers.count(ref->getDecl()))) return true;
      if (discard->getCastKind() == clang::CK_ToVoid &&
          llvm::isa<clang::DeclRefExpr>(discard->getSubExpr()->IgnoreParenImpCasts()) &&
          expression(discard->getSubExpr())) return true;
      return fail(s->getBeginLoc(), "only a discarded pure uint32_t reference is accepted as a void cast statement");
    }
    if (auto *branch = llvm::dyn_cast<clang::IfStmt>(s)) {
      if (region.orderedCalls && !region.guardedCalls) return fail(s->getBeginLoc(), "sequenced-v1 call contracts require straight-line statements");
      if (region.ordered()) region.memoryControl = true;
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
      if (region.orderedCalls && !region.guardedCalls) return fail(s->getBeginLoc(), "sequenced-v1 call contracts require straight-line statements");
      if (region.ordered()) region.memoryControl = true;
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
      if (!limit) return false;
      const auto maximum = upperBound(*limit);
      if (maximum > 32 || (!region.ordered() && limit->kind != Expr::Kind::Constant))
        return fail(s->getBeginLoc(), "loop bound must be a literal or admitted memory-region scalar expression bounded in 0..32");
      std::unordered_set<std::string> references;
      if (!limitReferences(*limit, references) || changesLimit(loop->getBody(), references))
        return fail(s->getBeginLoc(), "runtime loop bounds require immutable scalar expressions without memory loads");
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
      initialized.insert(index); loopIndices.insert(index); loopBounds[name] = maximum ? maximum - 1 : 0;
      Statement out(Statement::Kind::Repeat, name, nullptr); out.repetitions = maximum;
      if (region.ordered()) out.expression = std::move(limit);
      const bool valid = block(loop->getBody(), out.thenBranch);
      initialized.erase(index); loopIndices.erase(index); loopBounds.erase(name);
      if (maximum == 0) loopBounds = before;
      if (!valid) return false;
      output.push_back(std::move(out)); return true;
    }
    if (auto *d = llvm::dyn_cast<clang::DeclStmt>(s)) {
      if (nested && (!region.ordered() || (region.orderedCalls && !region.guardedCalls))) return fail(s->getBeginLoc(), "declarations inside these control-flow bodies are unsupported");
      if (!d->isSingleDecl()) return fail(s->getBeginLoc(), "use a single initialized variable per declaration");
      auto *v = llvm::dyn_cast<clang::VarDecl>(d->getSingleDecl());
      if (v && region.ordered() && names.count(v->getNameAsString()))
        return fail(v->getLocation(), "ordered-region local names must be fresh throughout the function");
      if (v && region.buffers.count(v->getNameAsString()) && region.buffers.at(v->getNameAsString()).persistent)
        return fail(v->getLocation(), "local declarations cannot shadow referenced persistent objects");
      if (v && v->getType()->isPointerType() && region.ownedHeap && v->hasInit() && heapExpression(v->getInit())) {
        if (v->getType().hasQualifiers() || !u32(v->getType()->getPointeeType()) ||
            !v->hasLocalStorage() || v->getStorageClass() != clang::SC_None || v->hasAttrs())
          return fail(v->getLocation(), "owned heap locals require unqualified automatic uint32_t pointers");
        const auto name = v->getNameAsString();
        if (!bindHeap(v->getInit(), name, true, output)) return false;
        Region::Buffer buffer; buffer.heap = true;
        region.buffers.emplace(name, buffer); heapPointers.insert(v); names.insert(name); return true;
      }
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
      if (ref && heapPointers.count(ref->getDecl()))
        return bindHeap(a->getRHS(), ref->getDecl()->getNameAsString(), false, output);
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
      if (!r->getRetValue() || (!final && (!region.ordered() || (region.orderedCalls && !region.guardedCalls))))
        return fail(s->getBeginLoc(), "early returns require memory or guarded call regions; every return needs a value");
      if (!final) region.memoryControl = true;
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
    region.guardedCalls = region.orderedCalls && std::any_of(contracts.begin(),contracts.end(),
      [](const auto &entry) { return entry.second.guarded; });
    region.ownedHeap = containsCall(f.getBody(), true);
    region.extendedMemory = region.orderedCalls || region.ownedHeap;
    region.memoryControl = region.ownedHeap || region.guardedCalls;
    if (region.ownedHeap && ctx.getTypeSize(ctx.CharTy) != 8) {
      fail(f.getLocation(), "owned uint32_t heaps require 8-bit bytes"); return std::move(result);
    }
    if (region.ownedHeap && region.orderedCalls) {
      fail(f.getLocation(), "owned heap regions cannot mix allocation with opaque calls or escaping pointers"); return std::move(result);
    }
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
      if (p->getType()->isFunctionPointerType()) {
        if (region.ownedHeap) { fail(p->getLocation(),"owned heaps cannot be combined with function-pointer parameters");return std::move(result); }
        const auto name=p->getNameAsString(), key=indirectContractKey(region.name,name);
        const auto found=contracts.find(key);
        if (found==contracts.end() || !found->second.guarded) {
          fail(p->getLocation(),"function-pointer parameter requires an explicit guarded contract: "+key);return std::move(result);
        }
        if (p->getType().hasQualifiers() || p->hasAttrs() || name.empty() || p->getStorageClass()!=clang::SC_None ||
            !callSignature(p->getType()->getPointeeType()->getAs<clang::FunctionProtoType>(),found->second,p->getLocation())) {
          fail(p->getLocation(),"require an unqualified ordinary C function-pointer parameter");return std::move(result);
        }
        functionPointers.insert(p);names.insert(name);region.parameters.push_back(name);
        region.functionPointers.emplace(name,key);region.calls.emplace(key,found->second);
        region.orderedCalls=region.guardedCalls=region.memoryControl=region.extendedMemory=true;
        continue;
      }
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
    if (!region.recursiveContract.empty()) {
      const auto &spec=region.calls.at(region.recursiveContract);
      for (unsigned i=0;i<region.parameters.size();++i) {
        const auto buffer=region.buffers.find(region.parameters[i]);
        if (buffer!=region.buffers.end() && buffer->second.minimumElements>spec.parameters.at(i).minimumElements) {
          fail(f.getLocation(),"recursive call contract understates the function's own buffer footprint");return std::move(result);
        }
      }
    }
    result.region = std::move(region);
    return std::move(result);
  }
};
}
Analysis analyze(clang::ASTContext &context, const clang::FunctionDecl &function, const CallContracts &contracts) {
  return Analyzer(context, contracts).run(function);
}
} // namespace csrd
