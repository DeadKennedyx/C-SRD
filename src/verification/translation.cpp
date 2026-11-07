#include "csrd/verification.hpp"
#include <z3++.h>
#include <map>
#include <stdexcept>

namespace csrd {
namespace {
using Environment = std::map<std::string, z3::expr>;
z3::expr expression(z3::context &ctx, const Expr &e, const Environment &values) {
  switch (e.kind) {
  case Expr::Kind::Constant: return ctx.bv_val(e.value, 32);
  case Expr::Kind::Reference: return values.at(e.name);
  case Expr::Kind::Add: return expression(ctx, *e.left, values) + expression(ctx, *e.right, values);
  case Expr::Kind::Subtract: return expression(ctx, *e.left, values) - expression(ctx, *e.right, values);
  case Expr::Kind::Scale: return expression(ctx, *e.left, values) * ctx.bv_val(e.value, 32);
  }
  throw std::logic_error("unmodeled expression in verification");
}
z3::expr execute(z3::context &ctx, const Region &r, const std::vector<z3::expr> &inputs) {
  Environment values;
  for (unsigned i = 0; i < inputs.size(); ++i) values.emplace(r.parameters.at(i), inputs[i]);
  for (const auto &s : r.statements) {
    auto value = expression(ctx, *s.expression, values);
    if (s.kind == Statement::Kind::Return) return value;
    values.insert_or_assign(s.name, value);
  }
  throw std::logic_error("region has no return");
}
}
std::string solverVersion() { return Z3_get_full_version(); }
Verification verify(const Region &original, const Region &candidate, unsigned timeoutMs) {
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
    z3::params simplifier(ctx); simplifier.set("som", true);
    auto mismatch = (left != right).simplify(simplifier);
    z3::solver solver(ctx, "QF_BV");
    solver.set("timeout", timeoutMs);
    solver.add(left != right);
    result.obligation = solver.to_smt2();
    solver.reset();
    solver.add(mismatch);
    const auto answer = solver.check();
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
