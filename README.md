# C-SRD — C Semantic Representation Diversification

Research project: **Verified Semantic and Representation Diversification for C Programs**.

C-SRD 0.1 is a working Clang LibTooling C-to-C prototype. It automatically
replaces eligible straight-line unsigned arithmetic with computation in an affine
representation, while retaining the function signature. Parameters are encoded
once, intermediate values stay encoded, and the return is decoded once.

This is experimental compiler research on benign programs. Affine encoding is
established prior art and provides no cryptographic confidentiality guarantee.
The implementation is differentially tested; the complete transformer is **not
formally verified**. See [verification](docs/verification.md) and the actual
[M1 validation record](reports/m1-validation.md).

## Build on Linux

Ubuntu 24.04, LLVM/Clang 18 development packages:

```sh
sudo apt-get update
sudo apt-get install -y cmake ninja-build clang-18 llvm-18-dev libclang-18-dev libclang-cpp18-dev libclang-rt-18-dev gcc g++ python3 z3
cmake -S . -B build -G Ninja -DCMAKE_PREFIX_PATH=/usr/lib/llvm-18 \
  -DCMAKE_C_COMPILER=clang-18 -DCMAKE_CXX_COMPILER=clang++-18 -DCMAKE_BUILD_TYPE=Debug
cmake --build build --parallel 2
CSRD_TEST_COMPILERS=clang-18:gcc CSRD_REQUIRE_BOTH_COMPILERS=1 \
  ctest --test-dir build --output-on-failure
```

Use the matching LLVM and Clang development libraries, including `clang-cpp`.
LLVM versions 18 and 23 are the initial validation targets. A compiler binary
alone does not supply LibTooling headers and libraries. Python tests use only the
standard library; the optional arithmetic contracts require the Z3 executable.

macOS with Homebrew:

```sh
brew install cmake ninja llvm gcc z3
cmake -S . -B build -G Ninja -DCMAKE_PREFIX_PATH="$(brew --prefix llvm)" -DCMAKE_BUILD_TYPE=Debug
cmake --build build --parallel 4
CSRD_REQUIRE_BOTH_COMPILERS=1 ctest --test-dir build --output-on-failure
```

Tests identify compiler versions and do not mistake Apple's `gcc` alias for GNU
GCC. Set `CSRD_TEST_COMPILERS` to a colon-separated list of compiler paths to
override discovery. Without LibTooling, independently test representations with
`cmake -S . -B build-rules -DCSRD_BUILD_FRONTEND=OFF` followed by build and CTest.

## Transform actual C

```sh
build/csrd transform benchmarks/arithmetic/calculate.c -o build/calculate.c \
  --seed 42 --report build/calculate.json
clang -std=c11 -pedantic-errors -Wall -Wextra -c build/calculate.c -o build/calculate.o
```

The input is:

```c
#include <stdint.h>
uint32_t calculate(uint32_t x, uint32_t y)
{
    uint32_t sum = x + y;
    return 3u * sum + 11u;
}
```

The tool parses this function, selects deterministic odd `a` and offset `b`, and
emits C with `E(x)=a*x+b` modulo 2^32. The output has three encoded operations,
two entry encodings and one exit decoding. The report records the actual
parameters, inverse, decisions and operation counts. An omitted seed is `0`.
There are no runtime libraries, helpers, generated identifiers, or hidden keys.

Only these CLI options exist: `transform input.c -o output.c`, `--seed`,
`--report`, `--help`, `--version`. In-place rewriting is rejected, including
symlink and hardlink aliases. A parsing error returns 1 and leaves existing
output untouched; CLI/I/O errors return 2. Successful processing returns 0 even
if all functions were skipped: inspect diagnostics or the report for coverage.
The report never upgrades a new input to "verified" just because a rewrite ran.

## Supported contract

The first region is a complete pure function: unqualified `uint32_t` parameters,
return type and automatic locals, initialized single-variable declarations,
simple assignments, parentheses, addition, subtraction and multiplication by a
literal, followed by one final return. Equivalent type aliases are accepted
when their canonical type is `unsigned int`. The frontend requires 32-bit
`int` and `unsigned int`; operations themselves must be unsigned 32-bit.
Nonnegative `int` literals may undergo the ordinary conversion to unsigned.

Functions with pointers, calls, globals, attributes, volatile/atomic access,
signed or wider arithmetic, general multiplication, casts, branches, loops,
macros, or directives are kept unchanged with a located diagnostic. The precise
whitelist and portability boundaries are in [semantics](docs/semantics.md).
Invalid C syntax is rejected by Clang before any output is written.

Bodies are printed compactly if necessary to preserve physical line counts
and later `__LINE__` expansions. Comments inside replaced bodies are removed.
Keep included headers available relative to the output location or use the
corresponding include search paths when compiling. Transformation-time custom
compiler flags and compilation databases are not yet supported.

## Reproduce validation

```sh
python3 tests/differential/run.py --csrd build/csrd --report build/differential.json
python3 tools/verify_rules.py --report build/rule-contracts.json
```

The differential runner builds original and transformed code separately, then
compares them on boundary pairs and seeded random inputs with GCC/Clang at `-O0`
and `-O2`. Clang also runs ASan/UBSan. It generates additional eligible programs
from a deterministic grammar, verifies transformation coverage, and includes
unchanged functions and a line-sensitive fixture. Timings in these reports are
test costs, **not** comparative runtime benchmarks.

For the Linux container recipe:

```sh
docker build -f tools/Dockerfile -t csrd-dev:m1 .
docker run --rm -v "$PWD:/work" csrd-dev:m1 sh -c \
  'cmake -S . -B build-linux -G Ninja -DCMAKE_PREFIX_PATH=/usr/lib/llvm-18 -DCMAKE_BUILD_TYPE=Debug && cmake --build build-linux --parallel 2 && ctest --test-dir build-linux --output-on-failure'
```

## Research status

M0 and the smallest M1 implementation are present. Arithmetic SMT contracts are
an initial M2 component. End-to-end translation validation, representation
selection, graph optimization, defensive recognition metrics, performance
comparisons and expanded C coverage remain future work. The independent
identity representation is a library baseline, not an additional CLI mode.

Read the [architecture](docs/architecture.md), [research charter](docs/research-charter.md),
[prior-art comparison](docs/prior-art.md), [questions](docs/research-questions.md),
[threat model](docs/threat-model.md), and [roadmap](docs/roadmap.md).
