#pragma once
#include "csrd/planner.hpp"
#include "csrd/limb_witness.hpp"
#include <set>
namespace csrd {
struct Emission {
  std::string body;
  LimbWitness limbWitness;
  unsigned operations = 0, encodedOperations = 0, boundaryConversions = 0,
           internalConversions = 0, estimatedOperations = 0, temporaries = 0,
           encodings = 0, decodings = 0, ordinaryIntermediates = 0, splitScales = 0;
};
Emission emitGraph(const Graph &graph, const Plan &plan, const PlanOptions &options,
                   const Affine &affine, uint32_t xorMask, unsigned originalNewlines,
                   const std::set<std::string> &reserved);
Emission emitLimbs16(const Graph &graph, unsigned originalNewlines, const std::set<std::string> &reserved);
Emission emitPositional(const Graph &graph, unsigned pieceBits, unsigned originalNewlines,
                        const std::set<std::string> &reserved);
}
