#include "csrd/private_regions.hpp"
#include <algorithm>
#include <functional>
#include <map>
#include <stdexcept>

namespace csrd {
Emission emitPrivateFrame(PrivateFrame &frame, const Representation &rep, const std::set<std::string> &reserved) {
  Emission out;
  frame.emittedDeclarations.clear();
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
    if (!out.body.empty()) out.body += " ";
    out.body += "unsigned int " + name + " = " + value + ";"; ++out.temporaries;
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
  const std::set<std::string> declarations(frame.declarations.begin(), frame.declarations.end());
  // Export original declarations in the same enclosing scope. A new block
  // would hide them from later unchanged statements.
  out.body = declarations.empty() ? "{" : "";
  for (const auto &name : frame.inputs) {
    declare(name, rep.entry(frame.bindings.at(name).name));
    if (encoded) { ++out.encodings; ++out.boundaryConversions; out.estimatedOperations += 2; }
  }
  for (const auto &s : frame.original->statements) {
    // Synthetic frame stores/return are proof devices, never runtime accesses.
    if (s.kind != Statement::Kind::Assign && s.kind != Statement::Kind::Declare) continue;
    const auto value = expression(*s.expression);
    if (values.count(s.name)) out.body += " " + values.at(s.name) + " = " + value + ";";
    else declare(s.name, value);
  }
  auto decode = [&](const std::string &id, bool declaration) {
    const auto &binding = frame.bindings.at(id);
    out.body += " ";
    if (declaration) {
      if (binding.registerStorage) out.body += "register ";
      out.body += "unsigned int ";
      frame.emittedDeclarations.emplace(id, unsigned(out.body.size()));
    }
    out.body += binding.name + " = " + rep.exit(values.at(id)) + ";";
    // A source local used only by this region still has a declared output, but
    // encoded temporaries replaced its internal uses. Keep warning-clean C.
    if (declaration) out.body += " (void)" + binding.name + ";";
    if (encoded) { ++out.decodings; ++out.boundaryConversions; out.estimatedOperations += 2; }
  };
  // Write outer objects before introducing any same-spelled inner objects.
  for (const auto &name : frame.outputs) if (!declarations.count(name)) decode(name, false);
  for (const auto &name : frame.declarations) decode(name, true);
  const auto lines = std::count(frame.originalText.begin(), frame.originalText.end(), '\n');
  if (declarations.empty()) out.body += std::string(lines, '\n') + "}";
  else {
    // Keep both the first token and final semicolon at the recorded boundaries.
    out.body.insert(out.body.size()-1, std::string(lines, '\n'));
  }
  return out;
}
} // namespace csrd
