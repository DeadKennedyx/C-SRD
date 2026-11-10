#include "csrd/graph_emitter.hpp"
#include <stdexcept>

namespace csrd {
namespace {
using Word = std::vector<LimbPiece>;
std::string text(const LimbPiece &piece) { return piece.name.empty() ? literal(piece.constant) : piece.name; }

// Fixed-width unsigned positional arithmetic, with normalized 4/8-bit pieces.
// Constants and all intermediate C storage use the frontend's unsigned-32 model.
class PositionalEmitter {
  const Graph &graph;
  const unsigned bits, count;
  const uint32_t mask;
  Emission result;
  std::set<std::string> reserved;
  std::vector<Word> values;
  std::vector<std::string> lines;
  std::vector<LimbScaleStep> scaleSteps;
  unsigned nextName = 0;

  std::string temporary(const std::string &expression, unsigned cost) {
    std::string name;
    do { name = "csrd_limb_" + std::to_string(nextName++); } while (!reserved.insert(name).second);
    lines.push_back("unsigned int " + name + " = " + expression + "; (void)" + name + ";");
    result.limbWitness.declarations.push_back(name);
    ++result.temporaries; result.estimatedOperations += cost;
    return name;
  }
  std::string decode(const Word &word, bool boundary) {
    if (boundary) ++result.boundaryConversions; else ++result.internalConversions;
    ++result.decodings;
    auto expression = text(word[0]);
    for (unsigned i = 1; i < count; ++i)
      expression += " | (" + text(word[i]) + " << " + literal(i * bits) + ")";
    return temporary("(" + expression + ")", 2 * (count - 1));
  }
  Word operation(const Node &node) {
    const auto &a = values.at(node.inputs.at(0));
    const Word zero(count);
    const auto &b = node.inputs.size() > 1 ? values.at(node.inputs[1]) : zero;
    Word out(count);
    using K = Expr::Kind;
    switch (node.kind) {
    case K::Add: case K::Subtract: case K::Scale: {
      auto carry = std::string("0u");
      for (unsigned i = 0; i < count; ++i) {
        const auto ai = text(a[i]), bi = text(b[i]);
        if (node.kind == K::Subtract) {
          const auto subtrahend = i ? temporary("(" + bi + " + " + carry + ")", 1) : bi;
          out[i] = temporary("((" + ai + " - " + subtrahend + ") & " + literal(mask) + ")", 2);
          if (i + 1 < count) carry = temporary("(" + ai + " < " + subtrahend + ")", 1);
        } else {
          // Overflow of this u32 partial sum/product discards only bits at or
          // above bit 32 of the final positional value. The actual fragment
          // must still prove the complete value/range invariant before output.
          const auto expression = ai + (node.kind == K::Add ? " + " + bi : " * " + literal(node.value));
          const auto partial = temporary("(" + expression + (i ? " + " + carry : "") + ")", i ? 2 : 1);
          out[i] = temporary("(" + partial + " & " + literal(mask) + ")", 1);
          if (i + 1 < count) carry = temporary("(" + partial + " >> " + literal(bits) + ")", 1);
          if (node.kind == K::Scale)
            scaleSteps.push_back({result.temporaries, LimbPiece(partial), i + 1 < count ? LimbPiece(carry) : LimbPiece(0)});
        }
      }
      return out;
    }
    case K::BitAnd: case K::BitOr: case K::BitXor: case K::BitNot: {
      const auto symbol = node.kind == K::BitAnd ? " & " : node.kind == K::BitOr ? " | " : " ^ ";
      for (unsigned i = 0; i < count; ++i)
        out[i] = temporary("(" + text(a[i]) + symbol +
                           (node.kind == K::BitNot ? literal(mask) : text(b[i])) + ")", 1);
      return out;
    }
    case K::ShiftLeft: case K::ShiftRight: {
      if (node.value >= 32) throw std::logic_error("positional shift exceeds admitted width");
      const int whole = int(node.value / bits);
      const unsigned rest = node.value % bits;
      const bool left = node.kind == K::ShiftLeft;
      for (unsigned i = 0; i < count; ++i) {
        const int source = int(i) + (left ? -whole : whole);
        if (source < 0 || source >= int(count)) continue;
        if (!rest) { out[i] = a[unsigned(source)]; continue; }
        auto expression = "(" + text(a[unsigned(source)]) + (left ? " << " : " >> ") + literal(rest) + ")";
        unsigned cost = 2; // shift and output normalization
        const int neighbour = source + (left ? -1 : 1);
        if (neighbour >= 0 && neighbour < int(count)) {
          expression += " | (" + text(a[unsigned(neighbour)]) + (left ? " >> " : " << ") + literal(bits - rest) + ")";
          cost += 2;
        }
        out[i] = temporary("((" + expression + ") & " + literal(mask) + ")", cost);
      }
      return out;
    }
    case K::Equal: case K::NotEqual: case K::Less: case K::LessEqual: case K::Greater: case K::GreaterEqual: {
      const std::string symbol = node.kind == K::Equal ? " == " : node.kind == K::NotEqual ? " != " :
        node.kind == K::Less ? " < " : node.kind == K::LessEqual ? " <= " :
        node.kind == K::Greater ? " > " : " >= ";
      auto comparison = temporary("((" + text(a[0]) + symbol + text(b[0]) + ") ? 1u : 0u)", 2);
      for (unsigned i = 1; i < count; ++i) {
        const auto unequal = node.kind == K::Equal ? "0u" : node.kind == K::NotEqual ? "1u" :
                             "((" + text(a[i]) + symbol + text(b[i]) + ") ? 1u : 0u)";
        comparison = temporary("((" + text(a[i]) + " == " + text(b[i]) + ") ? " + comparison + " : " + unequal + ")",
                               node.kind == K::Equal || node.kind == K::NotEqual ? 2 : 4);
      }
      out[0] = comparison; return out;
    }
    case K::Select: {
      const auto &c = values.at(node.inputs.at(2));
      auto predicate = text(a[0]);
      for (unsigned i = 1; i < count; ++i) predicate += " | " + text(a[i]);
      predicate = temporary("(" + predicate + ")", count - 1);
      for (unsigned i = 0; i < count; ++i)
        out[i] = temporary("(" + predicate + " ? " + text(b[i]) + " : " + text(c[i]) + ")", 1);
      return out;
    }
    case K::Table: {
      const auto index = decode(a, false);
      ++result.ordinaryIntermediates;
      for (unsigned p = 0; p < count; ++p) {
        auto expression = literal((node.table.back() >> (p * bits)) & mask);
        for (unsigned i = 0; i + 1 < node.table.size(); ++i)
          expression = "((" + index + " == " + literal(i) + ") ? " +
                       literal((node.table[i] >> (p * bits)) & mask) + " : " + expression + ")";
        out[p] = temporary(expression, unsigned(2 * (node.table.size() - 1)));
      }
      return out;
    }
    default: throw std::logic_error("unexpected positional graph operation");
    }
  }
public:
  PositionalEmitter(const Graph &g, unsigned width, const std::set<std::string> &names)
    : graph(g), bits(width), count(32 / width), mask((uint32_t(1) << width) - 1),
      reserved(names), values(g.nodes.size()) { result.limbWitness.pieceBits = bits; }
  Emission run(unsigned newlines) {
    for (unsigned id = 0; id < graph.nodes.size(); ++id) {
      scaleSteps.clear();
      const auto &node = graph.nodes[id];
      Word word(count);
      if (node.kind == Expr::Kind::Constant) {
        for (unsigned i = 0; i < count; ++i) word[i] = LimbPiece((node.value >> (i * bits)) & mask);
      } else if (node.kind == Expr::Kind::Reference) {
        for (unsigned i = 0; i < count; ++i) {
          const auto value = i ? "(" + node.parameter + " >> " + literal(i * bits) + ")" : node.parameter;
          word[i] = temporary("(" + value + " & " + literal(mask) + ")", i ? 2 : 1);
        }
        ++result.encodings; ++result.boundaryConversions;
      } else {
        word = operation(node);
        ++result.operations;
        if (node.kind != Expr::Kind::Table) ++result.encodedOperations;
      }
      values[id] = std::move(word);
      result.limbWitness.nodes.push_back({result.temporaries, values[id], scaleSteps});
    }
    const auto output = decode(values.at(graph.result), true);
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
Emission emitPositional(const Graph &g, unsigned bits, unsigned newlines, const std::set<std::string> &reserved) {
  if (bits != 4 && bits != 8) throw std::invalid_argument("positional prototype requires 4-bit or 8-bit pieces");
  return PositionalEmitter(g, bits, reserved).run(newlines);
}
}
