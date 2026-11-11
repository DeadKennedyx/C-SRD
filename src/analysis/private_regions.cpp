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
using DeclNames = std::map<Decl, std::string>;
std::string declarationId(clang::ASTContext &ctx, Decl d) {
  return "decl@" + std::to_string(ctx.getSourceManager().getFileOffset(d->getLocation()));
}
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
    auto add = [&](const clang::VarDecl *v) {
      if (!v || v->getName().empty()) return;
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
  }
};
std::unique_ptr<Expr> expression(clang::ASTContext &ctx, const clang::Expr *e, const DeclSet &allowed,
                                 unsigned &operations, unsigned depth = 0, const DeclNames *names = nullptr) {
  if (depth > 128) throw std::invalid_argument("private expression depth budget exceeded");
  if (e->getBeginLoc().isMacroID() || e->getEndLoc().isMacroID()) throw std::invalid_argument("macro expression boundary");
  if (const auto *p = llvm::dyn_cast<clang::ParenExpr>(e)) return expression(ctx, p->getSubExpr(), allowed, operations, depth+1, names);
  if (const auto *c = llvm::dyn_cast<clang::ImplicitCastExpr>(e)) {
    bool ok = c->getCastKind() == clang::CK_LValueToRValue && u32(ctx, c->getType()) && u32(ctx, c->getSubExpr()->getType());
    const auto *literal = llvm::dyn_cast<clang::IntegerLiteral>(c->getSubExpr()->IgnoreParens());
    ok |= c->getCastKind() == clang::CK_IntegralCast && u32(ctx, c->getType()) && literal &&
          ctx.hasSameType(literal->getType(), ctx.IntTy) && literal->getValue().getActiveBits() <= 31;
    if (!ok) throw std::invalid_argument("unsupported private integer conversion");
    return expression(ctx, c->getSubExpr(), allowed, operations, depth+1, names);
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
    out->name = names ? names->at(ref->getDecl()) : declarationId(ctx, ref->getDecl()); return out;
  }
  if (const auto *b = llvm::dyn_cast<clang::BinaryOperator>(e)) {
    if (!u32(ctx, b->getType()) || (b->getOpcode() != clang::BO_Add && b->getOpcode() != clang::BO_Sub && b->getOpcode() != clang::BO_Mul))
      throw std::invalid_argument("private arithmetic initially supports unsigned addition, subtraction and literal scaling");
    auto left = expression(ctx, b->getLHS(), allowed, operations, depth+1, names);
    auto right = expression(ctx, b->getRHS(), allowed, operations, depth+1, names);
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
Statement privateStatement(clang::ASTContext &ctx, const clang::Stmt *s, const DeclSet &allowed, unsigned &operations) {
  if (const auto *d = llvm::dyn_cast<clang::DeclStmt>(s)) {
    const auto *v = d->isSingleDecl() ? llvm::dyn_cast<clang::VarDecl>(d->getSingleDecl()) : nullptr;
    if (!v || !allowed.count(v) || !v->hasInit())
      throw std::invalid_argument("private declarations require one initialized unqualified automatic uint32 object");
    auto inputs = allowed; inputs.erase(v); // Its own initializer cannot read an uninitialized object.
    return {Statement::Kind::Declare, declarationId(ctx, v), expression(ctx, v->getInit(), inputs, operations)};
  }
  const auto *a = llvm::dyn_cast<clang::BinaryOperator>(s);
  if (!a || a->getOpcode() != clang::BO_Assign) throw std::invalid_argument("private regions require plain assignments or initialized scalar declarations");
  const auto *lhs = llvm::dyn_cast<clang::DeclRefExpr>(a->getLHS()->IgnoreParens());
  if (!lhs || !allowed.count(lhs->getDecl()) || !u32(ctx, lhs->getType()))
    throw std::invalid_argument("assignment target is not a private unqualified uint32 object");
  return {Statement::Kind::Assign, declarationId(ctx, lhs->getDecl()), expression(ctx, a->getRHS(), allowed, operations)};
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
unsigned statementEnd(clang::ASTContext &ctx, const clang::Stmt *s) {
  // DeclStmt includes its semicolon; expression statements do not.
  if (llvm::isa<clang::DeclStmt>(s) || llvm::isa<clang::CompoundStmt>(s)) return tokenEnd(ctx, s->getEndLoc());
  const auto next = clang::Lexer::findNextToken(s->getEndLoc(), ctx.getSourceManager(), ctx.getLangOpts());
  if (!next || !next->is(clang::tok::semi)) throw std::invalid_argument("cannot locate private statement semicolon");
  return tokenEnd(ctx, next->getLocation());
}
bool inside(unsigned pos, const std::vector<const PrivateFrame *> &frames, bool candidate) {
  for (const auto *f : frames)
    if (pos >= (candidate ? f->candidateBegin : f->begin) && pos < (candidate ? f->candidateEnd : f->end)) return true;
  return false;
}
unsigned mapOffset(unsigned pos, const std::vector<const PrivateFrame *> &frames) {
  int64_t result = pos;
  for (const auto *f : frames) {
    if (pos >= f->begin && pos < f->end) {
      for (const auto &[id, relative] : f->emittedDeclarations)
        if (f->bindings.at(id).declaration == pos) return f->candidateBegin + relative;
      throw std::invalid_argument("unchanged context refers to an unexported declaration inside a region");
    }
    if (pos >= f->end) result += int64_t(f->emission.body.size()) - int64_t(f->end-f->begin);
  }
  if (result < 0 || uint64_t(result) > UINT32_MAX) throw std::invalid_argument("private source offset overflow");
  return unsigned(result);
}
} // namespace

PrivateDiscovery discoverPrivateRegions(clang::ASTContext &ctx, const clang::FunctionDecl &f) {
  PrivateDiscovery result;
  const PrivateObjects privateObjects(ctx, f);
  if (!privateObjects.reason.empty()) { result.reason = privateObjects.reason; return result; }
  auto &sm = ctx.getSourceManager();
  const auto source = sm.getBufferData(sm.getMainFileID());
  std::map<std::string, PrivateBinding> bindings;
  for (const auto *decl : privateObjects.objects) {
    const auto *v = llvm::cast<clang::VarDecl>(decl);
    bindings.emplace(declarationId(ctx, decl), PrivateBinding{decl->getNameAsString(), sm.getFileOffset(decl->getLocation()),
                     0, v->getStorageClass() == clang::SC_Register});
  }
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
        auto statement = privateStatement(ctx, s, privateObjects.objects, operations);
        // Bounded proof workload; splitting preserves all scalar boundaries.
        if (pending.original && (pending.original->statements.size() >= 32 ||
            pending.original->operations + operations > 256 ||
            (pending.outputs.size() == 16 && !written.count(statement.name)))) flush();
        const auto end = statementEnd(ctx, s);
        if (!pending.original) {
          pending.original = std::make_shared<Region>(); pending.original->name = f.getNameAsString();
          pending.begin = sm.getFileOffset(s->getBeginLoc());
          pending.parentBegin = sm.getFileOffset(block->getBeginLoc());
          pending.line = sm.getSpellingLineNumber(s->getBeginLoc()); pending.column = sm.getSpellingColumnNumber(s->getBeginLoc());
        }
        pending.end = end;
        references(*statement.expression, [&](const std::string &name) {
          pending.bindings.emplace(name, bindings.at(name));
          if (!written.count(name) && std::find(pending.inputs.begin(), pending.inputs.end(), name) == pending.inputs.end())
            pending.inputs.push_back(name);
        });
        pending.bindings.emplace(statement.name, bindings.at(statement.name));
        if (statement.kind == Statement::Kind::Declare) pending.declarations.push_back(statement.name);
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
  if (result.frames.empty()) result.reason = "no eligible private uint32 arithmetic regions";
  return result;
}

void preparePrivateFrames(std::vector<PrivateFrame *> frames) {
  std::sort(frames.begin(), frames.end(), [](const PrivateFrame *a, const PrivateFrame *b) { return a->begin < b->begin; });
  int64_t delta = 0;
  unsigned previousEnd = 0;
  for (auto *frame : frames) {
    if (frame->begin < previousEnd) throw std::logic_error("private source regions overlap");
    frame->candidateBegin = unsigned(int64_t(frame->begin) + delta);
    frame->candidateEnd = frame->candidateBegin + unsigned(frame->emission.body.size());
    delta += int64_t(frame->emission.body.size()) - int64_t(frame->end-frame->begin);
    previousEnd = frame->end;
  }
  const std::vector<const PrivateFrame *> edits(frames.begin(), frames.end());
  for (auto *frame : frames) {
    frame->candidateParentBegin = mapOffset(frame->parentBegin, edits);
    for (auto &[id, binding] : frame->bindings) binding.candidateDeclaration = mapOffset(binding.declaration, edits);
  }
}

std::vector<PrivateReference> privateReferences(clang::ASTContext &ctx, const clang::FunctionDecl &f) {
  std::vector<PrivateReference> refs;
  auto &sm = ctx.getSourceManager();
  walk(f.getBody(), [&](const clang::Stmt *s) {
    if (const auto *r = llvm::dyn_cast<clang::DeclRefExpr>(s)) {
      const auto *d = r->getDecl()->getCanonicalDecl();
      const auto loc = sm.getSpellingLoc(d->getLocation());
      refs.push_back({sm.getFileOffset(sm.getSpellingLoc(r->getLocation())), sm.getFileOffset(loc),
        sm.isWrittenInMainFile(loc), sm.getFilename(loc).str(), r->getDecl()->getNameAsString(), d->getDeclKindName()});
    }
  });
  return refs;
}

bool privateContextMatches(const std::vector<PrivateReference> &original, const std::vector<PrivateReference> &candidate,
                           const std::vector<const PrivateFrame *> &frames, std::string &reason) {
  try {
    std::map<unsigned, const PrivateReference *> actual;
    for (const auto &r : candidate) if (!inside(r.position, frames, true)) {
      if (!actual.emplace(r.position, &r).second) throw std::invalid_argument("ambiguous unchanged reference position");
    }
    for (const auto &r : original) if (!inside(r.position, frames, false)) {
      const auto found = actual.find(mapOffset(r.position, frames));
      if (found == actual.end()) throw std::invalid_argument("unchanged reference missing after rewriting");
      const auto &a = *found->second;
      if (r.name != a.name || r.kind != a.kind || r.mainFile != a.mainFile ||
          (!r.mainFile && r.file != a.file) || a.declaration != (r.mainFile ? mapOffset(r.declaration, frames) : r.declaration))
        throw std::invalid_argument("unchanged reference binds to a different declaration: " + r.name);
      actual.erase(found);
    }
    if (!actual.empty()) throw std::invalid_argument("additional references appeared outside rewritten regions");
    return true;
  } catch (const std::exception &e) { reason = e.what(); return false; }
}

Verification validatePrivateFrame(clang::ASTContext &ctx, const clang::FunctionDecl &f, const PrivateFrame &frame, unsigned timeoutMs) {
  Verification proof;
  try {
    auto &sm = ctx.getSourceManager();
    const PrivateObjects privateObjects(ctx, f);
    if (!privateObjects.reason.empty()) throw std::invalid_argument(privateObjects.reason);
    const clang::CompoundStmt *parent = nullptr;
    walk(f.getBody(), [&](const clang::Stmt *s) {
      const auto *block = llvm::dyn_cast<clang::CompoundStmt>(s);
      if (block && !block->getBeginLoc().isMacroID() && sm.getFileOffset(block->getBeginLoc()) == frame.candidateParentBegin) parent = block;
    });
    if (!parent) throw std::invalid_argument("emitted region changed its enclosing scope");
    std::vector<const clang::Stmt *> statements;
    for (const auto *s : parent->body()) {
      const auto begin = sm.getFileOffset(s->getBeginLoc());
      if (begin >= frame.candidateBegin && begin < frame.candidateEnd) statements.push_back(s);
    }
    if (statements.empty() || sm.getFileOffset(statements.front()->getBeginLoc()) != frame.candidateBegin ||
        statementEnd(ctx, statements.back()) != frame.candidateEnd)
      throw std::invalid_argument("emitted private statement boundary is missing or changed");
    if (frame.declarations.empty()) {
      const auto *body = statements.size() == 1 ? llvm::dyn_cast<clang::CompoundStmt>(statements[0]) : nullptr;
      if (!body) throw std::invalid_argument("emitted assignment region must be a temporary block");
      statements.assign(body->body_begin(), body->body_end());
    }
    DeclSet initialized;
    std::set<std::string> outputs(frame.outputs.begin(), frame.outputs.end()), actualOutputs;
    std::set<std::string> exported(frame.declarations.begin(), frame.declarations.end()), actualDeclarations;
    DeclNames names;
    for (const auto &[id, binding] : frame.bindings) {
      const clang::VarDecl *found = nullptr;
      for (const auto *decl : privateObjects.objects) {
        if (sm.getFileOffset(decl->getLocation()) == binding.candidateDeclaration) found = llvm::cast<clang::VarDecl>(decl);
      }
      if (!found || found->getNameAsString() != binding.name ||
          (found->getStorageClass() == clang::SC_Register) != binding.registerStorage)
        throw std::invalid_argument("private object declaration/type/storage binding changed: " + binding.name);
      if (!exported.count(id) && binding.candidateDeclaration >= frame.candidateBegin)
        throw std::invalid_argument("private external binding is not declared before the region");
      names.emplace(found, id);
      if (std::find(frame.inputs.begin(), frame.inputs.end(), id) != frame.inputs.end()) initialized.insert(found);
    }
    if (initialized.size() != frame.inputs.size()) throw std::invalid_argument("private input bindings changed");
    Region candidate; candidate.name = f.getNameAsString();
    DeclSet locals;
    for (const auto *s : statements) {
      if (const auto *cast = llvm::dyn_cast<clang::CStyleCastExpr>(s)) {
        const auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(cast->getSubExpr()->IgnoreParenImpCasts());
        if (!cast->getType()->isVoidType() || cast->getCastKind() != clang::CK_ToVoid || !ref ||
            !initialized.count(ref->getDecl()) || !names.count(ref->getDecl()) || !exported.count(names.at(ref->getDecl())))
          throw std::invalid_argument("discarded expression is not an initialized exported scalar");
        continue;
      }
      if (const auto *d = llvm::dyn_cast<clang::DeclStmt>(s)) {
        const auto *v = d->isSingleDecl() ? llvm::dyn_cast<clang::VarDecl>(d->getSingleDecl()) : nullptr;
        if (!v || !privateObjects.objects.count(v) || !v->hasInit())
          throw std::invalid_argument("emitted private local has unsupported type, storage or initialization");
        const auto mapped = names.find(v);
        if (mapped == names.end()) {
          if (v->getStorageClass() != clang::SC_None) throw std::invalid_argument("generated temporary has unsupported storage");
          names.emplace(v, "temporary@" + std::to_string(sm.getFileOffset(v->getLocation())));
          locals.insert(v);
        } else {
          if (!exported.count(mapped->second)) throw std::invalid_argument("unexpected original declaration inside region");
          actualDeclarations.insert(mapped->second); actualOutputs.insert(mapped->second);
        }
        auto value = expression(ctx, v->getInit(), initialized, candidate.operations, 0, &names);
        candidate.statements.emplace_back(Statement::Kind::Declare, names.at(v), std::move(value));
        initialized.insert(v);
      } else {
        unsigned unused = 0;
        const auto *a = llvm::dyn_cast<clang::BinaryOperator>(s);
        if (!a || a->getOpcode() != clang::BO_Assign) throw std::invalid_argument("emitted region contains an unsupported statement or effect");
        const auto *ref = llvm::dyn_cast<clang::DeclRefExpr>(a->getLHS()->IgnoreParens());
        if (!ref || !names.count(ref->getDecl())) throw std::invalid_argument("emitted assignment escapes its scalar frame");
        const auto &id = names.at(ref->getDecl());
        if (!locals.count(ref->getDecl()) && !outputs.count(id))
          throw std::invalid_argument("emitted region writes a non-output object");
        auto value = expression(ctx, a->getRHS(), initialized, unused, 0, &names); candidate.operations += unused;
        candidate.statements.emplace_back(Statement::Kind::Assign, id, std::move(value));
        initialized.insert(ref->getDecl());
        if (!locals.count(ref->getDecl())) actualOutputs.insert(id);
      }
    }
    if (actualOutputs != outputs || actualDeclarations != exported) throw std::invalid_argument("emitted region omits an output or its enclosing-scope declaration");
    appendFrameOutputs(candidate, frame);
    proof = verifyMemory(*frame.original, candidate, timeoutMs);
    proof.strategy = "private-scalar-frame/" + proof.strategy;
    if (proof.status == "proved-under-model") proof.reason = "all written scalar outputs equal for every uint32 input; surrounding effects are unchanged under private-object assumptions";
  } catch (const std::exception &e) { proof.status = "unsupported"; proof.reason = e.what(); }
  return proof;
}
} // namespace csrd
