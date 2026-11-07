#pragma once
#include <cstdint>
#include <string>
#include <vector>
#include <memory>
#include "csrd/ir.hpp"
#include "csrd/verification.hpp"
namespace csrd {
struct Decision {
  std::string function, status, reason;
  unsigned line = 0, column = 0, operations = 0, conversions = 0;
  uint32_t a = 0, b = 0, inverse = 0;
  Verification verification;
  std::shared_ptr<Region> region;
};
struct TransformResult {
  std::string source;
  std::vector<Decision> decisions;
  std::string target;
  std::string inputHash, outputHash;
  std::vector<std::pair<std::string, std::string>> dependencies;
};
bool transform(const std::string &path, uint64_t seed, TransformResult &result, unsigned timeoutMs = 10000);
bool inspect(const std::string &path, TransformResult &result, const std::string *contents = nullptr);
std::string sha256(const std::string &data);
}
