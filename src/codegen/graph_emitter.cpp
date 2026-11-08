#include "csrd/graph_emitter.hpp"
#include <map>
#include <stdexcept>

namespace csrd {
namespace {
class Emitter {
  const Graph &graph;
  const Plan &plan;
  const PlanOptions &options;
  const Affine &affine;
  Xor xored;
  Identity identity;
  Emission result;
  std::set<std::string> reserved;
  std::vector<std::string> values, lines;
  std::map<std::pair<unsigned, Encoding>, std::string> conversions;
  unsigned nextName = 0;
  const Representation &representation(Encoding e) const {
    if (e == Encoding::Affine) return affine;
    if (e == Encoding::Xor) return xored;
    return identity;
  }
  std::string temporary(const std::string &expression) {
    std::string name;
    do { name = "csrd_value_" + std::to_string(nextName++); } while (!reserved.insert(name).second);
    lines.push_back("unsigned int " + name + " = " + expression + ";");
    ++result.temporaries;
    return name;
  }
  std::string convert(const std::string &value, Encoding from, Encoding to, bool boundary) {
    if (from == to) return value;
    if (boundary) ++result.boundaryConversions; else ++result.internalConversions;
    result.estimatedOperations += conversionCost(from, to);
    if (from != Encoding::Identity) ++result.decodings;
    if (to != Encoding::Identity) ++result.encodings;
    return temporary(representation(to).entry(representation(from).exit(value)));
  }
  std::string input(unsigned id, Encoding target, bool isReturn = false) {
    const auto &node = graph.nodes[id];
    if (node.kind == Expr::Kind::Constant) return representation(target).constant(node.value);
    const auto source = plan.labels[id];
    if (source == target) return values[id];
    auto key = std::make_pair(id, target);
    if (options.strategy != "independent") {
      auto found = conversions.find(key);
      if (found != conversions.end()) return found->second;
    }
    auto value = convert(values[id], source, target, node.kind == Expr::Kind::Reference || isReturn);
    if (options.strategy != "independent") conversions.emplace(key, value);
    return value;
  }
  std::string operation(const Node &n, Encoding encoding, const std::vector<std::string> &args) {
    const auto &r = representation(encoding);
    switch (n.kind) {
    case Expr::Kind::Add: return r.binary(Operation::Add, args[0], args[1]);
    case Expr::Kind::Subtract: return r.binary(Operation::Subtract, args[0], args[1]);
    case Expr::Kind::Scale: return r.times(args[0], n.value);
    case Expr::Kind::BitAnd: return r.binary(Operation::BitAnd, args[0], args[1]);
    case Expr::Kind::BitOr: return r.binary(Operation::BitOr, args[0], args[1]);
    case Expr::Kind::BitXor: return r.binary(Operation::BitXor, args[0], args[1]);
    case Expr::Kind::BitNot: return r.binary(Operation::BitNot, args[0], "0u");
    case Expr::Kind::ShiftLeft:
    case Expr::Kind::ShiftRight:
      if (encoding == Encoding::Xor) return xored.shift(args[0], n.value, n.kind == Expr::Kind::ShiftLeft);
      return r.binary(n.kind == Expr::Kind::ShiftLeft ? Operation::ShiftLeft : Operation::ShiftRight, args[0], literal(n.value));
    case Expr::Kind::Select: return "((" + args[0] + ") ? (" + args[1] + ") : (" + args[2] + "))";
    case Expr::Kind::Table: {
      std::string value = r.constant(n.table.back());
      for (unsigned i = 0; i + 1 < n.table.size(); ++i)
        value = "((" + args[0] + " == " + literal(i) + ") ? " + r.constant(n.table[i]) + " : (" + value + "))";
      return value;
    }
    case Expr::Kind::Equal: return "(" + args[0] + " == " + args[1] + ")";
    case Expr::Kind::NotEqual: return "(" + args[0] + " != " + args[1] + ")";
    case Expr::Kind::Less: return "(" + args[0] + " < " + args[1] + ")";
    case Expr::Kind::LessEqual: return "(" + args[0] + " <= " + args[1] + ")";
    case Expr::Kind::Greater: return "(" + args[0] + " > " + args[1] + ")";
    case Expr::Kind::GreaterEqual: return "(" + args[0] + " >= " + args[1] + ")";
    default: throw std::logic_error("unexpected graph operation");
    }
  }
public:
  Emitter(const Graph &g, const Plan &p, const PlanOptions &o, const Affine &a, uint32_t mask, const std::set<std::string> &names)
    : graph(g), plan(p), options(o), affine(a), xored(mask), reserved(names), values(g.nodes.size()) {}
  Emission run(unsigned newlines) {
    for (unsigned id = 0; id < graph.nodes.size(); ++id) {
      const auto &node = graph.nodes[id];
      if (node.kind == Expr::Kind::Constant) continue;
      if (node.kind == Expr::Kind::Reference) { values[id] = node.parameter; continue; }
      Encoding compute = plan.labels[id];
      if (options.strategy == "independent") {
        if (isArithmetic(node.kind)) compute = Encoding::Affine;
        else if (isBitwise(node.kind)) compute = Encoding::Xor;
      }
      std::vector<std::string> args;
      for (unsigned i = 0; i < node.inputs.size(); ++i) args.push_back(input(node.inputs[i], inputEncoding(node, i, compute)));
      values[id] = temporary(operation(node, compute, args));
      ++result.operations;
      result.estimatedOperations += operationCost(node, compute);
      if (compute != Encoding::Identity) ++result.encodedOperations;
      if (options.strategy == "independent") values[id] = convert(values[id], compute, Encoding::Identity, id == graph.result);
      if (plan.labels[id] == Encoding::Identity) ++result.ordinaryIntermediates;
    }
    lines.push_back("return " + input(graph.result, Encoding::Identity, true) + ";");
    result.body = "{";
    const bool multiline = newlines >= lines.size() + 1;
    for (const auto &line : lines) result.body += (multiline ? "\n    " : " ") + line;
    result.body.append(newlines - (multiline ? unsigned(lines.size()) : 0), '\n');
    result.body += "}";
    return result;
  }
};
}
Emission emitGraph(const Graph &g, const Plan &p, const PlanOptions &o, const Affine &a,
                   uint32_t mask, unsigned newlines, const std::set<std::string> &reserved) {
  return Emitter(g, p, o, a, mask, reserved).run(newlines);
}
}
