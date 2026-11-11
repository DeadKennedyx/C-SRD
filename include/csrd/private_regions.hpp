#pragma once
#include "csrd/graph_emitter.hpp"
#include "csrd/verification.hpp"
#include <memory>
#include <set>
#include <string>
#include <vector>

namespace clang { class ASTContext; class FunctionDecl; }
namespace csrd {
struct PrivateFrame {
  unsigned begin = 0, end = 0, candidateBegin = 0, candidateEnd = 0;
  unsigned line = 0, column = 0;
  std::vector<std::string> inputs, outputs;
  std::string originalText;
  std::shared_ptr<Region> original;
  Emission emission;
  Verification verification;
};
struct PrivateBoundary {
  unsigned line = 0, column = 0;
  std::string statement, reason;
};
struct PrivateDiscovery {
  std::vector<PrivateFrame> frames;
  std::vector<PrivateBoundary> boundaries;
  std::string reason;
};
PrivateDiscovery discoverPrivateRegions(clang::ASTContext &, const clang::FunctionDecl &);
Emission emitPrivateFrame(const PrivateFrame &, const Representation &, const std::set<std::string> &reserved);
Verification validatePrivateFrame(clang::ASTContext &, const clang::FunctionDecl &, const PrivateFrame &, unsigned timeoutMs);
} // namespace csrd
