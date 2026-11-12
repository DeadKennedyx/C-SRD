#include "csrd/graph.hpp"
#include <map>
#include <stdexcept>

namespace csrd {
namespace {
class Lowerer {
  Graph graph;
  using Environment = std::map<std::string, unsigned>;
  unsigned add(Node node) {
    if (graph.nodes.size() >= 4096) throw std::runtime_error("expanded region exceeds 4096 graph nodes");
    graph.nodes.push_back(std::move(node)); return unsigned(graph.nodes.size() - 1);
  }
  unsigned constant(uint32_t value) { Node node; node.value = value; return add(std::move(node)); }
  unsigned expression(const Expr &e, const Environment &env) {
    if (e.kind == Expr::Kind::Reference) return env.at(e.name);
    Node node; node.kind = e.kind; node.value = e.value; node.table = e.table;
    if (e.left) node.inputs.push_back(expression(*e.left, env));
    if (e.right) node.inputs.push_back(expression(*e.right, env));
    if (e.third) node.inputs.push_back(expression(*e.third, env));
    return add(std::move(node));
  }
  void statements(const std::vector<Statement> &body, Environment &env) {
    for (const auto &s : body) {
      if (s.kind == Statement::Kind::If) {
        const auto condition = expression(*s.expression, env);
        auto thenValues = env, elseValues = env;
        statements(s.thenBranch, thenValues); statements(s.elseBranch, elseValues);
        for (auto &[name, value] : env) {
          const auto a = thenValues.at(name), b = elseValues.at(name);
          if (a != b) { Node node; node.kind = Expr::Kind::Select; node.inputs = {condition, a, b}; value = add(std::move(node)); }
        }
      } else if (s.kind == Statement::Kind::Repeat) {
        for (unsigned i = 0; i < s.repetitions; ++i) {
          env.insert_or_assign(s.name, constant(i)); statements(s.thenBranch, env);
        }
        env.erase(s.name);
      } else {
        const auto value = expression(*s.expression, env);
        if (s.kind == Statement::Kind::Return) graph.result = value;
        else env.insert_or_assign(s.name, value);
      }
    }
  }
public:
  Graph run(const Region &r) {
    if (!r.buffers.empty()) throw std::invalid_argument("memory effects cannot be lowered through the pure graph");
    Environment env;
    for (const auto &name : r.parameters) { Node n; n.kind = Expr::Kind::Reference; n.parameter = name; env[name] = add(std::move(n)); }
    statements(r.statements, env);
    // Keep only nodes needed by the return; this is sound because accepted operations are total and pure.
    std::vector<bool> live(graph.nodes.size());
    auto visit = [&](auto &&self, unsigned id) -> void { if (live[id]) return; live[id] = true; for (auto input : graph.nodes[id].inputs) self(self, input); };
    visit(visit, graph.result);
    Graph compact; std::vector<unsigned> remap(graph.nodes.size());
    for (unsigned i = 0; i < graph.nodes.size(); ++i) if (live[i]) {
      auto node = std::move(graph.nodes[i]);
      for (auto &input : node.inputs) input = remap[input];
      remap[i] = unsigned(compact.nodes.size()); compact.nodes.push_back(std::move(node));
    }
    compact.result = remap[graph.result]; return compact;
  }
};
}
Graph lower(const Region &region) { return Lowerer().run(region); }
bool isArithmetic(Expr::Kind k) { return k == Expr::Kind::Add || k == Expr::Kind::Subtract || k == Expr::Kind::Scale; }
bool isBitwise(Expr::Kind k) { return k >= Expr::Kind::BitAnd && k <= Expr::Kind::ShiftRight; }
bool isComparison(Expr::Kind k) { return k >= Expr::Kind::Equal && k <= Expr::Kind::GreaterEqual; }
const char *operationName(Expr::Kind k) {
  static const char *names[] = {"constant", "parameter", "add", "subtract", "scale", "and", "or", "xor", "not", "shl", "lshr", "eq", "ne", "ult", "ule", "ugt", "uge", "select", "table", "load", "byte-cast"};
  return names[unsigned(k)];
}
}
