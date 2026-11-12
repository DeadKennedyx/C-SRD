#include "csrd/graph_emitter.hpp"
#include "csrd/verification.hpp"
#include <iostream>
#include <stdexcept>

namespace {
using namespace csrd;
using K = Expr::Kind;
std::unique_ptr<Expr> referenceExpr(const std::string &name) {
  auto e = std::make_unique<Expr>(K::Reference); e->name = name; return e;
}
std::unique_ptr<Expr> num(uint32_t value) {
  auto e = std::make_unique<Expr>(K::Constant); e->value = value; return e;
}
std::unique_ptr<Expr> binary(K k, std::unique_ptr<Expr> a, std::unique_ptr<Expr> b) {
  auto e = std::make_unique<Expr>(k); e->left = std::move(a); e->right = std::move(b); return e;
}
std::unique_ptr<Expr> shift(K k, const std::string &name, unsigned count) {
  auto e = std::make_unique<Expr>(k); e->left = referenceExpr(name); e->value = count; return e;
}
Region original() {
  Region r; r.name = "f"; r.parameters = {"x", "y"};
  r.statements.emplace_back(Statement::Kind::Return, "", binary(K::Add, referenceExpr("x"), referenceExpr("y")));
  return r;
}
Region candidate() {
  Region r; r.name = "f"; r.parameters = {"a", "b"};
  auto add = [&](const std::string &name, std::unique_ptr<Expr> e) {
    r.statements.emplace_back(Statement::Kind::Declare, name, std::move(e));
  };
  add("l0", binary(K::BitAnd, referenceExpr("a"), num(65535)));
  add("h0", shift(K::ShiftRight, "a", 16));
  add("l1", binary(K::BitAnd, referenceExpr("b"), num(65535)));
  add("h1", shift(K::ShiftRight, "b", 16));
  add("sum", binary(K::Add, referenceExpr("l0"), referenceExpr("l1")));
  add("lo", binary(K::BitAnd, referenceExpr("sum"), num(65535)));
  add("hi", binary(K::BitAnd, binary(K::Add, binary(K::Add, referenceExpr("h0"), referenceExpr("h1")),
                                    shift(K::ShiftRight, "sum", 16)), num(65535)));
  add("decoded", binary(K::BitOr, referenceExpr("lo"), shift(K::ShiftLeft, "hi", 16)));
  r.statements.emplace_back(Statement::Kind::Return, "", referenceExpr("decoded"));
  return r;
}
Region scaleSource() {
  Region r; r.name = "f"; r.parameters = {"x"};
  auto e = std::make_unique<Expr>(K::Scale); e->left = referenceExpr("x"); e->value = 3;
  r.statements.emplace_back(Statement::Kind::Return, "", std::move(e)); return r;
}
// Independent IR fixture with different names, not text parsed from the emitter.
Region scaleCandidate() {
  Region r; r.name = "f"; r.parameters = {"a"};
  auto add = [&](const std::string &name, std::unique_ptr<Expr> e) {
    r.statements.emplace_back(Statement::Kind::Declare, name, std::move(e));
  };
  for (unsigned i = 0; i < 4; ++i)
    add("a" + std::to_string(i), binary(K::BitAnd, shift(K::ShiftRight, "a", i * 8), num(255)));
  for (unsigned i = 0; i < 4; ++i) {
    const auto suffix = std::to_string(i);
    auto product = std::make_unique<Expr>(K::Scale); product->left = referenceExpr("a" + suffix); product->value = 3;
    add("p" + suffix, i ? binary(K::Add, std::move(product), referenceExpr("c" + std::to_string(i - 1))) : std::move(product));
    add("d" + suffix, binary(K::BitAnd, referenceExpr("p" + suffix), num(255)));
    if (i < 3) add("c" + suffix, shift(K::ShiftRight, "p" + suffix, 8));
  }
  auto decoded = referenceExpr("d0");
  for (unsigned i = 1; i < 4; ++i)
    decoded = binary(K::BitOr, std::move(decoded), shift(K::ShiftLeft, "d" + std::to_string(i), i * 8));
  add("decoded", std::move(decoded));
  r.statements.emplace_back(Statement::Kind::Return, "", referenceExpr("decoded")); return r;
}
void require(bool value, const std::string &message) { if (!value) throw std::runtime_error(message); }
}
int main() {
  try {
    {
      auto loopRegion = [](unsigned maximum, unsigned limit, bool returns) {
        Region r; r.name = "loop"; r.parameters = {"p"}; r.buffers.emplace("p",Region::Buffer{}); r.memoryControl = true;
        Statement loop(Statement::Kind::Repeat,"i",num(limit)); loop.repetitions = maximum;
        r.statements.push_back(std::move(loop));
        if (returns) r.statements.emplace_back(Statement::Kind::Return,"",num(7));
        return r;
      };
      require(verifyMemory(loopRegion(1,2,true),loopRegion(1,2,true),5000).status == "counterexample",
              "shared loop truncation incorrectly proved");
      require(verifyMemory(loopRegion(0,0,true),loopRegion(0,0,true),5000).status == "proved-under-model",
              "zero-trip termination rejected");
      require(verifyMemory(loopRegion(1,1,false),loopRegion(1,1,false),5000).status == "counterexample",
              "missing function return accepted");
    }
    {
      // Small-index enumeration must prove its domain even when both sides
      // carry the same bad IR hint; otherwise it could prove a shared clamp.
      auto memoryRegion = [](bool bounded) {
        Region r; r.name = "field"; r.parameters = {"p", "x"}; r.extendedMemory = true;
        Region::Buffer b; b.recordTag = "R"; b.recordBytes = b.recordAlignment = 4;
        b.fields.emplace("a",0); b.minimumElements = 1; r.buffers.emplace("p",b);
        auto e = std::make_unique<Expr>(K::Load); e->name = "p"; e->member = "a";
        e->left = bounded ? binary(K::BitAnd,referenceExpr("x"),num(0)) : referenceExpr("x");
        r.statements.emplace_back(Statement::Kind::Return,"",std::move(e));return r;
      };
      require(verifyMemory(memoryRegion(false),memoryRegion(false),5000).status == "counterexample",
              "unproved index bound silently clamped both programs");
      require(verifyMemory(memoryRegion(true),memoryRegion(true),5000).status == "proved-under-model",
              "valid enumerated record index rejected");
    }
    const auto source = original(); const auto graph = lower(source);
    const auto witness = emitLimbs16(graph, 0, {}).limbWitness;
    auto run = [&](const Region &r, const Graph &g, const LimbWitness &w, unsigned timeout = 5000) {
      return verifyLimbsComposition(source, r, g, w, timeout);
    };
    const auto valid = run(candidate(), graph, witness);
    require(valid.status == "proved-under-model", "valid artifact rejected: " + valid.reason);
    require(valid.steps.size() == graph.nodes.size() + 2, "missing proof steps");
    require(valid.composition->witness.nodes[0].pieces[0].name == "l0", "hints not rebound to actual declarations");
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
      auto w = witness; w.nodes[0].pieces[0].name = w.declarations.back();
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
    for (unsigned bits : {0u, 3u, 5u, 32u, 33u}) {
      auto w = witness; w.pieceBits = bits;
      require(run(candidate(), graph, w).status == "unsupported", "invalid proposed piece width admitted");
    }
    {
      auto w = witness; w.pieceBits = 8;
      require(run(candidate(), graph, w).status == "unsupported", "piece count inconsistent with width admitted");
    }
    {
      auto w = witness; w.nodes[0].pieces.pop_back();
      require(run(candidate(), graph, w).status == "unsupported", "incomplete piece vector admitted");
    }
    {
      auto w = witness; w.nodes[0].pieces.push_back(LimbPiece(0));
      require(run(candidate(), graph, w).status == "unsupported", "oversized piece vector admitted");
    }
    {
      auto r = candidate(); r.statements[0].expression->right->value = 131071;
      const auto bad = run(r, graph, witness);
      require(bad.status != "proved-under-model" && bad.steps.back().status == "local-counterexample",
              "decoded equality alone admitted an out-of-range piece");
      require(!bad.steps.back().localValues.empty(), "local countermodel missing");
    }
    {
      auto r = candidate(); r.statements[4].expression = binary(K::Add, referenceExpr("a"), referenceExpr("l1"));
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
    std::cout << "PASS compositional positive contract and 21 rejection/budget controls\n";
    const auto scale = scaleSource(); const auto scaleGraph = lower(scale);
    const auto scaleWitness = emitPositional(scaleGraph, 8, 0, {}).limbWitness;
    auto scaleRun = [&](const Region &r, const LimbWitness &w) {
      return verifyLimbsComposition(scale, r, scaleGraph, w, 5000);
    };
    const auto scaleProof = scaleRun(scaleCandidate(), scaleWitness);
    require(scaleProof.status == "proved-under-model", "valid scale rejected: " + scaleProof.reason);
    require(scaleProof.steps.at(2).strategy == "positional-scale-composition" &&
            scaleProof.steps.at(2).steps.size() == 5, "missing digit/bridge checks");
    require(scaleProof.composition->witness.nodes.back().scaleSteps[0].carry.name == "c0", "carry name not rebound");
    for (unsigned mutation = 0; mutation < 12; ++mutation) {
      auto w = scaleWitness; auto &point = w.nodes.back();
      switch (mutation) {
      case 0: point.scaleSteps.pop_back(); break;
      case 1: point.scaleSteps.push_back(point.scaleSteps.back()); break;
      case 2: point.scaleSteps[0].declarationEnd = w.nodes[0].declarationEnd; break;
      case 3: --point.scaleSteps.back().declarationEnd; break;
      case 4: point.scaleSteps[0].carry.name = w.declarations.back(); break;
      case 5: point.scaleSteps[0].carry = point.pieces[0]; break;
      case 6: point.scaleSteps.back().carry = LimbPiece(1); break;
      case 7: point.scaleSteps.back().carry = point.scaleSteps[0].carry; break;
      case 8: w.nodes[0].scaleSteps = point.scaleSteps; break;
      case 9: std::swap(point.pieces[0], point.pieces[1]); break;
      case 10: point.scaleSteps[0].partial = LimbPiece(0); break;
      case 11: point.scaleSteps[0].partial = point.pieces[0]; break;
      }
      require(scaleRun(scaleCandidate(), w).status != "proved-under-model", "malformed scale hint admitted: " + std::to_string(mutation));
    }
    for (unsigned mutation = 0; mutation < 5; ++mutation) {
      auto r = scaleCandidate();
      switch (mutation) {
      case 0: r.statements[4].expression->value = 4; break;
      case 1: r.statements[6].expression->value = 7; break;
      case 2: r.statements[5].expression->right->value = 511; break;
      case 3: r.statements[7].expression->right = num(0); break;
      case 4: r.statements.back().expression = num(0); break;
      }
      require(scaleRun(r, scaleWitness).status != "proved-under-model", "corrupted actual scale admitted: " + std::to_string(mutation));
    }
    std::cout << "PASS scale microcomposition and 17 malformed-hint/actual-code controls\n";
    return 0;
  } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
