#pragma once
#include <cstdint>
#include <memory>
#include <map>
#include <string>
#include <vector>

namespace csrd {
// Validated fixed-width IR. Memory regions retain statement order; they must
// never be lowered through the pure graph's return-only liveness analysis.
struct Expr {
  enum class Kind { Constant, Reference, Add, Subtract, Scale, BitAnd, BitOr, BitXor,
                    BitNot, ShiftLeft, ShiftRight, Equal, NotEqual, Less, LessEqual,
                    Greater, GreaterEqual, Select, Table, Load, ByteCast } kind;
  uint32_t value = 0; // Constant, scale, load index bound, or ByteCast signedness.
  std::string name;
  std::unique_ptr<Expr> left, right, third;
  std::vector<uint32_t> table;
  explicit Expr(Kind k) : kind(k) {}
};
struct Statement {
  enum class Kind { Declare, Assign, Return, If, Repeat, Store } kind;
  std::string name;
  std::unique_ptr<Expr> expression;
  std::vector<Statement> thenBranch, elseBranch;
  unsigned repetitions = 0;
  uint32_t index = 0; // Fixed Store index; Load uses Expr::value.
  std::unique_ptr<Expr> dynamicIndex; // If present, index is its proven upper bound.
  Statement(Kind k, std::string n, std::unique_ptr<Expr> e)
      : kind(k), name(std::move(n)), expression(std::move(e)) {}
};
struct Region {
  struct Buffer {
    bool readOnly = false;
    unsigned elementBits = 32;
    bool elementSigned = false;
    std::string elementType = "uint32";
    unsigned minimumElements = 0, loads = 0, stores = 0;
  };
  std::string name;
  std::vector<std::string> parameters;
  std::map<std::string, Buffer> buffers;
  std::vector<Statement> statements;
  unsigned operations = 0;
  bool extendedMemory = false, littleEndian = true;
};
} // namespace csrd
