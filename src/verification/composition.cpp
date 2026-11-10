#include "symbolic.hpp"
#include "csrd/graph_emitter.hpp"
#include <algorithm>
#include <chrono>
#include <set>
#include <stdexcept>

namespace csrd {
namespace {
using Clock = std::chrono::steady_clock;
using verification_detail::Environment;
using verification_detail::expression;
unsigned remaining(Clock::time_point deadline) {
  const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(deadline - Clock::now()).count();
  return ms > 0 ? unsigned(ms) : 0u;
}
std::unique_ptr<Expr> reference(const std::string &name) {
  auto e = std::make_unique<Expr>(Expr::Kind::Reference); e->name = name; return e;
}
unsigned arity(Expr::Kind kind) {
  using K = Expr::Kind;
  switch (kind) {
  case K::Constant: case K::Reference: return 0;
  case K::Scale: case K::BitNot: case K::ShiftLeft: case K::ShiftRight: case K::Table: return 1;
  case K::Select: return 3;
  case K::Add: case K::Subtract: case K::BitAnd: case K::BitOr: case K::BitXor:
  case K::Equal: case K::NotEqual: case K::Less: case K::LessEqual: case K::Greater: case K::GreaterEqual: return 2;
  }
  throw std::invalid_argument("invalid proposed graph operation");
}
void validateGraph(const Graph &g, const Region &original) {
  if (g.nodes.empty() || g.nodes.size() > 4096 || g.result >= g.nodes.size())
    throw std::invalid_argument("invalid proposed graph size/result");
  for (unsigned id = 0; id < g.nodes.size(); ++id) {
    const auto &n = g.nodes[id];
    if (n.inputs.size() != arity(n.kind)) throw std::invalid_argument("invalid proposed graph arity");
    for (auto input : n.inputs) if (input >= id) throw std::invalid_argument("proposed graph is not topological");
    if (n.kind == Expr::Kind::Reference &&
        std::find(original.parameters.begin(), original.parameters.end(), n.parameter) == original.parameters.end())
      throw std::invalid_argument("proposed graph references an unknown parameter");
    if ((n.kind == Expr::Kind::ShiftLeft || n.kind == Expr::Kind::ShiftRight) && n.value >= 32)
      throw std::invalid_argument("invalid proposed graph shift");
    if (n.kind == Expr::Kind::Table && (n.table.empty() || n.table.size() > 16))
      throw std::invalid_argument("invalid proposed graph table");
  }
}
std::unique_ptr<Expr> operation(const Node &n, const std::vector<std::string> &operands) {
  auto e = std::make_unique<Expr>(n.kind); e->value = n.value; e->name = n.parameter; e->table = n.table;
  if (!operands.empty()) e->left = reference(operands[0]);
  if (operands.size() > 1) e->right = reference(operands[1]);
  if (operands.size() > 2) e->third = reference(operands[2]);
  return e;
}
Region ordinaryGraph(const Graph &g, const Region &original) {
  Region r; r.name = original.name; r.parameters = original.parameters;
  std::set<std::string> used(r.parameters.begin(), r.parameters.end());
  std::vector<std::string> names;
  unsigned next = 0;
  for (const auto &n : g.nodes) {
    std::string name;
    do { name = "csrd_proof_" + std::to_string(next++); } while (!used.insert(name).second);
    std::vector<std::string> operands;
    for (auto input : n.inputs) operands.push_back(names.at(input));
    r.statements.emplace_back(Statement::Kind::Declare, name, operation(n, operands));
    names.push_back(name);
  }
  r.statements.emplace_back(Statement::Kind::Return, "", reference(names.at(g.result)));
  return r;
}

// Hints identify declaration positions, not trusted source spellings. Every
// returned expression is evaluated from the actual candidate Region.
class Partition {
  const Region &candidate;
  std::map<std::string, unsigned> positions;
public:
  Partition(const Region &r, const LimbWitness &w) : candidate(r) {
    if (r.statements.size() != w.declarations.size() + 1 ||
        r.statements.back().kind != Statement::Kind::Return)
      throw std::invalid_argument("candidate does not match proposed declaration partition");
    std::set<std::string> actual(r.parameters.begin(), r.parameters.end());
    if (actual.size() != r.parameters.size()) throw std::invalid_argument("duplicate parameter names");
    for (unsigned i = 0; i < w.declarations.size(); ++i) {
      const auto &s = r.statements[i];
      if (s.kind != Statement::Kind::Declare || !actual.insert(s.name).second ||
          w.declarations[i].empty() || !positions.emplace(w.declarations[i], i).second)
        throw std::invalid_argument("partition requires unique immutable declarations");
    }
  }
  std::string name(const LimbPiece &p, unsigned before) const {
    const auto found = positions.find(p.name);
    if (found == positions.end() || found->second >= before)
      throw std::invalid_argument("piece refers to an unavailable declaration");
    return candidate.statements[found->second].name;
  }
  z3::expr input(z3::context &ctx, const LimbPiece &p, unsigned before, Environment &env,
                 Environment &symbols) const {
    if (p.name.empty()) return ctx.bv_val(p.constant, 32);
    const auto actual = name(p, before);
    auto found = env.find(actual);
    if (found != env.end()) return found->second;
    const auto value = z3::zext(ctx.bv_const(("piece_" + std::to_string(positions.at(p.name))).c_str(), 16), 16);
    env.emplace(actual, value); symbols.emplace(actual, value); return value;
  }
  z3::expr output(z3::context &ctx, const LimbPiece &p, unsigned before, const Environment &env) const {
    return p.name.empty() ? ctx.bv_val(p.constant, 32) : env.at(name(p, before));
  }
  void execute(z3::context &ctx, unsigned begin, unsigned end, Environment &env) const {
    for (unsigned i = begin; i < end; ++i) {
      const auto &s = candidate.statements[i];
      // A missing binding rejects hidden cross-fragment dependencies. Do not
      // carry earlier auxiliary values or impose unproved relations on inputs.
      try { env.insert_or_assign(s.name, expression(ctx, *s.expression, env)); }
      catch (const std::out_of_range &) {
        throw std::invalid_argument("fragment declaration " + s.name + " reads outside its proved input set");
      }
    }
  }
};
z3::expr join(const z3::expr &low, const z3::expr &high) {
  // The invariant uses positional addition, and separately proves both ranges.
  // For normalized pieces this equals low | (high << 16). Keeping addition in
  // polynomial form avoids hiding distributivity inside an OR before scale.
  // The actual C return (which uses OR) is independently checked below.
  return low + high * low.ctx().bv_val(65536, 32);
}
Verification check(z3::context &ctx, const z3::expr &mismatch, const Environment &symbols,
                   const std::string &label, unsigned timeout) {
  Verification r; r.label = label; r.strategy = "simplify/bit-blast/sat";
  if (!timeout) { r.status = "inconclusive"; r.reason = "shared compositional timeout exhausted"; return r; }
  z3::params p(ctx); p.set("som", true); p.set("push_ite_bv", true);
  auto solver = (z3::with(z3::tactic(ctx, "simplify"), p) & z3::tactic(ctx, "bit-blast") &
                 z3::tactic(ctx, "sat")).mk_solver();
  solver.set("timeout", timeout); solver.add(mismatch); r.obligation = solver.to_smt2();
  const auto answer = solver.check();
  if (answer == z3::unsat) r.status = "proved-under-model";
  else if (answer == z3::sat) {
    r.status = "local-counterexample";
    r.reason = "countermodel to a local invariant; not necessarily a reachable function input";
    const auto model = solver.get_model();
    for (const auto &[name, value] : symbols)
      r.localValues.emplace_back(name, uint32_t(model.eval(value, true).get_numeral_uint64()));
  } else { r.status = "inconclusive"; r.reason = solver.reason_unknown(); }
  return r;
}
bool append(Verification &result, Verification step) {
  const bool ok = step.status == "proved-under-model";
  if (!ok) { result.status = "inconclusive"; result.reason = step.label + ": " + step.status + " " + step.reason; }
  result.steps.push_back(std::move(step)); return ok;
}
}

Verification verifyLimbsComposition(const Region &original, const Region &candidate,
                                    const Graph &graph, const LimbWitness &witness, unsigned timeoutMs) {
  Verification result; result.strategy = "compositional-limbs16";
  const auto deadline = Clock::now() + std::chrono::milliseconds(timeoutMs);
  try {
    if (original.parameters.size() != candidate.parameters.size()) throw std::invalid_argument("parameter arity mismatch");
    validateGraph(graph, original);
    if (witness.nodes.size() != graph.nodes.size()) throw std::invalid_argument("incomplete graph partition");
    const Partition partition(candidate, witness);
    unsigned previous = 0;
    for (const auto &point : witness.nodes) {
      if (point.declarationEnd < previous || point.declarationEnd > witness.declarations.size())
        throw std::invalid_argument("invalid checkpoint ordering");
      previous = point.declarationEnd;
    }
    result.composition = std::make_shared<LimbEvidence>();
    result.composition->graph = graph;
    result.composition->witness = witness;
    for (unsigned i = 0; i < witness.declarations.size(); ++i)
      result.composition->witness.declarations[i] = candidate.statements[i].name;
    for (auto &point : result.composition->witness.nodes) {
      for (auto *piece : {&point.low, &point.high})
        if (!piece->name.empty()) piece->name = partition.name(*piece, point.declarationEnd);
    }
    // Independent ordered-region execution checks lowering, including branches,
    // loops, tables and dead-code pruning. The lowerer is not assumed correct.
    const auto sourceBudget = std::min(1000u, remaining(deadline));
    if (!sourceBudget) { result.status = "inconclusive"; result.reason = "shared compositional timeout exhausted"; return result; }
    auto sourceProof = verification_detail::verifyDirect(original, ordinaryGraph(graph, original), sourceBudget);
    sourceProof.label = "source-to-graph";
    if (!append(result, std::move(sourceProof))) return result;
    unsigned begin = 0;
    for (unsigned id = 0; id < graph.nodes.size(); ++id) {
      z3::context ctx; Environment env, symbols, operands;
      const auto &node = graph.nodes[id]; const auto &point = witness.nodes[id];
      std::vector<std::string> names;
      for (unsigned i = 0; i < node.inputs.size(); ++i) {
        const auto &input = witness.nodes[node.inputs[i]];
        const auto low = partition.input(ctx, input.low, begin, env, symbols);
        const auto high = partition.input(ctx, input.high, begin, env, symbols);
        names.push_back("operand_" + std::to_string(i)); operands.emplace(names.back(), join(low, high));
      }
      if (node.kind == Expr::Kind::Reference) {
        const auto pos = unsigned(std::find(original.parameters.begin(), original.parameters.end(), node.parameter) - original.parameters.begin());
        const auto value = ctx.bv_const("parameter", 32);
        env.emplace(candidate.parameters[pos], value); symbols.emplace(candidate.parameters[pos], value);
        operands.emplace(node.parameter, value);
      }
      const auto expected = expression(ctx, *operation(node, names), operands);
      partition.execute(ctx, begin, point.declarationEnd, env);
      const auto low = partition.output(ctx, point.low, point.declarationEnd, env);
      const auto high = partition.output(ctx, point.high, point.declarationEnd, env);
      const auto bound = ctx.bv_val(65535, 32);
      const auto bad = (join(low, high) != expected) || !z3::ule(low, bound) || !z3::ule(high, bound);
      if (!append(result, check(ctx, bad, symbols, "node-" + std::to_string(id) + "-" + operationName(node.kind),
                                std::min(1000u, remaining(deadline))))) return result;
      begin = point.declarationEnd;
    }
    z3::context ctx; Environment env, symbols;
    const auto &output = witness.nodes[graph.result];
    const auto low = partition.input(ctx, output.low, begin, env, symbols);
    const auto high = partition.input(ctx, output.high, begin, env, symbols);
    const auto expected = join(low, high);
    partition.execute(ctx, begin, unsigned(witness.declarations.size()), env);
    const auto actual = expression(ctx, *candidate.statements.back().expression, env);
    if (!append(result, check(ctx, actual != expected, symbols, "emitted-return", remaining(deadline)))) return result;
    result.status = "proved-under-model";
  } catch (const z3::exception &e) { result.status = "inconclusive"; result.reason = e.msg(); }
    catch (const std::exception &e) { result.status = "unsupported"; result.reason = e.what(); }
  return result;
}

Verification verify(const Region &original, const Region &candidate, unsigned timeoutMs) {
  const auto deadline = Clock::now() + std::chrono::milliseconds(timeoutMs);
  Verification attempt;
  try {
    // Proposal generation is allowed to be incomplete or wrong. It cannot
    // establish a theorem: the independent checks above must all succeed.
    const bool straight = !candidate.statements.empty() && candidate.statements.back().kind == Statement::Kind::Return &&
      std::all_of(candidate.statements.begin(), candidate.statements.end() - 1,
                  [](const Statement &s) { return s.kind == Statement::Kind::Declare; });
    if (straight && original.parameters.size() == candidate.parameters.size() && timeoutMs >= 4) {
      const auto graph = lower(original);
      const std::set<std::string> reserved(original.parameters.begin(), original.parameters.end());
      const auto proposal = emitLimbs16(graph, 0, reserved);
      if (candidate.statements.size() == proposal.limbWitness.declarations.size() + 1) {
        attempt = verifyLimbsComposition(original, candidate, graph, proposal.limbWitness,
                                         std::min(timeoutMs / 2, remaining(deadline)));
        if (attempt.status == "proved-under-model") return attempt;
      }
    }
  } catch (const std::exception &e) { attempt.status = "unsupported"; attempt.reason = e.what(); }
  const auto budget = remaining(deadline);
  Verification result;
  if (budget) result = verification_detail::verifyDirect(original, candidate, budget);
  else { result.status = "inconclusive"; result.reason = "verification timeout exhausted"; }
  if (attempt.status != "not-verified") result.priorAttempts.push_back(std::move(attempt));
  return result;
}
}
