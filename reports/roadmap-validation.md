# C-SRD 0.5 validation record — 2026-11-08

Implementation commit: `2e88ae8901bb760bcaa06b98221b96595636b315`.
The [source snapshot](roadmap-source-snapshot.json) records source hashes,
native/Linux executable hashes, tool versions and the Docker image digest.
These results describe bounded experimental M0–M5 implementations, not full
C11 support or a verified compiler theorem. Historical M1 reports are retained.

## Actual correctness results

| Environment | Full CTest groups | Arithmetic comparisons | Expanded-subset comparisons |
| --- | --- | --- | --- |
| macOS arm64, Debug frontend, LLVM 23.1.5 / Z3 5.3.3 | **9/9 passed**, 48.00 s | 12,450,220 in 20 configurations | 10,281,472 in 64 configurations |
| Ubuntu 24.04 arm64 container, Release frontend, LLVM 18.1.3 / Z3 4.8.12 | **9/9 passed**, 10.64 s | 8,092,643 in 13 configurations | 6,747,216 in 42 configurations |
| Standalone core, Release, frontend disabled | **2/2 passed**, 0.41 s | 1,998,026 numeric representation checks | Separate arithmetic contracts passed |

No differential mismatches were observed. Counts are executed comparisons,
including repeated inputs across variants/compiler configurations, not unique
input coverage. The expanded suite was rerun after adding source, candidate and
proof hashes to its report; it passed with the same counts. Do not add those
repeat runs to inflate coverage.

Native C output was tested with Apple Clang 17, Homebrew Clang 23.1.5 and GNU
GCC 16.2.0. Linux used Clang 18.1.3 and GNU GCC 13.3.0. Both suites cover `-O0`
and `-O2`; selected Clang runs use ASan/UBSan. Exact flags, seeds, status and
counts are in the JSON reports. Both environments use the same physical Apple
M5 host; this is not cross-architecture or independent-machine evidence.

Raw records:

* [Native CTest](roadmap-macos-ctest.log), [Linux Release CTest](roadmap-linux-release.log), [core tests](roadmap-core-tests.log).
* [Native arithmetic](roadmap-macos-differential.json), [Linux arithmetic](roadmap-linux-differential.json).
* [Native expanded subset](roadmap-macos-expanded-differential.json), [Linux expanded subset](roadmap-linux-expanded-differential.json), plus [native](roadmap-macos-expanded.log) and [Linux](roadmap-linux-expanded.log) rerun logs.
* [Native arithmetic contracts](roadmap-macos-rule-contracts.json), [Linux arithmetic contracts](roadmap-linux-rule-contracts.json).

The nine test groups cover numeric rules, CLI/rejection behavior, artifact-bound
translation validation and compiled counterexamples, planner optimality versus
small exhaustive search and heuristic coverage, algorithm candidates, defensive
evaluation, original arithmetic differential tests, expanded differential tests,
and symbolic rule contracts. The declaration/array/loop subset is deliberately
conservative. Tests include an unsafe changing array index, invalid shifts,
loop-index mutation, fresh-name collisions with inactive macros, nested loop
index bounds, and a non-equivalent algorithm replacement that must not overwrite
an existing output.

Every transformed differential-test function passed the reparsed emitted-C SMT
gate. Native numeric checks cover identity/affine/XOR behavior; symbolic checks
cover three affine identities, six XOR identities, five inverse-correctness
low-bit steps and six specific multiplier round trips. The deliberately faulty
addition rule produced a concrete counterexample. These have the scopes stated
in [verification](../docs/verification.md); no independent proof certificate or
mechanized proof of Clang/analyzer/emitter is claimed.

Two independently compilable examples and their full evidence are saved:
[affine calculate](calculate-v05-seed42.c), [calculate proof](calculate-v05-seed42.json),
[SWAR low-byte population count](popcount8-swar.c), [population-count proof](popcount8-swar.json).
Both examples also passed eight combined native Clang/GCC `-O0`/`-O2` warning-clean
compilations: [commands/results](roadmap-example-compilation.json).

The bounded template-synthesis experiment enumerated 27 triples for each of two
operations and recovered one universally validated rule for each: addition
coefficients `(1,1,-1)` and subtraction `(1,-1,1)`. These are known affine laws,
not new representations. [Search record](roadmap-synthesis.json),
[addition obligation](add-0.smt2), [subtraction obligation](subtract-0.smt2).

## Defensive and performance experiment

The native and Linux experiments ran sequentially, separately from the compiler
test suites. Each uses eight curated sources, original plus affine/independent/
planned variants (32 artifacts), two compiler families, `-O0`/`-O2`, seed 42,
81 boundary pairs plus 1024 random pairs per split, and a held-out challenge.
Timing uses seven repetitions of one million calls per artifact, with randomized
variant order, warmup, precomputed inputs and observable checksums. Compilation
and standalone verification are timed separately. No CPU pinning/frequency
control or statistical significance claim is made.

