# Ghidra reconstruction and control-flow experiment — 2026-11-09

Implementation: [`1d059db24726`](https://github.com/DeadKennedyx/C-SRD/commit/1d059db24726879aaf61a71f458aa1d103c48bfc).
Scoring-input hardening: [`aa5937f5124c`](https://github.com/DeadKennedyx/C-SRD/commit/aa5937f5124c0fff91300a5069429290853ac15a).
[Protocol](../docs/decompiler-audit.md), [journal](../docs/journal/2026-11-09-decompiler-control-flow.md),
[derived counts](decompiler-evidence-20261109/summary.json), [archive index](decompiler-evidence-20261109/index.json).

**Finding:** the parity split can preserve an instruction-sequence difference in
some optimized configurations. We have not demonstrated increased reconstruction
difficulty. The separate input/output observer recovered all tested arithmetic
variants, including the split candidates. Ghidra adapter gaps are inconclusive.

## What changed

* A real headless Ghidra adapter exports decompiled C and high P-code from linked
  binaries. A separate bounded interpreter reconstructs C and scores it against
  the reference with full-domain source-model verification. Failed/incomplete
  attempts and deliberately incorrect controls remain in the report.
* `--control-flow split-scale` partitions existing constant-scale computations by
  stored-operand parity. Intermediate encodings remain consistent; actual emitted
  C still has to validate before it is written. This is elementary modular
  algebra, not a claimed novel protection technique.
* The matrix adds paired split/unsplit controls and unrelated unary programs,
  fixed rotations, parity and bounded arithmetic. A separate x86-64 CI workflow
  runs Ghidra and frozen held-out checks.

## Actual correctness and build checks

| Run | Build cells completed | Failed cells | Unavailable profiles | Paired output comparisons |
| --- | ---: | ---: | ---: | ---: |
| Linux ARM64 development | 700 | 0 | 1 | 81,900 |
| Linux ARM64 held-out | 126 | 0 | 0 | 12,708 |

The missing profile requires native x86-64 execution. It is not counted as a
pass. The total is **826 build cells and 94,608 paired comparisons**. Repeated
inputs, seeds and configurations are included; these are not independent
algorithms or unique inputs. Every completed cell passed source/model and actual
preprocessed-build-input checks. Clang 18.1.3 and GCC 13.3.0 were used on Linux;
the extended profiles include O0/O1/O2/O3/Os/Oz/Og, LTO/ThinLTO, PGO, native CPU
and ASan/UBSan. Identity uses seed 0, affine/planned use seed 42.

The main full suites passed **13/13 CTest groups** on native macOS ARM64 (88.52 s,
Clang 23.1.5/GCC 16.2.0) and Linux ARM64 (45.06 s), with real Ghidra enabled on
Linux. The native suite explicitly skips live Ghidra/GDB when unavailable;
the group total is not a claim that skipped tests ran. The later adapter-only
tests cover all implemented expression rule categories, including narrow
extension and boolean operations. Logs: [native](decompiler-native-ctest.log),
[Linux](decompiler-linux-ctest.log), [adapter](decompiler-adapter-tests.log).
After final scoring-input hardening, the focused [live integration suite](decompiler-final-integration.log)
passed all six tests (26.155 s); it also checks frozen-input integrity and frontend
mismatch rejection. Native adapter checks passed five tests with one explicit
live-Ghidra skip (1.271 s).
The [rule report](decompiler-rule-contracts.json) records the all-u/k/c parity
identity as an unsatisfiable counterexample query. This proves that formula
under the bit-vector model, not the C++ transformer or a machine-code lifter.

[Hosted correctness CI](https://github.com/DeadKennedyx/C-SRD/actions/runs/42748202813)
passed Debug and Release, including the Release linked matrix and runtime
observer. [Hosted Ghidra CI](https://github.com/DeadKennedyx/C-SRD/actions/runs/42748202852)
passed on x86-64, including live integration, development and held-out matrices
and reconstruction runs. [Job metadata](decompiler-ci-1d059db.json) records those
completed steps; per-observation outcomes are in that run's uploaded artifacts.
The local counts in this report do not include CI cells.

## Compiled contribution

Each row compares a split candidate with its matching unsplit strategy/seed.
The metric is the NOP-excluded mnemonic sequence of `main` plus the surviving
named function. It does not compare all operands or prove machine-code identity.

| Development function | Eligible split cells | Same mnemonic sequence | Different sequence |
| --- | ---: | ---: | ---: |
| calculate | 75 | 40 | 35 |
| rotate_mix | 75 | 53 | 22 |
| bounded_arithmetic | 75 | 21 | 54 |

Parity has no eligible scale node: its 75 split-labelled cells are no-op controls,
not diversification successes. On held-out functions, 15 of 36 eligible split
cells differed; 21 had the same sequence. Byte sum has no eligible scale node.
All paired planned variants had identical graph representation labels, confirmed
by the summary script, so those pairs did not accidentally compare different plans.

For example, Clang O2 ARM64 `calculate` has four instructions in original/affine
form and 21 in the affine split form, including `csel`. GCC O2 does not retain a
mnemonic difference for that pair. The extra instructions do not establish
additional analysis effort. Only `bounded_arithmetic` had split candidates that
passed all required O2/LTO contribution and observed cost gates. The cost-based
selector chose **affine-42 without splitting** for that function. No candidates
were re-ranked on held-out measurements. Timings are short paired samples on a
shared host; some tests overlapped the development run. No isolated-performance,
statistical-significance or best-protection claim is made.

## Reconstruction outcomes

Ghidra 12.2 used Java 25 and a locally built Linux ARM64 native decompiler.
The official archive hash, protocol revisions, native/library hashes and command
logs are retained. Development and held-out observer jobs overlapped on the host;
their elapsed times are budget diagnostics, not comparable analyst-effort scores.

| Fixed observer outcome | Development | Held-out | Total |
| --- | ---: | ---: | ---: |
| Reconstructed C proved equivalent under source model | 22 | 18 | 40 |
| Unsupported by bounded P-code adapter | 11 | 18 | 29 |
| Known function symbol absent | 31 | 12 | 43 |
| Incorrect reconstruction / timeout / integration error | 0 | 0 | 0 |
| Total observed linked binaries | 64 | 48 | 112 |

All **40** reconstructed-result-plus-one controls produced counterexamples.
This demonstrates that the scoring gate rejected those deliberately wrong
functions. It does not estimate the false-match probability for arbitrary code.
The 40 proofs trust the source model and solver; Ghidra lifting itself is unproved.

Final review tightened the scoring input after the frozen experiment: the runner
now requires the matrix's exact C-SRD binary and scores against the original
build's hash-bound preprocessed `.i` input. This prevents header/target drift
between building and scoring. All 40 saved reconstructions were re-scored against
those frozen references and **all 40 still proved equivalent**. No decompilation,
P-code reconstruction rule, candidate or held-out observation was changed.
The original reports and a separate frozen-reference rescoring archive are retained.

The adapter rejected exported control flow/merge nodes and 64-bit temporaries.
Some simple rotation baselines themselves contain such widened P-code, even
though their decompiled C is readable. LTO often removes, renames or inlines the
expected symbol. These gaps affect original programs too and **must not be scored
as protection wins**. There was no attempt to tune the observer after seeing the
held-out reconstruction data.

The independent black-box observer recovered all 175 development cells for each
of `calculate` and `bounded_arithmetic`, and all 42 held-out bounded-arithmetic
cells. It did not recover rotations, parity or byte sum, including their original
baselines. Those baseline failures are limitations of its fixed hypothesis library.

Functional fingerprint grouping reported no false matches or missed equivalences
in this small new corpus. Per development profile and arity group, the held-out
input scores were 42 true positives and 49 true negatives. Held-out unary groups
had the same counts; the single held-out binary family had 21 true positives and
no unrelated binary negative control. Do not infer a universal false-positive
rate or general recognition accuracy from these deliberately small groups.

## Failed pilot and evidence scope

The first development run completed 525 cells, then stopped when the planned
four-round mixed arithmetic/bitwise candidate timed out at a 10-second transform
proof budget. The candidate was not written. Its failed report, proof obligation,
stress benchmark and protocol snapshot are archived. Those cells are excluded
from the 826-cell final total. A pure arithmetic recurrence replaced that main
corpus entry before held-out evaluation; the mixed stress files remain available.
The revised driver forwards its 30-second timeout to transformation as well as
build-input verification. This is a recorded scope revision, not a passed test
of the more complex loop.

## Reproduce

Build using [the container instructions](../docs/decompiler-audit.md). In the
following commands, `build/csrd` denotes the binary built inside that Linux
container, and `analyzeHeadless` is the pinned Ghidra launcher on PATH. Run in
the same `/work` namespace to preserve report paths.

```sh
ctest --test-dir build --output-on-failure
python3 tools/verify_rules.py --report build/rules.json
python3 tools/run_matrix.py --csrd build/csrd --tier extended \
  --compiler clang=clang-18 --compiler gcc=gcc --objdump llvm-objdump-18 \
  --profdata llvm-profdata-18 --case calculate --case rotate_mix --case parity \
  --case bounded_arithmetic --control-flows none split-scale --seeds 42 \
  --inputs 32 --iterations 100000 --repetitions 3 --output-dir build/development
python3 tools/run_matrix.py --csrd build/csrd --tier holdout \
  --compiler clang=clang-18 --compiler gcc=gcc --objdump llvm-objdump-18 \
  --profdata llvm-profdata-18 --case rotate_mix_heldout --case bounded_arithmetic_heldout \
  --case byte_sum_heldout --control-flows none split-scale --seeds 42 \
  --inputs 32 --iterations 100000 --repetitions 3 --selection build/development/matrix.json \
  --output-dir build/heldout
python3 tools/audit_decompiler.py --csrd build/csrd --headless analyzeHeadless \
  --matrix-report build/development/matrix.json --profile clang-O2 --profile gcc-O2 \
  --profile clang-O2-lto --profile gcc-O2-lto --variant original --variant identity \
  --variant affine-42 --variant affine-42-split-scale --output-dir build/ghidra-development
python3 tools/audit_decompiler.py --csrd build/csrd --headless analyzeHeadless \
  --matrix-report build/heldout/matrix.json --profile clang-O3 --profile gcc-O3 \
  --profile clang-O3-thinlto --profile gcc-O3-lto --variant original --variant identity \
  --variant affine-42 --variant affine-42-split-scale --output-dir build/ghidra-heldout
```

Exact local directory names and settings are in the archived reports/protocol.
`experiments/summarize_decompiler.py` reproduces the descriptive summary from
those raw directories. `experiments/rescore_decompiler.py --report PATH` accepts
the saved observer reports (repeat the option for both), plus `--csrd PATH` and
`--output-dir NEW`, to reproduce the frozen-reference check without rerunning
Ghidra. The archive index binds compressed matrices, validated
inputs/proofs, protocol revisions, all 112 observed binaries and complete Ghidra
outputs. To limit repository size, only full linked-runtime disassembly command
stdout is omitted from matrix archives, with original hashes/lengths recorded;
all measured function instructions remain. Raw matrices, complete disassemblies
and all build products remain in ignored local `experiments/runs/` directories.

## Decision and next engineering task

Retain the split as an opt-in research candidate; do not promote it as demonstrated
software protection. Expand the independent observer to model bounded P-code
merges and wide intermediates, with explicit semantics and negative controls.
Then run a newly reserved corpus without tuning on these held-out observations.
Broader C memory/pointer support remains a separate contract and implementation task.
