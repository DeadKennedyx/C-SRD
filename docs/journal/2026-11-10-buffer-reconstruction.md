# Buffer reconstruction and measurement

## Question and observations

Contemporaneous entry, begun before new observer results. Baseline `ac88803`
implements fixed-index buffer transformations and memory equivalence. Its scalar
reconstruction observers reject pointer interfaces. Different code bytes and
correct outputs therefore do not yet establish additional reconstruction work.

I am extending the observer rather than interpreting its missing support as
protection. I want to know whether original, identity and affine buffer programs
can be recovered, with what resource cost, and which ordinary values can be
observed during their execution. This is increment 1 of the newly authorized
[fourteen-increment sequence](../coverage-increments.md).

## Prototype and predeclared controls

Use a separate memory-aware Ghidra export/adapter contract so the frozen scalar
observer experiments remain reproducible. Supply only compiled artifacts, symbol
and public parameter types; withhold original C, representation parameters and
seed from the observer. Interpret ordered loads/stores with symbolic
parameter-relative addresses. Preserve load snapshots across writes, including
aliases. Reconstruct actual C and independently grade returns plus entire final
memory using the existing memory verifier. Reject unknown spaces, widths,
pointer escapes, unresolved side effects and unsupported control flow.

Development corpus: the six existing `tests/fixtures/buffers.c` functions and
`benchmarks/arithmetic/buffer_update.c`. Compare original/identity/affine seed 42,
GCC and Clang, initially O0/O2 before broader matrix coverage. Include deliberately
wrong stores, reordered alias-sensitive operations, changed return and malformed
export controls. A returned constant must not allow stores to disappear.

Resource experiments will declare repetitions/order and budgets before executing
the comparison. Keep reconstruction, source grading and application execution
separate. Cold process totals include startup; do not label them native per-call
costs or infer improvement from their noise. Persistent-session calibration from
PROT-13 remains required for claims about steady-state per-function costs.

## Sources

The official [Ghidra P-code reference](https://ghidra.re/ghidra_docs/languages/html/pcodedescription.html)
defines address-space identifiers, addressable units, widths and ordered LOAD /
STORE behavior. The [PointerDataType API](https://ghidra.re/ghidra_docs/api/ghidra/program/model/data/PointerDataType.html)
supplies the public pointer ABI. These are implementation references; the binary
lifter remains trusted and is not proved correct by a source-equivalence query.

## Findings and deviations

The new adapter passed six unit/integration tests, including alias-sensitive
load/store order, memory-only counterexamples with equal returns, pointer offset
semantics and malformed-export rejection. Three runtime-oracle/fitting tests
also passed on macOS and Linux; compiled independent oracles cover both GCC and
Clang, all seven fixtures and four alias layouts.

The first optimized `buffer_update` smoke recovered all eight artifacts (two
compilers, original/identity/affine/identical copy). The subsequent development
run recovered 112/112 function/build/variant cells: seven functions, Clang 18 /
GCC 13, O0/O2, and four variants. Every answer passed return-plus-entire-memory
grading; 208 wrong-return/wrong-store controls produced counterexamples. Cold
CPU ratios for affine ranged 0.792–1.047, while identical-copy ratios ranged
0.830–1.074. These are one observation per cell, include process startup, and
establish no worthwhile resource-cost increase.

The first live runtime smoke completed 192 executions of Clang O2 buffer_update
(four variants, four alias layouts, four training/eight heldout inputs). Both
declared intermediate targets were inferred for every variant/layout. This is
finite evidence with supplied intermediate labels, not arbitrary algorithm
discovery or proof of a learned map. The ordinary caller-memory boundary is a
concrete recovery route.

After that smoke, the next declared runtime comparison uses the unchanged 112
compiled cells and all four layouts/12 inputs: 448 observation groups and 5,376
target executions. It retains missing/false fits, budget failures, register /
stack / caller-memory results and the permuted-label control. Resource collection
is serialized with other experiments.

The first full runtime attempt was deliberately interrupted after 1,448 trace
records: checkpointing rewrote the entire growing JSON history after every
trace, producing unnecessary quadratic serialization/I/O. The interruption
occurred during JSON serialization. The partial report, traces, exit 130,
interruption explanation and original implementation bytes are preserved in
`buffer-runtime-development-20261110`; it is not a completed experiment.

The corrected runner writes small progress checkpoints, one completed observation
per directory, and the full aggregate at completion/interruption. Schema 2 also
retains harness/executable/input/config/script hashes. The GDB sampling, finite
oracles and affine fitting semantics are unchanged. A new complete run will use
`buffer-runtime-development-20261110-v2`; the earlier attempt is not overwritten.

A review found that the original store mutation was not universally a negative
control: incrementing every store can cancel in `*p=x; *p=0u-*p; return 19u;`.
The 208 historical controls all produced real counterexamples, so those results
remain valid. New schema-2 reconstruction runs mutate only the final store,
which guarantees a changed final word in the admitted straight-line domain.
A regression checks both the cancelling old mutation and the rejecting new one.
Historical implementation bytes are retained, and ordinary reconstructed answers
must replay byte-for-byte. This changes control generation, not protection.

The complete second runtime run finished all 5,376 executions and 448 groups;
all returned values and 64-word final memories matched their independent oracle.
It recovered 104/160 declared target/build/layout cases per variant, identically
for original, identity, affine and copied original. The 56 misses per variant
were entirely explained by 14 target/layout training sets whose four labels all
had the same parity (times four build profiles). The fitter's odd-difference
inverse could not be constructed. No fitted map failed its heldout checks, and
the permuted-label control produced no validated maps. This is an input-design
gap, not evidence of protection.

The revised `basis-parity-v2` input protocol fixes those training constraints:
one training run perturbs only the scalar by one, another perturbs each memory
word by one, and the fourth remains an independent seeded sample. A unit test
checks odd target differences for every declared function/layout. The eight
heldout executions stay byte-for-byte unchanged. This adjustment is based on
training-set rank/parity, not selecting favorable transformed outcomes. The
reused heldout inputs are development validation, not a fresh generalization
study. A third full run will use a new output directory; earlier reports and
their exact implementation bytes remain intact.

The post-measurement evidence checker passed for the full reconstruction run,
the second runtime run and the initial runtime smoke. Separately, 45 distinct
recovered C answers compiled with Clang/GCC at O0/O2 on both macOS and Linux:
8,640 return/whole-memory comparisons per host, 17,280 total, all matching the
finite oracle. These compiled checks supplement the source-model proofs.

The third full runtime run completed all 448 groups / 5,376 executions with
100,656 instruction steps and matching returns/full memories. It recovered
160/160 supplied target/build/layout cases for each variant. There were no
false or inconclusive fitted maps and no validated permuted-label controls.
All four variants recovered the same targets through the same three sampled
location classes. The parity correction eliminated the apparent misses.

The final evidence audit replayed both completed runtime studies and every
static answer/control. Nine deliberately corrupted report copies were rejected;
the original reports remained unchanged. A new four-artifact static pilot also
passed the corrected final-store controls. The revised observer tests passed
on both hosts (eight adapter tests and four runtime tests). Frozen archives
retain 109,535 verified files, including failed/interrupted prototypes.

Conclusion: the buffer observer gap is closed for the declared development
contract. Extra stepping/fitting work exists in this pipeline, but complete
recovery and uncontrolled cold/fixed-order costs establish no worthwhile
protection advantage. Defer affine as a protection candidate. Keep native
per-function calibration, matching application costs and generalization as
explicit unresolved measurements; proceed to composition of private arithmetic
regions in larger functions rather than adding an unvalidated protection claim.
