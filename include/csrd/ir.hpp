#pragma once
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace csrd {
// Validated, pure, fixed-width IR. References name initialized local objects.
struct Expr {
  enum class Kind { Constant, Reference, Add, Subtract, Scale, BitAnd, BitOr, BitXor,
                    BitNot, ShiftLeft, ShiftRight, Equal, NotEqual, Less, LessEqual,
                    Greater, GreaterEqual, Select, Table } kind;
  uint32_t value = 0; // Constant or scale factor.
  std::string name;
  std::unique_ptr<Expr> left, right, third;
  std::vector<uint32_t> table;
  explicit Expr(Kind k) : kind(k) {}
};
struct Statement {
  enum class Kind { Declare, Assign, Return, If, Repeat } kind;
  std::string name;
  std::unique_ptr<Expr> expression;
  std::vector<Statement> thenBranch, elseBranch;
  unsigned repetitions = 0;
  Statement(Kind k, std::string n, std::unique_ptr<Expr> e)
      : kind(k), name(std::move(n)), expression(std::move(e)) {}
};
struct Region {
  std::string name;
  std::vector<std::string> parameters;
  std::vector<Statement> statements;
  unsigned operations = 0;
};
} // namespace csrd
