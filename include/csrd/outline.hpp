#pragma once
#include "csrd/private_regions.hpp"
#include <set>

namespace csrd {
struct OutlineEdit {
  unsigned begin=0, end=0, candidateBegin=0, candidateEnd=0;
  std::string original, emitted;
};
struct OutlineCapture {
  std::string name, type, parameter;
  unsigned declaration=0, candidateDeclaration=0;
};
struct OutlineToken { std::string text; int capture=-1; };
struct OutlineFrame : OutlineEdit {
  unsigned line=0, column=0, operations=0, callBytes=0;
  std::string type, signature, helper;
  std::vector<OutlineCapture> captures;
  std::vector<unsigned> argumentOrder;
  std::vector<OutlineToken> tokens;
  Verification verification;
};
struct OutlineFunction {
  OutlineEdit insertion;
  std::vector<OutlineFrame> frames;
  std::vector<PrivateBoundary> boundaries;
  std::string reason;
};
OutlineFunction discoverOutline(clang::ASTContext &, const clang::FunctionDecl &);
void emitOutline(OutlineFunction &, uint64_t seed, std::set<std::string> &reserved);
void prepareOutline(std::vector<OutlineFunction *>);
std::vector<const OutlineEdit *> outlineEdits(const std::vector<const OutlineFunction *> &);
bool outlineContextMatches(const std::vector<PrivateReference> &, const std::vector<PrivateReference> &,
                           const std::vector<const OutlineFunction *> &, std::string &reason);
Verification validateOutline(clang::ASTContext &, const clang::FunctionDecl &, OutlineFunction &);
} // namespace csrd
