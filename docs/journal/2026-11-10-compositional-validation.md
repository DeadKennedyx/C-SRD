# Compositional emitted-C validation

## Observation and hypothesis (before implementation)

The completed limb experiment retained 75 failed matrix cells: Jenkins XOR,
planned and limbs16 each exceeded the 30-second full-function verification
budget across 25 profiles. No candidate from those failures was emitted. The
limb rules already have independent universal checks, but those checks alone
cannot validate the implementation of the emitter or graph lowering.

Hypothesis: validating each actual emitted limb operation under an inductive
representation invariant can make long mixed-operation functions tractable.
First validate the original ordered region against the proposed ordinary value
graph. Then validate each reparsed C fragment for all normalized operand pieces,
and finally validate the actual emitted return. The graph and partition hints
are proposals, never trusted certificates. The invariant includes both decoded
value equality and each piece's 16-bit range.

## Planned experiment

Keep the limb source formulas unchanged. Record declaration positions and output
pieces as untrusted hints. For independent `verify` inputs, reconstruct a proposed
partition and rebind by declaration position; neither temporary spelling nor
comments establish correctness. Every fragment may read only its declared graph
operands and its own new immutable locals. A reference boundary may read its
corresponding public parameter. Prove the original-to-graph mapping separately,
so lowerer mistakes cannot bypass validation. Retain the full-function verifier
as fallback and distinguish local countermodels from whole-function inputs.

Use one shared timeout budget for the compositional attempt; do not grant a full
budget to every node. Record all successful and failed obligations. Test the
existing 88 generated operation contracts, mutated artifacts, falsely normalized
pieces, graph/cutpoint errors, renamed locals and Jenkins. Re-run GCC/Clang
differential tests on macOS and Linux, including sanitizer configurations. Keep
the previous failed experiment unchanged; any newly admitted candidate needs a
new measurement round. Reserved reconstruction families remain unopened.

## Prototype observations and correction

The first prototype proved Jenkins with 41 obligations (source-to-graph, 39 graph
nodes, return). Its full-suite run then failed one stricter test on both systems:
the constant-65,535 scale still timed out locally and used the existing successful
whole-function fallback. The emitted candidate was verified, but the intended
compositional coverage was incomplete. Retained both failing CTest logs and the
scale query/report in the experiment evidence.

The local invariant initially expressed positional reconstruction with OR. That
hid distributivity from polynomial simplification. Changed the invariant to
`L + 65536*H`, while still proving both ranges. For normalized pieces this has
the same value as OR; the actual OR-based C return is independently checked.
No emitted C formula changed. All 88 operation contracts then used composition,
including the troublesome scale. This was a solver-representation change, not
an increased timeout or reduced input domain.

## Correctness validation

All 17 CTest groups passed on macOS (135.46 seconds) and Linux (38.56 seconds).
These are test-run durations, not controlled performance estimates. Tests include
13 explicit graph/hint/range/dependency/return/budget controls, all 88 emitted
operation contracts, independently renamed Jenkins verification and SMT replay,
and GCC/Clang execution at O0/O2 and O1 with ASan/UBSan. An overlapping-bit control
is deliberately equal at function exit but fails the local range obligation;
its whole-function fallback succeeds without falsely validating that invariant.

The broader protection question remains open. Newly admitted candidates require
a separate matrix/observer round; the original 75 failed cells remain historical
evidence. This is a verification-engine improvement, not evidence of increased
software protection. Measurement results will be recorded separately.
