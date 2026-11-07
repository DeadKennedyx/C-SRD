#include "csrd/emitter.hpp"
#include <stdexcept>

namespace csrd {
namespace {
std::string emit(const Expr &e, const Representation &r) {
  switch (e.kind) {
  case Expr::Kind::Constant: return r.constant(e.value);
  case Expr::Kind::Reference: return "(" + e.name + ")";
  case Expr::Kind::Add: return r.binary(Operation::Add, emit(*e.left, r), emit(*e.right, r));
  case Expr::Kind::Subtract: return r.binary(Operation::Subtract, emit(*e.left, r), emit(*e.right, r));
  case Expr::Kind::Scale: return r.times(emit(*e.left, r), e.value);
  }
  throw std::logic_error("invalid IR expression");
}
}
std::string emitBody(const Region &region, const Representation &r, unsigned newlines) {
  std::vector<std::string> lines;
  for (const auto &p : region.parameters) lines.push_back(p + " = " + r.entry(p) + ";");
  for (const auto &s : region.statements) {
    const auto e = emit(*s.expression, r);
    if (s.kind == Statement::Kind::Return) lines.push_back("return " + r.exit(e) + ";");
    else lines.push_back((s.kind == Statement::Kind::Declare ? "unsigned int " : "") + s.name + " = " + e + ";");
  }
  std::string result = "{";
  // Never shift later __LINE__ expansions. Compact when the original body is short.
  const bool multiline = newlines >= lines.size() + 1;
  for (const auto &line : lines) {
    result += multiline ? "\n    " : " ";
    result += line;
  }
  const unsigned used = multiline ? unsigned(lines.size()) : 0;
  result.append(newlines - used, '\n');
  result += "}";
  return result;
}
} // namespace csrd
