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
  frame.emission.body = body; csrd::preparePrivateFrames({&frame});
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
    auto frame = discovery.frames[0];
    require(frame.inputs.size() == 2 && frame.bindings.at(frame.inputs[0]).name == "x" &&
            frame.bindings.at(frame.inputs[1]).name == "y" && frame.outputs == frame.inputs, "frame must track both outputs");
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
    // Declarations remain visible across effects and later frames; same-spelled
    // outer and inner objects have distinct output identities.
    const std::string declarations = "extern void sink(unsigned int);unsigned int f(unsigned int x,unsigned int y){"
      "register unsigned int total=x+y;total=3u*total+11u;sink(total);"
      "{x=x+1u;unsigned int x=total-y;x=5u*x+7u;sink(x);total=total+x;}"
      "total=total+x;return total;}\n";
    auto original = parse(declarations);
    auto regions = csrd::discoverPrivateRegions(original->getASTContext(), function(*original));
    require(regions.frames.size() == 4, "declarations/effects/scope must delimit four regions");
    require(regions.frames[1].outputs.size() == 2 && regions.frames[1].outputs[0] != regions.frames[1].outputs[1] &&
            regions.frames[1].bindings.at(regions.frames[1].outputs[0]).name == "x" &&
            regions.frames[1].bindings.at(regions.frames[1].outputs[1]).name == "x", "shadowed output identity lost");
    for (const auto seed : {uint64_t(0), uint64_t(42), UINT64_MAX}) {
      std::vector<csrd::PrivateFrame *> edits;
      for (auto &r : regions.frames) {
        r.emission = csrd::emitPrivateFrame(r, csrd::Affine::fromSeed(seed,"f"), {"x","y","total"}); edits.push_back(&r);
      }
      csrd::preparePrivateFrames(edits);
      auto candidate = declarations;
      for (auto it=edits.rbegin(); it!=edits.rend(); ++it) candidate.replace((*it)->begin, (*it)->end-(*it)->begin, (*it)->emission.body);
      auto generated = parse(candidate);
      std::string reason;
      require(csrd::privateContextMatches(csrd::privateReferences(original->getASTContext(),function(*original)),
        csrd::privateReferences(generated->getASTContext(),function(*generated)), {edits.begin(),edits.end()}, reason), reason);
      for (const auto *r : edits) {
        const auto proof = csrd::validatePrivateFrame(generated->getASTContext(),function(*generated),*r,10000);
        require(proof.status == "proved-under-model", "declaration frame proof failed: " + proof.reason);
      }
    }
    // A wrapping block leaves every outside byte unchanged but redirects y to
    // the global object. Both structural validation and reference audit reject.
    const std::string scope = "unsigned int y;extern void sink(unsigned int);unsigned int f(unsigned int x){unsigned int y=x+1u;sink(y);return y;}\n";
    auto scoped = parse(scope);
    auto scopeRegions = csrd::discoverPrivateRegions(scoped->getASTContext(),function(*scoped));
    auto badScope = scopeRegions.frames.at(0);
    badScope.emission = csrd::emitPrivateFrame(badScope,identity,{"x","y"});
    auto wrongDeclaration = badScope.emission.body;
    const auto constant = wrongDeclaration.find("1u");
    require(constant != std::string::npos, "identity fixture constant missing");
    wrongDeclaration[constant]='2';
    require(grade(scope,badScope,wrongDeclaration).status == "counterexample", "wrong initializer must fail output proof");
    require(grade(scope,badScope,badScope.emission.body+"(void)sink(y);").status == "unsupported", "discarded call admitted");
    badScope.emission.body = "{" + badScope.emission.body + "}";
    for (auto &[id, offset] : badScope.emittedDeclarations) ++offset;
    csrd::preparePrivateFrames({&badScope});
    auto badText=scope; badText.replace(badScope.begin,badScope.end-badScope.begin,badScope.emission.body);
    auto badAst=parse(badText); std::string reason;
    require(!csrd::privateContextMatches(csrd::privateReferences(scoped->getASTContext(),function(*scoped)),
      csrd::privateReferences(badAst->getASTContext(),function(*badAst)),{&badScope},reason), "context audit missed scope redirection");
    require(reason.find("different declaration") != std::string::npos, "wrong context rejection");
    require(csrd::validatePrivateFrame(badAst->getASTContext(),function(*badAst),badScope,10000).status == "unsupported",
            "frame validator accepted hidden output declaration");
    auto self = parse("unsigned int f(void){unsigned int x=x+1u;return x;}\n");
    require(csrd::discoverPrivateRegions(self->getASTContext(),function(*self)).frames.empty(), "self initializer admitted");
    std::cout << "PASS private frame proofs, shadow/declaration composition, scalar-state counterexample and scope/effect/initialization controls\n";
  } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
