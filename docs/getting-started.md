# Build, usage and reproduction

Run these commands from the repository root. The project specification is in
[README](../README.md); historical results are linked at the end.

## Build and test

Ubuntu 24.04:

```sh
sudo apt-get update
sudo apt-get install -y cmake ninja-build clang-18 llvm-18-dev libclang-18-dev libclang-cpp18-dev libclang-rt-18-dev gcc g++ python3 z3 libz3-dev
cmake -S . -B build -G Ninja -DCMAKE_PREFIX_PATH=/usr/lib/llvm-18 \
  -DCMAKE_C_COMPILER=clang-18 -DCMAKE_CXX_COMPILER=clang++-18 -DCMAKE_BUILD_TYPE=Debug
cmake --build build --parallel 4
CSRD_TEST_COMPILERS=clang-18:gcc CSRD_REQUIRE_BOTH_COMPILERS=1 \
  ctest --test-dir build --output-on-failure
```

macOS/Homebrew:

```sh
brew install cmake ninja llvm gcc z3
cmake -S . -B build -G Ninja -DCMAKE_PREFIX_PATH="$(brew --prefix llvm)" -DCMAKE_BUILD_TYPE=Debug
cmake --build build --parallel 4
CSRD_REQUIRE_BOTH_COMPILERS=1 ctest --test-dir build --output-on-failure
```

Use matching LLVM/Clang libraries, including `clang-cpp`. Z3 headers/library
are required for the frontend; its executable is used for standalone rule
contracts. Python tools use the standard library. Tests distinguish real GNU
GCC from Apple's `gcc` alias. Override compiler discovery with the colon-separated
`CSRD_TEST_COMPILERS`. The representation library can be built without Clang/Z3
libraries using `-DCSRD_BUILD_FRONTEND=OFF`.

## Transform, verify and analyze

```sh
build/csrd transform benchmarks/arithmetic/calculate.c -o build/calculate.c \
  --seed 42 --report build/calculate.json
build/csrd transform tests/fixtures/expanded.c -o build/planned.c \
  --strategy planned --coverage 50 --objective balanced --seed 42 --report build/planned.json
build/csrd verify tests/fixtures/expanded.c build/planned.c --report build/proof.json
build/csrd analyze build/planned.c --function mixed_regions
clang -std=c11 -pedantic-errors -Wall -Wextra -c build/calculate.c -o build/calculate.o
```

For `return 3u*(x+y)+11u`, affine mode encodes parameters, performs the three
operations in one representation and decodes the result. Its formulas are
`E(x)=a*x+b`, `E(x+y)=E(x)+E(y)-b` and
`E(k*x)=k*E(x)+(1-k)*b`, modulo 2^32, with odd `a`. Different deterministic
seeds change parameters. Fresh temporary names avoid source and macro names.

Implemented options:

| Command/option | Behavior |
| --- | --- |
| `transform input.c -o output.c` | Default uniform affine strategy; unsupported operations use legal ordinary representation boundaries |
| `--strategy identity\|affine\|xor\|independent\|planned` | Identity lowering; uniform supported affine/XOR operations; independent per-operation encoding; or graph planning |
| `--seed UINT64` | Deterministic representation parameters; default 0 |
| `--coverage 0..100` | Minimum percentage of live arithmetic/bitwise graph nodes encoded; planned only; default 50 |
| `--objective balanced\|runtime\|size` | Explicit proxy cost objective; planned only; no promise of actual speed or size improvement |
| `--algorithm popcount8-serial\|popcount8-swar` | Opt-in low-byte population-count candidate for unary functions; replacement must prove equivalent |
| `verify original.c candidate.c [--function NAME]` | Per-function equivalence query, including concrete counterexamples; no rewriting |
| `analyze input.c [--function NAME]` | Clang AST/CFG metrics and supported-subset diagnostics, JSON to stdout |
| `--report PATH` | JSON decisions, source/header hashes, proof obligations and counters |
| `--timeout-ms 1..600000` | Solver budget; default 10000; applicable to transform/verify |
| `--help`, `--version` | Implemented interface/version |

Exact planning is attempted on at most 16 choice nodes. Larger graphs or solver
timeouts use deterministic feasible local search, explicitly marked `heuristic`;
only certified optima are `optimized`. See [planning](planning.md).

Input/output/report aliases are rejected. Exit 0 means processing succeeded,
**not** that every function transformed: inspect coverage. Parse/translation
validation failure returns 1 without writing C; CLI/I/O errors return 2;
standalone verification with any non-proved function returns 3. Reports can
describe a failed candidate with `output_written: false`. No in-place rewriting.

## Supported subset

Pure functions with 32-bit `unsigned int`/`uint32_t` parameters, return and
locals; initialized declarations, assignment and one final return. Operations:
unsigned add/subtract, multiplication by literals, bitwise operators, literal
shifts 0–31, unsigned comparisons and ternary selections. Assignment-only
`if/else`, canonical loops with literal trip counts 0–32, and local literal
lookup arrays of 1–16 elements with statically bounded indexes are supported.

Pointers, calls, external effects, signed/wider arithmetic, general multiplication,
volatile/atomics, arbitrary loops, macros/directives within transformed functions,
and most C constructs remain unsupported. A rejected function stays unchanged
with a located diagnostic. See the exact [whitelist](semantics.md).

The host target and 32-bit integer model are part of the contract. Use compatible
headers and include paths when compiling output. Bodies preserve physical line
counts; internal comments/formatting are replaced. Output filenames can affect
untransformed `__FILE__` and include resolution. Compilation databases and custom
frontend flags are not implemented.

## Reproduce experiments

```sh
python3 tools/verify_rules.py --report build/rules.json
python3 tools/synthesize_rules.py --output-dir experiments/runs/synthesis
build/csrd transform benchmarks/algorithms/popcount8.c -o build/popcount8.c \
  --algorithm popcount8-swar --strategy planned --report build/popcount8.json
python3 tools/evaluate.py --csrd build/csrd --compiler clang-18 --compiler gcc \
  --objdump llvm-objdump-18 --output-dir experiments/runs/evaluation
```

Experiment output directories must be new. On macOS use `gcc-16` (or the
installed GNU version) and Homebrew's `llvm-objdump`. The evaluator records
fingerprints, false matches/misses, Clang AST/CFG metrics, LLVM instruction
histograms where available, object-code bytes, compiler costs and repeated
timings against each untransformed baseline at `-O0`/`-O2`. Raw artifacts remain
in the run directory. A deliberate one-input difference demonstrates that
fingerprints are not proofs. [Evaluation methodology](evaluation.md).

CTest records `build/differential.json`, `expanded-differential.json` and
`rule-contracts.json`. Both differential suites compile separate original and
variant objects with GCC/Clang, including Clang ASan/UBSan configurations.

```sh
docker build -f tools/Dockerfile -t csrd-dev:roadmap .
docker run --rm -v "$PWD:/work" csrd-dev:roadmap sh -c \
  'cmake -S . -B build-linux -G Ninja -DCMAKE_PREFIX_PATH=/usr/lib/llvm-18 -DCMAKE_BUILD_TYPE=Debug && cmake --build build-linux -j4 && ctest --test-dir build-linux --output-on-failure'
```

See the [current validation record](../reports/roadmap-validation.md), historical
[M1 results](../reports/m1-validation.md), [architecture](architecture.md),
[prior art](prior-art.md), [research questions](research-questions.md),
[threat model](threat-model.md) and [roadmap](roadmap.md).
