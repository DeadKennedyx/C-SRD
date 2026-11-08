#pragma once
#include <cstdint>
#include <string>

namespace csrd {
// All rules are over Z/(2^32). C emission requires a 32-bit unsigned int.
// Compatible values must share the same representation parameters.
enum class Operation { Add, Subtract, Scale, BitAnd, BitOr, BitXor, BitNot, ShiftLeft, ShiftRight };
class Representation {
public:
  virtual ~Representation() = default;
  virtual const char *name() const = 0;
  virtual uint32_t encode(uint32_t x) const = 0;
  virtual uint32_t decode(uint32_t x) const = 0;
  virtual uint32_t add(uint32_t x, uint32_t y) const = 0;
  virtual uint32_t subtract(uint32_t x, uint32_t y) const = 0;
  virtual uint32_t scale(uint32_t x, uint32_t k) const = 0;
  virtual std::string entry(const std::string &x) const = 0;
  virtual std::string exit(const std::string &x) const = 0;
  virtual std::string binary(Operation op, const std::string &x, const std::string &y) const = 0;
  virtual std::string times(const std::string &x, uint32_t k) const = 0;
  // Static scalar arithmetic count, not a CPU timing estimate.
  virtual unsigned cost(Operation op) const = 0;
  virtual bool supports(Operation op) const { return op <= Operation::Scale; }
  std::string constant(uint32_t x) const;
};
class Affine final : public Representation {
public:
  Affine(uint32_t multiplier, uint32_t offset);
  static Affine fromSeed(uint64_t seed, const std::string &function);
  const char *name() const override { return "affine-u32"; }
  uint32_t encode(uint32_t x) const override;
  uint32_t decode(uint32_t x) const override;
  uint32_t add(uint32_t x, uint32_t y) const override;
  uint32_t subtract(uint32_t x, uint32_t y) const override;
  uint32_t scale(uint32_t x, uint32_t k) const override;
  std::string entry(const std::string &x) const override;
  std::string exit(const std::string &x) const override;
  std::string binary(Operation op, const std::string &x, const std::string &y) const override;
  std::string times(const std::string &x, uint32_t k) const override;
  unsigned cost(Operation) const override { return 2; }
  uint32_t a() const { return a_; }
  uint32_t b() const { return b_; }
  uint32_t inverse() const { return inverse_; }
private:
  uint32_t a_, b_, inverse_;
};
class Identity final : public Representation {
public:
  const char *name() const override { return "identity-u32"; }
  uint32_t encode(uint32_t x) const override { return x; }
  uint32_t decode(uint32_t x) const override { return x; }
  uint32_t add(uint32_t x, uint32_t y) const override;
  uint32_t subtract(uint32_t x, uint32_t y) const override;
  uint32_t scale(uint32_t x, uint32_t k) const override;
  std::string entry(const std::string &x) const override { return x; }
  std::string exit(const std::string &x) const override { return x; }
  std::string binary(Operation op, const std::string &x, const std::string &y) const override;
  std::string times(const std::string &x, uint32_t k) const override;
  unsigned cost(Operation) const override { return 1; }
  bool supports(Operation) const override { return true; }
};
class Xor final : public Representation {
public:
  explicit Xor(uint32_t mask) : mask_(mask) {}
  const char *name() const override { return "xor-u32"; }
  uint32_t mask() const { return mask_; }
  uint32_t encode(uint32_t x) const override { return x ^ mask_; }
  uint32_t decode(uint32_t x) const override { return x ^ mask_; }
  uint32_t add(uint32_t, uint32_t) const override;
  uint32_t subtract(uint32_t, uint32_t) const override;
  uint32_t scale(uint32_t, uint32_t) const override;
  uint32_t bitwise(Operation op, uint32_t x, uint32_t y = 0) const;
  std::string entry(const std::string &x) const override;
  std::string exit(const std::string &x) const override { return entry(x); }
  std::string binary(Operation op, const std::string &x, const std::string &y) const override;
  std::string times(const std::string &, uint32_t) const override;
  std::string shift(const std::string &x, unsigned count, bool left) const;
  unsigned cost(Operation op) const override;
  bool supports(Operation op) const override { return op >= Operation::BitAnd; }
private:
  uint32_t mask_;
};
std::string literal(uint32_t x);
} // namespace csrd
