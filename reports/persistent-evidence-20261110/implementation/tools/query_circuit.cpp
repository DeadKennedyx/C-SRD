// Export saved bit-vector queries for an optional combinational checker.
// The checked circuit is an artifact; no C language support is added here.
#include <z3++.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace {
namespace fs = std::filesystem;
struct Gate { std::string name; std::vector<std::string> inputs; z3::expr native; };
struct Network {
  z3::context &ctx;
  std::map<unsigned, std::string> names;
  std::vector<std::string> inputs;
  std::vector<Gate> gates;
  explicit Network(z3::context &c) : ctx(c) {}
  std::string collect(const z3::expr &e) {
    auto found = names.find(e.id());
    if (found != names.end()) return found->second;
    if (!e.is_app() || !e.is_bool()) throw std::runtime_error("lowering did not produce a Boolean DAG");
    if (names.size() >= 200000) throw std::runtime_error("Boolean node budget exceeded");
    std::vector<std::string> arguments;
    z3::expr_vector wires(ctx);
    for (unsigned i = 0; i < e.num_args(); ++i) {
      arguments.push_back(collect(e.arg(i)));
      wires.push_back(ctx.bool_const(arguments.back().c_str()));
    }
    const auto name = "wire_" + std::to_string(names.size());
    names.emplace(e.id(), name);
    if (e.decl().decl_kind() == Z3_OP_UNINTERPRETED && e.num_args() == 0) inputs.push_back(name);
    else gates.push_back({name, arguments, e.decl()(wires)});
    return name;
  }
};

void inspect(const z3::expr &e, std::set<unsigned> &seen) {
  if (!seen.insert(e.id()).second) return;
  if (seen.size() > 100000 || !e.is_app()) throw std::runtime_error("query requires a bounded quantifier-free DAG");
  if (!e.is_bool() && !(e.is_bv() && e.get_sort().bv_size() <= 64))
    throw std::runtime_error("only Boolean and bit-vector sorts of at most 64 bits are supported");
  if (e.decl().decl_kind() == Z3_OP_UNINTERPRETED && e.num_args())
    throw std::runtime_error("uninterpreted function calls are unsupported");
  for (unsigned i = 0; i < e.num_args(); ++i) inspect(e.arg(i), seen);
}

z3::expr lower(z3::context &ctx, const fs::path &input) {
  if (fs::file_size(input) > 8 * 1024 * 1024) throw std::runtime_error("query file budget exceeded");
  auto assertions = ctx.parse_file(input.c_str());
  if (assertions.size() != 1) throw std::runtime_error("exactly one mismatch assertion is required");
  std::set<unsigned> seen; inspect(assertions[0], seen);
  z3::goal goal(ctx); goal.add(assertions[0]);
  z3::params params(ctx); params.set("som", true);
  auto result = (z3::with(z3::tactic(ctx, "simplify"), params) & z3::tactic(ctx, "bit-blast"))(goal);
  if (result.size() != 1) throw std::runtime_error("lowering produced multiple subgoals");
  auto root = ctx.bool_val(true);
  for (unsigned i = 0; i < result[0].size(); ++i) root = root && result[0][i];
  return root;
}

void writeQuery(const fs::path &path, const z3::expr &formula) {
  z3::solver solver(formula.ctx()); solver.add(formula);
  std::ofstream out(path); out << solver.to_smt2();
  if (!out) throw std::runtime_error("cannot write SMT obligation");
}

