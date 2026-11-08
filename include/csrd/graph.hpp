#pragma once
#include "csrd/ir.hpp"
#include <set>
namespace csrd {
struct Node {
  Expr::Kind kind = Expr::Kind::Constant;
  uint32_t value = 0;
  std::string parameter;
  std::vector<unsigned> inputs;
  std::vector<uint32_t> table;
};
struct Graph {
  std::vector<Node> nodes;
  unsigned result = 0;
};
Graph lower(const Region &region);
const char *operationName(Expr::Kind kind);
bool isArithmetic(Expr::Kind kind);
bool isBitwise(Expr::Kind kind);
bool isComparison(Expr::Kind kind);
}
