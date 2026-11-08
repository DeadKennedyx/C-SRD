#include "csrd/algorithms.hpp"
#include <stdexcept>
namespace csrd {
Graph algorithmCandidate(const Region &source, const std::string &algorithm) {
  if (source.parameters.size() != 1) throw std::runtime_error("popcount8 candidates require one uint32_t parameter");
  Graph g;
  auto node = [&](Expr::Kind kind, std::vector<unsigned> inputs, uint32_t value = 0) {
    Node n; n.kind = kind; n.inputs = std::move(inputs); n.value = value;
    g.nodes.push_back(std::move(n)); return unsigned(g.nodes.size() - 1);
  };
  auto constant = [&](uint32_t value) { return node(Expr::Kind::Constant, {}, value); };
  auto binary = [&](Expr::Kind kind, unsigned a, unsigned b) { return node(kind, {a, b}); };
  using K = Expr::Kind;
  const auto input = node(K::Reference, {}); g.nodes[input].parameter = source.parameters[0];
  auto x = binary(K::BitAnd, input, constant(255));
  if (algorithm == "popcount8-serial") {
    auto count = constant(0);
    for (unsigned bit = 0; bit < 8; ++bit) {
      count = binary(K::Add, count, binary(K::BitAnd, node(K::ShiftRight, {x}, bit), constant(1)));
    }
    g.result = count;
  } else if (algorithm == "popcount8-swar") {
    x = binary(K::Subtract, x, binary(K::BitAnd, node(K::ShiftRight, {x}, 1), constant(85)));
    x = binary(K::Add, binary(K::BitAnd, x, constant(51)), binary(K::BitAnd, node(K::ShiftRight, {x}, 2), constant(51)));
    g.result = binary(K::BitAnd, binary(K::Add, x, node(K::ShiftRight, {x}, 4)), constant(15));
  } else throw std::runtime_error("unknown candidate algorithm");
  return g;
}
}