void writeCircuit(const fs::path &path, const Network &net) {
  std::ofstream out(path);
  out << ".model query\n.inputs";
  for (const auto &input : net.inputs) out << ' ' << input;
  out << "\n.outputs output\n";
  for (const auto &gate : net.gates) {
    out << ".names";
    for (const auto &input : gate.inputs) out << ' ' << input;
    out << ' ' << gate.name << '\n';
    const auto n = gate.inputs.size();
    // The output is a named identity gate, represented by a free Boolean wire.
    if (gate.native.is_const() && !gate.native.is_true() && !gate.native.is_false()) {
      if (n != 1) throw std::runtime_error("identity arity");
      out << "1 1\n"; continue;
    }
    switch (gate.native.decl().decl_kind()) {
    case Z3_OP_TRUE: out << "1\n"; break;
    case Z3_OP_FALSE: break;
    case Z3_OP_NOT:
      if (n != 1) throw std::runtime_error("not arity");
      out << "0 1\n"; break;
    case Z3_OP_AND: out << std::string(n, '1') << " 1\n"; break;
    case Z3_OP_OR:
      for (unsigned i = 0; i < n; ++i) { std::string row(n, '-'); row[i] = '1'; out << row << " 1\n"; }
      break;
    case Z3_OP_XOR:
      if (n != 2) throw std::runtime_error("xor arity");
      out << "01 1\n10 1\n"; break;
    case Z3_OP_EQ:
      if (n != 2) throw std::runtime_error("equality arity");
      out << "00 1\n11 1\n"; break;
    case Z3_OP_ITE:
      if (n != 3) throw std::runtime_error("selection arity");
      out << "11- 1\n0-1 1\n"; break;
    default: throw std::runtime_error("unsupported lowered Boolean operation");
    }
  }
  out << ".end\n";
  if (!out) throw std::runtime_error("cannot write circuit");
}

std::vector<std::string> words(const std::string &line) {
  std::istringstream input(line); std::vector<std::string> values; std::string value;
  while (input >> value) values.push_back(value);
  return values;
}
struct Table { std::string name; std::vector<std::string> inputs, rows; };
struct Parsed { std::vector<std::string> inputs; std::vector<Table> tables; };

// Independent reader for the small positive-cover BLIF grammar emitted above.
// No writer truth-table case is reused by this reader.
Parsed readCircuit(const fs::path &path) {
  if (fs::file_size(path) > 64 * 1024 * 1024) throw std::runtime_error("circuit file budget exceeded");
  std::ifstream input(path); if (!input) throw std::runtime_error("cannot open circuit");
  Parsed result; std::string line;
  bool model = false, inputs = false, outputs = false, ended = false;
  while (std::getline(input, line)) {
    auto fields = words(line); if (fields.empty()) continue;
    if (ended) throw std::runtime_error("data after end directive");
    if (fields[0][0] == '.') {
      if (fields[0] == ".model") {
        if (model || fields.size() != 2) throw std::runtime_error("invalid model header");
        model = true;
      } else if (fields[0] == ".inputs") {
        if (!model || inputs || outputs) throw std::runtime_error("invalid input header");
        inputs = true; result.inputs.assign(fields.begin() + 1, fields.end());
      } else if (fields[0] == ".outputs") {
        if (!inputs || outputs || fields.size() != 2 || fields[1] != "output")
          throw std::runtime_error("exactly the output wire is required");
        outputs = true;
      } else if (fields[0] == ".names") {
        if (!outputs || fields.size() < 2 || fields.size() > 1026 || result.tables.size() >= 200001)
          throw std::runtime_error("invalid or oversized gate header");
        result.tables.push_back({fields.back(), {fields.begin() + 1, fields.end() - 1}, {}});
      } else if (fields[0] == ".end") {
        if (!outputs || fields.size() != 1) throw std::runtime_error("invalid end directive");
        ended = true;
      } else throw std::runtime_error("unsupported circuit directive");
    } else {
      if (result.tables.empty()) throw std::runtime_error("truth row outside a gate");
      auto &gate = result.tables.back();
      if (gate.inputs.empty()) {
        if (fields.size() != 1 || fields[0] != "1") throw std::runtime_error("invalid constant row");
        gate.rows.push_back("");
      } else {
        if (fields.size() != 2 || fields[1] != "1" || fields[0].size() != gate.inputs.size() ||
            fields[0].find_first_not_of("01-") != std::string::npos)
          throw std::runtime_error("invalid positive-cover row");
        gate.rows.push_back(fields[0]);
      }
    }
  }
  if (!ended) throw std::runtime_error("missing end directive");
  return result;
}

