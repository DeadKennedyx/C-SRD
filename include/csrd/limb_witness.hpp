#pragma once
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace csrd {
// Untrusted proof hints. Empty name denotes a literal, otherwise a declared
// temporary. The validator checks the actual reparsed C, not generated text.
struct LimbPiece {
  std::string name;
  uint32_t constant = 0;
  LimbPiece(uint32_t value = 0) : constant(value) {}
  LimbPiece(std::string variable) : name(std::move(variable)) {}
};
struct LimbScaleStep {
  unsigned declarationEnd = 0;
  LimbPiece partial; // first declaration in this step; independently checked
  LimbPiece carry; // final carry is deliberately discarded, represented by zero
};
struct LimbCheckpoint {
  unsigned declarationEnd = 0;
  std::vector<LimbPiece> pieces; // least significant first
  std::vector<LimbScaleStep> scaleSteps;
};
struct LimbWitness {
  unsigned pieceBits = 16;
  std::vector<std::string> declarations;
  std::vector<LimbCheckpoint> nodes;
};
}
