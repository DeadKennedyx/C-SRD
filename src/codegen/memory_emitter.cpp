#include "csrd/graph_emitter.hpp"
#include <map>
#include <stdexcept>

namespace csrd {
namespace {
class MemoryEmitter {
  const Representation &rep;
  const bool encoded;
  std::set<std::string> reserved;
  std::map<std::string, std::string> values;
  const Region *region = nullptr;
  Emission result;
  unsigned sequence = 0;

  std::string fresh() {
    std::string name;
    do { name = "csrd_mem_" + std::to_string(sequence++); } while (!reserved.insert(name).second);
    return name;
  }
  std::string encode(const std::string &value, bool internal = false) {
    if (encoded) { ++result.encodings; ++(internal ? result.internalConversions : result.boundaryConversions); result.estimatedOperations += 2; }
    return rep.entry(value);
  }
  std::string decode(const std::string &value, bool internal = false) {
    if (encoded) { ++result.decodings; ++(internal ? result.internalConversions : result.boundaryConversions); result.estimatedOperations += 2; }
    return rep.exit(value);
  }
  std::string temporary(const std::string &value) {
    const auto name = fresh();
    result.body += " unsigned int " + name + " = " + value + "; (void)" + name + ";";
    ++result.temporaries; return name;
  }
  std::string index(const Expr *e, uint32_t bound) {
    if (!e) return literal(bound);
    const auto value = temporary(decode(expression(*e)));
    // The source range analysis established this bound. Reparse the guard and
    // validate its no-op property against the source; never trust emitter hints.
    return "(" + value + " <= " + literal(bound) + " ? " + value + " : " + literal(bound) + ")";
  }
  std::string expression(const Expr &e) {
    if (e.kind == Expr::Kind::Constant) return rep.constant(e.value);
    if (e.kind == Expr::Kind::Reference) return values.at(e.name);
    if (e.kind == Expr::Kind::Load) {
      auto load = e.name + "[" + index(e.left.get(), e.value) + "]";
      if (region->buffers.at(e.name).elementBits == 8) load = "((unsigned int)(" + load + "))";
      return encode(load);
    }
    const auto left = e.left ? expression(*e.left) : "";
    const auto right = e.right ? expression(*e.right) : "";
    if (e.kind == Expr::Kind::ByteCast)
      return encode("((unsigned int)((" + std::string(e.value ? "signed char" : "unsigned char") + ")(" +
                    decode(left, true) + ")))", true);
    ++result.operations;
    if (encoded && (e.kind == Expr::Kind::Add || e.kind == Expr::Kind::Subtract || e.kind == Expr::Kind::Scale))
      ++result.encodedOperations;
    else ++result.ordinaryIntermediates;
    switch (e.kind) {
    case Expr::Kind::Add:
      result.estimatedOperations += rep.cost(Operation::Add);
      return rep.binary(Operation::Add, left, right);
    case Expr::Kind::Subtract:
      result.estimatedOperations += rep.cost(Operation::Subtract);
      return rep.binary(Operation::Subtract, left, right);
    case Expr::Kind::Scale:
      result.estimatedOperations += rep.cost(Operation::Scale);
      return rep.times(left, e.value);
    default: break;
    }
    ++result.estimatedOperations;
    if (e.kind == Expr::Kind::Select) {
      const auto other = expression(*e.third);
      return "(" + decode(left, true) + " ? " + right + " : " + other + ")";
    }
    const auto a = decode(left, true);
    if (e.kind == Expr::Kind::BitNot) return encode("(~(" + a + "))", true);
    if (e.kind == Expr::Kind::ShiftLeft || e.kind == Expr::Kind::ShiftRight)
      return encode("((" + a + ") " + (e.kind == Expr::Kind::ShiftLeft ? "<<" : ">>") + " " + literal(e.value) + ")", true);
    const char *op = nullptr;
    switch (e.kind) {
    case Expr::Kind::BitAnd: op = "&"; break;
    case Expr::Kind::BitOr: op = "|"; break;
    case Expr::Kind::BitXor: op = "^"; break;
    case Expr::Kind::Equal: op = "=="; break;
    case Expr::Kind::NotEqual: op = "!="; break;
    case Expr::Kind::Less: op = "<"; break;
    case Expr::Kind::LessEqual: op = "<="; break;
    case Expr::Kind::Greater: op = ">"; break;
    case Expr::Kind::GreaterEqual: op = ">="; break;
    default: throw std::invalid_argument("unmodeled operation in ordered memory emission");
    }
    // Comparisons have type int in C; make the representation boundary explicit.
    return encode("((unsigned int)((" + a + ") " + op + " (" + decode(right, true) + ")))", true);
  }
  void declare(const std::string &source, const std::string &value) {
    const auto name = temporary(value);
    values.insert_or_assign(source, name);
  }
public:
  MemoryEmitter(const Representation &r, const std::set<std::string> &names)
      : rep(r), encoded(std::string(r.name()) != "identity-u32"), reserved(names) {}
  Emission run(const Region &input, unsigned newlines) {
    region = &input;
    if (region->buffers.empty()) throw std::invalid_argument("ordered memory emission requires buffer parameters");
    result.body = "{";
    for (const auto &name : region->parameters) {
      if (region->buffers.count(name)) result.body += " (void)" + name + ";";
      else declare(name, encode(name));
    }
    for (const auto &s : region->statements) {
      if (!s.expression) throw std::invalid_argument("unmodeled memory statement");
      const auto value = expression(*s.expression);
      switch (s.kind) {
      case Statement::Kind::Declare: declare(s.name, value); break;
      case Statement::Kind::Assign: result.body += " " + values.at(s.name) + " = " + value + ";"; break;
      case Statement::Kind::Store: {
        const auto offset = index(s.dynamicIndex.get(), s.index);
        result.body += " " + s.name + "[" + offset + "] = " + decode(value) + ";"; break;
      }
      case Statement::Kind::Return: result.body += " return " + decode(value) + ";"; break;
      default: throw std::invalid_argument("control flow is unsupported in ordered memory emission");
      }
    }
    result.body += std::string(newlines, '\n') + "}";
    return result;
  }
};
}
Emission emitMemory(const Region &region, const Representation &representation,
                    unsigned originalNewlines, const std::set<std::string> &reserved) {
  return MemoryEmitter(representation, reserved).run(region, originalNewlines);
}
}
