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
#include "llvm/Support/SHA256.h"
#include "llvm/ADT/StringExtras.h"
#include <algorithm>
#include <filesystem>

namespace csrd {
std::string sha256(const std::string &data) {
  llvm::SHA256 hash; hash.update(data); return llvm::toHex(hash.final(), true);
}
namespace {
struct Preprocessing {
  std::vector<unsigned> hazards;
  bool keywordMacro = false;
  std::vector<std::pair<std::string, std::string>> dependencies;
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
  void FileChanged(clang::SourceLocation loc, FileChangeReason reason,
                   clang::SrcMgr::CharacteristicKind, clang::FileID) override {
    if (reason != EnterFile || loc.isInvalid()) return;
    const auto id = sm.getFileID(sm.getSpellingLoc(loc));
    if (id.isInvalid() || id == sm.getMainFileID()) return;
    const auto name = sm.getFilename(loc).str();
    if (!name.empty()) data.dependencies.emplace_back(name, sha256(sm.getBufferData(id).str()));
  }
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
  bool rewrite;
public:
  Consumer(clang::CompilerInstance &c, Preprocessing &p, uint64_t s, TransformResult &r, bool w) : ci(c), pp(p), seed(s), result(r), rewrite(w) {}
  void HandleTranslationUnit(clang::ASTContext &ctx) override {
    if (ci.getDiagnostics().hasErrorOccurred()) return;
    auto &sm = ctx.getSourceManager();
    const auto file = sm.getMainFileID();
    const auto buffer = sm.getBufferData(file);
    result.inputHash = sha256(buffer.str());
    result.dependencies = pp.dependencies;
    std::sort(result.dependencies.begin(), result.dependencies.end());
    result.dependencies.erase(std::unique(result.dependencies.begin(), result.dependencies.end()), result.dependencies.end());
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
          decision.region = std::make_shared<Region>(std::move(*analysis.region));
          if (!rewrite) {
            decision.status = "supported";
          } else {
          const auto &region = *decision.region;
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
      }
      if (decision.status.empty()) decision.status = "unchanged";
      auto presumed = sm.getPresumedLoc(sm.getExpansionLoc(loc));
      if (presumed.isValid()) {
        decision.line = presumed.getLine(); decision.column = presumed.getColumn();
        if (rewrite) llvm::errs() << presumed.getFilename() << ":" << decision.line << ":" << decision.column << ": ";
      }
      if (rewrite) {
        llvm::errs() << "csrd: " << decision.status << " " << decision.function;
        if (!decision.reason.empty()) llvm::errs() << ": " << decision.reason;
        llvm::errs() << "\n";
      }
      result.decisions.push_back(std::move(decision));
    }
    llvm::raw_string_ostream output(result.source);
    rewriter.getEditBuffer(file).write(output);
    result.outputHash = sha256(result.source);
  }
};
class Action final : public clang::ASTFrontendAction {
  Preprocessing pp;
  uint64_t seed;
  TransformResult &result;
  bool rewrite;
public:
  Action(uint64_t s, TransformResult &r, bool w) : seed(s), result(r), rewrite(w) {}
  std::unique_ptr<clang::ASTConsumer> CreateASTConsumer(clang::CompilerInstance &ci, llvm::StringRef) override {
    ci.getPreprocessor().addPPCallbacks(std::make_unique<Callbacks>(ci.getSourceManager(), pp));
    return std::make_unique<Consumer>(ci, pp, seed, result, rewrite);
  }
};
class Factory final : public clang::tooling::FrontendActionFactory {
  uint64_t seed;
  TransformResult &result;
  bool rewrite;
public:
  Factory(uint64_t s, TransformResult &r, bool w) : seed(s), result(r), rewrite(w) {}
  std::unique_ptr<clang::FrontendAction> create() override { return std::make_unique<Action>(seed, result, rewrite); }
};
bool parse(const std::string &path, uint64_t seed, TransformResult &result, bool rewrite, const std::string *contents) {
  std::vector<std::string> flags = {"-x", "c", "-std=c11", "-pedantic-errors", "-Wno-keyword-macro", "-fsyntax-only", "-resource-dir=" CSRD_RESOURCE_DIR};
  if (std::string(CSRD_SYSROOT).size()) { flags.push_back("-isysroot"); flags.push_back(CSRD_SYSROOT); }
  clang::tooling::FixedCompilationDatabase db(std::filesystem::current_path().string(), flags);
  const auto absolute = std::filesystem::absolute(path).lexically_normal().string();
  clang::tooling::ClangTool tool(db, {absolute});
  if (contents) tool.mapVirtualFile(absolute, *contents);
  Factory factory(seed, result, rewrite);
  return tool.run(&factory) == 0;
}
}
bool inspect(const std::string &path, TransformResult &result, const std::string *contents) {
  return parse(path, 0, result, false, contents);
}
bool transform(const std::string &path, uint64_t seed, TransformResult &result, unsigned timeoutMs) {
  if (!parse(path, seed, result, true, nullptr)) return false;
  TransformResult generated;
  if (!inspect(path, generated, &result.source)) return false;
  if (result.target != generated.target || result.dependencies != generated.dependencies) {
    llvm::errs() << "csrd: verification rejected a target or include-environment change\n"; return false;
  }
  for (auto &d : result.decisions) {
    if (d.status != "transformed") continue;
    auto match = std::find_if(generated.decisions.begin(), generated.decisions.end(), [&](const Decision &other) { return other.function == d.function; });
    if (match == generated.decisions.end() || !match->region) {
      d.verification.status = "unsupported"; d.verification.reason = "emitted C was not accepted by the validator";
    } else d.verification = verify(*d.region, *match->region, timeoutMs);
    if (d.verification.status != "proved-under-model") {
      llvm::errs() << "csrd: verification failed for " << d.function << ": " << d.verification.status << " " << d.verification.reason << "\n";
      return false;
    }
  }
  return true;
}
} // namespace csrd
