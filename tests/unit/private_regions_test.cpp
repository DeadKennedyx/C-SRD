#include "csrd/private_regions.hpp"
#include "clang/AST/ASTContext.h"
#include "clang/AST/Decl.h"
#include "clang/Frontend/ASTUnit.h"
#include "clang/Tooling/Tooling.h"
#include <iostream>
#include <stdexcept>

namespace {
void require(bool condition, const std::string &message) { if (!condition) throw std::runtime_error(message); }
std::unique_ptr<clang::ASTUnit> parse(const std::string &source) {
  auto ast = clang::tooling::buildASTFromCodeWithArgs(source, {"-std=c11", "-pedantic-errors"}, "frame.c");
  require(bool(ast) && !ast->getDiagnostics().hasErrorOccurred(), "test C must parse"); return ast;
}
const clang::FunctionDecl &function(clang::ASTUnit &ast) {
  for (const auto *d : ast.getASTContext().getTranslationUnitDecl()->decls())
    if (const auto *f = llvm::dyn_cast<clang::FunctionDecl>(d))
      if (f->getName() == "f" && f->doesThisDeclarationHaveABody()) return *f;
  throw std::runtime_error("missing f");
}
csrd::Verification grade(const std::string &source, csrd::PrivateFrame frame, const std::string &body) {
  const auto candidate = source.substr(0, frame.begin) + body + source.substr(frame.end);
  frame.candidateBegin = frame.begin; frame.candidateEnd = frame.begin + unsigned(body.size());
  auto ast = parse(candidate);
  return csrd::validatePrivateFrame(ast->getASTContext(), function(*ast), frame, 10000);
}
}
int main() {
  try {
    const std::string source = "unsigned int global; extern void sink(unsigned int); int f(unsigned int x,unsigned int y){x=x+y;y=3u*x+11u;sink(y);return 0;}\n";
    auto ast = parse(source);
    auto discovery = csrd::discoverPrivateRegions(ast->getASTContext(), function(*ast));
    require(discovery.frames.size() == 1, "one arithmetic frame required");
    const auto frame = discovery.frames[0];
    require(frame.inputs == std::vector<std::string>({"x", "y"}) && frame.outputs == frame.inputs, "frame must track both outputs");
    for (const auto seed : {uint64_t(0), uint64_t(42), UINT64_MAX}) {
      const auto affine = csrd::Affine::fromSeed(seed, "f");
      const auto emitted = csrd::emitPrivateFrame(frame, affine, {"x", "y"});
      require(grade(source, frame, emitted.body).status == "proved-under-model", "reparsed affine frame failed");
      require(emitted.encodedOperations == 3 && emitted.boundaryConversions == 4, "multi-operation encoded accounting");
    }
    csrd::Identity identity;
    require(grade(source, frame, csrd::emitPrivateFrame(frame, identity, {}).body).status == "proved-under-model", "identity frame failed");
    const auto wrong = grade(source, frame, "{x=x+y;y=3u*x+12u;}");
    require(wrong.status == "counterexample" && wrong.originalOutput == wrong.candidateOutput, "wrong scalar output needs memory-only counterexample");
    require(!wrong.memoryCells.empty(), "counterexample must report frame output state");
    for (const auto &bad : {"{x=x+y;}", "{x=x+y;y=3u*x+11u;global=x;}",
                           "{x=x+y;y=3u*x+11u;sink(y);}", "{x=x+y;y=3u*x+11u;return 0;}",
                           "{unsigned int t;t=t+1u;x=x+y;y=t;}",
                           "{unsigned int t=x+1u;x=x+y;y=(unsigned int)(double)t;}"})
      require(grade(source, frame, bad).status == "unsupported", "effect/omitted output/unmodeled arithmetic accepted");

    const std::string overwrite = "unsigned int f(unsigned int x){unsigned int y;y=7u;x=y+3u;return x;}\n";
    auto other = parse(overwrite);
    auto d = csrd::discoverPrivateRegions(other->getASTContext(), function(*other));
    require(d.frames.size() == 1 && d.frames[0].inputs.empty(), "overwritten uninitialized locals must not be captured");
    require(grade(overwrite, d.frames[0], csrd::emitPrivateFrame(d.frames[0], csrd::Affine::fromSeed(42,"f"), {}).body).status == "proved-under-model", "write-only initialization frame failed");
    std::cout << "PASS private frame proofs, scalar-state counterexample and six effect/initialization controls\n";
  } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
