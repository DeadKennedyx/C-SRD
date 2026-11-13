#pragma once
#include <cstdint>
#include <memory>
#include <map>
#include <set>
#include <string>
#include <vector>
#include "csrd/calls.hpp"

namespace csrd {
// Validated fixed-width IR. Memory regions retain statement order; they must
// never be lowered through the pure graph's return-only liveness analysis.
struct Expr {
  enum class Kind { Constant, Reference, Add, Subtract, Scale, BitAnd, BitOr, BitXor,
                    BitNot, ShiftLeft, ShiftRight, Equal, NotEqual, Less, LessEqual,
                    Greater, GreaterEqual, Select, Table, Load, ByteCast, PointerNonNull } kind;
  uint32_t value = 0; // Constant, scale, load index bound, or ByteCast signedness.
  std::string name;
  std::string member; // Named record field for a Load; never a C text fragment.
  std::unique_ptr<Expr> left, right, third;
  std::vector<uint32_t> table;
  explicit Expr(Kind k) : kind(k) {}
};
struct Statement {
  enum class Kind { Declare, Assign, Return, If, Repeat, Store, Call,
                    Allocate, Release, PointerBind } kind;
  std::string name;
  std::string member; // Named record field for a Store.
  std::unique_ptr<Expr> expression;
  std::vector<Statement> thenBranch, elseBranch;
  unsigned repetitions = 0;
  // Repeat.expression, when present, is the runtime trip limit. repetitions
  // is its maximum, checked by verification rather than assumed truncation.
  uint32_t index = 0; // Fixed Store index; Load uses Expr::value.
  std::unique_ptr<Expr> dynamicIndex; // If present, index is its proven upper bound.
  struct Argument {
    std::string buffer; // Empty for uint32; otherwise an original buffer parameter.
    std::string stream; // Opaque caller-owned FILE identity; never a data address.
    bool nonnegativeInt = false;
    std::unique_ptr<Expr> value; // Scalar value or captured pointer offset.
    uint32_t bound = 0;
  };
  std::string callee;
  std::string indirectTarget; // Original function-pointer parameter, never encoded.
  bool recursiveCall = false;
  std::vector<Argument> arguments;
  bool declaresCallResult = false;
  std::string pointer; // Owned pointer source; empty denotes null.
  bool pointerArithmetic = false, callocSwapped = false;
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
    bool persistent = false, isUnion = false;
    bool heap = false; // Local owned handle, never a caller footprint assumption.
    std::string recordTag;
    unsigned recordBytes = 0, recordAlignment = 0;
    std::map<std::string, unsigned> fields; // Byte offsets from Clang's layout.
    unsigned stride() const { return recordBytes ? recordBytes : elementBits / 8; }
  };
  std::string name;
  std::vector<std::string> parameters;
  std::map<std::string, Buffer> buffers;
  std::vector<Statement> statements;
  unsigned operations = 0;
  bool extendedMemory = false, littleEndian = true;
  bool orderedCalls = false;
  bool guardedCalls = false;
  std::map<std::string, std::string> functionPointers; // Parameter -> contract key.
  std::set<std::string> streams; // Caller-owned ordinary FILE * parameters.
  std::string recursiveContract;
  bool memoryControl = false;
  bool ownedHeap = false;
  CallContracts calls;
  bool ordered() const { return !buffers.empty() || orderedCalls || ownedHeap || !functionPointers.empty() || !streams.empty(); }
};
} // namespace csrd