void checkCircuit(const fs::path &path, const fs::path &directory, const Network &reference) {
  auto actual = readCircuit(path);
  if (actual.inputs != reference.inputs || actual.tables.size() != reference.gates.size())
    throw std::runtime_error("circuit interface or gate count differs from lowering");
  auto &ctx = reference.ctx;
  std::set<std::string> available(reference.inputs.begin(), reference.inputs.end());
  std::map<unsigned, unsigned> checked;
  std::vector<z3::expr> obligations; // Retain ASTs: ids must not be recycled.
  std::ofstream index(directory / "gate-checks.tsv"), definitions(directory / "bindings.smt2");
  z3::solver bindings(ctx);
  index << "gate\tobligation\n";
  for (unsigned i = 0; i < reference.gates.size(); ++i) {
    const auto &expected = reference.gates[i]; const auto &gate = actual.tables[i];
    if (expected.name != gate.name || available.count(gate.name)) throw std::runtime_error("gate order or driver mismatch");
    std::set<std::string> arguments(expected.inputs.begin(), expected.inputs.end());
    arguments.insert(gate.inputs.begin(), gate.inputs.end());
    for (const auto &name : arguments) if (!available.count(name)) throw std::runtime_error("forward or missing wire");
    // Local inputs are arbitrary and independent, including any extra wire the
    // artifact reads. Only universal unsat admits a gate; no sampled values.
    auto table = ctx.bool_val(false);
    for (const auto &row : gate.rows) {
      auto cube = ctx.bool_val(true);
      for (unsigned j = 0; j < gate.inputs.size(); ++j) {
        auto wire = ctx.bool_const(gate.inputs[j].c_str());
        if (row[j] == '1') cube = cube && wire;
        else if (row[j] == '0') cube = cube && !wire;
      }
      table = table || cube;
    }
    z3::expr_vector from(ctx), to(ctx);
    for (const auto &name : arguments) {
      from.push_back(ctx.bool_const(name.c_str()));
      to.push_back(ctx.bool_const(("local_" + std::to_string(to.size())).c_str()));
    }
    auto mismatch = expected.native != table;
    mismatch = mismatch.substitute(from, to);
    auto found = checked.find(mismatch.id()); unsigned obligation;
    if (found != checked.end()) obligation = found->second;
    else {
      obligation = unsigned(obligations.size()); obligations.push_back(mismatch);
      const auto filename = "obligation-" + std::to_string(obligation) + ".smt2";
      writeQuery(directory / filename, mismatch);
      auto solver = (z3::tactic(ctx, "simplify") & z3::tactic(ctx, "sat")).mk_solver();
      solver.set("timeout", 1000u); solver.add(mismatch);
      if (solver.check() != z3::unsat) throw std::runtime_error("gate contract did not prove: " + gate.name);
      checked.emplace(mismatch.id(), obligation);
    }
    index << gate.name << '\t' << "obligation-" << obligation << ".smt2\n";
    bindings.add(ctx.bool_const(expected.name.c_str()) == expected.native);
    available.insert(gate.name);
  }
  definitions << bindings.to_smt2();
  if (!index || !definitions) throw std::runtime_error("cannot write gate evidence");
  unsigned major, minor, build, revision; Z3_get_version(&major, &minor, &build, &revision);
  std::cout << "{\"status\":\"circuit-validated\",\"inputs\":" << reference.inputs.size()
            << ",\"gates\":" << reference.gates.size() << ",\"obligations\":" << obligations.size()
            << ",\"z3_version\":\"" << major << '.' << minor << '.' << build << '.' << revision << "\"}\n";
}
}

int main(int argc, char **argv) {
  try {
    if (argc < 2 || (std::string(argv[1]) == "export" ? argc != 4 : std::string(argv[1]) == "check" ? argc != 5 : true))
      throw std::runtime_error("usage: csrd-query-circuit export QUERY.smt2 NEW_DIRECTORY | check QUERY.smt2 CIRCUIT.blif NEW_DIRECTORY");
    const bool exporting = std::string(argv[1]) == "export";
    const fs::path directory = argv[exporting ? 3 : 4];
    if (!fs::create_directory(directory)) throw std::runtime_error("output directory must be new");
    z3::context ctx; auto formula = lower(ctx, argv[2]);
    Network network(ctx); const auto root = network.collect(formula);
    network.gates.push_back({"output", {root}, ctx.bool_const(root.c_str())});
    writeQuery(directory / "lowering.smt2", formula);
    if (exporting) {
      writeCircuit(directory / "circuit.blif", network);
      std::cout << "{\"status\":\"exported-not-validated\",\"inputs\":" << network.inputs.size()
                << ",\"gates\":" << network.gates.size() << "}\n";
    } else checkCircuit(argv[3], directory, network);
    return 0;
  } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
