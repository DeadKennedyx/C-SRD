# Persistent per-function reconstruction costs

**The nibble variants increased native per-function decompiler CPU by
2.712–39.879 times baseline, while every measured function was still recovered
correctly under the source model.** This establishes a specific automated
analysis-cost increase. Its practical value depends on absolute cost,
application overhead and whether it generalizes.

This study separates automated analysis of a function from analyzer startup.
It uses the same 40 optimized binaries and semantic observer as the
[wide-value study](pcode-wide-values.md). It changes the measurement protocol,
not the representation or accepted C subset. No cost ceiling selects candidates.

## Question and apparatus

The earlier whole-observer CPU was about six seconds even when individual
function stages grew. Can persistent sessions expose that local cost, and how
does it compare with the application's runtime and size overhead?

Implementation was frozen at `54d3feaa15a4b3b8e032b9c05a220f14e24b0aca` before
the main run. The [technical specification](../docs/persistent-sessions.md) and
[journal](../docs/journal/2026-11-10-persistent-observer.md) define the question,
controls, pilots and measurement contract. The graph-export block and semantic
reconstruction modules remain those of the prior observer. Original C is
withheld during observation and used only by the separate grader.

Each of four development functions has original, identity, 16-bit, 8-bit and
4-bit implementations under Clang 18.1.3 and GCC 13.3 at O2, using the frozen
candidate seed 42. Three independent
sessions per cell are randomized in matched blocks with seed 731123. A session
starts a fresh JVM/import/native decompiler, records and excludes its first 32
requests, then measures five batches of 32 requests. Every request flushes the
decompiler interface cache and performs real analysis/export. Only stored
graphs/answers and subsequent grading are deduplicated. Python reconstruction
runs every matching request in a separate persistent process after Ghidra exits.

The guest is Linux ARM64 with two logical CPUs, Ghidra 12.2 and Java 25, in image
`sha256:880358a74512e1deac327db13818f10e5b0cf8538f3490996952b8d379541f00`.
The protocol pins the headless launcher, installed Ghidra JARs, native
decompilers and AARCH64 language files before results. Tests/builds finished
before resource collection. Other shared-host activity is not isolated.

External POSIX process clocks separate native, JVM/export and adapter CPU.
Process identity loss invalidates a phase; empty phases quantify overhead.
RSS uses 5 ms sampling and endpoints. It measures retained resident memory,
not per-request allocations or secrecy. Shared pages may be counted twice and
peaks may be missed. Direct native-call/adapter wall times and whole-session
reaping totals are retained separately. The latter include 192 requests and
cannot be compared directly with a historical one-request process total.

The primary summary takes each session's median of five per-request batch costs,
then pairs its candidate/original session within repetition. All three ratios
and their range are retained; 15 correlated batches are not treated as 15
independent trials. No significance claim or protection threshold is selected.

## Validation and pilots

All 24 CTest groups passed on macOS ARM64 and Linux ARM64, in 334.72 and 254.49
seconds. These correctness suites overlapped, so their durations are not a
performance comparison. The new tests cover frozen export correspondence,
CPU versus sleep, retained-memory growth, lost/reset counters, malformed phase
order/request counts and live cold/persistent reconstruction equivalence.
A final focused run added session-pair counting and preservation of unknown
grades: six tests passed on Linux; macOS passed with three Linux/live skips.
Across the full macOS suite, six subtests needed unavailable or unconfigured
Linux/live tooling and were skipped; Linux exercised those controls.

The initial fixture's final verification failed because the reference included
a signed `main`. The C verifier correctly rejected that unrelated interface;
moving the link harness to a separate file fixed the fixture. The failed source
and log remain available. An eight-cell pilot completed with unchanged recovered
C hashes, valid counters and zero native CPU in empty phases. A final two-cell
pilot validated the full resource-to-grade chain: one direct source proof, one
successful circuit follow-up, both wrong-output rejections and all replay
controls. Pilot costs are excluded from the main comparison.

```sh
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure

docker run --rm \
  -e CSRD_GHIDRA_HEADLESS=/work/experiments/runs/dependencies/ghidra_12.2_PUBLIC/support/analyzeHeadless \
  -v "$PWD:/work" -w /work csrd-dev:ghidra sh -c \
  'cmake --build build-linux-release --parallel 2 && ctest --test-dir build-linux-release --output-on-failure'
```

## Results and correctness

All **120 sessions completed**, with one continuous JVM/native/adapter identity
per session, no invalid counters and no RSS sample errors. The recorded process
clock resolution was 1 ns; that is a reported clock property, not a claim of
nanosecond measurement accuracy. Each stage executed **19,200 measured requests**
in 600 batches and **3,840 excluded initial requests**. Those are repetitions of
40 fixed build cells, not 19,200 independent programs or necessary queries for
one reconstruction.

