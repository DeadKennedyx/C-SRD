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
};
using CallContracts = std::map<std::string, CallContract>;
CallContracts parseCallContracts(const std::string &json);
} // namespace csrd
