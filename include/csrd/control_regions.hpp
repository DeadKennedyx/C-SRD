#pragma once
#include "csrd/private_regions.hpp"
#include <cstdint>
#include <set>
#include <string>
#include <vector>

namespace clang { class ASTContext; class FunctionDecl; }
namespace csrd {
// Negative edges leave the region; nonnegative edges index its nodes.
constexpr int ControlEnd = -1, ControlBreak = -2, ControlContinue = -3;
enum class ControlKind { Effect, Branch, Return, Jump };
struct ControlNode {
  ControlKind kind = ControlKind::Jump;
  int yes = ControlEnd, no = ControlEnd;
  unsigned begin = 0, end = 0, emittedOffset = 0;
  uint32_t state = 0;
  std::string text;
};
struct ControlFrame {
  unsigned begin = 0, end = 0, parentBegin = 0;
  unsigned candidateBegin = 0, candidateEnd = 0, candidateParentBegin = 0;
  unsigned line = 0, column = 0, stateDeclarationOffset = 0;
  unsigned branches = 0, loops = 0;
  int entry = ControlEnd;
  bool outerBreak = false, outerContinue = false;
  std::string originalText, emitted, stateName;
  std::vector<ControlNode> nodes;
  Verification verification;
};
struct ControlDiscovery {
  std::vector<ControlFrame> frames;
  std::vector<PrivateBoundary> boundaries;
  std::string reason;
};
ControlDiscovery discoverControlRegions(clang::ASTContext &, const clang::FunctionDecl &);
void emitControlFrame(ControlFrame &, uint64_t seed, const std::string &function,
                      const std::set<std::string> &reserved);
void prepareControlFrames(std::vector<ControlFrame *>);
Verification validateControlFrame(clang::ASTContext &, const clang::FunctionDecl &, const ControlFrame &);
bool controlContextMatches(const std::vector<PrivateReference> &, const std::vector<PrivateReference> &,
                           const std::vector<const ControlFrame *> &, std::string &reason);
const char *controlKindName(ControlKind);
std::set<int> controlExits(const ControlFrame &);
} // namespace csrd
