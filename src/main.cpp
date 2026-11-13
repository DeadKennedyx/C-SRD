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
    "       [--scope functions|private-regions] (private-regions: affine/identity integer declarations and assignments)\n"
    "       [--call-contracts contracts.json] (transform/analyze/verify, functions scope)\n"
    "       csrd verify original.c candidate.c [--function NAME] [--report report.json] [--timeout-ms UINT]\n"
    "         [--heap-observation events|successful-private] (verify only; default events checks allocation failures)\n"
    "         [--recursion-observation events|bounded-body] (verify only; bounded-body expands ranked self-calls)\n"
    "       csrd analyze input.c [--function NAME] [--report report.json] [--scope functions|private-regions]\n"
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
  if (v.integerComposition) {
    llvm::json::Array points;
    for(const auto &point:v.integerComposition->checkpoints) {
      llvm::json::Object mapping;
      for(const auto &[id,name]:point.encoded) mapping[id]=name;
      points.push_back(llvm::json::Object{{"source_statement_end",point.sourceEnd},
        {"candidate_statement_end",point.candidateEnd},{"encoded_values",std::move(mapping)}});
    }
    result["integer_composition"]=llvm::json::Object{
      {"invariant","temporary_u64 = zero_extend(a * source_bits + b modulo 2^source_width)"},
      {"multiplier_decimal",std::to_string(v.integerComposition->multiplier)},
      {"offset_decimal",std::to_string(v.integerComposition->offset)},
      {"checkpoints",std::move(points)}};
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
  if(!v.definedInputs.empty()) {
    result["defined_input_condition"]=v.definedInputs;
    result["defined_domain_smtlib"]=v.definedDomainObligation;
    result["defined_domain_sha256"]=csrd::sha256(v.definedDomainObligation);
    result["equivalence_scope"]="defined original inputs under declared C integer implementation model";
  }
  if (v.status == "counterexample") {
    llvm::json::Array inputs;
    for (auto x : v.inputs) inputs.push_back(x);
    result["inputs"] = std::move(inputs);
    result["original_output"] = v.originalOutput;
    result["candidate_output"] = v.candidateOutput;
    if(!v.integerInputs.empty() || !v.integerOutputs.empty()) {
      llvm::json::Array values,outputs;
      for(const auto &x:v.integerInputs) values.push_back(llvm::json::Object{{"id",x.id},{"raw_bits_decimal",x.bits},
        {"width",x.type.bits},{"signed",x.type.isSigned},{"c_type",x.type.spelling}});
      for(const auto &x:v.integerOutputs) outputs.push_back(llvm::json::Object{{"id",x.id},{"original_bits_decimal",x.original},
        {"candidate_bits_decimal",x.candidate},{"width",x.type.bits},{"signed",x.type.isSigned},{"c_type",x.type.spelling}});
      result["integer_inputs"]=std::move(values);result["integer_outputs"]=std::move(outputs);
      result["candidate_arithmetic_defined"]=v.candidateDefined;
    }
    if (!v.pointerBases.empty()) {
      llvm::json::Object bases;
      llvm::json::Array cells;
      for (const auto &entry : v.pointerBases) bases[entry.first] = entry.second;
      for (const auto &cell : v.memoryCells) cells.push_back(llvm::json::Object{
        {v.memoryAddressUnit == "byte" ? "byte_address" : "word_address", cell.address}, {"initial", cell.initial},
        {"original", cell.original}, {"candidate", cell.candidate}});
      result[v.memoryAddressUnit == "byte" ? "pointer_byte_bases" : "pointer_word_bases"] = std::move(bases);
      result["address_unit"] = v.memoryAddressUnit;
      result["memory_cells"] = std::move(cells);
      result["input_layout"] = "inputs contains scalar parameters only, in signature order; pointer bases are abstract addresses in address_unit";
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
    if (!d.privateFrames.empty() || result.options.scope == "private-regions") {
      f["semantic_model"] = "private-integer-frame-c11-v3";
      f["context_bindings_verified"] = d.privateContextVerified;
      llvm::json::Array frames, boundaries;
      for (const auto &frame : d.privateFrames) {
        llvm::json::Array inputs, outputs, inputIds, outputIds, declarations, bindings;
        for (const auto &id : frame.inputs) { inputs.push_back(frame.bindings.at(id).name); inputIds.push_back(id); }
        for (const auto &id : frame.outputs) { outputs.push_back(frame.bindings.at(id).name); outputIds.push_back(id); }
        for (const auto &id : frame.declarations) declarations.push_back(id);
        for (const auto &[id, b] : frame.bindings)
          bindings.push_back(llvm::json::Object{{"id", id}, {"name", b.name}, {"source_declaration", b.declaration},
            {"candidate_declaration", b.candidateDeclaration}, {"register_storage", b.registerStorage},
            {"c_type",b.type.spelling},{"value_bits",b.type.bits},{"signed",b.type.isSigned},{"boolean",b.type.isBool}});
        frames.push_back(llvm::json::Object{{"line", frame.line}, {"column", frame.column},
          {"bindings", std::move(bindings)}, {"declared_objects", std::move(declarations)},
          {"input_ids", std::move(inputIds)}, {"output_ids", std::move(outputIds)},
          {"long_bits",frame.longBits},{"plain_char_signed",frame.plainCharSigned},
          {"source_scope_begin", frame.parentBegin}, {"candidate_scope_begin", frame.candidateParentBegin},
          {"source_begin", frame.begin}, {"source_end", frame.end}, {"candidate_begin", frame.candidateBegin},
          {"candidate_end", frame.candidateEnd}, {"inputs", std::move(inputs)}, {"outputs", std::move(outputs)},
          {"operations", frame.original->operations}, {"operations_without_decoding", frame.emission.encodedOperations},
          {"boundary_conversions", frame.emission.boundaryConversions}, {"temporaries", frame.emission.temporaries},
          {"internal_conversions",frame.emission.internalConversions},{"ordinary_intermediates",frame.emission.ordinaryIntermediates},
          {"original_fragment_sha256", csrd::sha256(frame.originalText)},
          {"emitted_fragment_sha256", csrd::sha256(frame.emission.body)}, {"proof", proof(frame.verification)}});
      }
      for (const auto &boundary : d.privateBoundaries)
        boundaries.push_back(llvm::json::Object{{"line", boundary.line}, {"column", boundary.column},
          {"statement", boundary.statement}, {"reason", boundary.reason}});
      f["private_regions"] = std::move(frames); f["unchanged_boundaries"] = std::move(boundaries);
      f["operations_transformed"] = d.operations; f["boundary_conversions"] = d.conversions;
    }
    if (d.region) {
      const auto &region = *d.region;
      const bool records = std::any_of(region.buffers.begin(), region.buffers.end(),
        [](const auto &entry) { return entry.second.persistent || entry.second.recordBytes; });
      f["semantic_model"] = !region.streams.empty() ? "ordered-stdio-c11-v1" : region.ownedHeap ? "owned-heap-c11-v1" : region.guardedCalls ? "guarded-calls-c11-v2" : region.memoryControl ? "guarded-memory-c11-v1" : records ? "records-state-byte-c11-v1" : region.orderedCalls ? "ordered-calls-byte-c11-v1" : region.buffers.empty() ? "pure-u32-c11-v2" :
        region.extendedMemory ? "buffers-byte-c11-v2" : "buffers-u32-c11-v1";
      if (!region.buffers.empty()) f["byte_order"] = region.littleEndian ? "little" : "big";
      llvm::json::Array parameters;
      auto descriptor = [](const std::string &name, const csrd::Region::Buffer &buffer) {
        llvm::json::Object item{{"name", name}, {"kind", buffer.elementType + "-buffer"},
          {"element_bits", buffer.elementBits}, {"element_signed", buffer.elementSigned},
          {"read_only", buffer.readOnly}, {"minimum_elements", buffer.minimumElements},
          {"loads", buffer.loads}, {"stores", buffer.stores}};
        if (buffer.recordBytes) {
          llvm::json::Array fields;
          for (const auto &[field, offset] : buffer.fields)
            fields.push_back(llvm::json::Object{{"name", field}, {"byte_offset", offset}, {"kind", "uint32"}});
          item["record"] = llvm::json::Object{{"tag", buffer.recordTag}, {"union", buffer.isUnion},
            {"bytes", buffer.recordBytes}, {"alignment", buffer.recordAlignment}, {"fields", std::move(fields)}};
        }
        return item;
      };
      for (const auto &name : region.parameters) {
        const auto buffer = region.buffers.find(name);
        const auto target=region.functionPointers.find(name);
        if (region.streams.count(name)) parameters.push_back(llvm::json::Object{{"name",name},{"kind","file-stream"}});
        else if (target!=region.functionPointers.end()) {
          const auto &contract=region.calls.at(target->second);llvm::json::Array args;
          for (const auto &p:contract.parameters) args.push_back(llvm::json::Object{
            {"kind",p.kind},{"read_only",p.readOnly},{"minimum_elements",p.minimumElements}});
          parameters.push_back(llvm::json::Object{{"name",name},{"kind","function-pointer"},
            {"returns",contract.returnKind()},{"parameters",std::move(args)}});
        } else if (buffer == region.buffers.end()) parameters.push_back(llvm::json::Object{{"name", name}, {"kind", "uint32"}});
        else parameters.push_back(descriptor(name, buffer->second));
      }
      f["parameters"] = std::move(parameters);
      if (region.memoryControl) {
        f["control_assumptions"] = "structured branches and early returns; calls require guarded-v2 contracts; for loops start at zero with ++ and immutable scalar limits bounded by 32; live initialized prefixes for all admitted accesses; every loop exit and function return checked after finite expansion";
        f["observations_checked"] = "return, entire final shared memory, conditional effects and termination within admitted loop bounds";
      }
      if (records) {
        llvm::json::Array globals;
        for (const auto &[name, buffer] : region.buffers) if (buffer.persistent)
          globals.push_back(descriptor(name, buffer));
        f["persistent_objects"] = std::move(globals);
        f["state_assumptions"] = "equal incoming global state; original declarations and initialization retained by transform; globals are distinct complete objects; record pointers designate complete records, scalar pointers may alias fields; initialized live prefixes, no concurrent/asynchronous access; no record padding";
        if (!region.memoryControl) f["observations_checked"] = "return, entire final shared byte memory and ordered call prefixes; persistent state participates in shared memory";
      }
      if (region.orderedCalls) {
        llvm::json::Array calls;
        auto collectCalls=[&](auto &self,const auto &body)->void { for (const auto &s:body) {
          self(self,s.thenBranch);self(self,s.elseBranch);
          if (s.kind != csrd::Statement::Kind::Call) continue;
          const auto &spec = region.calls.at(s.callee);
          llvm::json::Array args;
          for (const auto &p : spec.parameters) {
            llvm::json::Object arg{{"kind", p.kind}};
            if (p.kind != "uint32" && p.kind!="file-stream" && p.kind!="int32-nonnegative") {
              arg["read_only"] = p.readOnly; arg["minimum_elements"] = p.minimumElements;
            }
            args.push_back(std::move(arg));
          }
          calls.push_back(llvm::json::Object{{"callee", s.indirectTarget.empty() ? s.callee : s.indirectTarget},
            {"contract_key",s.callee},{"indirect",!s.indirectTarget.empty()},{"recursive",s.recursiveCall},
            {"returns", spec.returnKind()},{"parameters", std::move(args)}, {"result_used", !s.name.empty()}});
        }};
        collectCalls(collectCalls,region.statements);
        f["ordered_calls"] = std::move(calls);
        f["call_contract_model"] = region.guardedCalls ? "opaque-guarded-v2" : "opaque-sequenced-v1";
        f["call_assumptions"] = "synchronous; no callbacks/reentry, nonlocal jumps, retained pointers, frame introspection, async effects or invalidation of caller buffers; matching environment choices";
        f["observations_checked"] = "callee, argument values, entire pre-call memory at each event; return and entire final memory";
        if (region.guardedCalls) {
          f["control_assumptions"]="structured branches and for loops bounded by 32; at most 64 expanded call sites and 4096 expanded statements per activation";
          f["call_assumptions"]="valid nonnull contracted function pointers; synchronous external callees with no callbacks/reentry, retained pointers, nonlocal jumps, frame inspection, async effects or invalidation of caller storage; only explicitly ranked self-recursion is admitted";
          f["observations_checked"]="executed call order, direct callee or indirect code identity, arguments and entire pre-call memory; return and entire final memory; recursion descent on every executed self-call";
        }
        if (!region.recursiveContract.empty()) {
          const auto &spec=region.calls.at(region.recursiveContract);
          f["recursion"] = llvm::json::Object{{"rank_parameter",spec.rankParameter},{"maximum_rank",spec.maximumRank},
            {"maximum_activation_depth",spec.maximumRank+1},{"proof_rule","induction on unsigned entry rank; child rank strictly smaller; caller rank bounded at every self-call; buffer contract closed under calls; self calls bind to this definition; sufficient C stack storage assumed"}};
          f["recursion_observation"]=result.options.recursionObservation;
          if (result.options.recursionObservation=="bounded-body") {
            f["semantic_model"]="bounded-recursion-body-c11-v1";
            f["observations_checked"]="return, entire final memory and external call trace; self-call events excluded from the required observations; proved by stronger ranked induction or complete checked body expansion";
          }
        }
        if (!region.streams.empty()) {
          f["call_contract_model"]="opaque-stdio-v3";
          f["stream_assumptions"]="standard C11 fgetc/fputc/fflush/feof/ferror/clearerr; valid nonnull caller-owned FILE objects with appropriate mode/orientation for each executed call; all library-managed storage including errno, FILE internals and setvbuf buffers disjoint from admitted user storage; equal incoming external state and coupled outcomes including EOF/errors; no interposition, callbacks/reentry, concurrency or asynchronous state changes";
          f["call_assumptions"]="stdio int results explicitly converted modulo 2^32; signed character arguments proved nonnegative and representable as int; handles and call order stay ordinary; stream opening/closing, null handles, stream aliases in locals and formatted I/O excluded";
          f["observations_checked"]="exact executed library calls, stream identities (including aliases), character arguments and pre-call user memory; return and entire final user memory; external stream effects preserved by identical call traces under coupled library behavior";
        }
      }
      if (region.ownedHeap) {
        llvm::json::Array handles;
        for (const auto &[name,buffer]:region.buffers) if (buffer.heap) handles.push_back(name);
        f["owned_heap_handles"]=std::move(handles);
        f["heap_assumptions"]="standard C11 malloc/calloc/realloc/free; coupled allocation outcomes; owned nonescaping uint32_t arrays of at most 32 elements; no allocator interposition or pointer-address observations; positive-size realloc; complete cleanup required on all returns";
        f["heap_obligations"]="nonnull live storage, bounds, initialized reads, valid base for free/realloc, no dangling-handle use or leaks; checked for source and candidate on every path";
        f["observations_checked"]="return, entire public memory, guarded allocator event order/arguments and public memory at events; private heap payload may differ";
        f["control_assumptions"]="structured branches and bounded for loops; no opaque calls; at most 64 expanded allocator events and 4096 expanded statements";
        f["heap_observation"]=result.options.heapObservation;
        if (result.options.heapObservation=="successful-private") {
          f["semantic_model"]="owned-heap-success-c11-v1";
          f["heap_assumptions"]="all executed allocations succeed; standard C11 allocator behavior; private nonescaping uint32_t arrays; no allocator interposition or pointer-address observations; positive-size realloc; complete cleanup";
          f["observations_checked"]="return and entire public memory under successful allocations; allocator events and allocation-failure behavior excluded";
        }
      }
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
  root["scope"] = result.options.scope;
  if (action=="verify") root["verification_heap_observation"] = result.options.heapObservation;
  if (action=="verify") root["verification_recursion_observation"] = result.options.recursionObservation;
  root["control_flow"] = result.options.controlFlow;
  root["objective"] = result.options.objective;
  root["coverage_percent"] = result.options.coverage;
  root["timeout_ms"] = result.options.timeoutMs;
  root["output_written"] = result.outputWritten;
  if (!result.options.callContractsHash.empty()) root["call_contracts_sha256"] = result.options.callContractsHash;
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
    std::string output, reportPath, function, contractsPath;
    uint64_t seed = 0;
    unsigned timeout = 10000;
    bool seedSet = false, timeoutSet = false, heapObservationSet = false, recursionObservationSet = false;
    csrd::PlanOptions options;
    bool strategySet = false, coverageSet = false, objectiveSet = false, algorithmSet = false, controlFlowSet = false, scopeSet = false;
    if (action == "verify") output = argv[3];
    for (int i = action == "verify" ? 4 : 3; i < argc; ++i) {
      const std::string key = argv[i];
      if (i + 1 >= argc) throw std::runtime_error("missing value for " + key);
      const std::string value = argv[++i];
      if (key == "-o" && action == "transform" && output.empty()) output = value;
      else if (key == "--report" && reportPath.empty()) reportPath = value;
      else if (key == "--function" && action != "transform" && function.empty()) function = value;
      else if (key == "--call-contracts" && contractsPath.empty()) contractsPath = value;
      else if (key == "--heap-observation" && action == "verify" && !heapObservationSet) {
        if (value != "events" && value != "successful-private") throw std::runtime_error("unknown heap observation contract");
        options.heapObservation=value;heapObservationSet=true;
      }
      else if (key == "--recursion-observation" && action == "verify" && !recursionObservationSet) {
        if (value!="events" && value!="bounded-body") throw std::runtime_error("unknown recursion observation contract");
        options.recursionObservation=value;recursionObservationSet=true;
      }
      else if (key == "--seed" && action == "transform" && !seedSet) { seed = number(value); seedSet = true; }
      else if (key == "--scope" && action != "verify" && !scopeSet) {
        if (value != "functions" && value != "private-regions") throw std::runtime_error("unknown transformation scope");
        options.scope = value; scopeSet = true;
      }
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
    if (options.scope == "private-regions" && ((options.strategy != "affine" && options.strategy != "identity") ||
        options.algorithm != "none" || options.controlFlow != "none"))
      throw std::runtime_error("private regions support affine/identity without algorithm or control-flow candidates");
    options.timeoutMs = timeout;
    if (!contractsPath.empty()) {
      if (options.scope != "functions") throw std::runtime_error("call contracts require functions scope");
      if (samePath(contractsPath, input) || (!output.empty() && samePath(contractsPath, output)) ||
          (!reportPath.empty() && samePath(contractsPath, reportPath)))
        throw std::runtime_error("call-contract path must be distinct from input/output/report");
      if (std::filesystem::file_size(contractsPath) > 1024 * 1024) throw std::runtime_error("call-contract file exceeds 1 MiB");
      std::ifstream stream(contractsPath, std::ios::binary);
      if (!stream) throw std::runtime_error("cannot read call contracts");
      const std::string contents((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
      options.callContracts = csrd::parseCallContracts(contents);
      options.callContractsHash = csrd::sha256(contents);
    }
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
      candidate.options = options;
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
        } else if ((options.heapObservation=="successful-private" && (d.region->ownedHeap || found->region->ownedHeap)) ||
                   (options.recursionObservation=="bounded-body" && (!d.region->recursiveContract.empty() || !found->region->recursiveContract.empty())))
          d.verification = csrd::verifyMemory(*d.region,*found->region,timeout,options.heapObservation=="successful-private",options.recursionObservation=="bounded-body");
        else d.verification = csrd::verify(*d.region, *found->region, timeout);
        std::cerr << "csrd: " << d.function << ": " << d.verification.status
                  << (options.heapObservation=="successful-private" ? " (successful private allocations only)" : "") << '\n';
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
