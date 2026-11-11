#include "csrd/private_regions.hpp"
#include <algorithm>
#include <functional>
#include <map>
#include <stdexcept>

namespace csrd {
Emission emitPrivateFrame(const PrivateFrame &frame, const Representation &rep, const std::set<std::string> &reserved) {
  Emission out;
  const bool encoded = std::string(rep.name()) != "identity-u32";
  auto names = reserved;
  std::map<std::string, std::string> values;
  unsigned sequence = 0;
  auto fresh = [&]() {
    std::string name;
    do { name = "csrd_frame_" + std::to_string(frame.begin) + "_" + std::to_string(sequence++); }
    while (!names.insert(name).second);
    return name;
  };
  auto declare = [&](const std::string &original, const std::string &value) {
    const auto name = fresh(); values.emplace(original, name);
    out.body += " unsigned int " + name + " = " + value + ";"; ++out.temporaries;
  };
  std::function<std::string(const Expr &)> expression = [&](const Expr &e) -> std::string {
    if (e.kind == Expr::Kind::Constant) return rep.constant(e.value);
    if (e.kind == Expr::Kind::Reference) return values.at(e.name);
    const auto left = expression(*e.left);
    ++out.operations;
    if (encoded) ++out.encodedOperations; else ++out.ordinaryIntermediates;
    if (e.kind == Expr::Kind::Scale) {
      out.estimatedOperations += rep.cost(Operation::Scale); return rep.times(left, e.value);
    }
    const auto right = expression(*e.right);
    const auto operation = e.kind == Expr::Kind::Add ? Operation::Add : Operation::Subtract;
    if (e.kind != Expr::Kind::Add && e.kind != Expr::Kind::Subtract)
      throw std::invalid_argument("unmodeled private arithmetic");
    out.estimatedOperations += rep.cost(operation); return rep.binary(operation, left, right);
  };
  out.body = "{";
  for (const auto &name : frame.inputs) {
    declare(name, rep.entry(name));
    if (encoded) { ++out.encodings; ++out.boundaryConversions; out.estimatedOperations += 2; }
  }
  for (const auto &s : frame.original->statements) {
    // Synthetic frame stores/return are proof devices, never runtime accesses.
    if (s.kind != Statement::Kind::Assign) continue;
    const auto value = expression(*s.expression);
    if (values.count(s.name)) out.body += " " + values.at(s.name) + " = " + value + ";";
    else declare(s.name, value);
  }
  for (const auto &name : frame.outputs) {
    out.body += " " + name + " = " + rep.exit(values.at(name)) + ";";
    if (encoded) { ++out.decodings; ++out.boundaryConversions; out.estimatedOperations += 2; }
  }
  out.body += std::string(std::count(frame.originalText.begin(), frame.originalText.end(), '\n'), '\n') + "}";
  return out;
}
} // namespace csrd
