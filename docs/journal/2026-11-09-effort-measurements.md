# Reconstruction effort measurement increment

## Observation and question, before running the new experiment

The previous audit measured structural survival, successful reconstruction and
application runtime. Its overlapping, single-attempt analyzer timings cannot
establish increased reconstruction effort. CPU, process-tree memory, observation
budget curves, blinded candidate grading and human task timing were missing.

Question: under a fixed observer and matched build, does a diversified candidate
require more resources to produce a correct reconstruction, or reduce recovery
success at a declared budget? The null hypothesis is no reproducible improvement.
The transformed program must continue to pass its correctness gates.

## Design decisions

Use repeated, serialized, randomized blocks with the original as the paired
baseline. Retain every outcome and raw sample. Freeze observer answers before
grading; charge the privileged reference checker separately. Run query and trace
budget sweeps. Separate complete recovery, wrong answers, budget exhaustion,
unsupported observer models and infrastructure errors. Record both individual
process high-water RSS and sampled simultaneous process-tree RSS with their
limitations. No aggregate protection score or selector change is planned.

Prepare an actual human task timer/submission ledger and a study protocol, but
report human effort as unassessed until participants perform the tasks. Synthetic
tests of the recorder are not participant data. Existing public examples form a
measurement pilot, not a newly held-out research corpus.

## Planned validation

Exercise real CPU-consuming children, memory allocation and group termination;
test false candidate scoring, budget accounting, paired statistics and session
timing. Run black-box, Ghidra and bounded runtime observers against saved,
validated Linux artifacts. Preserve hashes, tool versions, order, budgets and
raw evidence. Report small-sample intervals as exploratory and retain null
results. Record deviations and actual results below after execution.

## Pilot configuration, before execution

Fresh Linux Clang/GCC O2 validated builds of `calculate`, XOR and `rotate_mix`,
with original, identity, affine seed 42 and affine seed 42 plus split control.
Existing public examples are deliberately reused to validate instrumentation.
They do not constitute a newly reserved holdout. Five measured repetitions and
one excluded warmup per cell, serialized within each observer run.

- Black-box: calculate and XOR, both compilers, all four variants; 3/12/64
  queries and a 5-second outer budget. XOR supplies a deliberately ambiguous
  three-probe fit, with independent formal counterexample grading.
- Ghidra: calculate and rotation, both compilers, original/affine/split;
  1/30-second outer budgets, internal analysis/decompile limits 30/15 seconds.
  The rotation case retains known observer coverage gaps as a control.
- Runtime: calculate, Clang O2, original/affine/split; 3/4/8 training traces and
  1/4/16/64 instruction steps, 60-second outer budget. Sixteen held-out traces
  score frozen training fits. Human sessions remain unassessed.

CPU/RSS grid enforcement is exercised by real integration tests. The pilot
collects their uncapped costs; additional CPU/RSS sweeps are available through
the CLI. No threshold for declaring software protection is invented after
measurement. Any apparent speed/memory increase is exploratory on this host.

## Deviation during the pilot

All 144 Ghidra attempts (24 warmups, 120 measured) were collected, but the final
summary raised an exception on a timed-out trial whose answer was `null`. The
earlier tests retained timeout outcomes without modeling an absent answer. Fix
the summary and add both a null-answer regression and a real CLI experiment
whose 1 ms budget prevents the worker from writing an answer. Preserve the
original report and recompute **only statistics**, with separate implementation
hashes and provenance. Do not rerun or replace inconvenient observations. The
runtime sweep will use the corrected driver; no observer inference rule changed.

## Results and interpretation

The 30 fresh build cells pass validation and 5,264 original-versus-variant
differential comparisons. All 14 CTest groups pass on both native macOS and
Linux, including real GDB/Ghidra on Linux. After the summary fix, the seven-test
focused suite passes on Linux and passes with one Linux-only skip on macOS.

There are 540 measured observer attempts and 108 excluded warmups. Black-box:
200 correct reconstructions, 40 wrong three-query XOR fits; every version
recovers at 12/64 queries. Ghidra: 25 recoveries, 35 unsupported reconstructions,
60 one-second budget expirations. Comparable successful CPU ratios remain near
one; peak-RSS intervals are wide. Runtime: 135 held-out recoveries and 45
no-candidate outcomes, with all variants recovering at the same lowest tested
three-trace/four-observation point. Human data is still unassessed.

An increased instruction count has not supplied a general reconstruction
barrier in this pilot. The split version costs slightly more to trace at a
64-step setting, but the observer already succeeds at four observations. The
known target sum is also determined by the public output. Treat that example
as an exposure control. Do not optimize for unsupported Ghidra operations.

Meaningful next work is improving the independent adapter's coverage and
designing new held-out tasks with predeclared practical effect thresholds;
human claims require actual participants. The [result report](../../reports/reconstruction-effort.md)
links archived raw evidence, counterexamples, resource curves, uncertainty,
the recovered summary and exact commands. The corpus is a methodological pilot,
not a new general software-protection result.
