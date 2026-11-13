#pragma once
#include <map>
#include <string>
#include <vector>

namespace csrd {
// Explicit environmental assumptions, not inferred callee purity. Calls may
// change shared memory/external state; private automatic objects cannot escape.
struct CallParameter {
  std::string kind;
  bool readOnly = false;
  unsigned minimumElements = 0;
};
struct CallContract {
  bool returnsVoid = false;
  std::vector<CallParameter> parameters;
  bool guarded = false;
  std::string indirectParameter;
  bool recursive = false;
  unsigned rankParameter = 0, maximumRank = 0;
};
using CallContracts = std::map<std::string, CallContract>;
inline std::string indirectContractKey(const std::string &function, const std::string &parameter) {
  return function + "::" + parameter;
}
CallContracts parseCallContracts(const std::string &json);
} // namespace csrd
