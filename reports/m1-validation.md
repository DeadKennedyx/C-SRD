# M1 validation record — 2026-11-07

M0 and the smallest M1 transformer are implemented and tested. A real C11 file
is parsed with Clang LibTooling, eligible function bodies are transformed
automatically, intermediate arithmetic stays encoded, and generated C compiles
and passes differential tests. This record does not claim a verified compiler,
novel affine encoding, measured performance improvement or secrecy.

## Environment actually used

The starting repository was empty and not under Git. A `main` Git repository
was initialized. Initially only Apple Clang 17 was available; `/usr/bin/gcc`
was the same Apple compiler. CMake, LibTooling, GNU GCC and Z3 were absent.
Homebrew installed CMake, Ninja, LLVM/Clang, GNU GCC and Z3. A Linux development
container was then built from `tools/Dockerfile` and exercised locally.

| Environment | Tool versions |
| --- | --- |
| macOS arm64, Darwin 25.3.0 | Apple Clang 17.0.0 (clang-1700.6.4.2); Homebrew LLVM/Clang 23.1.5; GNU GCC 16.2.0; CMake 4.4.5; Ninja 1.13.2; Python 3.14.6; Z3 5.3.3 |
| Ubuntu 24.04 container, Linux aarch64 | LLVM/Clang 18.1.3; GNU GCC 13.3.0; CMake 3.28.3; Ninja 1.11.1; Python 3.12.3; Z3 4.8.12 |

CBMC, Frama-C and Alive2 were not installed or run. No remote GitHub CI job has
been run; the checked-in workflow is configured for Ubuntu 24.04 Debug/Release.
The local Linux run used Debug on aarch64, not the hosted x86_64 runner.

## Commands and actual outcomes

macOS build and final gate:

```sh
cmake -S . -B build -G Ninja -DCMAKE_PREFIX_PATH=/opt/homebrew/opt/llvm -DCMAKE_BUILD_TYPE=Debug
cmake --build build --parallel 4
CSRD_REQUIRE_BOTH_COMPILERS=1 ctest --test-dir build --output-on-failure
python3 tests/differential/run.py --csrd build/csrd --report reports/m1-differential.json
python3 tools/verify_rules.py --report reports/m1-rule-contracts.json
```

Linux build and final gate (the Dockerfile sets compiler discovery and requires
both families):

```sh
docker build -f tools/Dockerfile -t csrd-dev:m1 .
docker run --rm -v "$PWD:/work" csrd-dev:m1 sh -c \
  'cmake -S . -B build-linux -G Ninja -DCMAKE_PREFIX_PATH=/usr/lib/llvm-18 -DCMAKE_BUILD_TYPE=Debug && cmake --build build-linux --parallel 2 && ctest --test-dir build-linux --output-on-failure && python3 tests/differential/run.py --csrd build-linux/csrd --report reports/m1-linux-differential.json && python3 tools/verify_rules.py --report reports/m1-linux-rule-contracts.json'
```

| Check | Actual result |
| --- | --- |
| macOS CTest | **4/4 passed**, final gate 11.60 seconds |
| Linux CTest | **4/4 passed**, final gate 1.72 seconds |
| Library-only Release build | **2/2 passed**, frontend disabled; independent core and rule contracts |
| Representation tests | **1,988,549 checks passed** per run; identity and affine boundary/random tests, inverses and invalid multiplier rejection |
| CLI integration | **10 test methods passed** on both hosts, including a matrix of unsupported constructs, macro/directive preservation, input aliases, determinism, parse-error output preservation, nullary functions, aliases and CR-only line endings |
| macOS compiled differential report | **20 configurations, 12,450,220 comparisons, zero discrepancies** |
| Linux compiled differential report | **13 configurations, 8,092,643 comparisons, zero discrepancies** |
| Sanitizers | Clang `-O1 -fsanitize=address,undefined -fno-sanitize-recover=all`, seed 42, passed on Apple Clang 17, Homebrew Clang 23 and Ubuntu Clang 18 |
| Generic arithmetic SMT contracts | Addition, subtraction and scaling: all three counterexample queries **unsat** with both Z3 versions |
| Concrete multiplier round trips | Six listed odd multipliers: **unsat** for all input values and offsets, with both Z3 versions |
| Incorrect arithmetic control | Deliberately omitted offset correction: **sat**, real counterexample saved |

