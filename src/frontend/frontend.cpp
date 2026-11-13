#include "csrd/frontend.hpp"
#include "csrd/analyzer.hpp"
#include "csrd/config.hpp"
#include "csrd/algorithms.hpp"
#include "clang/AST/ASTConsumer.h"
#include "clang/AST/Expr.h"
#include "clang/AST/RecursiveASTVisitor.h"
#include "clang/Basic/TargetInfo.h"
#include "clang/Frontend/CompilerInstance.h"
#include "clang/Frontend/FrontendActions.h"
#include "clang/Frontend/Utils.h"
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
bool supportedCompilationSemantics(clang::CompilerInstance &ci) {
  const auto &lang = ci.getLangOpts();
  if (lang.CPlusPlus || lang.ObjC || lang.OpenCL || lang.OpenMP || !lang.C11 ||
      lang.getSignedOverflowBehavior() != clang::LangOptions::SOB_Undefined) {
    const auto id = ci.getDiagnostics().getCustomDiagID(clang::DiagnosticsEngine::Error,
      "C-SRD requires C11-compatible sequential C with default signed-overflow semantics; this compilation configuration is unsupported");
    ci.getDiagnostics().Report(id);
    return false;
  }
  return true;
}
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
        name == "short" || name == "char" || name == "_Bool" || name == "_Static_assert" || name == "sizeof" ||
        name == "static" || name == "return") data.keywordMacro = true;
  }
};
class SourceLocations final : public clang::RecursiveASTVisitor<SourceLocations> {
  clang::SourceManager &sm;
public:
  bool found=false;
  explicit SourceLocations(clang::SourceManager &manager):sm(manager) {}
  bool VisitSourceLocExpr(clang::SourceLocExpr *expression) {
    if (sm.isWrittenInMainFile(sm.getExpansionLoc(expression->getBeginLoc()))) found=true;
    return true;
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
    const bool preprocessed=!ci.getFrontendOpts().Inputs.empty() && ci.getFrontendOpts().Inputs.front().getKind().isPreprocessed();
    clang::Token token;
    std::set<std::string> reserved;
    for (const auto &entry : ci.getPreprocessor().getIdentifierTable()) reserved.insert(entry.getKey().str());
    do {
      lexer.LexFromRawLexer(token);
      if (token.is(clang::tok::hash)) {
        const auto offset=sm.getFileOffset(token.getLocation());
        if (preprocessed) {
          // Already parsed compiler line markers are location metadata, even
          // when the preprocessor compresses blank lines inside a function.
          // Other directives stay hazards. No text-based C parsing is used.
          lexer.LexFromRawLexer(token);
          if (!token.is(clang::tok::numeric_constant)) pp.hazards.push_back(offset);
        } else pp.hazards.push_back(offset);
      }
      if (token.is(clang::tok::raw_identifier)) reserved.insert(token.getRawIdentifier().str());
    } while (!token.is(clang::tok::eof));
    clang::Rewriter rewriter(sm, ctx.getLangOpts());
    bool outlineLocations=false;
    if (result.options.scope=="outline-regions") {
      SourceLocations locations(sm);locations.TraverseDecl(ctx.getTranslationUnitDecl());
      outlineLocations=locations.found;
    }
    for (const auto *decl : ctx.getTranslationUnitDecl()->decls()) {
      const auto *f = llvm::dyn_cast<clang::FunctionDecl>(decl);
      if (!f || !f->doesThisDeclarationHaveABody() || !sm.isWrittenInMainFile(sm.getExpansionLoc(f->getLocation()))) continue;
      Decision decision;
      decision.function = f->getNameAsString();
      decision.parameterCount = f->getNumParams();
      decision.internalLinkage = !f->isExternallyVisible();
      decision.metrics = measure(ctx, *f);
      auto loc = f->getLocation();
      const auto begin = sm.getExpansionLoc(f->getBeginLoc());
      const auto end = sm.getExpansionLoc(f->getEndLoc());
      const auto first = sm.getFileOffset(begin), last = sm.getFileOffset(end);
      const bool hazard = std::any_of(pp.hazards.begin(), pp.hazards.end(), [=](unsigned pos) { return pos >= first && pos <= last; });
      if (pp.keywordMacro || hazard || f->getBeginLoc().isMacroID() || f->getEndLoc().isMacroID()) {
        decision.reason = pp.keywordMacro ? "macro definitions for generated C type keywords are unsupported" : "function contains macro expansions or preprocessor directives";
      } else if (result.options.scope == "outline-regions") {
        if (!outlineLocations) decision.outlineReferences=csrd::privateReferences(ctx,*f);
        if (outlineLocations) decision.reason="translation unit uses source-location builtins whose columns could move";
        else if (validationSource) {
          const auto original=std::find_if(validationSource->decisions.begin(),validationSource->decisions.end(),
            [&](const auto &d){return d.function==decision.function;});
          if (original==validationSource->decisions.end()) continue; // Helpers are checked with their caller.
          decision.outline=original->outline;
          std::vector<const OutlineFunction *> functions;
          for (const auto &d:validationSource->decisions) functions.push_back(&d.outline);
          decision.outlineContextVerified=outlineContextMatches(original->outlineReferences,decision.outlineReferences,functions,decision.reason);
          if (!decision.outline.frames.empty()) decision.verification=validateOutline(ctx,*f,decision.outline);
          decision.status="checked-outline-regions";
        } else {
          decision.outline=discoverOutline(ctx,*f);
          decision.privateBoundaries=decision.outline.boundaries;decision.reason=decision.outline.reason;
          decision.status=decision.outline.frames.empty() ? "unchanged":rewrite ? "outline-transformed":"supported-outline-regions";
          if (rewrite && !decision.outline.frames.empty()) {
            emitOutline(decision.outline,seed,reserved);
            const auto start=sm.getLocForStartOfFile(file);
            if (rewriter.InsertTextBefore(start.getLocWithOffset(decision.outline.insertion.begin),decision.outline.insertion.emitted))
              throw std::runtime_error("outline helpers could not be inserted");
            for (const auto &frame:decision.outline.frames) {
              if (rewriter.ReplaceText(clang::CharSourceRange::getCharRange(start.getLocWithOffset(frame.begin),
                    start.getLocWithOffset(frame.end)),frame.emitted)) throw std::runtime_error("outline expression could not be replaced");
              decision.operations+=frame.operations;
            }
          }
        }
      } else if (result.options.scope == "control-regions") {
        decision.controlReferences = csrd::privateReferences(ctx, *f);
        if (validationSource) {
          const auto original = std::find_if(validationSource->decisions.begin(), validationSource->decisions.end(),
            [&](const Decision &d) { return d.function == decision.function; });
          if (original != validationSource->decisions.end()) {
            decision.controlFrames = original->controlFrames;
            std::vector<const ControlFrame *> edits;
            for (const auto &d : validationSource->decisions) for (const auto &frame : d.controlFrames) edits.push_back(&frame);
            decision.controlContextVerified = controlContextMatches(original->controlReferences, decision.controlReferences, edits, decision.reason);
            for (auto &frame : decision.controlFrames) frame.verification = validateControlFrame(ctx, *f, frame);
            decision.status = "checked-control-regions";
          }
        } else {
          auto discovery = discoverControlRegions(ctx, *f);
          decision.controlFrames = std::move(discovery.frames);
          decision.privateBoundaries = std::move(discovery.boundaries);
          decision.reason = discovery.reason;
          decision.status = decision.controlFrames.empty() ? "unchanged" : rewrite ? "control-transformed" : "supported-control-regions";
          for (auto &frame : decision.controlFrames) {
            if (!rewrite) continue;
            emitControlFrame(frame, seed, decision.function, reserved);
            const auto start = sm.getLocForStartOfFile(file);
            if (rewriter.ReplaceText(clang::CharSourceRange::getCharRange(start.getLocWithOffset(frame.begin),
                  start.getLocWithOffset(frame.end)), frame.emitted)) throw std::runtime_error("control source range could not be replaced");
          }
        }
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
    if (rewrite && result.options.scope == "control-regions") {
      std::vector<ControlFrame *> frames;
      for (auto &d : result.decisions) for (auto &frame : d.controlFrames) frames.push_back(&frame);
      prepareControlFrames(std::move(frames));
    }
    if (rewrite && result.options.scope=="outline-regions") {
      std::vector<OutlineFunction *> functions;
      for (auto &d:result.decisions) functions.push_back(&d.outline);
      prepareOutline(std::move(functions));
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
  bool BeginSourceFileAction(clang::CompilerInstance &ci) override { return supportedCompilationSemantics(ci); }
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
class PreprocessAction final : public clang::PreprocessorFrontendAction {
  TransformResult &result;
  Preprocessing pp;
public:
  explicit PreprocessAction(TransformResult &r) : result(r) {}
  bool BeginSourceFileAction(clang::CompilerInstance &ci) override { return supportedCompilationSemantics(ci); }
  void ExecuteAction() override {
    auto &ci = getCompilerInstance();
    auto &sm = ci.getSourceManager();
    ci.getPreprocessor().addPPCallbacks(std::make_unique<Callbacks>(sm, pp));
    result.inputHash = sha256(sm.getBufferData(sm.getMainFileID()).str());
    result.target = ci.getTarget().getTriple().str();
    result.source.clear();
    llvm::raw_string_ostream output(result.source);
    auto options = ci.getPreprocessorOutputOpts();
    options.ShowCPP = 1;
    options.ShowLineMarkers = 1;
    clang::DoPrintPreprocessedInput(ci.getPreprocessor(), &output, options);
    output.flush();
    result.outputHash = sha256(result.source);
    result.dependencies = pp.dependencies;
    std::sort(result.dependencies.begin(), result.dependencies.end());
    result.dependencies.erase(std::unique(result.dependencies.begin(), result.dependencies.end()), result.dependencies.end());
  }
};
class PreprocessFactory final : public clang::tooling::FrontendActionFactory {
  TransformResult &result;
public:
  explicit PreprocessFactory(TransformResult &r) : result(r) {}
  std::unique_ptr<clang::FrontendAction> create() override { return std::make_unique<PreprocessAction>(result); }
};
std::vector<std::string> compilerArguments(const std::string &path, const FrontendOptions &options, bool preprocessing) {
  // Compiler-frozen .i files retain line markers and system-header provenance.
  // Let Clang consume its actual preprocessed-C input format instead of treating
  // those markers as GNU extensions in a fresh C source translation unit.
  const auto language=std::filesystem::path(path).extension()==".i" ? "cpp-output" : "c";
  std::vector<std::string> flags = {"-x", language, "-std=c11", "-pedantic-errors", "-Wno-keyword-macro",
    preprocessing ? "-E" : "-fsyntax-only", "-resource-dir=" CSRD_RESOURCE_DIR};
  if (std::filesystem::path(path).extension()==".i") flags.push_back("-Wno-gnu-line-marker");
  if (!options.target.empty()) flags.push_back("--target=" + options.target);
  if (!options.sysroot.empty()) flags.push_back("--sysroot=" + options.sysroot);
  // An explicit target must never inherit the host SDK. Cross targets use their
  // supplied sysroot/include paths or Clang's target-specific defaults.
  else if (options.target.empty() && std::string(CSRD_SYSROOT).size()) {
    flags.push_back("-isysroot"); flags.push_back(CSRD_SYSROOT);
  }
  for (const auto &directory : options.includeDirectories) flags.push_back("-I" + directory);
  for (const auto &definition : options.definitions) flags.push_back("-D" + definition);
  return flags;
}
bool runTool(const std::string &path, TransformResult &result, clang::tooling::FrontendActionFactory &factory,
             const std::string *contents, bool preprocessing = false) {
  const auto absolute = std::filesystem::absolute(path).lexically_normal().string();
  std::unique_ptr<clang::tooling::CompilationDatabase> db;
  if (result.frontend.compilationDatabase.empty()) {
    result.compilerArguments = compilerArguments(path, result.frontend, preprocessing);
    db = std::make_unique<clang::tooling::FixedCompilationDatabase>(std::filesystem::current_path().string(), result.compilerArguments);
  } else {
    result.compilation = loadCompilationConfiguration(path, result.frontend, preprocessing);
    const auto &configuration = *result.compilation;
    result.compilerArguments = configuration.arguments;
    class Single final : public clang::tooling::CompilationDatabase {
      clang::tooling::CompileCommand command;
    public:
      explicit Single(clang::tooling::CompileCommand c) : command(std::move(c)) {}
      std::vector<clang::tooling::CompileCommand> getCompileCommands(llvm::StringRef) const override { return {command}; }
    };
    db = std::make_unique<Single>(clang::tooling::CompileCommand(configuration.directory, absolute, configuration.arguments, ""));
  }
  clang::tooling::ClangTool tool(*db, {absolute});
  if (preprocessing || result.compilation) tool.clearArgumentsAdjusters();
  if (contents) tool.mapVirtualFile(absolute, *contents);
  return tool.run(&factory) == 0;
}
bool parse(const std::string &path, uint64_t seed, TransformResult &result, bool rewrite, const std::string *contents,
           const TransformResult *validationSource = nullptr) {
  Factory factory(seed, result, rewrite, validationSource);
  return runTool(path, result, factory, contents);
}
}
bool preprocess(const std::string &path, TransformResult &result) {
  PreprocessFactory factory(result);
  return runTool(path, result, factory, nullptr, true);
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
  TransformResult generated; generated.options = result.options; generated.frontend = result.frontend;
  if (!parse(path, 0, generated, false, &candidate, &result)) return false;
  result.candidateDependencies = generated.dependencies;
  result.candidateCompilerArguments = generated.compilerArguments;
  if (result.target != generated.target || result.dependencies != generated.dependencies ||
      result.compilerArguments != generated.compilerArguments ||
      (result.compilation && result.compilation->databaseHash != generated.compilation->databaseHash)) return false;
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
bool validateControlCandidate(const std::string &path, TransformResult &result, const std::string &candidate) {
  std::vector<const ControlFrame *> frames;
  for (const auto &d : result.decisions) for (const auto &frame : d.controlFrames) frames.push_back(&frame);
  std::sort(frames.begin(), frames.end(), [](const auto *a, const auto *b) { return a->candidateBegin < b->candidateBegin; });
  std::string restored = candidate;
  for (auto it = frames.rbegin(); it != frames.rend(); ++it) {
    const auto &frame = **it;
    if (frame.candidateBegin > frame.candidateEnd || frame.candidateEnd > restored.size()) return false;
    restored.replace(frame.candidateBegin, frame.candidateEnd-frame.candidateBegin, frame.originalText);
  }
  if (sha256(restored) != result.inputHash) {
    llvm::errs() << "csrd: control validation rejected a change outside selected regions\n"; return false;
  }
  TransformResult generated; generated.options = result.options; generated.frontend = result.frontend;
  if (!parse(path, 0, generated, false, &candidate, &result)) return false;
  result.candidateDependencies = generated.dependencies;
  result.candidateCompilerArguments = generated.compilerArguments;
  if (result.target != generated.target || result.dependencies != generated.dependencies || result.compilerArguments != generated.compilerArguments ||
      (result.compilation && result.compilation->databaseHash != generated.compilation->databaseHash)) return false;
  for (auto &decision : result.decisions) {
    if (decision.controlFrames.empty()) continue;
    const auto match = std::find_if(generated.decisions.begin(), generated.decisions.end(), [&](const auto &d) { return d.function == decision.function; });
    if (match == generated.decisions.end() || match->controlFrames.size() != decision.controlFrames.size()) return false;
    decision.controlContextVerified = match->controlContextVerified;
    if (!decision.controlContextVerified) { llvm::errs() << "csrd: " << match->reason << "\n"; return false; }
    decision.verification.status = "proved-under-model";
    decision.verification.strategy = "control-graph-isomorphism";
    decision.verification.reason = "identical opaque C payloads, declaration bindings and source control graph; stuttering private dispatch steps; not a proof of compiler, binary or full C11 semantics";
    for (unsigned i = 0; i < decision.controlFrames.size(); ++i) {
      auto &frame = decision.controlFrames[i]; frame.verification = match->controlFrames[i].verification;
      if (frame.verification.status != "proved-under-model") {
        decision.verification = frame.verification;
        llvm::errs() << "csrd: control validation failed for " << decision.function << ": " << frame.verification.reason << "\n";
        return false;
      }
    }
  }
  return true;
}
bool validateOutlineCandidate(const std::string &path,TransformResult &result,const std::string &candidate) {
  std::vector<const OutlineFunction *> functions;
  for (const auto &d:result.decisions) functions.push_back(&d.outline);
  const auto edits=outlineEdits(functions);
  std::string restored=candidate;
  for (auto it=edits.rbegin();it!=edits.rend();++it) {
    const auto &edit=**it;
    if (edit.candidateBegin>edit.candidateEnd || edit.candidateEnd>restored.size()) return false;
    restored.replace(edit.candidateBegin,edit.candidateEnd-edit.candidateBegin,edit.original);
  }
  if (sha256(restored)!=result.inputHash) {llvm::errs()<<"csrd: outline validation rejected a change outside selected edits\n";return false;}
  TransformResult generated;generated.options=result.options;generated.frontend=result.frontend;
  if (!parse(path,0,generated,false,&candidate,&result)) return false;
  result.candidateDependencies=generated.dependencies;result.candidateCompilerArguments=generated.compilerArguments;
  if (result.target!=generated.target || result.dependencies!=generated.dependencies || result.compilerArguments!=generated.compilerArguments ||
      (result.compilation && result.compilation->databaseHash!=generated.compilation->databaseHash)) return false;
  for (auto &decision:result.decisions) {
    const auto match=std::find_if(generated.decisions.begin(),generated.decisions.end(),[&](const auto &d){return d.function==decision.function;});
    if (match==generated.decisions.end()) return false;
    // Functions skipped for preprocessing/context hazards have no outline references.
    if (decision.outlineReferences.empty() && decision.outline.frames.empty()) continue;
    decision.outlineContextVerified=match->outlineContextVerified;
    if (!decision.outlineContextVerified) {llvm::errs()<<"csrd: outline context: "<<match->reason<<"\n";return false;}
    if (decision.outline.frames.empty()) continue;
    decision.verification=match->verification;decision.outline=match->outline;
    if (decision.verification.status!="proved-under-model") {llvm::errs()<<"csrd: outline validation: "<<decision.verification.reason<<"\n";return false;}
  }
  return true;
}
bool transform(const std::string &path, uint64_t seed, TransformResult &result, const PlanOptions &options, const FrontendOptions &frontend) {
  result.options = options;
  result.frontend = frontend;
  if (!parse(path, seed, result, true, nullptr)) return false;
  if (options.scope == "private-regions") return validatePrivateCandidate(path, result, result.source);
  if (options.scope == "control-regions") return validateControlCandidate(path, result, result.source);
  if (options.scope == "outline-regions") return validateOutlineCandidate(path,result,result.source);
  TransformResult generated;
  generated.options = options;
  generated.frontend = frontend;
  if (!inspect(path, generated, &result.source)) return false;
  result.candidateDependencies = generated.dependencies;
  result.candidateCompilerArguments = generated.compilerArguments;
  if (result.target != generated.target || result.dependencies != generated.dependencies ||
      result.compilerArguments != generated.compilerArguments ||
      (result.compilation && result.compilation->databaseHash != generated.compilation->databaseHash)) {
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
