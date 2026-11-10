#include "csrd/config.hpp"
#include "csrd/frontend.hpp"
#include "clang/Basic/Version.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"
#include <algorithm>
#include <charconv>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
void usage() {
  std::cout << "C-SRD " CSRD_VERSION "\n"
    "Usage: csrd transform input.c -o output.c [--seed UINT64] [--report report.json] [--timeout-ms UINT]\n"
    "       [--strategy affine|xor|identity|independent|planned|limbs16|limbs8|limbs4] [--coverage 0..100] [--objective balanced|runtime|size]\n"
    "       [--algorithm popcount8-serial|popcount8-swar]\n"
    "       [--control-flow none|split-scale] (experimental)\n"
    "       csrd verify original.c candidate.c [--function NAME] [--report report.json] [--timeout-ms UINT]\n"
    "       csrd analyze input.c [--function NAME] [--report report.json]\n"
    "Transformations are checked against reparsed emitted C before output is written.\n";
}
bool samePath(const std::string &a, const std::string &b) {
  if (std::filesystem::weakly_canonical(a) == std::filesystem::weakly_canonical(b)) return true;
  return std::filesystem::exists(a) && std::filesystem::exists(b) && std::filesystem::equivalent(a, b);
}
void writeFile(const std::string &path, const std::string &contents) {
  std::ofstream stream(path, std::ios::binary | std::ios::trunc);
  if (!stream || !(stream << contents) || !stream.flush()) throw std::runtime_error("cannot write " + path);
}
uint64_t number(const std::string &value) {
  uint64_t result = 0;
  const auto parsed = std::from_chars(value.data(), value.data() + value.size(), result);
  if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size()) throw std::runtime_error("expected a decimal unsigned integer: " + value);
  return result;
}
llvm::json::Object proof(const csrd::Verification &v) {
  llvm::json::Object result{{"status", v.status}, {"reason", v.reason}, {"solver_strategy", v.strategy}};
  if (!v.label.empty()) result["label"] = v.label;
  if (!v.steps.empty()) {
    llvm::json::Array steps;
    for (const auto &step : v.steps) steps.push_back(proof(step));
    result["steps"] = std::move(steps);
  }
  if (!v.priorAttempts.empty()) {
    llvm::json::Array attempts;
    for (const auto &attempt : v.priorAttempts) attempts.push_back(proof(attempt));
    result["prior_attempts"] = std::move(attempts);
  }
  if (!v.localValues.empty()) {
    llvm::json::Object values;
    for (const auto &entry : v.localValues) values[entry.first] = entry.second;
    result["local_countermodel"] = std::move(values);
  }
  if (v.composition) {
    llvm::json::Array graph, declarations, points;
    for (const auto &name : v.composition->witness.declarations) declarations.push_back(name);
    for (unsigned id = 0; id < v.composition->graph.nodes.size(); ++id) {
      const auto &node = v.composition->graph.nodes[id];
      llvm::json::Array inputs, table;
      for (auto input : node.inputs) inputs.push_back(input);
      for (auto value : node.table) table.push_back(value);
      graph.push_back(llvm::json::Object{{"id", id}, {"operation", csrd::operationName(node.kind)},
        {"value", node.value}, {"parameter", node.parameter}, {"inputs", std::move(inputs)}, {"table", std::move(table)}});
    }
    auto piece = [](const csrd::LimbPiece &p) {
      return p.name.empty() ? llvm::json::Object{{"constant", p.constant}} : llvm::json::Object{{"declaration", p.name}};
    };
    const auto bits = v.composition->witness.pieceBits;
    for (const auto &point : v.composition->witness.nodes) {
      llvm::json::Array pieces;
      for (const auto &p : point.pieces) pieces.push_back(piece(p));
      llvm::json::Object checkpoint{{"declaration_end", point.declarationEnd}, {"pieces", std::move(pieces)}};
      if (!point.scaleSteps.empty()) {
        llvm::json::Array steps;
        for (const auto &step : point.scaleSteps)
          steps.push_back(llvm::json::Object{{"declaration_end", step.declarationEnd},
            {"partial", piece(step.partial)}, {"carry", piece(step.carry)}});
        checkpoint["scale_steps"] = std::move(steps);
      }
      if (bits == 16) { // Preserve the legacy aliases in new two-piece reports.
        checkpoint["low"] = piece(point.pieces.at(0)); checkpoint["high"] = piece(point.pieces.at(1));
      }
      points.push_back(std::move(checkpoint));
    }
    const auto invariant = bits == 16 ? "decoded-value-equality-and-both-pieces-u16" :
      "decoded-value-equality-and-each-piece-u" + std::to_string(bits);
    result["composition"] = llvm::json::Object{{"invariant", invariant},
      {"piece_bits", bits}, {"piece_order", "least-significant-first"},
      {"graph", std::move(graph)}, {"result", v.composition->graph.result},
      {"declarations", std::move(declarations)}, {"checkpoints", std::move(points)}};
  }
  if (!v.obligation.empty()) {
    result["obligation_sha256"] = csrd::sha256(v.obligation);
    result["smtlib"] = v.obligation;
  }
  if (v.status == "counterexample") {
    llvm::json::Array inputs;
    for (auto x : v.inputs) inputs.push_back(x);
    result["inputs"] = std::move(inputs);
    result["original_output"] = v.originalOutput;
    result["candidate_output"] = v.candidateOutput;
    if (!v.pointerBases.empty()) {
      llvm::json::Object bases;
      llvm::json::Array cells;
      for (const auto &entry : v.pointerBases) bases[entry.first] = entry.second;
      for (const auto &cell : v.memoryCells) cells.push_back(llvm::json::Object{
        {"word_address", cell.address}, {"initial", cell.initial},
        {"original", cell.original}, {"candidate", cell.candidate}});
      result["pointer_word_bases"] = std::move(bases);
      result["memory_cells"] = std::move(cells);
      result["input_layout"] = "inputs contains scalar parameters only, in signature order; pointer bases are abstract word addresses";
    }
  }
  return result;
}
std::string report(const csrd::TransformResult &result, uint64_t seed, const std::string &action) {
  llvm::json::Array functions, dependencies, candidateDependencies;
  for (const auto &dep : result.dependencies)
    dependencies.push_back(llvm::json::Object{{"path", dep.first}, {"sha256", dep.second}});
  for (const auto &dep : result.candidateDependencies)
    candidateDependencies.push_back(llvm::json::Object{{"path", dep.first}, {"sha256", dep.second}});
  for (const auto &d : result.decisions) {
    llvm::json::Object f{{"function", d.function}, {"status", d.status}, {"line", d.line}, {"column", d.column},
                         {"verification", d.verification.status}, {"proof", proof(d.verification)}};
    llvm::json::Object operators;
    for (const auto &entry : d.metrics.operators) operators[entry.first] = entry.second;
    f["parameter_count"] = d.parameterCount;
    if (d.region) {
      const auto &region = *d.region;
      f["semantic_model"] = region.buffers.empty() ? "pure-u32-c11-v2" : "buffers-u32-c11-v1";
      llvm::json::Array parameters;
      for (const auto &name : region.parameters) {
        const auto buffer = region.buffers.find(name);
        if (buffer == region.buffers.end()) parameters.push_back(llvm::json::Object{{"name", name}, {"kind", "uint32"}});
        else parameters.push_back(llvm::json::Object{{"name", name}, {"kind", "uint32-buffer"},
          {"read_only", buffer->second.readOnly}, {"minimum_elements", buffer->second.minimumElements},
          {"loads", buffer->second.loads}, {"stores", buffer->second.stores}});
      }
      f["parameters"] = std::move(parameters);
    }
    f["source_metrics"] = llvm::json::Object{{"ast_nodes", d.metrics.astNodes}, {"expressions", d.metrics.expressions},
      {"branches", d.metrics.branches}, {"loops", d.metrics.loops}, {"cfg_blocks", d.metrics.cfgBlocks},
      {"cfg_edges", d.metrics.cfgEdges}, {"cyclomatic", d.metrics.cyclomatic}, {"ast_shape_sha256", d.metrics.astShape},
      {"cfg_adjacency_sha256", d.metrics.cfgShape}, {"operators", std::move(operators)}};
    if (d.status == "transformed") {
      f["strategy"] = result.options.strategy;
      f["algorithm_candidate"] = result.options.algorithm;
      f["control_flow"] = result.options.controlFlow;
      f["split_scales"] = d.emission.splitScales;
      if (!csrd::limbBits(result.options.strategy)) {
        f["a"] = d.a; f["b"] = d.b; f["inverse"] = d.inverse;
        f["xor_mask"] = d.xorMask;
      }
      f["seed_affects_representation"] = !csrd::limbBits(result.options.strategy) && result.options.strategy != "identity";
      f["operations_transformed"] = d.operations;
      f["operations_without_decoding"] = d.emission.encodedOperations;
      f["boundary_conversions"] = d.conversions;
      f["internal_conversions"] = d.emission.internalConversions;
      f["encodings"] = d.emission.encodings;
      f["decodings"] = d.emission.decodings;
      f["estimated_scalar_operations"] = d.emission.estimatedOperations;
      f["temporaries"] = d.emission.temporaries;
      f["ordinary_value_nodes"] = d.emission.ordinaryIntermediates;
      f["planner_status"] = d.plan.status;
      f["planner_reason"] = d.plan.reason;
      f["required_encoded_operations"] = d.plan.requiredEncoded;
      llvm::json::Array nodes;
      for (unsigned id = 0; d.graph && id < d.graph->nodes.size(); ++id) {
        const auto &node = d.graph->nodes[id];
        llvm::json::Array inputs;
        for (auto input : node.inputs) inputs.push_back(input);
        nodes.push_back(llvm::json::Object{{"id", id}, {"operation", csrd::operationName(node.kind)},
          {"representation", csrd::encodingName(d.plan.labels[id])}, {"inputs", std::move(inputs)}});
      }
      f["graph"] = std::move(nodes);
    }
    if (!d.reason.empty()) f["reason"] = d.reason;
    functions.push_back(std::move(f));
  }
  llvm::json::Object root{{"schema_version", 2}, {"csrd_version", CSRD_VERSION}, {"action", action}, {"seed", std::to_string(seed)},
    {"target", result.target}, {"source_sha256", result.inputHash}, {"candidate_sha256", result.outputHash},
    {"clang", clang::getClangFullVersion()}, {"solver", csrd::solverVersion()}, {"dependencies", std::move(dependencies)},
    {"candidate_dependencies", std::move(candidateDependencies)},
    {"model", "per-function semantic_model; identical target, headers and compilation environment required"}, {"functions", std::move(functions)}};
  root["strategy"] = result.options.strategy;
  root["control_flow"] = result.options.controlFlow;
  root["objective"] = result.options.objective;
  root["coverage_percent"] = result.options.coverage;
  root["timeout_ms"] = result.options.timeoutMs;
  root["output_written"] = result.outputWritten;
  std::string out;
  llvm::raw_string_ostream stream(out);
  stream << llvm::formatv("{0:2}\n", llvm::json::Value(std::move(root)));
  return out;
}
}
int main(int argc, char **argv) {
  try {
    if (argc == 2 && (std::string(argv[1]) == "--help" || std::string(argv[1]) == "--version")) { usage(); return 0; }
    if (argc < 3) { usage(); return 2; }
    const std::string action = argv[1], input = argv[2];
    if (action != "transform" && action != "verify" && action != "analyze") { usage(); return 2; }
    if (action == "verify" && argc < 4) { usage(); return 2; }
    std::string output, reportPath, function;
    uint64_t seed = 0;
    unsigned timeout = 10000;
    bool seedSet = false, timeoutSet = false;
    csrd::PlanOptions options;
    bool strategySet = false, coverageSet = false, objectiveSet = false, algorithmSet = false, controlFlowSet = false;
    if (action == "verify") output = argv[3];
    for (int i = action == "verify" ? 4 : 3; i < argc; ++i) {
      const std::string key = argv[i];
      if (i + 1 >= argc) throw std::runtime_error("missing value for " + key);
      const std::string value = argv[++i];
      if (key == "-o" && action == "transform" && output.empty()) output = value;
      else if (key == "--report" && reportPath.empty()) reportPath = value;
      else if (key == "--function" && action != "transform" && function.empty()) function = value;
      else if (key == "--seed" && action == "transform" && !seedSet) { seed = number(value); seedSet = true; }
      else if (key == "--control-flow" && action == "transform" && !controlFlowSet) {
        if (value != "none" && value != "split-scale") throw std::runtime_error("unknown control-flow candidate");
        options.controlFlow = value; controlFlowSet = true;
      }
      else if (key == "--algorithm" && action == "transform" && !algorithmSet) {
        if (value != "popcount8-serial" && value != "popcount8-swar") throw std::runtime_error("unknown candidate algorithm");
        options.algorithm = value; algorithmSet = true;
      }
      else if (key == "--strategy" && action == "transform" && !strategySet) {
        if (value != "affine" && value != "xor" && value != "identity" && value != "independent" && value != "planned" && !csrd::limbBits(value))
          throw std::runtime_error("unknown representation strategy");
        options.strategy = value; strategySet = true;
      } else if (key == "--coverage" && action == "transform" && !coverageSet) {
        auto n = number(value); if (n > 100) throw std::runtime_error("coverage must be in 0..100");
        options.coverage = unsigned(n); coverageSet = true;
      } else if (key == "--objective" && action == "transform" && !objectiveSet) {
        if (value != "balanced" && value != "runtime" && value != "size") throw std::runtime_error("unknown planning objective");
        options.objective = value; objectiveSet = true;
      }
      else if (key == "--timeout-ms" && action != "analyze" && !timeoutSet) {
        auto n = number(value);
        if (n == 0 || n > 600000) throw std::runtime_error("timeout must be 1..600000 milliseconds");
        timeout = unsigned(n); timeoutSet = true;
      } else throw std::runtime_error("unknown or repeated option: " + key);
    }
    if (output.empty() && action != "analyze") throw std::runtime_error("an output/candidate file is required");
    if ((coverageSet || objectiveSet) && options.strategy != "planned") throw std::runtime_error("coverage/objective require --strategy planned");
    if (csrd::limbBits(options.strategy) && options.controlFlow != "none") throw std::runtime_error(options.strategy + " requires --control-flow none");
    options.timeoutMs = timeout;
    if ((action == "transform" && samePath(input, output)) ||
        (!reportPath.empty() && (samePath(input, reportPath) || (!output.empty() && samePath(output, reportPath)))))
      throw std::runtime_error("input, output and report paths must be distinct");
    csrd::TransformResult result;
    result.options = options;
    if (action == "transform") {
      if (!csrd::transform(input, seed, result, options)) {
        if (!reportPath.empty() && !result.inputHash.empty()) writeFile(reportPath, report(result, seed, action));
        return 1;
      }
      writeFile(output, result.source);
      result.outputWritten = true;
    } else if (action == "verify") {
      csrd::TransformResult candidate;
      if (!csrd::inspect(input, result) || !csrd::inspect(output, candidate)) return 1;
      result.outputHash = candidate.inputHash;
      result.candidateDependencies = candidate.dependencies;
      if (result.target != candidate.target) throw std::runtime_error("target mismatch");
      if (!function.empty()) result.decisions.erase(std::remove_if(result.decisions.begin(), result.decisions.end(),
        [&](const csrd::Decision &d) { return d.function != function; }), result.decisions.end());
      if (result.decisions.empty()) throw std::runtime_error("no selected function definitions");
      for (auto &d : result.decisions) {
        auto found = std::find_if(candidate.decisions.begin(), candidate.decisions.end(), [&](const csrd::Decision &other) { return other.function == d.function; });
        d.status = "checked";
        if (!d.region || found == candidate.decisions.end() || !found->region) {
          d.verification.status = "unsupported";
          d.verification.reason = !d.reason.empty() ? d.reason : "candidate function missing or unsupported";
        } else d.verification = csrd::verify(*d.region, *found->region, timeout);
        std::cerr << "csrd: " << d.function << ": " << d.verification.status << '\n';
      }
    } else {
      if (!csrd::inspect(input, result)) return 1;
      if (!function.empty()) result.decisions.erase(std::remove_if(result.decisions.begin(), result.decisions.end(),
        [&](const csrd::Decision &d) { return d.function != function; }), result.decisions.end());
      if (!function.empty() && result.decisions.empty()) throw std::runtime_error("selected function not found");
    }
    if (!reportPath.empty()) writeFile(reportPath, report(result, seed, action));
    else if (action == "analyze") std::cout << report(result, seed, action);
    if (action == "verify") {
      for (const auto &d : result.decisions) if (d.verification.status != "proved-under-model") return 3;
    }
    return 0;
  } catch (const std::exception &e) {
    std::cerr << "csrd: error: " << e.what() << '\n';
    return 2;
  }
}
