#pragma once
#include <cstdint>
#include <memory>
#include <map>
#include <string>
#include <vector>

namespace csrd {
struct IntegerType {
  unsigned bits = 32;
  bool isSigned = false, isBool = false;
  std::string spelling = "unsigned int";
  bool operator==(const IntegerType &other) const {
    return bits == other.bits && isSigned == other.isSigned && isBool == other.isBool && spelling == other.spelling;
  }
  bool operator!=(const IntegerType &other) const { return !(*this == other); }
};
struct IntegerExpr {
  enum class Kind { Constant, Reference, Convert, Add, Subtract, Scale, Negate,
    BitAnd, BitOr, BitXor, BitNot, ShiftLeft, ShiftRight,
    Equal, NotEqual, Less, LessEqual, Greater, GreaterEqual, Select, LogicalNot } kind;
  IntegerType type;
  uint64_t value = 0;
  std::string name;
  std::unique_ptr<IntegerExpr> left, right, third;
  IntegerExpr(Kind k, IntegerType t) : kind(k), type(std::move(t)) {}
};
struct IntegerStatement {
  enum class Kind { Declare, Assign } kind;
  std::string name;
  IntegerType type;
  std::unique_ptr<IntegerExpr> expression;
  IntegerStatement(Kind k, std::string n, IntegerType t, std::unique_ptr<IntegerExpr> e)
    : kind(k), name(std::move(n)), type(std::move(t)), expression(std::move(e)) {}
};
struct IntegerRegion {
  std::string name;
  std::vector<IntegerStatement> statements;
  unsigned operations = 0;
};
// Untrusted hints. Candidate names/cuts must be resolved against reparsed C,
// and each relation proved before it may be used by the next fragment.
struct IntegerCheckpoint {
  unsigned sourceEnd = 0, candidateEnd = 0;
  std::string anchor;
  std::map<std::string,std::string> encoded;
};
struct IntegerWitness {
  uint64_t multiplier = 1, offset = 0;
  std::vector<IntegerCheckpoint> checkpoints;
};

// Compatible affine parameters at all widths: reducing an encoded value to
// fewer bits directly yields the encoding of its truncated value.
class IntegerCodec {
  uint64_t a_, b_, inverse_;
public:
  IntegerCodec(uint64_t a, uint64_t b);
  static IntegerCodec fromSeed(uint64_t seed, const std::string &key);
  static IntegerCodec identity() { return {1,0}; }
  bool encoded() const { return a_ != 1 || b_ != 0; }
  uint64_t multiplier() const { return a_; }
  uint64_t offset() const { return b_; }
  uint64_t inverse() const { return inverse_; }
  uint64_t encode(uint64_t x, unsigned bits) const;
  uint64_t decode(uint64_t x, unsigned bits) const;
  uint64_t add(uint64_t x, uint64_t y, unsigned bits) const;
  uint64_t subtract(uint64_t x, uint64_t y, unsigned bits) const;
  uint64_t scale(uint64_t x, uint64_t k, unsigned bits) const;
  std::string entry(const std::string &, unsigned bits) const;
  std::string exit(const std::string &, unsigned bits) const;
  std::string binary(bool addition, const std::string &, const std::string &, unsigned bits) const;
  std::string times(const std::string &, uint64_t k, unsigned bits) const;
};
uint64_t integerMask(unsigned bits);
std::string integerLiteral(uint64_t);
std::string integerTruncate(const std::string &, unsigned bits);
// Reconstruct signed values using representable casts and bitwise complement.
std::string integerRestore(const std::string &raw, const IntegerType &);
} // namespace csrd
