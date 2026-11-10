# P-code control-flow observer validation, 2026-11-10

## Result

The new observer recovered the previously unsupported **GCC O2 Jenkins original
in all five measured repeats**. Every answer passed the full-input C-SRD source
model check; every result-plus-one control produced a counterexample. The binary
is unchanged. This closes an observer coverage gap, not a protection result.

The two separately reserved validation shapes produced 16 reconstructed answers
across GCC/Clang O1/O2 and original/identity controls. Twelve passed full-input
verification. Four Clang recurrence answers remain **inconclusive** after the
standard grader and the previously validated checked-circuit replay. All 16
wrong-output proof controls were rejected. The adapter was frozen before these
observer results and was not tuned on them.

All 16 answers also matched their frozen original executables and independently
written arithmetic oracles on **2,112 inputs per build**, using GCC/Clang O0/O2
and Clang ASan/UBSan. That is 80 answer builds and 168,960 matching comparisons;
80 corrupted builds yielded zero matches in another 168,960 comparisons. These
finite checks do not resolve the four proof gaps or estimate a population-wide
false-positive rate. The trials contain five distinct answer artifacts, not 16
independent algorithms.

Implementation: `23f90d8`. The [specification](../docs/pcode-control-flow.md) and
[journal](../docs/journal/2026-11-10-pcode-cfg.md) record semantics, fixed bounds,
controls and the fixture correction. The
[machine-readable summary](pcode-cfg-evidence-20261110/summary.json) is generated
from preserved raw records by
[the summarizer](../experiments/summarize_pcode_cfg.py).

## Method and actual coverage

Schema 2 exports live operations in basic-block order and reciprocal, ordered
CFG edges. The adapter checks node/type/definition integrity, SSA dominance,
terminators, merge arities and exact incoming-edge association. Phi values are
read simultaneously from the predecessor state. Exact constants can select a
branch; otherwise both successors are expanded. Every explored path must return
within declared budgets before an answer is emitted. No sampled inputs prune
paths, and partial expansions are rejected.

| Validation shape and compiler | Build cells | Terminal paths in answer construction | Recovered C bytes | Full-input grade |
| --- | ---: | ---: | ---: | --- |
| Unsigned distance, Clang | 4 | 2 | 267 | 4 proved under model |
| Unsigned distance, GCC | 4 | 2 | 266 | 4 proved under model |
| Five-step recurrence, Clang | 4 | 1 | 1,209 | 4 inconclusive |
| Five-step recurrence, GCC | 4 | 32 | 8,454 | 4 proved under model |

GCC's original recurrence required 157 expanded block entries; its identity
version required 94. Both enumerate 32 terminal paths. The Clang O1 original
needed five fixed loop iterations; other Clang recurrence cells were straight
line. Clang's conditional arithmetic became a mask expression. These are
observations of specific builds, not general claims about either compiler.
Shorter recovered C did not imply easier grading in this experiment.

The observer receives only the binary, known symbol and public u32 ABI. Reference
source and the independent oracle are consulted after the answer is frozen.
Scalar payload widths remain 8/16/32 bits. Wide/vector operations, memory
effects, calls and general input-dependent loops remain outside this adapter's
contract. Source language coverage and the transformation engine did not change.
The separate reserved algorithm families were not opened.

## Repeated Jenkins resources

Five measured trials followed one excluded warmup, serially after all builds and
tests, on the recorded Linux ARM64 container with two guest CPUs. Each imported
a fresh Ghidra project; filesystem caches were not flushed. Each made one target
decompile request and zero chosen-input training queries. All six runs, including
warmup, passed their proof and corruption checks. The earlier development pilot
also passed but is excluded from these measurements.

| Quantity | Median | Observed range |
| --- | ---: | ---: |
| Whole observer wall time | 5.090 s | 5.086–5.367 s |
| Whole observer user + system CPU | 5.979 s | 5.772–6.008 s |
| Peak single-process RSS | 420.5 MiB | 380.4–426.8 MiB |
| Peak sampled aggregate process-tree RSS | 452.7 MiB | 405.4–663.5 MiB |
| Python reconstruction stage | 0.844 ms | 0.631–1.061 ms |
| Separate equivalence-grading wall time | 21.40 ms | 21.31–21.61 ms |

The reconstructed Jenkins answer is 1,098 bytes: four constant branch decisions,
six expanded block entries, one terminal path and 28 emitted statements. The
five repetitions produced one distinct answer artifact. Whole-observer costs
include Java/Ghidra startup and analysis; they are not human reconstruction time.
The Python stage includes reading the export JSON and writing candidate C.
Aggregate RSS sums sampled live-process RSS, can count shared pages more than
once and may miss peaks. No speedup ratio is computed against the old adapter,
which returned unsupported instead of completing reconstruction.

