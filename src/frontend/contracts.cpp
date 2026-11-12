#include "csrd/calls.hpp"
#include "llvm/Support/JSON.h"
#include <set>
#include <stdexcept>

namespace csrd {
namespace {
void keys(const llvm::json::Object &object, std::initializer_list<const char *> allowed) {
  std::set<std::string> names(allowed.begin(), allowed.end());
  for (const auto &entry : object)
    if (!names.count(entry.first.str())) throw std::invalid_argument("unknown call-contract field: " + entry.first.str());
}
std::string string(const llvm::json::Object &object, const char *name) {
  auto value = object.getString(name);
  if (!value) throw std::invalid_argument(std::string("call contract requires string: ") + name);
  return value->str();
}
}
CallContracts parseCallContracts(const std::string &text) {
  auto parsed = llvm::json::parse(text);
  if (!parsed) throw std::invalid_argument("invalid call-contract JSON: " + llvm::toString(parsed.takeError()));
  const auto *root = parsed->getAsObject();
  if (!root) throw std::invalid_argument("call contracts must be an object");
  keys(*root, {"model", "functions"});
  if (string(*root, "model") != "opaque-sequenced-v1") throw std::invalid_argument("unsupported call-contract model");
  const auto *functions = root->getArray("functions");
  if (!functions || functions->empty() || functions->size() > 64) throw std::invalid_argument("require 1..64 call contracts");
  CallContracts result;
  for (const auto &value : *functions) {
    const auto *function = value.getAsObject();
    if (!function) throw std::invalid_argument("call contract must be an object");
    keys(*function, {"name", "returns", "parameters"});
    const auto name = string(*function, "name"), returns = string(*function, "returns");
    if (name.empty() || (returns != "uint32" && returns != "void")) throw std::invalid_argument("invalid call name or return kind");
    const auto *parameters = function->getArray("parameters");
    if (!parameters || parameters->size() > 8) throw std::invalid_argument("require 0..8 call parameters");
    CallContract contract; contract.returnsVoid = returns == "void";
    for (const auto &p : *parameters) {
      const auto *parameter = p.getAsObject();
      if (!parameter) throw std::invalid_argument("call parameter must be an object");
      CallParameter arg; arg.kind = string(*parameter, "kind");
      if (arg.kind == "uint32") keys(*parameter, {"kind"});
      else {
        keys(*parameter, {"kind", "read_only", "minimum_elements"});
        if (arg.kind != "uint32-buffer" && arg.kind != "unsigned-char-buffer" &&
            arg.kind != "signed-char-buffer" && arg.kind != "char-buffer") throw std::invalid_argument("unsupported call parameter kind");
        const auto readOnly = parameter->getBoolean("read_only");
        const auto count = parameter->getInteger("minimum_elements");
        if (!readOnly || !count || *count < 0 || *count > 256) throw std::invalid_argument("buffer call contract requires read_only and minimum_elements in 0..256");
        arg.readOnly = *readOnly; arg.minimumElements = unsigned(*count);
      }
      contract.parameters.push_back(std::move(arg));
    }
    if (!result.emplace(name, std::move(contract)).second) throw std::invalid_argument("duplicate call contract: " + name);
  }
  return result;
}
} // namespace csrd
