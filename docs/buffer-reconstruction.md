# Buffer reconstruction and runtime observation

This increment adds defensive observers for `buffers-u32-c11-v1`. It does not
add a new encoding or expand accepted input-C constructs. Existing scalar-only
observers and their historical protocols remain unchanged.

## Binary reconstruction

`tools/ghidra/ExportCSRDBuffers.java` receives a linked library, symbol and public
parameter types (`u` scalar uint32, `p` mutable uint32 pointer, `c` pointer to
const uint32). It receives no original source, seed, encoding multiplier or
memory footprint. It exports live P-code in basic-block order, with explicit
address-space identifier and pointer width. Ghidra's binary interpretation is
a trusted component; source validation does not prove the lifter.

`tools/pcode_memory.py` accepts schema 4, a single basic block, one final uint32
return, 32/64-bit pointers in byte-addressed memory, and exact 32-bit accesses at
fixed offsets 0..60 divisible by four. Pointer computations must resolve to a
public parameter plus a constant byte offset. Dynamic offsets, pointer escapes,
unknown effects/spaces and unsupported operations are rejected. In particular,
`PTRSUB` is field-offset addition, not arithmetic subtraction.

Each load materializes a fresh scalar at its actual position; every store stays
in sequence. The adapter does not assume distinct pointer arguments or reuse a
load across a possibly aliasing write. It retains stores even with a constant
return. Reconstructed C is independently checked against the original compiler-
preprocessed source using equal return and entire final memory. Return-plus-one
and last-store-plus-one controls are separately checked. Unsupported and inconclusive
grades remain explicit and are never counted as successful protection.

Example (Linux, with the existing development tools installed):

```sh
python3 tools/audit_buffer_reconstruction.py \
  --csrd build-linux/csrd \
  --headless experiments/runs/dependencies/ghidra_12.2_PUBLIC/support/analyzeHeadless \
  --compiler clang=clang-18 --compiler gcc=gcc \
  --source tests/fixtures/buffers.c \
  --source benchmarks/arithmetic/buffer_update.c \
  --repetitions 3 --output-dir experiments/runs/buffer-reconstruction
```

Profiles come from `experiments/matrix.json`. The default is Clang/GCC O0/O2;
repeat `--profile ID` to select ordinary, LTO or native-CPU profiles. PGO,
explicit cross-target and sanitizer profiles are excluded by this observer;
the correctness differential suite covers its own recorded profiles. Repeat
`--function NAME` to restrict the selected functions. Time budgets are
`--process-seconds` (default 120) and `--timeout-ms` (source grading, default
10000). Directories must be new. Original, identity, affine seed 42 and a byte-
identical original copy are included in every selected group.

All builds precede observer resource collection; all source grading follows it.
Variant order is randomized within matched function/profile/repetition blocks
using `--order-seed` (default 20261110). Retained measurements include:

* Ghidra cold process-tree wall time, CPU, sampled RSS, process peak RSS, page
  faults, switches and I/O; direct decompile wall time is also retained.
* Adapter process totals and reconstruction-only wall/CPU time, operation/load/
  store counts, emitted C and whole-process peak RSS.
* Separately timed verification, recovered/false/inconclusive/unsupported
  outcomes, corruption controls, tool/source/binary/implementation hashes.

Cold totals include launcher/JVM startup, import and analysis. They are not
native decompiler per-request CPU or steady-state costs. A single repetition is
a development observation, not an estimate of timing variation. The existing
persistent-session warmup-calibration issue remains relevant to stronger cost
claims. A successful reconstruction can still cost more; automatic recovery
and resource overhead must both be reported.

## Bounded runtime observation

`tools/observe_buffer_runtime.py` links a controlled caller to unchanged shared
objects from a completed reconstruction report. The seven declared benchmark
functions have independent finite oracles in `buffer_observation_cases.py`.
Every completed execution is checked for its return and all 64 caller words.
The protocol uses four training and eight heldout inputs, including scalar
boundary values, across identical, overlapping in both directions, and disjoint
pointer layouts. The default `--input-protocol basis-parity-v2` includes scalar
and memory perturbations that give each declared target an odd difference for
modular fitting. `--input-protocol seeded-v1` retains the earlier experiment,
which had insufficient parity variation for some original and transformed cases.
The heldout inputs are identical across these two development protocols.
Traces sample low32 general registers, 64 bytes at SP and the
64-word caller object before each instruction, up to the declared step budget.
SIMD values and all other memory are outside the sampling scope.

```sh
python3 tools/observe_buffer_runtime.py \
  --reconstruction-report experiments/runs/buffer-reconstruction/reconstruction.json \
  --function buffer_update --profile clang-O2 --profile gcc-O2 \
  --step-limit 512 --output-dir experiments/runs/buffer-runtime
```

It requires GDB with Python on AArch64/x86-64 little-endian Linux; container
debugging uses the existing documented ptrace configuration. LTO and instrumented
profiles are excluded from this runtime protocol. Repeat function/profile
filters, or omit them to use all recorded groups. `--gdb` selects the executable.

The separate fit worker learns invertible affine maps from training observations
and known intermediate labels, then scores the fixed maps against heldout
traces. It receives no representation parameters. Wrong permuted training
labels are a negative control. Every candidate map is retained, including
false and unavailable-location outcomes. Report literal presence separately
from inferred values and distinguish register, stack and caller-memory matches.
These location matches are correlated and are not independent experiments.

`tools/check_buffer_evidence.py` checks schedules, byte-identical controls,
artifact hashes, every reconstructed answer/proof association, trace membership,
finite oracle results and replayed fits after measurement. Historical orchestrator
sources can be supplied by recorded implementation snapshots; replay outputs
must still match exactly. `tools/validate_buffer_answers.py` compiles every
distinct recovered answer with selected compilers at O0/O2 and checks its return
and all caller words on the declared finite corpus. Both stages run separately
from resource collection. Deliberately tampered report copies are exercised by
`experiments/check_buffer_evidence_controls.py`.

This is a known-intermediate diagnostic, not discovery of arbitrary algorithmic
meaning. Finite heldout matches are evidence, not universal proofs. Caller
storage is ordinary by design, so recovery using its contents is an expected
boundary limitation, not evidence that affine parameters were secret. Trace
budgets, sampling gaps and observer failures cannot establish secrecy.

References: [Ghidra P-code semantics](https://ghidra.re/ghidra_docs/languages/html/pcodedescription.html),
[additional pointer operations](https://ghidra.re/ghidra_docs/languages/html/additionalpcode.html),
[buffer source contract](buffer-contract.md), [fourteen increments](coverage-increments.md),
[research journal](journal/2026-11-10-buffer-reconstruction.md).