The old and new trials bind binary SHA-256
`efe9ce2da86b3548a9b559d9e67e8e935866adf2f805fab5636b24c0e9b50712`.
The five old unsupported statuses remain unchanged. New recovery does not turn
those old attempts into successes. No application runtime/size change or new
protection candidate was introduced here.

## Tests, unresolved grades and retained failures

All **19 CTest groups passed** on native macOS and Linux ARM64; Linux enabled the
real Ghidra integration. Wall times were 79.40 and 58.08 seconds during overlapping
test execution, not performance experiments. The new CFG tests include seven
valid graphs, universal source-model comparisons, a separate concrete interpreter,
compiler/sanitizer checks, wrong-output and wrong-edge controls, simultaneous
self-loop phi swaps, 22 malformed/effect controls and three expansion failures.

The validation-matrix pilot stopped before compiling/decompiling the recurrence:
the fixture used `i = i + 1u`, while the existing frontend requires `++i`. Its
eight completed distance build cells, failure report and rejected source are
retained. Correcting only that counter syntax produced a fresh successful
16-cell matrix; neither adapter rules nor the recurrence contract changed.

The four unresolved Clang grades represent two distinct saved mismatch queries.
The standard Z3 stage had 10 seconds per query. The existing circuit replay
used a five-second ABC budget and eight-second per-stage cap: all four remained
inconclusive. Its seven controls passed (five satisfiable incorrect cases and
two unsatisfiable valid rules). The replay preserved the original answers and
statuses. No new solver prototype or increased budget was fitted to these data.
Compiled execution checks were added after these grading failures and are
explicitly supplemental finite evidence.

## Reproduction and evidence

Build the tooling and run the regression suite:

```sh
cmake -S . -B build -G Ninja -DCMAKE_PREFIX_PATH=/usr/lib/llvm-18 -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
```

The measured runs used the documented `csrd-dev:ghidra` Linux ARM64 environment
with Ghidra 12.2, Clang 18.1.3 and GCC 13.3. The existing Docker recipe and pinned
dependencies are described in [the decompiler protocol](../docs/decompiler-audit.md).
Inside that container, mounted at `/work`, fresh validation can use:

```sh
python3 tools/run_matrix.py --matrix experiments/pcode-cfg-validation.json \
  --csrd build/csrd --compiler clang=clang-18 --compiler gcc=gcc --objdump llvm-objdump-18 \
  --strategies identity --inputs 128 --iterations 100000 --repetitions 3 \
  --output-dir experiments/runs/new-cfg-matrix
python3 tools/measure_effort.py --matrix-report experiments/runs/new-cfg-matrix/matrix.json \
  --csrd build/csrd --observer ghidra --headless "$CSRD_GHIDRA_HEADLESS" \
  --case unsigned_distance --case recurrence5 \
  --profile clang-O1 --profile clang-O2 --profile gcc-O1 --profile gcc-O2 \
  --variant original --variant identity --repetitions 1 --warmups 0 \
  --wall-budgets 60 --timeout-ms 10000 --output-dir experiments/runs/new-cfg-observer
python3 experiments/check_cfg_validation_answers.py \
  --matrix-report experiments/runs/new-cfg-matrix/matrix.json \
  --effort-report experiments/runs/new-cfg-observer/effort.json \
  --clang clang-18 --gcc gcc --output-dir experiments/runs/new-cfg-compiled-checks
```

Saved-query replay uses the unchanged
[circuit grading driver and pinned ABC build](circuit-grading.md#reproduce),
with the observer run as `--prior-run`. Repeated Jenkins recovery uses the frozen
matrix/verifier from the evidence, `--case jenkins_word --profile gcc-O2
--variant original --repetitions 5 --warmups 1`, and the same observer budgets.
Raw protocols contain all actual arguments and tool/source/artifact hashes.

The [evidence index](pcode-cfg-evidence-20261110/index.json) binds the pilot,
failed and corrected matrices, reserved validation, circuit replay, compiled
checks, repeated recovery, tests and frozen inputs. Archives retain exact file
bytes, with per-file manifests. Transient Ghidra project databases are excluded
explicitly. The existing circuit-tool distribution is linked rather than
silently replacing its version. Historical reports have not been rewritten.

## Decision and next experiment

Use the new bounded CFG observer for subsequent development comparisons, while
retaining unknown grading and unsupported instructions as explicit gaps. This
increment demonstrates additional validated reconstruction coverage. It does
not establish that any representation increases analyst CPU, memory, queries,
human effort or confidentiality.

Next compare additional positional widths and selected algorithm variants under
the frozen correctness/observer protocol, reporting reconstruction effort,
application runtime and code size without cost cutoffs. Wide/vector modeling,
the four recurrence proof gaps, broader memory inference and independent C-level
verification remain separate tasks. No protection winner has been selected.
