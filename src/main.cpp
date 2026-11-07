#include "csrd/config.hpp"
#include "csrd/frontend.hpp"
#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"
#include <charconv>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
void usage() {
  std::cout << "C-SRD " CSRD_VERSION "\nUsage: csrd transform input.c -o output.c [--seed UINT64] [--report report.json]\n"
               "Pure straight-line unsigned 32-bit C11 functions; unsupported functions remain unchanged.\n";
}
bool samePath(const std::string &a, const std::string &b) {
  if (std::filesystem::weakly_canonical(a) == std::filesystem::weakly_canonical(b)) return true;
  return std::filesystem::exists(a) && std::filesystem::exists(b) && std::filesystem::equivalent(a, b);
}
void writeFile(const std::string &path, const std::string &contents) {
  std::ofstream stream(path, std::ios::binary | std::ios::trunc);
  if (!stream || !(stream << contents) || !stream.flush()) throw std::runtime_error("cannot write " + path);
}
std::string report(const csrd::TransformResult &result, uint64_t seed) {
  llvm::json::Array functions;
  for (const auto &d : result.decisions) {
    llvm::json::Object f{{"function", d.function}, {"status", d.status}, {"line", d.line}, {"column", d.column}};
    if (d.status == "transformed") {
      f["representation"] = "affine-u32";
      f["a"] = d.a; f["b"] = d.b; f["inverse"] = d.inverse;
      f["operations_transformed"] = d.operations;
      f["operations_without_decoding"] = d.operations;
      f["boundary_conversions"] = d.conversions;
      f["internal_conversions"] = 0;
      f["verification"] = "not-verified-for-this-input";
    } else f["reason"] = d.reason;
    functions.push_back(std::move(f));
  }
  llvm::json::Object root{{"schema_version", 1}, {"csrd_version", CSRD_VERSION}, {"seed", std::to_string(seed)},
                          {"target", result.target}, {"functions", std::move(functions)}};
  std::string out;
  llvm::raw_string_ostream stream(out);
  stream << llvm::formatv("{0:2}\n", llvm::json::Value(std::move(root)));
  return out;
}
}
int main(int argc, char **argv) {
  try {
    if (argc == 2 && (std::string(argv[1]) == "--help" || std::string(argv[1]) == "--version")) { usage(); return 0; }
    if (argc < 5 || std::string(argv[1]) != "transform") { usage(); return 2; }
    const std::string input = argv[2];
    std::string output, reportPath;
    uint64_t seed = 0;
    bool seedSet = false;
    for (int i = 3; i < argc; ++i) {
      const std::string key = argv[i];
      if (i + 1 >= argc) throw std::runtime_error("missing value for " + key);
      const std::string value = argv[++i];
      if (key == "-o" && output.empty()) output = value;
      else if (key == "--report" && reportPath.empty()) reportPath = value;
      else if (key == "--seed" && !seedSet) {
        const auto parsed = std::from_chars(value.data(), value.data() + value.size(), seed);
        if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size()) throw std::runtime_error("seed must be a decimal uint64 value");
        seedSet = true;
      } else throw std::runtime_error("unknown or repeated option: " + key);
    }
    if (output.empty()) throw std::runtime_error("-o output.c is required");
    if (samePath(input, output) || (!reportPath.empty() && (samePath(input, reportPath) || samePath(output, reportPath))))
      throw std::runtime_error("input, output and report paths must be distinct");
    csrd::TransformResult result;
    if (!csrd::transform(input, seed, result)) return 1;
    writeFile(output, result.source);
    if (!reportPath.empty()) writeFile(reportPath, report(result, seed));
    return 0;
  } catch (const std::exception &e) {
    std::cerr << "csrd: error: " << e.what() << '\n';
    return 2;
  }
}
