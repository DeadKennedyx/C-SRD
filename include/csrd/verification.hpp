#pragma once
#include "csrd/ir.hpp"
#include <cstdint>
#include <string>
#include <vector>
namespace csrd {
struct Verification {
  std::string status = "not-verified", reason, obligation, strategy;
  std::vector<uint32_t> inputs;
  uint32_t originalOutput = 0, candidateOutput = 0;
};
Verification verify(const Region &original, const Region &candidate, unsigned timeoutMs = 10000);
std::string solverVersion();
}
