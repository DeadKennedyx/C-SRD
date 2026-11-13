#pragma once
#include <cstdint>
#include <string>
#include <vector>
#include <memory>
#include "csrd/ir.hpp"
#include "csrd/verification.hpp"
#include "csrd/graph_emitter.hpp"
#include "csrd/metrics.hpp"
#include "csrd/private_regions.hpp"
#include "csrd/compilation.hpp"
namespace csrd {
struct Decision {
  std::string function, status, reason;
  unsigned line = 0, column = 0, operations = 0, conversions = 0;
  uint32_t a = 0, b = 0, inverse = 0;
  Verification verification;
  std::shared_ptr<Region> region;
  std::shared_ptr<Graph> graph;
  Plan plan;
  Emission emission;
  uint32_t xorMask = 0;
  unsigned parameterCount = 0;
  Metrics metrics;
  std::vector<PrivateFrame> privateFrames;
  std::vector<PrivateBoundary> privateBoundaries;
  std::vector<PrivateReference> privateReferences;
  bool privateContextVerified = false;
};
struct TransformResult {
  std::string source;
  std::vector<Decision> decisions;
  std::string target;
  std::string inputHash, outputHash;
  std::vector<std::pair<std::string, std::string>> dependencies;
  PlanOptions options;
  FrontendOptions frontend;
  std::optional<CompilationConfiguration> compilation;
  std::vector<std::string> compilerArguments, candidateCompilerArguments;
  std::vector<std::pair<std::string, std::string>> candidateDependencies;
  bool outputWritten = false;
};
bool transform(const std::string &path, uint64_t seed, TransformResult &result,
               const PlanOptions &options = {}, const FrontendOptions &frontend = {});
bool inspect(const std::string &path, TransformResult &result, const std::string *contents = nullptr);
// Freeze the chosen preprocessing configuration into Clang's .i input format.
// This records provenance, not a proof of the preprocessor implementation.
bool preprocess(const std::string &path, TransformResult &result);
// Reparse actual C, enforce unchanged surrounding bytes, then check every frame.
bool validatePrivateCandidate(const std::string &path, TransformResult &result, const std::string &candidate);
std::string sha256(const std::string &data);
}
