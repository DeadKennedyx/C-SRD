#include "csrd/planner.hpp"
#include <z3++.h>
#include <stdexcept>
#include <array>
#include <set>

namespace csrd {
namespace {
using Score = std::array<unsigned, 4>;
Score evaluate(const Graph &g, const PlanOptions &options, Plan &p) {
  p.estimatedOperations = p.statements = 0;
  unsigned ordinary = 0, tie = 0;
  std::set<std::pair<unsigned, Encoding>> conversions;
  for (unsigned id = 0; id < g.nodes.size(); ++id) {
    const auto &n = g.nodes[id]; const auto label = p.labels[id];
    p.estimatedOperations += operationCost(n, label);
    if (options.controlFlow == "split-scale" && n.kind == Expr::Kind::Scale && n.value > 1)
      p.estimatedOperations += 4;
    tie += (id + 1) * unsigned(label);
    if (n.kind != Expr::Kind::Reference && n.kind != Expr::Kind::Constant) {
      ++p.statements; ordinary += label == Encoding::Identity;
    }
    for (unsigned operand = 0; operand < n.inputs.size(); ++operand) {
      auto producer = n.inputs[operand]; auto target = inputEncoding(n, operand, label);
      if (g.nodes[producer].kind != Expr::Kind::Constant && p.labels[producer] != target)
        conversions.emplace(producer, target);
    }
  }
  if (g.nodes[g.result].kind != Expr::Kind::Constant && p.labels[g.result] != Encoding::Identity)
    conversions.emplace(g.result, Encoding::Identity);
  for (const auto &[producer, target] : conversions)
    p.estimatedOperations += conversionCost(p.labels[producer], target);
  p.conversions = unsigned(conversions.size()); p.statements += p.conversions;
  unsigned primary = options.objective == "runtime" ? p.estimatedOperations : options.objective == "size" ? p.statements :
    p.estimatedOperations + 2 * p.conversions + p.statements;
  return {primary, p.conversions, ordinary, tie};
}
Plan heuristic(const Graph &g, const PlanOptions &options, const std::string &reason) {
  Plan best; Score bestScore{~0u, ~0u, ~0u, ~0u};
  unsigned eligible = 0;
  for (const auto &n : g.nodes) eligible += isArithmetic(n.kind) || isBitwise(n.kind);
  unsigned required = (eligible * options.coverage + 99) / 100;
  // Three deterministic starting states differ in selection/table representations.
  // Each begins with full operation coverage; only cost-improving feasible moves are accepted.
  for (unsigned start = 0; start < 3; ++start) {
    Plan p; p.requiredEncoded = required;
    for (const auto &n : g.nodes) {
      const auto choices = allowed(n);
      p.labels.push_back(choices.size() == 3 ? Encoding(start) : choices.back());
    }
    unsigned encoded = eligible; auto score = evaluate(g, options, p);
    for (;;) {
      Plan next = p; auto nextScore = score; unsigned nextEncoded = encoded;
      for (unsigned id = 0; id < g.nodes.size(); ++id) for (auto choice : allowed(g.nodes[id])) {
        if (choice == p.labels[id]) continue;
        unsigned count = encoded;
        if (isArithmetic(g.nodes[id].kind) || isBitwise(g.nodes[id].kind)) {
          count -= p.labels[id] != Encoding::Identity; count += choice != Encoding::Identity;
        }
        if (count < required) continue;
        Plan candidate = p; candidate.labels[id] = choice;
        auto candidateScore = evaluate(g, options, candidate);
        if (candidateScore < nextScore) { next = std::move(candidate); nextScore = candidateScore; nextEncoded = count; }
      }
      if (!(nextScore < score)) break;
      p = std::move(next); score = nextScore; encoded = nextEncoded;
    }
    if (score < bestScore) { best = std::move(p); bestScore = score; }
  }
  best.status = "heuristic"; best.reason = reason; return best;
}
}
Plan plan(const Graph &g, const PlanOptions &options) {
  Plan result;
  if (const auto bits = limbBits(options.strategy)) {
    result.labels.assign(g.nodes.size(), bits == 16 ? Encoding::Limbs16 : bits == 8 ? Encoding::Limbs8 : Encoding::Limbs4);
    result.status = "fixed-representation";
    result.reason = std::to_string(32 / bits) + " positional " + std::to_string(bits) +
                    "-bit pieces; no seed diversification or cost optimization";
    return result;
  }
  if (options.strategy != "planned") {
    for (const auto &node : g.nodes) {
      Encoding choice = Encoding::Identity;
      if (options.strategy == "affine" && (isArithmetic(node.kind) || node.kind == Expr::Kind::Select || node.kind == Expr::Kind::Table)) choice = Encoding::Affine;
      if (options.strategy == "xor" && (isBitwise(node.kind) || node.kind == Expr::Kind::Select || node.kind == Expr::Kind::Table)) choice = Encoding::Xor;
      result.labels.push_back(choice);
    }
    return result;
  }
  if (g.nodes.size() > 512) { result.status = "inconclusive"; result.reason = "planner limit is 512 live graph nodes"; return result; }
  unsigned choicesCount = 0;
  for (const auto &n : g.nodes) choicesCount += allowed(n).size() > 1;
  if (choicesCount > 16) return heuristic(g, options, "more than 16 choice nodes; deterministic local search, no optimality guarantee");
  z3::context ctx;
  z3::optimize optimizer(ctx);
  z3::params settings(ctx); settings.set("timeout", options.timeoutMs); optimizer.set(settings);
  std::vector<z3::expr> labels;
  z3::expr arithmetic = ctx.int_val(0), converted = ctx.int_val(0), materialized = ctx.int_val(0), encoded = ctx.int_val(0), ordinary = ctx.int_val(0), tie = ctx.int_val(0);
  unsigned eligible = 0;
  for (unsigned id = 0; id < g.nodes.size(); ++id) {
    const auto &node = g.nodes[id];
    const auto choices = allowed(node);
    const auto name = "representation_" + std::to_string(id);
    if (choices.size() == 1) labels.push_back(ctx.int_val(0));
    else if (choices.size() == 2)
      labels.push_back(z3::ite(ctx.bool_const(name.c_str()), ctx.int_val(int(choices[1])), ctx.int_val(0)));
    else {
      auto affine = ctx.bool_const((name + "_affine").c_str());
      auto xored = ctx.bool_const((name + "_xor").c_str());
      optimizer.add(!(affine && xored));
      labels.push_back(z3::ite(affine, ctx.int_val(1), z3::ite(xored, ctx.int_val(2), ctx.int_val(0))));
    }
    for (auto e : choices) {
      arithmetic = arithmetic + z3::ite(labels.back() == int(e), ctx.int_val(operationCost(node, e)), ctx.int_val(0));
    }
    if (options.controlFlow == "split-scale" && node.kind == Expr::Kind::Scale && node.value > 1)
      arithmetic = arithmetic + 4;
    if (node.kind != Expr::Kind::Reference && node.kind != Expr::Kind::Constant) {
      materialized = materialized + 1;
      ordinary = ordinary + z3::ite(labels.back() == 0, ctx.int_val(1), ctx.int_val(0));
    }
    if (isArithmetic(node.kind) || isBitwise(node.kind)) {
      ++eligible; encoded = encoded + z3::ite(labels.back() != 0, ctx.int_val(1), ctx.int_val(0));
    }
    tie = tie + labels.back() * int(id + 1);
  }
  result.requiredEncoded = (eligible * options.coverage + 99) / 100;
  optimizer.add(encoded >= int(result.requiredEncoded));
  // One conversion per producer/destination representation, shared by all consumers.
  for (unsigned producer = 0; producer < g.nodes.size(); ++producer) {
    if (g.nodes[producer].kind == Expr::Kind::Constant) continue;
    for (unsigned destination = 0; destination < 3; ++destination) {
      z3::expr needed = ctx.bool_val(producer == g.result && destination == 0);
      for (unsigned consumer = producer + 1; consumer < g.nodes.size(); ++consumer) {
        const auto &node = g.nodes[consumer];
        for (unsigned operand = 0; operand < node.inputs.size(); ++operand) if (node.inputs[operand] == producer) {
          if (inputEncoding(node, operand, Encoding::Affine) == Encoding::Identity) {
            if (destination == 0) needed = ctx.bool_val(true);
          } else needed = needed || labels[consumer] == int(destination);
        }
      }
      auto exists = needed && labels[producer] != int(destination);
      converted = converted + z3::ite(exists, ctx.int_val(1), ctx.int_val(0));
      materialized = materialized + z3::ite(exists, ctx.int_val(1), ctx.int_val(0));
      for (unsigned source = 0; source < 3; ++source)
        arithmetic = arithmetic + z3::ite(exists && labels[producer] == int(source),
          ctx.int_val(conversionCost(Encoding(source), Encoding(destination))), ctx.int_val(0));
    }
  }
  z3::expr score = options.objective == "runtime" ? arithmetic : options.objective == "size" ? materialized : arithmetic + 2 * converted + materialized;
  std::vector<z3::optimize::handle> objectives;
  objectives.push_back(optimizer.minimize(score.simplify()));
  objectives.push_back(optimizer.minimize(converted.simplify()));
  objectives.push_back(optimizer.minimize(ordinary.simplify()));
  objectives.push_back(optimizer.minimize(tie.simplify()));
  const auto answer = optimizer.check();
  if (answer != z3::sat) {
    return heuristic(g, options, answer == z3::unsat ? "solver reported unsatisfiable; feasible heuristic fallback" : Z3_optimize_get_reason_unknown(ctx, optimizer));
  }
  for (auto objective : objectives) if (!z3::eq(optimizer.lower(objective).simplify(), optimizer.upper(objective).simplify())) {
    return heuristic(g, options, "solver did not certify an optimal objective bound");
  }
  const auto model = optimizer.get_model();
  for (const auto &label : labels) result.labels.push_back(Encoding(model.eval(label).get_numeral_uint()));
  result.estimatedOperations = model.eval(arithmetic).get_numeral_uint();
  result.conversions = model.eval(converted).get_numeral_uint();
  result.statements = model.eval(materialized).get_numeral_uint();
  result.status = "optimized";
  return result;
}
}
