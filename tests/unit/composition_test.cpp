#include "csrd/graph_emitter.hpp"
#include "csrd/verification.hpp"
#include <iostream>
#include <stdexcept>

namespace {
using namespace csrd;
using K = Expr::Kind;
std::unique_ptr<Expr> ref(const std::string &name) {
  auto e = std::make_unique<Expr>(K::Reference); e->name = name; return e;
}
std::unique_ptr<Expr> num(uint32_t value) {
  auto e = std::make_unique<Expr>(K::Constant); e->value = value; return e;
}
std::unique_ptr<Expr> binary(K k, std::unique_ptr<Expr> a, std::unique_ptr<Expr> b) {
  auto e = std::make_unique<Expr>(k); e->left = std::move(a); e->right = std::move(b); return e;
}
std::unique_ptr<Expr> shift(K k, const std::string &name, unsigned count) {
  auto e = std::make_unique<Expr>(k); e->left = ref(name); e->value = count; return e;
}
Region original() {
  Region r; r.name = "f"; r.parameters = {"x", "y"};
  r.statements.emplace_back(Statement::Kind::Return, "", binary(K::Add, ref("x"), ref("y")));
  return r;
}
Region candidate() {
  Region r; r.name = "f"; r.parameters = {"a", "b"};
  auto add = [&](const std::string &name, std::unique_ptr<Expr> e) {
    r.statements.emplace_back(Statement::Kind::Declare, name, std::move(e));
  };
  add("l0", binary(K::BitAnd, ref("a"), num(65535)));
  add("h0", shift(K::ShiftRight, "a", 16));
  add("l1", binary(K::BitAnd, ref("b"), num(65535)));
  add("h1", shift(K::ShiftRight, "b", 16));
  add("sum", binary(K::Add, ref("l0"), ref("l1")));
  add("lo", binary(K::BitAnd, ref("sum"), num(65535)));
  add("hi", binary(K::BitAnd, binary(K::Add, binary(K::Add, ref("h0"), ref("h1")),
                                    shift(K::ShiftRight, "sum", 16)), num(65535)));
  add("decoded", binary(K::BitOr, ref("lo"), shift(K::ShiftLeft, "hi", 16)));
  r.statements.emplace_back(Statement::Kind::Return, "", ref("decoded"));
  return r;
}
void require(bool value, const std::string &message) { if (!value) throw std::runtime_error(message); }
}
int main() {
  try {
    const auto source = original(); const auto graph = lower(source);
    const auto witness = emitLimbs16(graph, 0, {}).limbWitness;
    auto run = [&](const Region &r, const Graph &g, const LimbWitness &w, unsigned timeout = 5000) {
      return verifyLimbsComposition(source, r, g, w, timeout);
    };
    const auto valid = run(candidate(), graph, witness);
    require(valid.status == "proved-under-model", "valid artifact rejected: " + valid.reason);
    require(valid.steps.size() == graph.nodes.size() + 2, "missing proof steps");
    require(valid.composition->witness.nodes[0].low.name == "l0", "hints not rebound to actual declarations");
    {
      auto g = graph; g.nodes.back().kind = K::Subtract;
      const auto bad = run(candidate(), g, witness);
      require(bad.status != "proved-under-model" && bad.steps.at(0).status == "counterexample",
              "wrong graph bypassed original-to-graph check");
    }
    {
      auto g = graph; g.nodes.back().inputs[0] = unsigned(g.nodes.size() - 1);
      require(run(candidate(), g, witness).status == "unsupported", "cyclic graph admitted");
    }
    {
      auto g = graph; g.nodes[0].parameter = "nonexistent";
      require(run(candidate(), g, witness).status == "unsupported", "unknown graph parameter admitted");
    }
    {
      auto w = witness; w.nodes.pop_back();
      require(run(candidate(), graph, w).status == "unsupported", "missing checkpoint admitted");
    }
    {
      auto w = witness; w.nodes[0].low.name = w.declarations.back();
      require(run(candidate(), graph, w).status == "unsupported", "future value admitted at entry");
    }
    {
      auto w = witness; w.nodes[1].declarationEnd = 0;
      require(run(candidate(), graph, w).status == "unsupported", "backward checkpoint admitted");
    }
    {
      auto w = witness; w.declarations[1] = w.declarations[0];
      require(run(candidate(), graph, w).status == "unsupported", "duplicate hint name admitted");
    }
    {
      auto r = candidate(); r.statements[0].expression->right->value = 131071;
      const auto bad = run(r, graph, witness);
      require(bad.status != "proved-under-model" && bad.steps.back().status == "local-counterexample",
              "decoded equality alone admitted an out-of-range piece");
      require(!bad.steps.back().localValues.empty(), "local countermodel missing");
    }
    {
      auto r = candidate(); r.statements[4].expression = binary(K::Add, ref("a"), ref("l1"));
      require(run(r, graph, witness).status == "unsupported", "ordinary parameter crossed an unproved cutpoint");
    }
    {
      auto r = candidate(); r.statements[6].expression = num(0);
      require(run(r, graph, witness).status != "proved-under-model", "lost carry admitted");
    }
    {
      auto r = candidate(); r.statements.back().expression = num(0);
      const auto bad = run(r, graph, witness);
      require(bad.status != "proved-under-model" && bad.steps.back().label == "emitted-return",
              "wrong actual return admitted");
    }
    {
      auto r = candidate(); r.statements[5].kind = Statement::Kind::Assign;
      require(run(r, graph, witness).status == "unsupported", "mutable checkpoint admitted");
    }
    require(run(candidate(), graph, witness, 0).status == "inconclusive", "exhausted budget admitted");
    std::cout << "PASS compositional positive contract and 13 rejection/budget controls\n";
    return 0;
  } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
