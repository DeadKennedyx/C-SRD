#pragma once
#include "csrd/graph_emitter.hpp"
#include "csrd/verification.hpp"
#include "csrd/integer.hpp"
#include <memory>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace clang { class ASTContext; class FunctionDecl; }
namespace csrd {
struct PrivateBinding {
  std::string name;
  unsigned declaration = 0, candidateDeclaration = 0;
  bool registerStorage = false;
  IntegerType type;
};
struct PrivateFrame {
  unsigned begin = 0, end = 0, candidateBegin = 0, candidateEnd = 0;
  unsigned parentBegin = 0, candidateParentBegin = 0;
  unsigned line = 0, column = 0;
  unsigned longBits = 64;
  bool plainCharSigned = true;
  // IR names are declaration IDs, never source spellings (which can shadow).
  std::vector<std::string> inputs, outputs;
  std::vector<std::string> declarations;
  std::map<std::string, PrivateBinding> bindings;
  std::map<std::string, unsigned> emittedDeclarations;
  std::string originalText;
  std::shared_ptr<IntegerRegion> original;
  IntegerWitness witness;
  Emission emission;
  Verification verification;
};
struct PrivateReference {
  unsigned position = 0, declaration = 0;
  bool mainFile = false;
  std::string file, name, kind;
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
Emission emitPrivateFrame(PrivateFrame &, const IntegerCodec &, const std::set<std::string> &reserved);
// Called with every edit in the translation unit, after emission.
void preparePrivateFrames(std::vector<PrivateFrame *>);
std::vector<PrivateReference> privateReferences(clang::ASTContext &, const clang::FunctionDecl &);
bool privateContextMatches(const std::vector<PrivateReference> &, const std::vector<PrivateReference> &,
                           const std::vector<const PrivateFrame *> &, std::string &reason);
Verification validatePrivateFrame(clang::ASTContext &, const clang::FunctionDecl &, const PrivateFrame &, unsigned timeoutMs);
} // namespace csrd