The requests produced **33 distinct original/answer contracts**. Source grading
proved 25 and left eight inconclusive, covering 15,360 and 3,840 measured request
memberships respectively. All 33 output-plus-one mutations were refuted. The
separate circuit replay proved all eight unknown queries UNSAT; all eight
wrong-output and three arithmetic controls passed. Thus all 40 build cells and
all 33 distinct contracts were recovered correctly under the model, including
answers from initial requests. Historical unknown reports remain unchanged;
these final grades are derived, bound follow-up results. No answer required a
new semantic rule. There were no training input/output queries.

## Per-function CPU and application costs

The table reports medians across sessions. Ratios are medians of three matched
candidate/original pairs, so they need not equal ratios of the displayed absolute
medians. Application runtime ratios are reused from the same frozen build
matrix; the application was not retimed in this study.

| Function | Compiler | Byte native CPU | Nibble native CPU | Original → nibble native ms/request | Nibble application runtime |
| --- | --- | ---: | ---: | ---: | ---: |
| CRC32 byte | Clang | 1.620× | 3.470× | 1.695 → 5.882 | 4.108× |
| CRC32 byte | GCC | 10.819× | 29.223× | 0.216 → 6.740 | 4.154× |
| Jenkins word | Clang | 10.924× | 30.947× | 0.396 → 11.210 | 7.107× |
| Jenkins word | GCC | 15.901× | 39.879× | 0.266 → 10.615 | 7.774× |
| Morton16 | Clang | 1.096× | 2.712× | 1.685 → 4.391 | 1.147× |
| Morton16 | GCC | 2.483× | 3.907× | 0.292 → 1.142 | 1.363× |
| RGB weighting | Clang | 1.751× | 6.037× | 0.178 → 1.080 | 1.855× |
| RGB weighting | GCC | 1.836× | 5.214× | 0.169 → 0.880 | 1.916× |

Summed native/JVM/adapter CPU per request has paired median ratios of
**0.811–5.970× for bytes** and **1.226–10.977× for nibbles**. Individual stages can
move differently: original Clang CRC has an expensive vector/CFG adapter
expansion, so its larger nibble native cost does not produce a proportional
combined increase. The complete [40-cell table](persistent-evidence-20261110/cells.csv)
includes original, identity and 16-bit controls, every paired range, absolute
cost, direct wall times and frozen application/runtime/symbol-size measurements.

For Clang Jenkins, the stage breakdown is:

| CPU per request | Original | Nibbles | Paired median ratio |
| --- | ---: | ---: | ---: |
| Native decompiler | 0.396 ms | 11.210 ms | 30.947× |
| JVM/export | 1.335 ms | 6.327 ms | 4.850× |
| Python adapter | 0.093 ms | 1.788 ms | 19.266× |
| Combined | 1.782 ms | 19.347 ms | 10.783× |

The combined metric sums each batch before taking medians; separately displayed
stage medians need not add exactly. Its three paired combined ratios were
10.335–10.921×. Direct decompiler-call wall time rose from 0.701 to 18.767 ms;
that includes more than the native process CPU and is retained as a separate
metric. The application costs 7.107× its original runtime, and its function
symbol grows from 72 to 1,392 bytes in the frozen matrix.

These local increases refine the previous whole-process conclusion. The older
cold totals include startup/import and remained close to baseline; they did not
establish absence of a per-function cost. This experiment does establish
increased cost for this observer on these artifacts. It still reconstructs every
function automatically, with absolute native costs in milliseconds. No minimum
acceptable analysis delay or application-overhead ceiling has been chosen, so
no universal protection winner follows from these measurements.

## Memory, controls and warmup limits

Nibble native sampled-RSS paired medians span **1.022–1.522×** baseline. For Clang
Jenkins, native retained RSS is 5.75 → 8.75 MiB and adapter RSS is 18.50 → 22.57
MiB (1.220× paired). JVM RSS does not show a corresponding increase in that
cell: its paired median is 0.999×. These values describe resident analyzer
processes, not protected-program memory exposure or allocations per request.

Seven non-original cells are byte-identical controls. Across their 21 individual
pairs, native CPU ratios span 0.818–1.530× (median 1.008×), and combined CPU ratios
span 0.738–1.438× (median 1.016×). This observed noise cautions against treating
small ratios such as byte Morton/Clang's 1.096× as an established benefit. The
large Jenkins effects exceed the observed control spread, but three sessions
on a shared host do not justify population-level statistical claims.

Every empty phase recorded zero native CPU. Median empty-phase JVM CPU was
1.039 ms and adapter CPU 0.020 ms; background JVM work can occur without a native
request. These numbers are retained without subtracting them from measured
batches. Whole-session CPU outside all recorded phases was 5.978–9.900 seconds,
median 6.514 seconds. That remainder also includes collector/launcher and
between-phase work; it is not a pure measurement of startup.

A descriptive check of later batches found median last/first batch CPU ratios
of **0.695 for JVM**, **0.979 for native** and **0.996 for adapter**. JVM costs
continued to fall after the declared 32 initial requests. Thus the study measures
a specified warmed-session protocol, not established JVM steady state. The
[diagnostics](persistent-evidence-20261110/diagnostics.json) retain every trend,
identity check, identical-byte control and historical cold-cell distribution.
No outcome was removed or warmup length retuned after observing this result.


