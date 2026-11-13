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
  const auto model=string(*root,"model");
  const bool streams=model=="opaque-stdio-v3";
  const bool guarded=model=="opaque-guarded-v2" || streams;
  if (model != "opaque-sequenced-v1" && !guarded) throw std::invalid_argument("unsupported call-contract model");
  const auto *functions = root->getArray("functions");
  if (!functions || functions->empty() || functions->size() > 64) throw std::invalid_argument("require 1..64 call contracts");
  CallContracts result;
  for (const auto &value : *functions) {
    const auto *function = value.getAsObject();
    if (!function) throw std::invalid_argument("call contract must be an object");
    if (guarded && !streams) keys(*function, {"name", "returns", "parameters", "indirect_parameter", "recursion"});
    else keys(*function, {"name", "returns", "parameters"});
    const auto name = string(*function, "name"), returns = string(*function, "returns");
    if (name.empty() || (returns != "uint32" && returns != "void" && !(streams && returns=="int32")))
      throw std::invalid_argument("invalid call name or return kind");
    const auto *parameters = function->getArray("parameters");
    if (!parameters || parameters->size() > 8) throw std::invalid_argument("require 0..8 call parameters");
    CallContract contract; contract.returnsVoid = returns == "void"; contract.guarded=guarded;
    contract.returnsSigned=returns=="int32";contract.standardStream=streams;
    for (const auto &p : *parameters) {
      const auto *parameter = p.getAsObject();
      if (!parameter) throw std::invalid_argument("call parameter must be an object");
      CallParameter arg; arg.kind = string(*parameter, "kind");
      if (arg.kind == "uint32" || (streams && (arg.kind=="file-stream" || arg.kind=="int32-nonnegative"))) keys(*parameter, {"kind"});
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
    if (streams) {
      const std::map<std::string,std::vector<std::string>> allowed{
        {"fgetc",{"file-stream"}}, {"fputc",{"int32-nonnegative","file-stream"}},
        {"fflush",{"file-stream"}}, {"feof",{"file-stream"}}, {"ferror",{"file-stream"}}, {"clearerr",{"file-stream"}}};
      const auto found=allowed.find(name);std::vector<std::string> kinds;
      for (const auto &p:contract.parameters) kinds.push_back(p.kind);
      if (found==allowed.end() || found->second!=kinds || returns!=(name=="clearerr" ? "void" : "int32"))
        throw std::invalid_argument("stdio contracts require the exact supported C11 stream interface");
    }
    std::string key=name;
    if (function->get("indirect_parameter")) {
      contract.indirectParameter=string(*function,"indirect_parameter");
      if (contract.indirectParameter.empty() || name.find("::")!=std::string::npos || contract.indirectParameter.find("::")!=std::string::npos)
        throw std::invalid_argument("indirect contracts require an unambiguous function and parameter name");
      key=indirectContractKey(name,contract.indirectParameter);
    }
    if (function->get("recursion")) {
      const auto *recursion=function->getObject("recursion");
      if (!recursion || !contract.indirectParameter.empty() || contract.returnsVoid)
        throw std::invalid_argument("recursion requires a direct uint32 function contract");
      keys(*recursion,{"rank_parameter","maximum_rank"});
      const auto rank=recursion->getInteger("rank_parameter"), maximum=recursion->getInteger("maximum_rank");
      if (!rank || !maximum || *rank<0 || uint64_t(*rank)>=contract.parameters.size() ||
          contract.parameters[size_t(*rank)].kind!="uint32" || *maximum<1 || *maximum>32)
        throw std::invalid_argument("recursion requires a uint32 rank parameter index and maximum_rank in 1..32");
      contract.recursive=true;contract.rankParameter=unsigned(*rank);contract.maximumRank=unsigned(*maximum);
    }
    if (!result.emplace(key, std::move(contract)).second) throw std::invalid_argument("duplicate call contract: " + key);
  }
  return result;
}
} // namespace csrd
