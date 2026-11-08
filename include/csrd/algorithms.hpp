#pragma once
#include "csrd/graph.hpp"
namespace csrd {
// Explicit candidate algorithms. Equivalence is never inferred from a name:
// the ordinary emitted-C translation validator must prove the replacement.
Graph algorithmCandidate(const Region &source, const std::string &algorithm);
}
