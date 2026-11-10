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
struct LimbCheckpoint {
  unsigned declarationEnd = 0;
  LimbPiece low, high;
};
struct LimbWitness {
  std::vector<std::string> declarations;
  std::vector<LimbCheckpoint> nodes;
};
}
