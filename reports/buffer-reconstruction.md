# Buffer reconstruction and runtime evidence

Status: reconstruction, revised runtime comparison and evidence audit complete.
No worthwhile protection advantage is established in this development corpus.
The [frozen evidence](buffer-observer-evidence-20261110/index.json) retains raw
artifacts, earlier protocols and an interrupted prototype; its archive checker
verified all 109,535 included files against their recorded hashes.

## What changed

The new observer reconstructs ordered uint32 loads/stores from a compiled
function supplied with a public pointer/scalar ABI. It preserves possible
aliases and load snapshots, and grades return plus entire final memory.
Unknown effects and out-of-contract operations remain unsupported. This closes
a measurement gap around the existing buffer transformer; accepted input-C
coverage and representation laws are unchanged.

See [protocol and commands](../docs/buffer-reconstruction.md),
[meaningful prototypes/deviations](../docs/journal/2026-11-10-buffer-reconstruction.md),
and the [fourteen-increment sequence](../docs/coverage-increments.md).

## Reconstruction result

The development comparison used Linux ARM64, Clang 18.1.3, GCC 13.3.0 and
Ghidra 12.2. Seven existing benign functions were built with each compiler at
O0/O2, using original, identity, affine seed 42 and an identical original copy.
Every group used all four variants, in randomized order. The source/seed were
withheld from the observer; source grading followed resource collection.

| Outcome | Actual result |
| --- | --- |
| Compiled function/profile/variant observations | 112, including 28 identical-copy controls |
| Recovered C answers proved under the buffer source model | 112/112 |
| Wrong-return/wrong-store controls rejected | 208/208 |
| Unsupported or inconclusive reconstructions | 0 in this corpus |
| Independently different functions | 7; variants and copies are correlated |
| Target execution queries for static reconstruction | 0; the observer reads the binary |

These are proofs of reconstructed C against the original C under
`buffers-u32-c11-v1`, not proofs of Ghidra's binary lifting or arbitrary C.
The source contract retains its valid-object, initialization, alignment,
lifetime and footprint assumptions. Whole-program behavior outside the
admitted function is not covered by these grades.

The cold-process comparison has **one observation per cell**. It is a development
measurement, not a calibrated steady-state cost study. Its Ghidra CPU totals
include startup/import/export and do not isolate native decompilation CPU.

| Paired ratio to original, across the 28 groups | Affine | Identical-byte control |
| --- | --- | --- |
| Cold process-tree CPU, range | 0.792–1.047 | 0.830–1.074 |
| Cold process-tree wall time, range | 0.851–1.054 | 0.905–1.079 |
| Sampled process-tree peak RSS, range | 0.643–2.055 | 0.600–1.608 |

The overlapping controls and single repetitions establish no worthwhile cost
increase. They also cannot rule out a smaller increase in native per-function
work. Affine direct decompile wall times were 10.7–23.8 ms; adapter computation
was 83.5–167.1 microseconds CPU in these cold attempts. Those scopes differ and
must not be added to claim human analysis time. RSS counts shared pages per
process and can miss peaks; a large RSS ratio is not hidden application data.

Application cost evidence from [the earlier buffer pilot](buffers-validation.md)
uses its recorded native compiler/build conditions. It is not a matched
application-cost denominator for this Linux shared-library observer comparison.

## Runtime comparison

The initial smoke completed 192 Clang O2 `buffer_update` executions. The observer
inferred both supplied intermediate targets for every variant/layout, including
affine. This is finite known-intermediate recovery with training labels; it is
not discovery of an unknown algorithm or a universal proof of the learned map.

An expanded run was interrupted after 1,448 recorded traces to correct growing
full-history report serialization. Its partial output and implementation are
retained. The second run completed 5,376 executions but recovered only 104/160
target/build/layout cases per variant. All 56 misses per variant came from
training labels with the same parity, preventing this fitter from constructing
an odd-difference inverse. Original and transformed programs had identical
misses. This was an observer input-design limitation.

The revised `basis-parity-v2` protocol perturbs the scalar and memory inputs
separately during training. Its eight heldout inputs are unchanged: this is
development validation, not a fresh generalization study.

