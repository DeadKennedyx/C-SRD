#include "csrd/representation.hpp"
#include <stdexcept>

namespace csrd {
namespace {
uint32_t mul(uint32_t x, uint32_t y) { return uint32_t(uint64_t(x) * y); }
uint64_t next(uint64_t &state) {
  // SplitMix64: specified integer operations, no implementation-defined RNG distribution.
  uint64_t z = (state += UINT64_C(0x9e3779b97f4a7c15));
  z = (z ^ (z >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
  z = (z ^ (z >> 27)) * UINT64_C(0x94d049bb133111eb);
  return z ^ (z >> 31);
}
}
std::string literal(uint32_t x) { return std::to_string(x) + "u"; }
std::string Representation::constant(uint32_t x) const { return literal(encode(x)); }
Affine::Affine(uint32_t multiplier, uint32_t offset) : a_(multiplier), b_(offset), inverse_(1) {
  if (!(a_ & 1u)) throw std::invalid_argument("affine multiplier must be odd");
  // Newton inversion doubles correct low bits: 1 -> 2 -> 4 -> 8 -> 16 -> 32.
  for (unsigned i = 0; i < 5; ++i) inverse_ = mul(inverse_, uint32_t(2u - mul(a_, inverse_)));
}
Affine Affine::fromSeed(uint64_t seed, const std::string &function) {
  uint64_t hash = UINT64_C(14695981039346656037);
  for (unsigned char c : function) { hash ^= c; hash *= UINT64_C(1099511628211); }
  uint64_t state = seed ^ hash;
  uint32_t a = uint32_t(next(state)) | 1u;
  if (a == 1) a = 3; // Ensure a nonidentity representation for every seed.
  return Affine(a, uint32_t(next(state)));
}
uint32_t Affine::encode(uint32_t x) const { return uint32_t(uint64_t(mul(a_, x)) + b_); }
uint32_t Affine::decode(uint32_t x) const { return mul(inverse_, uint32_t(uint64_t(x) - b_)); }
uint32_t Affine::add(uint32_t x, uint32_t y) const { return uint32_t(uint64_t(x) + y - b_); }
uint32_t Affine::subtract(uint32_t x, uint32_t y) const { return uint32_t(uint64_t(x) - y + b_); }
uint32_t Affine::scale(uint32_t x, uint32_t k) const {
  return uint32_t(uint64_t(mul(k, x)) + mul(uint32_t(1u - k), b_));
}
std::string Affine::entry(const std::string &x) const {
  return "((" + literal(a_) + " * (" + x + ")) + " + literal(b_) + ")";
}
std::string Affine::exit(const std::string &x) const {
  return "(" + literal(inverse_) + " * ((" + x + ") - " + literal(b_) + "))";
}
std::string Affine::binary(Operation op, const std::string &x, const std::string &y) const {
  if (op == Operation::Scale) throw std::invalid_argument("use times for scaling");
  return "(((" + x + (op == Operation::Add ? ") + (" : ") - (") + y +
         (op == Operation::Add ? ")) - " : ")) + ") + literal(b_) + ")";
}
std::string Affine::times(const std::string &x, uint32_t k) const {
  return "((" + literal(k) + " * (" + x + ")) + " + literal(mul(uint32_t(1u - k), b_)) + ")";
}
uint32_t Identity::add(uint32_t x, uint32_t y) const { return uint32_t(uint64_t(x) + y); }
uint32_t Identity::subtract(uint32_t x, uint32_t y) const { return uint32_t(uint64_t(x) - y); }
uint32_t Identity::scale(uint32_t x, uint32_t k) const { return mul(x, k); }
std::string Identity::binary(Operation op, const std::string &x, const std::string &y) const {
  if (op == Operation::Scale) throw std::invalid_argument("use times for scaling");
  return "((" + x + (op == Operation::Add ? ") + (" : ") - (") + y + "))";
}
std::string Identity::times(const std::string &x, uint32_t k) const {
  return "(" + literal(k) + " * (" + x + "))";
}
} // namespace csrd
