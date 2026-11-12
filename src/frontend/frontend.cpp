#include "csrd/frontend.hpp"
#include "csrd/analyzer.hpp"
#include "csrd/config.hpp"
#include "csrd/algorithms.hpp"
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
    if (name == "unsigned" || name == "int" || name == "void" || name == "signed" || name == "long" ||
        name == "short" || name == "char" || name == "_Bool" || name == "_Static_assert" || name == "sizeof") data.keywordMacro = true;
  }
};
class Consumer final : public clang::ASTConsumer {
  clang::CompilerInstance &ci;
  Preprocessing &pp;
  uint64_t seed;
  TransformResult &result;
  bool rewrite;
  const TransformResult *validationSource;
public:
  Consumer(clang::CompilerInstance &c, Preprocessing &p, uint64_t s, TransformResult &r, bool w, const TransformResult *v)
      : ci(c), pp(p), seed(s), result(r), rewrite(w), validationSource(v) {}
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
    std::set<std::string> reserved;
    for (const auto &entry : ci.getPreprocessor().getIdentifierTable()) reserved.insert(entry.getKey().str());
    do {
      lexer.LexFromRawLexer(token);
      if (token.is(clang::tok::hash)) pp.hazards.push_back(sm.getFileOffset(token.getLocation()));
      if (token.is(clang::tok::raw_identifier)) reserved.insert(token.getRawIdentifier().str());
    } while (!token.is(clang::tok::eof));
    clang::Rewriter rewriter(sm, ctx.getLangOpts());
    for (const auto *decl : ctx.getTranslationUnitDecl()->decls()) {
      const auto *f = llvm::dyn_cast<clang::FunctionDecl>(decl);
      if (!f || !f->doesThisDeclarationHaveABody() || !sm.isWrittenInMainFile(sm.getExpansionLoc(f->getLocation()))) continue;
      Decision decision;
      decision.function = f->getNameAsString();
      decision.parameterCount = f->getNumParams();
      decision.metrics = measure(ctx, *f);
      auto loc = f->getLocation();
      const auto begin = sm.getExpansionLoc(f->getBeginLoc());
      const auto end = sm.getExpansionLoc(f->getEndLoc());
      const auto first = sm.getFileOffset(begin), last = sm.getFileOffset(end);
      const bool hazard = std::any_of(pp.hazards.begin(), pp.hazards.end(), [=](unsigned pos) { return pos >= first && pos <= last; });
      if (pp.keywordMacro || hazard || f->getBeginLoc().isMacroID() || f->getEndLoc().isMacroID()) {
        decision.reason = pp.keywordMacro ? "macro definitions for generated C type keywords are unsupported" : "function contains macro expansions or preprocessor directives";
      } else if (result.options.scope == "private-regions") {
        decision.privateReferences = csrd::privateReferences(ctx, *f);
        if (validationSource) {
          const auto original = std::find_if(validationSource->decisions.begin(), validationSource->decisions.end(),
            [&](const Decision &d) { return d.function == decision.function; });
          if (original != validationSource->decisions.end()) {
            decision.privateFrames = original->privateFrames;
            std::vector<const PrivateFrame *> edits;
            for (const auto &d : validationSource->decisions)
              for (const auto &frame : d.privateFrames) edits.push_back(&frame);
            decision.privateContextVerified = privateContextMatches(original->privateReferences,
              decision.privateReferences, edits, decision.reason);
            for (auto &frame : decision.privateFrames)
              frame.verification = validatePrivateFrame(ctx, *f, frame, result.options.timeoutMs);
            decision.status = "checked-regions";
          }
        } else {
          auto discovery = discoverPrivateRegions(ctx, *f);
          decision.privateFrames = std::move(discovery.frames);
          decision.privateBoundaries = std::move(discovery.boundaries);
          decision.reason = discovery.reason;
          decision.status = decision.privateFrames.empty() ? "unchanged" : rewrite ? "regions-transformed" : "supported-regions";
          for (auto &frame : decision.privateFrames) {
            if (!rewrite) continue;
            const auto rep = result.options.strategy == "identity" ? IntegerCodec::identity() :
              IntegerCodec::fromSeed(seed, decision.function + ":" + std::to_string(frame.begin));
            frame.emission = emitPrivateFrame(frame, rep, reserved);
            const auto start = sm.getLocForStartOfFile(file);
            if (rewriter.ReplaceText(clang::CharSourceRange::getCharRange(start.getLocWithOffset(frame.begin),
                  start.getLocWithOffset(frame.end)), frame.emission.body))
              throw std::runtime_error("private source range could not be replaced");
            decision.operations += frame.emission.operations;
            decision.conversions += frame.emission.boundaryConversions;
          }
        }
      } else {
        auto analysis = analyze(ctx, *f, result.options.callContracts);
        if (!analysis.region) { decision.reason = analysis.reason; loc = analysis.location; }
        else {
          decision.region = std::make_shared<Region>(std::move(*analysis.region));
          try {
          const bool memory = decision.region->ordered();
          if (!memory) decision.graph = std::make_shared<Graph>(lower(*decision.region));
          if (!rewrite) {
            decision.status = "supported";
          } else {
          const auto &region = *decision.region;
          if (memory && ((result.options.strategy != "affine" && result.options.strategy != "identity") ||
                         result.options.algorithm != "none" || result.options.controlFlow != "none"))
            throw std::invalid_argument("buffer/call regions support only affine/identity with no algorithm or control-flow candidate");
          if (result.options.algorithm != "none")
            decision.graph = std::make_shared<Graph>(algorithmCandidate(region, result.options.algorithm));
          const auto rep = Affine::fromSeed(seed, region.name);
          decision.xorMask = rep.a() ^ rep.b();
          if (!decision.xorMask) decision.xorMask = 1;
          if (memory) {
            decision.plan.status = "ordered-memory";
            decision.plan.reason = "bounded ordered loads/stores; encoded scalars; no pure-graph pruning";
          } else decision.plan = plan(*decision.graph, result.options);
          if (decision.plan.status == "inconclusive") throw std::runtime_error(decision.plan.reason);
          const auto range = clang::CharSourceRange::getTokenRange(f->getBody()->getSourceRange());
          const unsigned lines = sm.getSpellingLineNumber(f->getBody()->getEndLoc()) -
                                 sm.getSpellingLineNumber(f->getBody()->getBeginLoc());
          if (memory) {
            Identity identity;
            const Representation &representation = result.options.strategy == "identity" ?
              static_cast<const Representation &>(identity) : static_cast<const Representation &>(rep);
            decision.emission = emitMemory(region, representation, lines, reserved);
          } else decision.emission = emitGraph(*decision.graph, decision.plan, result.options, rep, decision.xorMask, lines, reserved);
          // Dead-region pruning can remove every read of a public parameter.
          // A discarded pure read preserves warning-clean interfaces
          // and remains within the same independently checked C subset.
          if (!memory) for (const auto &parameter : region.parameters) {
            bool used = false;
            for (const auto &node : decision.graph->nodes)
              used |= node.kind == Expr::Kind::Reference && node.parameter == parameter;
            if (!used) decision.emission.body.insert(1, " (void)" + parameter + ";");
          }
          if ((decision.plan.status == "optimized" || decision.plan.status == "heuristic") &&
              (decision.emission.estimatedOperations != decision.plan.estimatedOperations ||
               decision.emission.temporaries != decision.plan.statements ||
               decision.emission.boundaryConversions + decision.emission.internalConversions != decision.plan.conversions))
            throw std::logic_error("planner and emitter cost accounting disagree");
          if (rewriter.ReplaceText(range, decision.emission.body)) { decision.reason = "source range cannot be rewritten safely"; }
          else {
            decision.status = "transformed";
            decision.operations = decision.emission.operations;
            decision.conversions = decision.emission.boundaryConversions;
            decision.a = rep.a(); decision.b = rep.b(); decision.inverse = rep.inverse();
          }
          }
          } catch (const std::exception &e) {
            decision.reason = e.what(); decision.status = "unchanged"; decision.region.reset(); decision.graph.reset();
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
    if (rewrite && result.options.scope == "private-regions") {
      std::vector<PrivateFrame *> frames;
      for (auto &d : result.decisions) for (auto &frame : d.privateFrames) frames.push_back(&frame);
      preparePrivateFrames(std::move(frames));
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
  const TransformResult *validationSource;
public:
  Action(uint64_t s, TransformResult &r, bool w, const TransformResult *v) : seed(s), result(r), rewrite(w), validationSource(v) {}
  std::unique_ptr<clang::ASTConsumer> CreateASTConsumer(clang::CompilerInstance &ci, llvm::StringRef) override {
    ci.getPreprocessor().addPPCallbacks(std::make_unique<Callbacks>(ci.getSourceManager(), pp));
    return std::make_unique<Consumer>(ci, pp, seed, result, rewrite, validationSource);
  }
};
class Factory final : public clang::tooling::FrontendActionFactory {
  uint64_t seed;
  TransformResult &result;
  bool rewrite;
  const TransformResult *validationSource;
public:
  Factory(uint64_t s, TransformResult &r, bool w, const TransformResult *v) : seed(s), result(r), rewrite(w), validationSource(v) {}
  std::unique_ptr<clang::FrontendAction> create() override { return std::make_unique<Action>(seed, result, rewrite, validationSource); }
};
bool parse(const std::string &path, uint64_t seed, TransformResult &result, bool rewrite, const std::string *contents,
           const TransformResult *validationSource = nullptr) {
  std::vector<std::string> flags = {"-x", "c", "-std=c11", "-pedantic-errors", "-Wno-keyword-macro", "-fsyntax-only", "-resource-dir=" CSRD_RESOURCE_DIR};
  if (std::string(CSRD_SYSROOT).size()) { flags.push_back("-isysroot"); flags.push_back(CSRD_SYSROOT); }
  clang::tooling::FixedCompilationDatabase db(std::filesystem::current_path().string(), flags);
  const auto absolute = std::filesystem::absolute(path).lexically_normal().string();
  clang::tooling::ClangTool tool(db, {absolute});
  if (contents) tool.mapVirtualFile(absolute, *contents);
  Factory factory(seed, result, rewrite, validationSource);
  return tool.run(&factory) == 0;
}
}
bool inspect(const std::string &path, TransformResult &result, const std::string *contents) {
  return parse(path, 0, result, false, contents);
}
bool validatePrivateCandidate(const std::string &path, TransformResult &result, const std::string &candidate) {
  std::vector<PrivateFrame *> frames;
  for (auto &d : result.decisions) for (auto &frame : d.privateFrames) frames.push_back(&frame);
  std::sort(frames.begin(), frames.end(), [](const PrivateFrame *a, const PrivateFrame *b) { return a->candidateBegin < b->candidateBegin; });
  std::string restored = candidate;
  for (auto it = frames.rbegin(); it != frames.rend(); ++it) {
    const auto &frame = **it;
    if (frame.candidateBegin > frame.candidateEnd || frame.candidateEnd > restored.size()) return false;
    restored.replace(frame.candidateBegin, frame.candidateEnd-frame.candidateBegin, frame.originalText);
  }
  if (sha256(restored) != result.inputHash) {
    llvm::errs() << "csrd: private validation rejected a change outside the selected regions\n"; return false;
  }
  TransformResult generated; generated.options = result.options;
  if (!parse(path, 0, generated, false, &candidate, &result)) return false;
  result.candidateDependencies = generated.dependencies;
  if (result.target != generated.target || result.dependencies != generated.dependencies) return false;
  for (auto &decision : result.decisions) {
    if (decision.privateFrames.empty()) continue;
    const auto match = std::find_if(generated.decisions.begin(), generated.decisions.end(),
      [&](const Decision &d) { return d.function == decision.function; });
    if (match == generated.decisions.end() || match->privateFrames.size() != decision.privateFrames.size()) return false;
    decision.privateContextVerified = match->privateContextVerified;
    if (!decision.privateContextVerified) {
      decision.verification.status = "unsupported"; decision.verification.reason = match->reason;
      llvm::errs() << "csrd: private context binding validation failed: " << match->reason << "\n";
      return false;
    }
    decision.verification.status = "proved-under-model";
    decision.verification.strategy = "contextual-private-frames";
    decision.verification.reason = "pointwise private scalar frame equivalence with byte-identical surrounding source and unchanged reference bindings; not a whole-C or binary proof";
    for (unsigned i = 0; i < decision.privateFrames.size(); ++i) {
      auto &frame = decision.privateFrames[i]; frame.verification = match->privateFrames[i].verification;
      if (frame.verification.status != "proved-under-model") {
        decision.verification = frame.verification;
        llvm::errs() << "csrd: private frame validation failed for " << decision.function << ": "
                     << frame.verification.status << ": " << frame.verification.reason << "\n";
        return false;
      }
    }
  }
  return true;
}
bool transform(const std::string &path, uint64_t seed, TransformResult &result, const PlanOptions &options) {
  result.options = options;
  if (!parse(path, seed, result, true, nullptr)) return false;
  if (options.scope == "private-regions") return validatePrivateCandidate(path, result, result.source);
  TransformResult generated;
  generated.options = options;
  if (!inspect(path, generated, &result.source)) return false;
  result.candidateDependencies = generated.dependencies;
  if (result.target != generated.target || result.dependencies != generated.dependencies) {
    llvm::errs() << "csrd: verification rejected a target or include-environment change\n"; return false;
  }
  for (auto &d : result.decisions) {
    if (d.status != "transformed") continue;
    auto match = std::find_if(generated.decisions.begin(), generated.decisions.end(), [&](const Decision &other) { return other.function == d.function; });
    if (match == generated.decisions.end() || !match->region) {
      d.verification.status = "unsupported"; d.verification.reason = "emitted C was not accepted by the validator";
    } else d.verification = verify(*d.region, *match->region, options.timeoutMs);
    if (d.verification.status != "proved-under-model") {
      llvm::errs() << "csrd: verification failed for " << d.function << ": " << d.verification.status << " " << d.verification.reason << "\n";
      return false;
    }
  }
  return true;
}
} // namespace csrd