## Reproduction

The main resource command is:

```sh
caffeinate -i docker run --rm --name csrd-persistent-observer-20261110 \
  -v "$PWD:/work" -w /work csrd-dev:ghidra \
  python3 tools/measure_sessions.py \
  --prior-cold experiments/runs/pcode-wide-observer-20261110/effort/effort.json \
  --headless experiments/runs/dependencies/ghidra_12.2_PUBLIC/support/analyzeHeadless \
  --output-dir experiments/runs/persistent-observer-20261110
```

The resource run must finish before grading. Source grading uses the frozen
Linux C-SRD binary with a ten-second SMT budget for every distinct answer and
an output-plus-one negative control. Every unknown answer's saved query is
then replayed separately with the declared 30-second circuit solver and
35-second stage budget, negative controls and three arithmetic controls.
Grading time is never added to observer cost.

```sh
docker run --rm -v "$PWD:/work" -w /work csrd-dev:ghidra \
  python3 experiments/grade_session_answers.py \
  --sessions experiments/runs/persistent-observer-20261110/sessions.json \
  --output-dir experiments/runs/persistent-source-grades-20261110

python3 experiments/grade_session_queries.py \
  --grades experiments/runs/persistent-source-grades-20261110 \
  --circuit-tool build/csrd-query-circuit \
  --abc experiments/runs/solver-probes-20261110/abc-src/abc \
  --output-dir experiments/runs/persistent-query-grades-20261110

python3 experiments/summarize_sessions.py \
  --sessions experiments/runs/persistent-observer-20261110/sessions.json \
  --grades experiments/runs/persistent-source-grades-20261110 \
  --followup experiments/runs/persistent-query-grades-20261110 \
  --application-summary reports/positional-widths-evidence-20261110/summary.json \
  --output-dir experiments/runs/persistent-summary-20261110
```

Use new output directories for reruns. Archived commands retain their original
`/work` and native paths; restore those conventions or regenerate protocols.
The temporary macOS `caffeinate` wrapper only prevents idle host sleep.

## Retained evidence

The [validated summary](persistent-evidence-20261110/summary.json),
[per-session medians](persistent-evidence-20261110/session-medians.json),
[600 measured batches](persistent-evidence-20261110/batches.csv),
[initial/empty phases](persistent-evidence-20261110/calibration.csv),
[archive index](persistent-evidence-20261110/index.json),
[per-file hashes](persistent-evidence-20261110/file-manifests.json.gz),
[archive validation](persistent-evidence-20261110/archive-validation.json) and
[package hashes](persistent-evidence-20261110/sha256.json) retain every session,
CPU endpoint, RSS sample, distinct graph/answer, request membership, proof,
saved-query replay, negative control, pilot, failed fixture and source snapshot.
The original matrix/binaries, cold-process evidence and native circuit tools are
referenced by hash without rewriting or duplicating them. Transient Ghidra
project databases are excluded with hashes retained when present.
Packaging validated all **3,922 archived files** against their recorded hashes;
the new evidence package is approximately 10 MB, including readable summaries.

```sh
python3 experiments/diagnose_sessions.py \
  --sessions experiments/runs/persistent-observer-20261110/sessions.json \
  --summary-dir experiments/runs/persistent-summary-20261110

python3 experiments/archive_sessions.py \
  --development experiments/runs/persistent-development-20261110 \
  --sessions experiments/runs/persistent-observer-20261110 \
  --grades experiments/runs/persistent-source-grades-20261110 \
  --followup experiments/runs/persistent-query-grades-20261110 \
  --summary-dir experiments/runs/persistent-summary-20261110 \
  --output-dir reports/persistent-evidence-20261110
```

## Interpretation limits

These are repeated requests for the same function, not a whole-application
session, an unbiased corpus or a guarantee of steady-state JVM behavior. Cache
flushing does not prove that all internal caches are empty. JVM costs include
graph export, hashing, JIT/GC and other threads active during the interval;
adapter costs include C generation, hashing and metrics. Collector CPU is
excluded from phase process clocks, but its scheduling interference remains.
Raw within-session trends and empty-phase costs are available without an
assumed overhead subtraction.

Correctness grades are conditional on the admitted C model and trusted frontend,
Ghidra lifting, adapter and solvers. Repeated identical C hashes share a grade;
they are not independent correctness trials. Reconstructing equivalent C does
not mean recovering an algorithm name or the author's source. This increment
does not collect human comprehension times, runtime debugger/memory traces,
one-time observer-development costs or evidence from reserved algorithm families.

## Next engineering task

Declare a longer fixed warmup/batch comparison on development controls to check
how much the declining JVM stage changes combined ratios. Keep the current run
and every new condition; do not choose a favorable stabilization point after
seeing results. Then freeze the sampling protocol and test reserved families
without changing the observer based on their outcomes. These steps are tracked
as PROT-13 and PROT-12 in the [backlog](../docs/backlog.md).
