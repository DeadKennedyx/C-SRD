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
  case K::Load: case K::ByteCast: case K::PointerNonNull: throw std::invalid_argument("memory expression is not a pure graph operation");
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
  const unsigned bits;
  std::map<std::string, unsigned> positions;
public:
  Partition(const Region &r, const LimbWitness &w) : candidate(r), bits(w.pieceBits) {
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
                 Environment &symbols, unsigned symbolBits = 0) const {
    if (p.name.empty()) return ctx.bv_val(p.constant, 32);
    const auto actual = name(p, before);
    auto found = env.find(actual);
    if (found != env.end()) return found->second;
    const auto width = symbolBits ? symbolBits : bits;
    const auto value = z3::zext(ctx.bv_const(("piece_" + std::to_string(positions.at(p.name))).c_str(), width), 32 - width);
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
z3::expr join(z3::context &ctx, const std::vector<z3::expr> &pieces, unsigned bits) {
  // Positional equality plus independently checked ranges. Polynomial form
  // exposes scale distributivity; the actual C OR-based return is checked too.
  auto result = ctx.bv_val(0, 32);
  for (unsigned i = 0; i < pieces.size(); ++i)
    result = result + pieces[i] * ctx.bv_val(uint32_t(1) << (i * bits), 32);
  return result;
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

// Each actual C digit/carry fragment establishes a weighted modular equation.
// Carry inputs are arbitrary u32 values, never assumed to fit in one digit.
// A separately checked telescoping identity connects these local equations to
// decoded multiplication. No part of the emitted C is trusted by this bridge.
Verification scaleComposition(const Partition &partition, const LimbCheckpoint &input,
                              const LimbCheckpoint &point, uint32_t factor, unsigned bits,
                              unsigned begin, Clock::time_point deadline, const std::string &label) {
  Verification result; result.label = label; result.strategy = "positional-scale-composition";
  const unsigned count = unsigned(point.pieces.size());
  const auto wordBegin = begin;
  LimbPiece previousCarry(0);
  for (unsigned i = 0; i < count; ++i) {
    const auto &step = point.scaleSteps[i];
    Verification digit; digit.label = "digit-" + std::to_string(i); digit.strategy = "positional-scale-digit";
    {
      z3::context ctx; Environment env, symbols;
      // Bind the unrestricted carry first. If an untrusted hint aliases it with
      // a normalized input digit, this overapproximates the reachable inputs.
      const auto carryIn = partition.input(ctx, previousCarry, begin, env, symbols, 32);
      const auto digitIn = partition.input(ctx, input.pieces[i], wordBegin, env, symbols);
      partition.execute(ctx, begin, begin + 1, env);
      const auto partial = partition.output(ctx, step.partial, begin + 1, env);
      const auto expected = digitIn * ctx.bv_val(factor, 32) + carryIn;
      if (!append(digit, check(ctx, partial != expected, symbols, "actual-partial-product",
                               std::min(1000u, remaining(deadline))))) {
        append(result, std::move(digit)); return result;
      }
    }
    {
      z3::context ctx; Environment env, symbols;
      const auto partial = partition.input(ctx, step.partial, begin + 1, env, symbols, 32);
      partition.execute(ctx, begin + 1, step.declarationEnd, env);
      const auto digitOut = partition.output(ctx, point.pieces[i], step.declarationEnd, env);
      const auto carryOut = partition.output(ctx, step.carry, step.declarationEnd, env);
      const auto base = ctx.bv_val(uint32_t(1) << bits, 32);
      const auto weight = ctx.bv_val(uint32_t(1) << (i * bits), 32);
      const auto error = (digitOut + base * carryOut - partial) * weight;
      const auto bad = (error != ctx.bv_val(0, 32)) || !z3::ule(digitOut, base - ctx.bv_val(1, 32));
      if (!append(digit, check(ctx, bad, symbols, "actual-digit-and-carry",
                               std::min(1000u, remaining(deadline))))) {
        append(result, std::move(digit)); return result;
      }
    }
    digit.status = "proved-under-model"; append(result, std::move(digit));
    previousCarry = step.carry; begin = step.declarationEnd;
  }
  z3::context ctx; Environment symbols;
  std::vector<z3::expr> inputs, outputs, carries;
  carries.push_back(ctx.bv_val(0, 32));
  for (unsigned i = 0; i < count; ++i) {
    auto symbol = [&](const std::string &name) {
      const auto value = ctx.bv_const(name.c_str(), 32); symbols.emplace(name, value); return value;
    };
    inputs.push_back(symbol("input_" + std::to_string(i)));
    outputs.push_back(symbol("output_" + std::to_string(i)));
    carries.push_back(i + 1 < count ? symbol("carry_" + std::to_string(i + 1)) : ctx.bv_val(0, 32));
  }
  const auto k = ctx.bv_val(factor, 32), base = ctx.bv_val(uint32_t(1) << bits, 32);
  auto errors = ctx.bv_val(0, 32);
  for (unsigned i = 0; i < count; ++i)
    errors = errors + (outputs[i] + base * carries[i + 1] - inputs[i] * k - carries[i]) *
                       ctx.bv_val(uint32_t(1) << (i * bits), 32);
  const auto defect = join(ctx, outputs, bits) - k * join(ctx, inputs, bits);
  if (!append(result, check(ctx, errors != defect, symbols, "telescoping-word-bridge",
                            std::min(1000u, remaining(deadline))))) return result;
  result.status = "proved-under-model"; return result;
}
}

Verification verifyLimbsComposition(const Region &original, const Region &candidate,
                                    const Graph &graph, const LimbWitness &witness, unsigned timeoutMs) {
  Verification result; result.strategy = "compositional-limbs" + std::to_string(witness.pieceBits);
  const auto deadline = Clock::now() + std::chrono::milliseconds(timeoutMs);
  try {
    if (original.parameters.size() != candidate.parameters.size()) throw std::invalid_argument("parameter arity mismatch");
    const auto bits = witness.pieceBits;
    if (bits != 4 && bits != 8 && bits != 16) throw std::invalid_argument("unsupported proposed piece width");
    validateGraph(graph, original);
    if (witness.nodes.size() != graph.nodes.size()) throw std::invalid_argument("incomplete graph partition");
    const Partition partition(candidate, witness);
    unsigned previous = 0;
    for (unsigned id = 0; id < witness.nodes.size(); ++id) {
      const auto &point = witness.nodes[id];
      if (point.pieces.size() != 32 / bits) throw std::invalid_argument("checkpoint piece count differs from width");
      if (point.declarationEnd < previous || point.declarationEnd > witness.declarations.size())
        throw std::invalid_argument("invalid checkpoint ordering");
      if (bits != 16 && graph.nodes[id].kind == Expr::Kind::Scale) {
        if (point.scaleSteps.size() != point.pieces.size()) throw std::invalid_argument("incomplete scale partition");
        auto end = previous;
        for (const auto &step : point.scaleSteps) {
          if (step.declarationEnd <= end + 1 || step.declarationEnd > point.declarationEnd)
            throw std::invalid_argument("invalid scale step ordering");
          if (step.partial.name.empty() || step.partial.name != witness.declarations.at(end))
            throw std::invalid_argument("scale partial must be the first declaration of its step");
          end = step.declarationEnd;
        }
        if (end != point.declarationEnd) throw std::invalid_argument("scale steps do not cover their checkpoint");
        const auto &lastCarry = point.scaleSteps.back().carry;
        if (!lastCarry.name.empty() || lastCarry.constant != 0)
          throw std::invalid_argument("final discarded carry must be literal zero");
      } else if (!point.scaleSteps.empty()) throw std::invalid_argument("unexpected scale partition");
      previous = point.declarationEnd;
    }
    result.composition = std::make_shared<LimbEvidence>();
    result.composition->graph = graph;
    result.composition->witness = witness;
    for (unsigned i = 0; i < witness.declarations.size(); ++i)
      result.composition->witness.declarations[i] = candidate.statements[i].name;
    for (auto &point : result.composition->witness.nodes) {
      for (auto &piece : point.pieces)
        if (!piece.name.empty()) piece.name = partition.name(piece, point.declarationEnd);
      for (auto &step : point.scaleSteps) {
        step.partial.name = partition.name(step.partial, step.declarationEnd);
        if (!step.carry.name.empty()) step.carry.name = partition.name(step.carry, step.declarationEnd);
      }
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
      const auto label = "node-" + std::to_string(id) + "-" + operationName(node.kind);
      if (!point.scaleSteps.empty()) {
        if (!append(result, scaleComposition(partition, witness.nodes[node.inputs[0]], point, node.value,
                                              bits, begin, deadline, label))) return result;
        begin = point.declarationEnd; continue;
      }
      std::vector<std::string> names;
      for (unsigned i = 0; i < node.inputs.size(); ++i) {
        const auto &input = witness.nodes[node.inputs[i]];
        std::vector<z3::expr> pieces;
        for (const auto &piece : input.pieces) pieces.push_back(partition.input(ctx, piece, begin, env, symbols));
        names.push_back("operand_" + std::to_string(i)); operands.emplace(names.back(), join(ctx, pieces, bits));
      }
      if (node.kind == Expr::Kind::Reference) {
        const auto pos = unsigned(std::find(original.parameters.begin(), original.parameters.end(), node.parameter) - original.parameters.begin());
        const auto value = ctx.bv_const("parameter", 32);
        env.emplace(candidate.parameters[pos], value); symbols.emplace(candidate.parameters[pos], value);
        operands.emplace(node.parameter, value);
      }
      const auto expected = expression(ctx, *operation(node, names), operands);
      partition.execute(ctx, begin, point.declarationEnd, env);
      std::vector<z3::expr> pieces;
      for (const auto &piece : point.pieces) pieces.push_back(partition.output(ctx, piece, point.declarationEnd, env));
      const auto bound = ctx.bv_val((uint32_t(1) << bits) - 1, 32);
      auto bad = join(ctx, pieces, bits) != expected;
      for (const auto &piece : pieces) bad = bad || !z3::ule(piece, bound);
      if (!append(result, check(ctx, bad, symbols, label,
                                std::min(1000u, remaining(deadline))))) return result;
      begin = point.declarationEnd;
    }
    z3::context ctx; Environment env, symbols;
    const auto &output = witness.nodes[graph.result];
    std::vector<z3::expr> pieces;
    for (const auto &piece : output.pieces) pieces.push_back(partition.input(ctx, piece, begin, env, symbols));
    const auto expected = join(ctx, pieces, bits);
    partition.execute(ctx, begin, unsigned(witness.declarations.size()), env);
    const auto actual = expression(ctx, *candidate.statements.back().expression, env);
    if (!append(result, check(ctx, actual != expected, symbols, "emitted-return", remaining(deadline)))) return result;
    result.status = "proved-under-model";
  } catch (const z3::exception &e) { result.status = "inconclusive"; result.reason = e.msg(); }
    catch (const std::exception &e) { result.status = "unsupported"; result.reason = e.what(); }
  return result;
}

Verification verify(const Region &original, const Region &candidate, unsigned timeoutMs) {
  if (original.ordered() || candidate.ordered()) return verifyMemory(original, candidate, timeoutMs);
  const auto deadline = Clock::now() + std::chrono::milliseconds(timeoutMs);
  std::vector<Verification> attempts;
  try {
    // Proposal generation is allowed to be incomplete or wrong. It cannot
    // establish a theorem: the independent checks above must all succeed.
    const bool straight = !candidate.statements.empty() && candidate.statements.back().kind == Statement::Kind::Return &&
      std::all_of(candidate.statements.begin(), candidate.statements.end() - 1,
                  [](const Statement &s) { return s.kind == Statement::Kind::Declare; });
    if (straight && original.parameters.size() == candidate.parameters.size() && timeoutMs >= 4) {
      const auto graph = lower(original);
      const std::set<std::string> reserved(original.parameters.begin(), original.parameters.end());
      const auto proposalDeadline = Clock::now() + std::chrono::milliseconds(std::min(timeoutMs / 2, remaining(deadline)));
      for (const unsigned bits : {16u, 8u, 4u}) {
        if (!remaining(proposalDeadline)) break;
        const auto proposal = bits == 16 ? emitLimbs16(graph, 0, reserved) : emitPositional(graph, bits, 0, reserved);
        if (candidate.statements.size() == proposal.limbWitness.declarations.size() + 1) {
          auto attempt = verifyLimbsComposition(original, candidate, graph, proposal.limbWitness,
                                                std::min(remaining(proposalDeadline), remaining(deadline)));
          if (attempt.status == "proved-under-model") {
            attempt.priorAttempts = std::move(attempts); return attempt;
          }
          attempts.push_back(std::move(attempt));
        }
      }
    }
  } catch (const std::exception &e) {
    Verification attempt; attempt.status = "unsupported"; attempt.reason = e.what(); attempts.push_back(std::move(attempt));
  }
  const auto budget = remaining(deadline);
  Verification result;
  if (budget) result = verification_detail::verifyDirect(original, candidate, budget);
  else { result.status = "inconclusive"; result.reason = "verification timeout exhausted"; }
  result.priorAttempts = std::move(attempts);
  return result;
}
}
