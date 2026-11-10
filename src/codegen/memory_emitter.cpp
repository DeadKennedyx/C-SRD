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
  Emission result;
  unsigned sequence = 0;

  std::string fresh() {
    std::string name;
    do { name = "csrd_mem_" + std::to_string(sequence++); } while (!reserved.insert(name).second);
    return name;
  }
  std::string encode(const std::string &value) {
    if (encoded) { ++result.encodings; ++result.boundaryConversions; result.estimatedOperations += 2; }
    return rep.entry(value);
  }
  std::string decode(const std::string &value) {
    if (encoded) { ++result.decodings; ++result.boundaryConversions; result.estimatedOperations += 2; }
    return rep.exit(value);
  }
  std::string expression(const Expr &e) {
    if (e.kind == Expr::Kind::Constant) return rep.constant(e.value);
    if (e.kind == Expr::Kind::Reference) return values.at(e.name);
    if (e.kind == Expr::Kind::Load) return encode(e.name + "[" + literal(e.value) + "]");
    const auto left = e.left ? expression(*e.left) : "";
    const auto right = e.right ? expression(*e.right) : "";
    ++result.operations;
    if (encoded) ++result.encodedOperations; else ++result.ordinaryIntermediates;
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
    default: throw std::invalid_argument("unmodeled operation in ordered memory emission");
    }
  }
  void declare(const std::string &source, const std::string &value) {
    const auto name = fresh();
    values.insert_or_assign(source, name);
    result.body += " unsigned int " + name + " = " + value + "; (void)" + name + ";";
    ++result.temporaries;
  }
public:
  MemoryEmitter(const Representation &r, const std::set<std::string> &names)
      : rep(r), encoded(std::string(r.name()) != "identity-u32"), reserved(names) {}
  Emission run(const Region &region, unsigned newlines) {
    if (region.buffers.empty()) throw std::invalid_argument("ordered memory emission requires buffer parameters");
    result.body = "{";
    for (const auto &name : region.parameters) {
      if (region.buffers.count(name)) result.body += " (void)" + name + ";";
      else declare(name, encode(name));
    }
    for (const auto &s : region.statements) {
      if (!s.expression) throw std::invalid_argument("unmodeled memory statement");
      const auto value = expression(*s.expression);
      switch (s.kind) {
      case Statement::Kind::Declare: declare(s.name, value); break;
      case Statement::Kind::Assign: result.body += " " + values.at(s.name) + " = " + value + ";"; break;
      case Statement::Kind::Store:
        result.body += " " + s.name + "[" + literal(s.index) + "] = " + decode(value) + ";"; break;
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
