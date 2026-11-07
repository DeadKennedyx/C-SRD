#pragma once
#include <cstdint>
#include <string>
#include <vector>
namespace csrd {
struct Decision {
  std::string function, status, reason;
  unsigned line = 0, column = 0, operations = 0, conversions = 0;
  uint32_t a = 0, b = 0, inverse = 0;
};
struct TransformResult {
  std::string source;
  std::vector<Decision> decisions;
  std::string target;
};
bool transform(const std::string &path, uint64_t seed, TransformResult &result);
}