| Revised runtime outcome | Actual result |
| --- | --- |
| Observation groups / target executions | 448 / 5,376 |
| Checked return and entire 64-word final memory | 5,376/5,376 match the independent oracle |
| Target/build/layout cases recovered | 160/160 for each of original, identity, affine and copied original |
| Fitted maps failing heldout validation / inconclusive maps | 0 / 0 |
| Permuted-training-label controls yielding validated maps | 0 |
| Cases recovered from registers / stack / caller memory | 160 / 104 / 144 per variant; overlapping categories |
| Instruction steps recorded | 100,656 across all four variants |

The affine runs required 39,696 instruction steps, versus 19,872 for original,
over the same 1,344 executions. Across the 112 matched groups, affine/original
ratios for debugger acquisition CPU were 0.943–1.225 (median 1.033); Python
loading/fitting CPU ratios were 0.914–2.667 (median 1.972). These fixed-order
development measurements include observer overhead. They show extra work in
this specific pipeline, with every supplied target still recovered. They do not
establish worthwhile practical protection, native application slowdown, human
analysis time or resistance to a different observer.

## Validation and limitations

The evidence audit replayed 112 reconstructed answers, 208 rejecting corruption
controls, both complete runtime studies and their fits. Nine tampered report
copies were rejected, covering missing attempts, mismatched artifacts, invented
proof/recovery status and changed training membership. A separate four-artifact
pilot checked the improved final-store mutation, rejecting all eight controls.
The earlier all-store mutation can cancel in some programs; a regression
preserves that counterexample to the original control design.

All 45 distinct recovered answers compiled with GCC and Clang at O0/O2 on both
macOS ARM64 and Linux ARM64: 180 builds and 8,640 return/full-memory comparisons
per host, 17,280 total, all passing. Those compiler checks used the earlier
seeded input protocol, retained verbatim in their reports.

Focused CTest groups `pcode_memory`, `buffer_runtime_observer`,
`persistent_sessions` and `reconstruction_effort` passed on both hosts. After
the control/input revisions, the two new observer groups passed again (eight
memory-adapter tests and four runtime-protocol tests per host). This is not a
claim that all 29 registered CTest groups were freshly executed. Optional live
session checks remained skipped unless their dependencies were configured.

Remaining measurement scope: calibrated persistent native decompiler CPU,
matched application runtime/size on these exact Linux artifacts, broader
compiler profiles, x86 execution, unseen algorithms and human reconstruction.
The affine technique is deferred as a protection candidate; coverage work can
continue without treating those missing measurements as a win.

## Reproduction

Commands were run with `/Users/admin/C-SRD` mounted as `/work` in the existing
`csrd-dev:ghidra` development image. Exact tool, compiler input, binary and
implementation hashes are retained in the raw reports.

```sh
docker run --rm -v "$PWD:/work" -w /work csrd-dev:ghidra \
  python3 tools/audit_buffer_reconstruction.py \
  --csrd build-linux/csrd \
  --headless experiments/runs/dependencies/ghidra_12.2_PUBLIC/support/analyzeHeadless \
  --compiler clang=clang-18 --compiler gcc=gcc \
  --source tests/fixtures/buffers.c --source benchmarks/arithmetic/buffer_update.c \
  --repetitions 1 --output-dir experiments/runs/buffer-reconstruction-development-20261110

docker run --rm --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \
  -v "$PWD:/work" -w /work csrd-dev:ghidra \
  python3 tools/observe_buffer_runtime.py \
  --reconstruction-report experiments/runs/buffer-reconstruction-development-20261110/reconstruction.json \
  --input-protocol basis-parity-v2 \
  --output-dir experiments/runs/buffer-runtime-development-20261110-v3

docker run --rm -v "$PWD:/work" -w /work csrd-dev:ghidra \
  python3 tools/check_buffer_evidence.py \
  --reconstruction-report experiments/runs/buffer-reconstruction-development-20261110/reconstruction.json \
  --runtime-report experiments/runs/buffer-runtime-development-20261110-v3/runtime.json \
  --runtime-report experiments/runs/buffer-runtime-development-20261110-v2/runtime.json \
  --output experiments/runs/buffer-observer-tests-20261110/evidence-check-v3.json
```

Use new output directories when reproducing. The historical paths above already
contain results and are never overwritten. No hosted CI or x86 execution result
is claimed.

The [machine-readable summary](buffer-observer-evidence-20261110/summary.json)
binds its source reports by SHA256. `experiments/summarize_buffer_observers.py`
recomputes the tables; `experiments/archive_buffer_observers.py` packages and
checks the evidence. Restore archives at the repository root to retain their
original relative paths; Linux reports use `/work` inside the development image.
