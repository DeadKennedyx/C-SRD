#pragma once
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace csrd {
// Validated, pure, fixed-width IR. References name initialized local objects.
struct Expr {
  enum class Kind { Constant, Reference, Add, Subtract, Scale } kind;
  uint32_t value = 0; // Constant or scale factor.
  std::string name;
  std::unique_ptr<Expr> left, right;
  explicit Expr(Kind k) : kind(k) {}
};
struct Statement {
  enum class Kind { Declare, Assign, Return } kind;
  std::string name;
  std::unique_ptr<Expr> expression;
};
struct Region {
  std::string name;
  std::vector<std::string> parameters;
  std::vector<Statement> statements;
  unsigned operations = 0;
};
} // namespace csrd
