# Decompiler baseline and bounded control-flow experiment

## Before implementation

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

Final experiment outcomes will be appended after execution.
