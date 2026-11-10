#pragma once
#include "csrd/planner.hpp"
#include <set>
namespace csrd {
struct Emission {
  std::string body;
  unsigned operations = 0, encodedOperations = 0, boundaryConversions = 0,
           internalConversions = 0, estimatedOperations = 0, temporaries = 0,
           encodings = 0, decodings = 0, ordinaryIntermediates = 0, splitScales = 0;
};
Emission emitGraph(const Graph &graph, const Plan &plan, const PlanOptions &options,
                   const Affine &affine, uint32_t xorMask, unsigned originalNewlines,
                   const std::set<std::string> &reserved);
}
