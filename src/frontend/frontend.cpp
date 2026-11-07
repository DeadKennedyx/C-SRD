#include "csrd/frontend.hpp"
#include "csrd/analyzer.hpp"
#include "csrd/config.hpp"
#include "csrd/emitter.hpp"
#include "clang/AST/ASTConsumer.h"
#include "clang/Basic/TargetInfo.h"
#include "clang/Frontend/CompilerInstance.h"
#include "clang/Frontend/FrontendActions.h"
#include "clang/Lex/Lexer.h"
#include "clang/Lex/PPCallbacks.h"
#include "clang/Lex/Preprocessor.h"
#include "clang/Rewrite/Core/Rewriter.h"
#include "clang/Tooling/CompilationDatabase.h"
#include "clang/Tooling/Tooling.h"
#include "llvm/Support/raw_ostream.h"
#include <algorithm>
#include <filesystem>

namespace csrd {
namespace {
struct Preprocessing {
  std::vector<unsigned> hazards;
  bool keywordMacro = false;
};
class Callbacks final : public clang::PPCallbacks {
  clang::SourceManager &sm;
  Preprocessing &data;
  void record(clang::SourceLocation loc) {
    loc = sm.getExpansionLoc(loc);
    if (sm.isWrittenInMainFile(loc)) data.hazards.push_back(sm.getFileOffset(loc));
  }
public:
  Callbacks(clang::SourceManager &source, Preprocessing &p) : sm(source), data(p) {}
  void MacroExpands(const clang::Token &, const clang::MacroDefinition &, clang::SourceRange range,
                    const clang::MacroArgs *) override { record(range.getBegin()); }
  void PragmaDirective(clang::SourceLocation loc, clang::PragmaIntroducerKind) override { record(loc); }
  void MacroDefined(const clang::Token &token, const clang::MacroDirective *) override {
    const auto name = token.getIdentifierInfo()->getName();
    if (name == "unsigned" || name == "int") data.keywordMacro = true;
  }
};
class Consumer final : public clang::ASTConsumer {
  clang::CompilerInstance &ci;
  Preprocessing &pp;
  uint64_t seed;
  TransformResult &result;
public:
  Consumer(clang::CompilerInstance &c, Preprocessing &p, uint64_t s, TransformResult &r) : ci(c), pp(p), seed(s), result(r) {}
  void HandleTranslationUnit(clang::ASTContext &ctx) override {
    if (ci.getDiagnostics().hasErrorOccurred()) return;
    auto &sm = ctx.getSourceManager();
    const auto file = sm.getMainFileID();
    const auto buffer = sm.getBufferData(file);
    result.target = ctx.getTargetInfo().getTriple().str();
    // Raw Clang lexing sees directives even in skipped preprocessor branches.
    clang::Lexer lexer(sm.getLocForStartOfFile(file), ctx.getLangOpts(), buffer.begin(), buffer.begin(), buffer.end());
    clang::Token token;
    do {
      lexer.LexFromRawLexer(token);
      if (token.is(clang::tok::hash)) pp.hazards.push_back(sm.getFileOffset(token.getLocation()));
    } while (!token.is(clang::tok::eof));
    clang::Rewriter rewriter(sm, ctx.getLangOpts());
    for (const auto *decl : ctx.getTranslationUnitDecl()->decls()) {
      const auto *f = llvm::dyn_cast<clang::FunctionDecl>(decl);
      if (!f || !f->doesThisDeclarationHaveABody() || !sm.isWrittenInMainFile(sm.getExpansionLoc(f->getLocation()))) continue;
      Decision decision;
      decision.function = f->getNameAsString();
      auto loc = f->getLocation();
      const auto begin = sm.getExpansionLoc(f->getBeginLoc());
      const auto end = sm.getExpansionLoc(f->getEndLoc());
      const auto first = sm.getFileOffset(begin), last = sm.getFileOffset(end);
      const bool hazard = std::any_of(pp.hazards.begin(), pp.hazards.end(), [=](unsigned pos) { return pos >= first && pos <= last; });
      if (pp.keywordMacro || hazard || f->getBeginLoc().isMacroID() || f->getEndLoc().isMacroID()) {
        decision.reason = pp.keywordMacro ? "macro definitions for generated C type keywords are unsupported" : "function contains macro expansions or preprocessor directives";
      } else {
        auto analysis = analyze(ctx, *f);
        if (!analysis.region) { decision.reason = analysis.reason; loc = analysis.location; }
        else {
          const auto &region = *analysis.region;
          const auto rep = Affine::fromSeed(seed, region.name);
          const auto range = clang::CharSourceRange::getTokenRange(f->getBody()->getSourceRange());
          const unsigned lines = sm.getSpellingLineNumber(f->getBody()->getEndLoc()) -
                                 sm.getSpellingLineNumber(f->getBody()->getBeginLoc());
          const auto body = emitBody(region, rep, lines);
          if (rewriter.ReplaceText(range, body)) { decision.reason = "source range cannot be rewritten safely"; }
          else {
            decision.status = "transformed";
            decision.operations = region.operations;
            decision.conversions = unsigned(region.parameters.size()) + 1;
            decision.a = rep.a(); decision.b = rep.b(); decision.inverse = rep.inverse();
          }
        }
      }
      if (decision.status.empty()) decision.status = "unchanged";
      auto presumed = sm.getPresumedLoc(sm.getExpansionLoc(loc));
      if (presumed.isValid()) {
        decision.line = presumed.getLine(); decision.column = presumed.getColumn();
        llvm::errs() << presumed.getFilename() << ":" << decision.line << ":" << decision.column << ": ";
      }
      llvm::errs() << "csrd: " << decision.status << " " << decision.function;
      if (!decision.reason.empty()) llvm::errs() << ": " << decision.reason;
      llvm::errs() << "\n";
      result.decisions.push_back(std::move(decision));
    }
    llvm::raw_string_ostream output(result.source);
    rewriter.getEditBuffer(file).write(output);
  }
};
class Action final : public clang::ASTFrontendAction {
  Preprocessing pp;
  uint64_t seed;
  TransformResult &result;
public:
  Action(uint64_t s, TransformResult &r) : seed(s), result(r) {}
  std::unique_ptr<clang::ASTConsumer> CreateASTConsumer(clang::CompilerInstance &ci, llvm::StringRef) override {
    ci.getPreprocessor().addPPCallbacks(std::make_unique<Callbacks>(ci.getSourceManager(), pp));
    return std::make_unique<Consumer>(ci, pp, seed, result);
  }
};
class Factory final : public clang::tooling::FrontendActionFactory {
  uint64_t seed;
  TransformResult &result;
public:
  Factory(uint64_t s, TransformResult &r) : seed(s), result(r) {}
  std::unique_ptr<clang::FrontendAction> create() override { return std::make_unique<Action>(seed, result); }
};
}
bool transform(const std::string &path, uint64_t seed, TransformResult &result) {
  std::vector<std::string> flags = {"-x", "c", "-std=c11", "-pedantic-errors", "-Wno-keyword-macro", "-fsyntax-only", "-resource-dir=" CSRD_RESOURCE_DIR};
  if (std::string(CSRD_SYSROOT).size()) { flags.push_back("-isysroot"); flags.push_back(CSRD_SYSROOT); }
  clang::tooling::FixedCompilationDatabase db(std::filesystem::current_path().string(), flags);
  clang::tooling::ClangTool tool(db, {path});
  Factory factory(seed, result);
  return tool.run(&factory) == 0;
}
} // namespace csrd
