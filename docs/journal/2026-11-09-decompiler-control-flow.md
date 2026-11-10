# Decompiler baseline and bounded control-flow experiment

## Initial design, before measurements

The previous linked matrix found that optimized affine arithmetic often collapses
to the original computation. More instructions at O0 did not prevent the bounded
runtime observer from recovering the labelled intermediate sum. We need an
independent decompiler task, not an assumption that unfamiliar source is protection.

Hypothesis H1: a bounded split of constant multiplication by operand parity can
produce a persistent compiled difference at acceptable cost. H2: that difference,
if present, changes the success rate of a fixed reconstruction observer. Both are
open questions; compiler collapse rejects H1 for that configuration. An observer's
unsupported construct, missing function or timeout is inconclusive for H2.

Prototype: for a stored unsigned operand u and F(u)=k*u+c modulo 2^32, emit
F(u-1)+k when u is odd and F(u) otherwise. Apply only to existing constant-scale
graph nodes with k>1. For affine representation c=(1-k)*b. This introduces no
decode, external effect, unbounded loop or new C type. Mandatory validation of
reparsed emitted C remains the publication gate. This is elementary algebra,
not a novelty claim. Compare with the same algorithm, representation and seed
with the prototype disabled.

The observer receives a linked binary and known function interface/location via
its symbol, but no original source, seed or representation parameters during
reconstruction. Ghidra exports decompiled C and high P-code. A bounded adapter
reconstructs supported pure expression graphs; C-SRD independently checks the
result against the reference only at scoring. Preserve raw output, tool identity,
timeouts, counterexamples and unsupported cases. A successful source-model proof
does not prove Ghidra's machine-code lifting correct.

Freeze the implementation and development protocol before held-out measurements.
Use additional bitwise, fixed-rotation, parity and bounded arithmetic programs;
include unrelated unary functions as negative controls. Run compiler/LTO/PGO/
sanitizer profiles from the declared matrix. Human effort, stripped function
discovery, arbitrary code and all-memory confidentiality remain unassessed.

## Outcomes

Initial smoke: Ghidra reconstructed original/identity/affine `calculate` at Clang
O2; all three scored `proved-under-model`, and all three +1 corruption controls
were rejected. The generic parity-split bit-vector obligation returned unsat.
The first integration tests exposed a missing split cost in the planner; the
planner/emitter consistency guard conservatively skipped that candidate. Added
the same four-operation surcharge to exact and heuristic planner accounting.

Protocol revision before held-out evaluation: the first development pilot stopped
on `bounded_mix` (four rounds combining multiplication and XOR/shift). The planned
candidate timed out at the transform CLI's default 10-second proof budget and
was not written. Identity and affine candidates had validated. This is a solver
capacity limit, not evidence of inequivalence or protection. Preserve the pilot
and the stress benchmark. Use a four-round pure arithmetic recurrence for the
main bounded-loop comparison, and reserve a different three-round recurrence
for held-out evaluation. The more complex held-out mixed-loop file remains
unmeasured; it was not inspected experimentally to tune the observer.

The pilot also exposed that the matrix timeout option was not passed to the
transform command (only build-input verification). Forward it explicitly, making
the new experiment's transform/proof budget reproducible at 30 seconds. Keep
both protocol snapshots and the pilot's actual 10-second failure manifest.

## Final observations and decision

Implementation was frozen and pushed as `1d059db24726` using the personal
DeadKennedyx account. The revised development run completed 700 cells with zero
correctness failures and one native-x86 capability gap. Held-out evaluation
completed 126 cells with no failure and no re-ranking. The two final matrices
made 94,608 paired output comparisons. Planned labels matched in every paired
split/unsplit graph. Full final suites passed 13/13 groups on native macOS and
Linux; the Linux suite includes real Ghidra integration. Hosted Debug/Release
correctness and the separate x86-64 Ghidra workflow also passed.

H1 has configuration-specific support: the split survives the required compiled
contribution checks for the bounded arithmetic case, but not across all tested
functions/compilers. Cost screening selected the unsplit affine candidate there.
For Clang O2 ARM64 `calculate`, the split leaves 21 instructions versus four for
the original/affine pair, whereas GCC O2 does not retain the same contribution.
Instruction count alone does not establish additional reconstruction effort.

The fixed Ghidra observer completed 112 attempts: 40 recovered C functions proved
equivalent under the source model, 29 unsupported reconstructions and 43 missing
known symbols. All 40 +1 corruption controls produced counterexamples. P-code
control-flow merges and 64-bit temporaries were observer gaps; simple original
rotation functions were affected too. LTO often removed the symbol. There were
no timed-out, incorrect reconstructed or integration-error results in this run.

H2 has no demonstrated positive result. The separate black-box affine observer
still recovered all tested arithmetic variants, including every split version
and the held-out arithmetic function. Keep the prototype opt-in, preserve all
negative/inconclusive evidence and improve the independent observer before
making a protection claim. Wider C memory support is still a separate task.

The next experiment needs bounded P-code merge/wide-value semantics and a newly
reserved corpus. No observer rule was changed after viewing held-out results.
Subsequent tests expanded rule-category coverage without changing the observer.
The [result report](../../reports/decompiler-control-flow.md) links commands,
archives, actual counts, scope revisions and CI evidence. Shared-host timing
samples and overlapping observer jobs are not human-effort or isolated-performance
measurements.

## Post-experiment scoring-input review

Review found that the first runner re-read the reference source at scoring time.
It preserved its bytes, but changed headers or a different frontend could change
its interpretation. Harden scoring to require the same C-SRD binary and the
matched original build's frozen, hash-checked preprocessed input. This changes
the evidence binding, not the observer's inference rules. Re-score the 40 saved,
unchanged reconstructions; all 40 again prove equivalent. Preserve both original
reports and the separate rescoring evidence. Focused tests cover frozen-input
mutation, frontend mismatch and real headless operation after this change.
Hardening commit: `aa5937f5124c`; six focused Linux tests passed, including the
real decompiler, and all unchanged reconstruction results survived rescoring.