The differential population is 31 functions (29 transformed, two unchanged),
each evaluated on 81 boundary pairs and 20,000 pseudorandom pairs per
configuration. Seeds are 0, 42 and 18446744073709551615. Every compiler runs at
`-O0` and `-O2`; each Clang additionally runs the sanitizer configuration at seed
42. The same input population is reused across configurations, so these counts
are comparisons, not distinct exhaustive inputs. Timings are test costs only.

The explicit macOS differential JSON was recorded before the CR-only line-count
fix; that corpus uses LF endings and its generated artifacts are unaffected.
The final macOS CTest reran the complete suite after the fix. The Linux report
was generated after it. This distinction is retained rather than silently
presenting the earlier JSON as a later run.

The independent build was also executed with
`cmake -S . -B build-rules -G Ninja -DCSRD_BUILD_FRONTEND=OFF -DCMAKE_BUILD_TYPE=Release`,
followed by `cmake --build build-rules --parallel 4` and
`ctest --test-dir build-rules --output-on-failure` (2/2 passed, 0.53 seconds).

## Saved artifacts

* [Actual generated example](calculate-seed42.c) and [decision manifest](calculate-seed42.json).
* [macOS differential data](m1-differential.json) and [Linux differential data](m1-linux-differential.json).
* [macOS solver data](m1-rule-contracts.json) and [Linux solver data](m1-linux-rule-contracts.json).
* [macOS raw final CTest log](m1-macos-ctest.log) and [Linux raw final CTest log](m1-linux-ctest.log).
* [Final source/tool snapshot](m1-source-snapshot.json), with SHA-256 hashes of implementation, tests, benchmark, build and workflow files.

The example selects `a=1789947473`, `b=1549411197`, `inverse=846699185` at seed
42. Its manifest records three transformed operations, three boundary
conversions and zero internal conversions. Its verification field remains
`not-verified-for-this-input`; the artifact is covered by the separately
recorded fixture tests, and the CLI does not attach unsound automatic proof labels.

## Failures found and repaired

The first build used an incorrect three-argument `FixedCompilationDatabase`
constructor; it was corrected to the API supported by both tested LLVM versions.
The generated test corpus initially had unused locals under `-Werror`; its
return now consumes every local. Keyword-macro diagnostics were adjusted so
the conservative macro rejection can retain valid input unchanged.

The first Linux sanitizer link failed because `libclang-rt-18-dev` was missing
from the minimal container; it is now a listed setup/CI dependency. A final
review found that LF-only newline counting changed a later `__LINE__` for
CR-only source files. A compiled regression reproduced the discrepancy, and
using Clang's physical line map fixed it on both hosts. No known failing test
is suppressed in the final gate.

## What has not been established

The solver checks mathematical formulas, not the C++ analyzer, source emitter,
Newton inversion implementation for every parameter, or complete generated C.
Differential results are empirical and not exhaustive. No per-input translation
validator or whole-program memory/effect proof exists yet. The supported type
model, grammar and build-environment assumptions are in
[semantics](../docs/semantics.md).

There are no measurements of relative execution cost, binary size, CFG distance,
IR/machine-code diversity, algorithmic novelty or defensive recognition accuracy.
The current arithmetic generator is not evidence of generalization to unrelated
algorithms. No benchmark or verification result for unimplemented later modules
is claimed.

The next task is artifact-bound per-region bit-vector translation validation
with concrete counterexamples, followed by broader benign corpus coverage.
