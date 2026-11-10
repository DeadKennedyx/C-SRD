#include "symbolic.hpp"
#include <stdexcept>
#include <algorithm>

namespace csrd {
namespace verification_detail {
z3::expr expression(z3::context &ctx, const Expr &e, const Environment &values) {
  switch (e.kind) {
  case Expr::Kind::Constant: return ctx.bv_val(e.value, 32);
  case Expr::Kind::Reference: return values.at(e.name);
  case Expr::Kind::Load: throw std::invalid_argument("memory load reached pure verification");
  case Expr::Kind::Add: return expression(ctx, *e.left, values) + expression(ctx, *e.right, values);
  case Expr::Kind::Subtract: return expression(ctx, *e.left, values) - expression(ctx, *e.right, values);
  case Expr::Kind::Scale: return expression(ctx, *e.left, values) * ctx.bv_val(e.value, 32);
  case Expr::Kind::BitAnd: return expression(ctx, *e.left, values) & expression(ctx, *e.right, values);
  case Expr::Kind::BitOr: return expression(ctx, *e.left, values) | expression(ctx, *e.right, values);
  case Expr::Kind::BitXor: return expression(ctx, *e.left, values) ^ expression(ctx, *e.right, values);
  case Expr::Kind::BitNot: return ~expression(ctx, *e.left, values);
  // For admitted constant counts 0..31, unsigned left shift is multiplication
  // by 2^count modulo 2^32. Keep this in polynomial form so equivalent
  // shift/add and constant-multiply implementations normalize together.
  case Expr::Kind::ShiftLeft:
    return expression(ctx, *e.left, values) * ctx.bv_val(e.value < 32 ? uint32_t(uint64_t(1) << e.value) : 0u, 32);
  case Expr::Kind::ShiftRight: return z3::lshr(expression(ctx, *e.left, values), ctx.bv_val(e.value, 32));
  case Expr::Kind::Equal: return z3::ite(expression(ctx, *e.left, values) == expression(ctx, *e.right, values), ctx.bv_val(1, 32), ctx.bv_val(0, 32));
  case Expr::Kind::NotEqual: return z3::ite(expression(ctx, *e.left, values) != expression(ctx, *e.right, values), ctx.bv_val(1, 32), ctx.bv_val(0, 32));
  case Expr::Kind::Less: return z3::ite(z3::ult(expression(ctx, *e.left, values), expression(ctx, *e.right, values)), ctx.bv_val(1, 32), ctx.bv_val(0, 32));
  case Expr::Kind::LessEqual: return z3::ite(z3::ule(expression(ctx, *e.left, values), expression(ctx, *e.right, values)), ctx.bv_val(1, 32), ctx.bv_val(0, 32));
  case Expr::Kind::Greater: return z3::ite(z3::ugt(expression(ctx, *e.left, values), expression(ctx, *e.right, values)), ctx.bv_val(1, 32), ctx.bv_val(0, 32));
  case Expr::Kind::GreaterEqual: return z3::ite(z3::uge(expression(ctx, *e.left, values), expression(ctx, *e.right, values)), ctx.bv_val(1, 32), ctx.bv_val(0, 32));
  case Expr::Kind::Select: return z3::ite(expression(ctx, *e.left, values) != ctx.bv_val(0, 32), expression(ctx, *e.right, values), expression(ctx, *e.third, values));
  case Expr::Kind::Table: {
    auto index = expression(ctx, *e.left, values);
    auto value = ctx.bv_val(e.table.back(), 32);
    for (unsigned i = 0; i + 1 < e.table.size(); ++i)
      value = z3::ite(index == ctx.bv_val(i, 32), ctx.bv_val(e.table[i], 32), value);
    return value;
  }
  }
  throw std::logic_error("unmodeled expression in verification");
}
z3::expr statements(z3::context &ctx, const std::vector<Statement> &body, Environment &values) {
  for (const auto &s : body) {
    if (s.kind == Statement::Kind::If) {
      auto condition = expression(ctx, *s.expression, values) != ctx.bv_val(0, 32);
      auto thenValues = values, elseValues = values;
      statements(ctx, s.thenBranch, thenValues); statements(ctx, s.elseBranch, elseValues);
      for (auto &[name, value] : values) value = z3::ite(condition, thenValues.at(name), elseValues.at(name));
      continue;
    }
    if (s.kind == Statement::Kind::Repeat) {
      for (unsigned i = 0; i < s.repetitions; ++i) {
        values.insert_or_assign(s.name, ctx.bv_val(i, 32)); statements(ctx, s.thenBranch, values);
      }
      values.erase(s.name); continue;
    }
    auto value = expression(ctx, *s.expression, values);
    if (s.kind == Statement::Kind::Return) return value;
    values.insert_or_assign(s.name, value);
  }
  return ctx.bv_val(0, 32);
}
z3::expr execute(z3::context &ctx, const Region &r, const std::vector<z3::expr> &inputs) {
  Environment values;
  for (unsigned i = 0; i < inputs.size(); ++i) values.emplace(r.parameters.at(i), inputs[i]);
  return statements(ctx, r.statements, values);
}
}
std::string solverVersion() { return Z3_get_full_version(); }
Verification verification_detail::verifyDirect(const Region &original, const Region &candidate, unsigned timeoutMs) {
  Verification result;
  if (original.parameters.size() != candidate.parameters.size()) {
    result.status = "unsupported"; result.reason = "parameter arity mismatch"; return result;
  }
  try {
    z3::context ctx;
    std::vector<z3::expr> inputs;
    for (unsigned i = 0; i < original.parameters.size(); ++i)
      inputs.push_back(ctx.bv_const(("input_" + std::to_string(i)).c_str(), 32));
    auto left = execute(ctx, original, inputs);
    auto right = execute(ctx, candidate, inputs);
    // Polynomial normalization is important for modular affine expressions.
    z3::params simplifier(ctx); simplifier.set("som", true); simplifier.set("push_ite_bv", true);
    auto simplify = z3::with(z3::tactic(ctx, "simplify"), simplifier);
    auto lift = z3::tactic(ctx, "blast-term-ite");
    // Direct bit-blasting is fast for XOR circuits. Affine branch results often
    // need term selections lifted before polynomial normalization instead.
    auto solver = (simplify & z3::tactic(ctx, "bit-blast") & z3::tactic(ctx, "sat")).mk_solver();
    const auto firstBudget = std::min(1000u, std::max(1u, timeoutMs / 4));
    solver.set("timeout", firstBudget);
    solver.add(left != right);
    result.obligation = solver.to_smt2();
    result.strategy = "simplify/bit-blast/sat";
    auto answer = solver.check();
    unsigned usedBudget = firstBudget;
    if (answer == z3::unknown && timeoutMs > usedBudget) {
      // A bijective change of solver variables, not a restriction of C inputs.
      // Every u32 is exactly low + 65536*high for independent 16-bit halves.
      // Exposing that arithmetic structure helps positional/carry identities.
      z3::expr_vector from(ctx), to(ctx);
      for (unsigned i = 0; i < inputs.size(); ++i) {
        from.push_back(inputs[i]);
        const auto name = "input_" + std::to_string(i);
        to.push_back(z3::zext(ctx.bv_const((name + "_low").c_str(), 16), 16) +
                     z3::zext(ctx.bv_const((name + "_high").c_str(), 16), 16) * ctx.bv_val(65536, 32));
      }
      left = left.substitute(from, to); right = right.substitute(from, to);
      for (unsigned i = 0; i < inputs.size(); ++i) inputs[i] = to[i];
      const auto splitBudget = std::min(1000u, std::max(1u, (timeoutMs - usedBudget) / 2));
      solver = (simplify & z3::tactic(ctx, "bit-blast") & z3::tactic(ctx, "sat")).mk_solver();
      solver.set("timeout", splitBudget); solver.add(left != right);
      result.obligation = solver.to_smt2();
      result.strategy = "split-inputs/simplify/bit-blast/sat (after direct solver inconclusive)";
      answer = solver.check();
      usedBudget += splitBudget;
    }
    if (answer == z3::unknown && timeoutMs > usedBudget) {
      solver = (simplify & lift & simplify & z3::tactic(ctx, "smt")).mk_solver();
      solver.set("timeout", timeoutMs - usedBudget);
      solver.add(left != right);
      result.obligation = solver.to_smt2();
      result.strategy = "split-inputs/simplify/blast-term-ite/simplify/smt (after direct solvers inconclusive)";
      answer = solver.check();
    }
    if (answer == z3::unsat) result.status = "proved-under-model";
    else if (answer == z3::sat) {
      result.status = "counterexample";
      const auto model = solver.get_model();
      for (const auto &input : inputs) result.inputs.push_back(uint32_t(model.eval(input, true).get_numeral_uint64()));
      result.originalOutput = uint32_t(model.eval(left, true).get_numeral_uint64());
      result.candidateOutput = uint32_t(model.eval(right, true).get_numeral_uint64());
    } else { result.status = "inconclusive"; result.reason = solver.reason_unknown(); }
  } catch (const z3::exception &e) { result.status = "inconclusive"; result.reason = e.msg(); }
  return result;
}
}
