#pragma once
#include "csrd/ir.hpp"
#include "csrd/graph.hpp"
#include "csrd/limb_witness.hpp"
#include <cstdint>
#include <string>
#include <vector>
namespace csrd {
struct LimbEvidence {
  Graph graph;
  LimbWitness witness;
};
struct Verification {
  std::string status = "not-verified", reason, obligation, strategy;
  std::string label;
  std::vector<Verification> steps, priorAttempts;
  std::vector<std::pair<std::string, uint32_t>> localValues;
  std::shared_ptr<LimbEvidence> composition;
  std::vector<uint32_t> inputs;
  uint32_t originalOutput = 0, candidateOutput = 0;
  // Memory counterexamples use mathematical word addresses, not host pointers.
  std::vector<std::pair<std::string, std::string>> pointerBases;
  struct MemoryCell { std::string address; uint32_t initial, original, candidate; };
  std::vector<MemoryCell> memoryCells;
};
Verification verify(const Region &original, const Region &candidate, unsigned timeoutMs = 10000);
Verification verifyMemory(const Region &original, const Region &candidate, unsigned timeoutMs);
// Graph and witness are untrusted proposals; all actual C fragments and the
// original-to-graph relationship must be checked before success is returned.
Verification verifyLimbsComposition(const Region &original, const Region &candidate,
                                    const Graph &graph, const LimbWitness &witness, unsigned timeoutMs);
std::string solverVersion();
}
