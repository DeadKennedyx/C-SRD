# Bounded buffers: ordered memory alongside encoded scalars

Stage: contract, implementation and validation. Starting revision: `9ba06de`.
This initial entry is prospective; results will be appended after execution.

## Observation and hypothesis

The pure graph prunes work not reaching the return and merges pure branches.
Reusing that graph for stores without effect dependencies would be unsound.
The first prototype therefore keeps memory statements ordered and reuses the
existing affine laws for scalar arithmetic between load/store boundaries.

Hypothesis: straight-line fixed-index accesses can retain arbitrary pointer
aliasing while preserving both returns and whole memory, with encoded scalar
intermediates and ordinary caller interfaces. This is a correctness/coverage
hypothesis, not a protection claim.

## Design choice and protocol

The [contract](../buffer-contract.md) specifies supported syntax, caller
preconditions, alias semantics, compiler profiles, seeds and negative controls.
All pointers share one symbolic memory; fresh per-pointer arrays would silently
assume disjointness. Reparse actual emitted C and compare complete post-states.
Keep the pure validation path unchanged and reject unsupported memory options.

This deliberately starts with literal indexes and straight-line arithmetic.
Dynamic indexing, branches, loops and calls need additional contracts rather
than implicit admission through the new pointer types. The published
[Tigress alias/design discussion](https://tigress.wtf/encodeData.html) informs
the boundary questions; no Tigress integration or code reuse is introduced.

CBMC was absent on the native PATH and in the existing roadmap container at
inspection. Investigate an independent bounded harness; record unavailable or
inconclusive outcomes separately. The [CBMC tutorial](https://diffblue.github.io/cbmc/cprover-manual/md_cbmc-tutorial.html)
describes pointer/bounds checks and unwinding assertions required for that path.

## First validation and independent-check prototype

The first implementation passed 12 focused controls and the native compiler
matrix: 88 build cells and 4,363,480 function/whole-buffer comparisons. The
existing profile catalog also supplied O1/Og/Oz/native and both sanitizer
families; PGO and cross-target profiles are explicitly not run by this harness.

Homebrew supplied CBMC 6.11.0 as a bottle. The first independent check used the
actual affine-42 `buffer_store` artifact, equal pointer offsets 0/0 and three
words. Default SAT exceeded its declared 30-second wall budget; the partial log
and report remain in `build/cbmc-buffer-pilot`. This is inconclusive, not a proof
or counterexample. The next probe keeps the candidate and layout fixed and uses
CBMC's Z3 backend. The adapter now kills its complete process group on timeout
so an external solver cannot continue in the background. Independent positive
and deliberately incorrect C controls are required regardless of solver choice.

The first Z3 probe exposed a harness error: `csrd_nondet_u32` was treated as an
unresolved function, not CBMC's nondeterministic-function convention. The raw
pilot reports a failure, but its failed property is `main.no-body...`, not a
program mismatch. Corrected the helper to `nondet_csrd_u32` and made such
failures adapter errors. Both earlier pilot artifacts are retained as invalid
harness evidence; their results cannot establish anything about the candidate.

## Cost pilot protocol before measurement

Use `benchmarks/arithmetic/buffer_update.c`, seed 42, original/identity/affine
plus a byte-identical copy of the original binary. Build GCC 16 and Clang 23 at
O0/O2. After other builds/tests finish, run one excluded execution per binary,
then seven randomized paired repetitions of 10 million calls. Each loop mixes
same-pointer and disjoint input storage and checks matching output/write
checksums. Reuse the existing paired-cost aggregator and retain raw wall time,
process CPU time, peak RSS, compilation/link time and linked size. Input
generation/harness costs are included; RSS includes the process loader. These
are pilot workload costs, not isolated function latency or reconstruction effort.

The first cost-pilot build failed before timing: macOS hides `ru_maxrss` when
only POSIX interfaces are requested. The local SDK header documents that field
as an OS extension. The measurement harness now enables `_DARWIN_C_SOURCE` on
Apple targets and retains the existing OS-specific RSS units. Generated target
C remains independent of this measurement harness. The failed build is retained
in `build/buffer-costs`; the corrected run uses a new output directory.

## Results and handoff

The final [evidence record](../../reports/buffers-validation.md) contains native
and Linux matrices: 176 build cells and 8,726,960 function/whole-memory
comparisons across the two hosts. Twelve focused memory tests passed on each.
CBMC checked all 24 affine artifact/layout pairs; seven adapter/control tests
passed natively. Its absent Linux installation is reported through explicit
skips, not inferred success. The mandatory C-SRD gate proves actual emitted
return and entire-memory equality under the shared-word model and assumptions.

Full regression runs exposed two outdated rejection expectations and one
strict-C11 fixture missing its final newline. Corrected those tests and retained
both initial full logs and focused successful reruns. All 27 groups have passing
evidence on each host, with the documented optional subtest skips.

Final review also tightened the scalar evaluator: both supported buffer
interfaces and unsupported pointer functions must be rejected before a scalar
calling harness is constructed. The focused memory/evaluation groups were
rerun on both hosts after adding controls for those two cases.

The four static compiler/optimization audits found different code sections,
with text-size ratios 2.12–2.57. The corrected native cost pilot recorded 112
paired measurements and 16 excluded warmups. Affine median wall ratios ranged
from 1.0012 to 1.0185 for the complete workload. Identical-binary controls and
raw CPU/RSS samples remain available. Small linked executables retained equal
file size despite different text sizes. No reconstruction/protection conclusion
follows from these costs or byte differences.

The implemented increment is deliberately fixed-index and straight-line.
Ordinary caller memory remains readable in its ordinary representation.
Direct-call/effect summaries are the next language milestone; dynamic indexing,
general pointer/state reasoning and memory-capable observers remain open.
Each future coverage change needs its own contract and evidence rather than
silently inheriting these results.
