#pragma once
#include "csrd/graph.hpp"
#include "csrd/representation.hpp"
namespace csrd {
enum class Encoding : unsigned { Identity = 0, Affine = 1, Xor = 2 };
struct PlanOptions {
  std::string strategy = "affine", objective = "balanced";
  std::string algorithm = "none";
  std::string controlFlow = "none";
  unsigned coverage = 50, timeoutMs = 10000;
};
struct Plan {
  std::vector<Encoding> labels;
  std::string status = "baseline", reason;
  unsigned requiredEncoded = 0, estimatedOperations = 0, conversions = 0, statements = 0;
};
std::vector<Encoding> allowed(const Node &node);
unsigned operationCost(const Node &node, Encoding encoding);
unsigned conversionCost(Encoding from, Encoding to);
Encoding inputEncoding(const Node &node, unsigned operand, Encoding output);
Plan plan(const Graph &graph, const PlanOptions &options);
const char *encodingName(Encoding encoding);
}
