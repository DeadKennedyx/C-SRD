#include "csrd/representation.hpp"
#include <cstdlib>
#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>

namespace {
uint64_t checks = 0;
void require(bool ok) {
  ++checks;
  if (!ok) { std::cerr << "representation check " << checks << " failed\n"; std::exit(1); }
}
void check(const csrd::Representation &r, uint32_t x, uint32_t y, uint32_t k) {
  require(r.decode(r.encode(x)) == x);
  require(r.decode(r.encode(y)) == y);
  require(r.add(r.encode(x), r.encode(y)) == r.encode(uint32_t(uint64_t(x) + y)));
  require(r.subtract(r.encode(x), r.encode(y)) == r.encode(uint32_t(uint64_t(x) - y)));
  require(r.scale(r.encode(x), k) == r.encode(uint32_t(uint64_t(x) * k)));
}
}
int main() {
  const std::vector<uint32_t> edges = {0, 1, 2, 3, 0x7fffffffu, 0x80000000u, 0x80000001u, 0xfffffffeu, 0xffffffffu};
  std::vector<csrd::Affine> reps = {{1, 0}, {1, 0xffffffffu}, {3, 11}, {0xffffffffu, 0xffffffffu}, {0x80000001u, 0x80000000u}};
  for (uint64_t seed = 0; seed < 32; ++seed) reps.push_back(csrd::Affine::fromSeed(seed, "unit"));
  std::mt19937 generator(0x43535244u);
  csrd::Identity identity;
  for (auto x : edges) for (auto y : edges) for (auto k : edges) check(identity, x, y, k);
  for (const auto &r : reps) {
    require(uint32_t(uint64_t(r.a()) * r.inverse()) == 1u);
    for (auto x : edges) for (auto y : edges) for (auto k : edges) check(r, x, y, k);
    for (unsigned i = 0; i < 10000; ++i) {
      const uint32_t x = generator(), y = generator(), k = generator();
      check(r, x, y, k);
    }
  }
  bool rejected = false;
  try { csrd::Affine invalid(2, 1); } catch (const std::invalid_argument &) { rejected = true; }
  require(rejected);
  require(csrd::Affine::fromSeed(42, "f").a() == csrd::Affine::fromSeed(42, "f").a());
  for (auto mask : edges) {
    csrd::Xor r(mask);
    for (auto x : edges) for (auto y : edges) {
      require(r.decode(r.encode(x)) == x);
      require(r.bitwise(csrd::Operation::BitXor, r.encode(x), r.encode(y)) == r.encode(x ^ y));
      require(r.bitwise(csrd::Operation::BitAnd, r.encode(x), r.encode(y)) == r.encode(x & y));
      require(r.bitwise(csrd::Operation::BitOr, r.encode(x), r.encode(y)) == r.encode(x | y));
      require(r.bitwise(csrd::Operation::BitNot, r.encode(x)) == r.encode(~x));
      for (unsigned shift : {0u, 1u, 15u, 31u}) {
        require(r.bitwise(csrd::Operation::ShiftLeft, r.encode(x), shift) == r.encode(uint32_t(uint64_t(x) << shift)));
        require(r.bitwise(csrd::Operation::ShiftRight, r.encode(x), shift) == r.encode(x >> shift));
      }
    }
  }
  std::cout << "PASS " << checks << " representation checks (empirical)\n";
}