Full results: [native evaluation](roadmap-macos-evaluation.json) and
[Linux evaluation](roadmap-linux-evaluation.json). Generated C, obligations,
objects, LLVM IR and drivers remain in `experiments/runs/v05-macos/` and
`experiments/runs/v05-linux/` (ignored build artifacts). The JSON reports contain
all raw timing samples, hashes and metrics needed to assess these observations;
the commands below regenerate artifacts.

Across all eight compiler/optimization configurations, discovery fingerprints
produced the same pairwise confusion counts:

| Split | True positive | True negative | False positive | False negative | Pairs |
| --- | --- | --- | --- | --- | --- |
| Discovery | 96 | 368 | **32** | 0 | 496 |
| Held-out, including the explicit challenge | 96 | 400 | 0 | 0 | 496 |

The 32 false matches involve the rare-input negative control and its variants.
This demonstrates why finite fingerprints do not prove equivalence. The manual
challenge resolves that specific difference; the zero error count on this small
curated split is not a general recognition-accuracy result. Artifact pairs are
correlated and must not be treated as 496 independent benchmark programs.

Summed conversion events over the eight sources were 18 for affine, 42 for
independent and 16 for planned. Those strategies have different encoded-coverage
choices; the counts alone do not prove a fair universal planning advantage.
No head-to-head comparison with Tigress or other prior systems was performed.

Observed `-O2` results for planned variants, each relative to its own original:

| Compiler/environment | Range of median runtime ratios | Range of text-size ratios | Byte-identical code sections |
| --- | --- | --- | --- |
| Clang 23.1.5 / macOS | 1.000–1.567 | 1.000–7.000 | 6/8 |
| GCC 16.2.0 / macOS | 0.999–1.506 | 1.000–7.000 | 4/8 |
| Clang 18.1.3 / Linux | 0.989–1.531 | 1.000–6.500 | 6/8 |
| GCC 13.3.0 / Linux | 0.658–1.494 | 1.000–7.000 | 4/8 |

These ranges are measured observations, not confidence intervals or speedup
claims. Tiny kernels, call/harness overhead, scheduling and code layout influence
timings; identical code can still have different measured times. Affine variants
had identical code bytes to originals in 7/8 cases under each Clang at `-O2`.
Source differences therefore cannot stand in for machine-code differences.
Code sizes are object code sections, including padding, not executable sizes.

## Reproduction commands

Use the build/dependency instructions in [README](../README.md). Native validation:

```sh
cmake -S . -B build -G Ninja -DCMAKE_PREFIX_PATH=/opt/homebrew/opt/llvm -DCMAKE_BUILD_TYPE=Debug
cmake --build build -j4
ctest --test-dir build --output-on-failure
python3 tests/differential/expanded.py --csrd build/csrd --report build/expanded-differential.json
python3 tools/evaluate.py --csrd build/csrd --output-dir experiments/runs/reproduce-macos \
  --compiler /opt/homebrew/opt/llvm/bin/clang --compiler gcc-16 \
  --objdump /opt/homebrew/opt/llvm/bin/llvm-objdump
```

Linux Release and evaluation:

```sh
docker build -f tools/Dockerfile -t csrd-dev:roadmap .
docker run --rm -v "$PWD:/work" csrd-dev:roadmap sh -c \
  'cmake -S . -B build-linux-release -G Ninja -DCMAKE_PREFIX_PATH=/usr/lib/llvm-18 -DCMAKE_BUILD_TYPE=Release && cmake --build build-linux-release -j4 && ctest --test-dir build-linux-release --output-on-failure'
docker run --rm -v "$PWD:/work" csrd-dev:roadmap python3 tools/evaluate.py \
  --csrd build-linux-release/csrd --output-dir experiments/runs/reproduce-linux \
  --compiler clang-18 --compiler gcc --objdump llvm-objdump-18
```

The Docker recipe uses package repositories rather than pinned package files;
the recorded image digest identifies this run, while future rebuilds can have
different dependencies. Exact wall-clock timings and solver timeout outcomes
are not reproducible constants. The implementation, inputs, seeds, flags and
reported environment make the experiments repeatable and inspectable.

## Failures fixed and remaining limits

Development exposed planner timeouts on a mixed loop graph, affine/XOR branch
proof timeouts, an unsupported tactic-parameter setting, unused-parameter warnings
after dead-region pruning, strict-Clang harness-indentation warnings, and a test
that incorrectly assumed a graph exceeded the heuristic threshold. Fixes were
deterministic heuristic fallback, a recorded two-path solver portfolio, removal
of the invalid setting, validated pure discarded reads, explicit harness braces,
and a larger threshold-regression fixture. Final tests above passed after these
corrections. A timeout remains inconclusive, never a proof.

CBMC, Frama-C and Alive2 are not installed/integrated; no results from them are
claimed. Hosted GitHub CI has been configured, not executed here. Strings,
escaping/mutable memory, calls, arbitrary loops, signed arithmetic and full C11
remain unsupported. The planner uses uncalibrated scalar costs and exact solving
only for small graphs. The corpus is small and both OS runs share hardware.

The next engineering task is an independent C-level validation backend with
explicit unwinding assertions, followed by a larger held-out benign corpus and
planner cost calibration. Novelty and the long-term research questions remain open.
