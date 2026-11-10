#include "csrd/graph_emitter.hpp"
#include <stdexcept>

namespace csrd {
namespace {
// Positional representation: x = low + 2^16 * high, both in [0, 65535].
// All storage/arithmetic remains unsigned int under the frontend's 32-bit model.
// This is not secret sharing: each piece exposes sixteen ordinary value bits.
struct Pair { LimbPiece low, high; };
std::string spelling(const LimbPiece &p) { return p.name.empty() ? literal(p.constant) : p.name; }
class LimbEmitter {
  const Graph &graph;
  Emission result;
  std::set<std::string> reserved;
  std::vector<Pair> values;
  std::vector<std::string> lines;
  unsigned nextName = 0;
  std::string temporary(const std::string &expression, unsigned cost) {
    std::string name;
    do { name = "csrd_limb_" + std::to_string(nextName++); } while (!reserved.insert(name).second);
    // A subsequent fixed shift can discard one half. Pure discarded reads keep
    // all admitted generated forms warning-clean without evaluating twice.
    lines.push_back("unsigned int " + name + " = " + expression + "; (void)" + name + ";");
    result.limbWitness.declarations.push_back(name);
    ++result.temporaries;
    result.estimatedOperations += cost;
    return name;
  }
  std::string decode(const Pair &p, bool boundary) {
    if (boundary) ++result.boundaryConversions; else ++result.internalConversions;
    ++result.decodings;
    return temporary("(" + spelling(p.low) + " | (" + spelling(p.high) + " << 16u))", 2);
  }
  Pair operation(const Node &n) {
    const auto a = values[n.inputs[0]];
    const auto b = n.inputs.size() > 1 ? values[n.inputs[1]] : Pair{};
    const auto al = spelling(a.low), ah = spelling(a.high);
    const auto bl = spelling(b.low), bh = spelling(b.high);
    using K = Expr::Kind;
    switch (n.kind) {
    case K::Add: {
      const auto sum = temporary("(" + al + " + " + bl + ")", 1);
      return {temporary("(" + sum + " & 65535u)", 1),
              temporary("((" + ah + " + " + bh + " + (" + sum + " >> 16u)) & 65535u)", 4)};
    }
    case K::Subtract: {
      const auto borrow = temporary("(" + al + " < " + bl + ")", 1);
      return {temporary("((" + al + " - " + bl + ") & 65535u)", 2),
              temporary("((" + ah + " - " + bh + " - " + borrow + ") & 65535u)", 3)};
    }
    case K::Scale: {
      const auto k = literal(n.value);
      const auto product = temporary("(" + al + " * " + k + ")", 1);
      return {temporary("(" + product + " & 65535u)", 1),
              temporary("((" + ah + " * " + k + " + (" + product + " >> 16u)) & 65535u)", 4)};
    }
    case K::BitAnd: case K::BitOr: case K::BitXor: {
      const auto op = n.kind == K::BitAnd ? " & " : n.kind == K::BitOr ? " | " : " ^ ";
      return {temporary("(" + al + op + bl + ")", 1),
              temporary("(" + ah + op + bh + ")", 1)};
    }
    case K::BitNot:
      return {temporary("(" + al + " ^ 65535u)", 1), temporary("(" + ah + " ^ 65535u)", 1)};
    case K::ShiftLeft: case K::ShiftRight: {
      const auto nbits = n.value;
      if (nbits >= 32) throw std::logic_error("limb shift exceeds admitted width");
      if (nbits == 0) return a;
      const auto shift = literal(nbits);
      if (n.kind == K::ShiftLeft) {
        if (nbits >= 16) return {LimbPiece(0), temporary("((" + al + " << " + literal(nbits - 16) + ") & 65535u)", 2)};
        return {temporary("((" + al + " << " + shift + ") & 65535u)", 2),
                temporary("(((" + ah + " << " + shift + ") | (" + al + " >> " + literal(16 - nbits) + ")) & 65535u)", 4)};
      }
      if (nbits >= 16) return {temporary("(" + ah + " >> " + literal(nbits - 16) + ")", 1), LimbPiece(0)};
      return {temporary("(((" + al + " >> " + shift + ") | (" + ah + " << " + literal(16 - nbits) + ")) & 65535u)", 4),
              temporary("(" + ah + " >> " + shift + ")", 1)};
    }
    case K::Equal: case K::NotEqual: case K::Less: case K::LessEqual: case K::Greater: case K::GreaterEqual: {
      std::string op = n.kind == K::Equal ? " == " : n.kind == K::NotEqual ? " != " :
                       n.kind == K::Less ? " < " : n.kind == K::LessEqual ? " <= " :
                       n.kind == K::Greater ? " > " : " >= ";
      const auto low = "((" + al + op + bl + ") ? 1u : 0u)";
      const auto high = n.kind == K::Equal ? "0u" : n.kind == K::NotEqual ? "1u" :
                        "((" + ah + op + bh + ") ? 1u : 0u)";
      return {temporary("((" + ah + " == " + bh + ") ? " + low + " : " + high + ")",
                        n.kind == K::Equal || n.kind == K::NotEqual ? 4 : 6), LimbPiece(0)};
    }
    case K::Select: {
      const auto c = values[n.inputs[2]];
      const auto condition = temporary("(" + al + " | " + ah + ")", 1);
      return {temporary("(" + condition + " ? " + bl + " : " + spelling(c.low) + ")", 1),
              temporary("(" + condition + " ? " + bh + " : " + spelling(c.high) + ")", 1)};
    }
    case K::Table: {
      // Index is an explicit internal boundary. Payloads remain decomposed.
      const auto index = decode(a, false);
      ++result.ordinaryIntermediates;
      auto low = literal(n.table.back() & 65535u), high = literal(n.table.back() >> 16);
      for (unsigned i = 0; i + 1 < n.table.size(); ++i) {
        const auto condition = "(" + index + " == " + literal(i) + ")";
        low = "(" + condition + " ? " + literal(n.table[i] & 65535u) + " : " + low + ")";
        high = "(" + condition + " ? " + literal(n.table[i] >> 16) + " : " + high + ")";
      }
      const auto cost = unsigned(2 * (n.table.size() - 1));
      return {temporary(low, cost), temporary(high, cost)};
    }
    default: throw std::logic_error("unexpected limb graph operation");
    }
  }
public:
  LimbEmitter(const Graph &g, const std::set<std::string> &names)
    : graph(g), reserved(names), values(g.nodes.size()) {}
  Emission run(unsigned newlines) {
    for (unsigned id = 0; id < graph.nodes.size(); ++id) {
      const auto &n = graph.nodes[id];
      if (n.kind == Expr::Kind::Constant) values[id] = {LimbPiece(n.value & 65535u), LimbPiece(n.value >> 16)};
      else if (n.kind == Expr::Kind::Reference) {
        values[id] = {temporary("(" + n.parameter + " & 65535u)", 1), temporary("(" + n.parameter + " >> 16u)", 1)};
        ++result.encodings; ++result.boundaryConversions;
      } else {
        values[id] = operation(n);
        ++result.operations;
        if (n.kind != Expr::Kind::Table) ++result.encodedOperations;
      }
      result.limbWitness.nodes.push_back({result.temporaries, {values[id].low, values[id].high}, {}});
    }
    const auto output = decode(values[graph.result], true);
    lines.push_back("return " + output + ";");
    result.body = "{";
    const bool multiline = newlines >= lines.size() + 1;
    for (const auto &line : lines) result.body += (multiline ? "\n    " : " ") + line;
    result.body.append(newlines - (multiline ? unsigned(lines.size()) : 0), '\n');
    result.body += "}";
    return result;
  }
};
}
Emission emitLimbs16(const Graph &g, unsigned newlines, const std::set<std::string> &reserved) {
  return LimbEmitter(g, reserved).run(newlines);
}
}
