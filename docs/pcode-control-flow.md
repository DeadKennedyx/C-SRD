# Bounded scalar P-code control-flow observer

## Problem and hypothesis

An observer that rejects a compiler's ordinary fixed loop cannot measure whether
that loop increases reconstruction effort. An explicit CFG plus complete bounded
expansion may recover those functions while preserving conservative failure for
unmodeled behavior. This is a defensive observer extension, not a protection
technique or an expansion of C-SRD's admitted source language.

## Export contract

`ExportCSRD.java` schema 2 records the known symbol and public u32 interface,
varnode sizes/constants/parameter slots, and live instructions in each basic
block's execution order. Each block has an `id`, ordered `operations` indexes,
and ordered `incoming`/`outgoing` lists. An edge is
`{"block": other_id, "reverse_index": slot_in_other_block}`. The explicit
`entry_block` is the unique block containing the function entry address.

Both directions of every edge must agree. Parallel edges retain separate slots:
predecessor block identity alone does not identify a merge input. Ghidra's
outgoing slot 0 is the conditional false edge; slot 1 is the true edge.
`MULTIEQUAL` input slot k selects incoming edge k. This follows the pinned
[block API](https://github.com/NationalSecurityAgency/ghidra/blob/Ghidra_12.2_build/Ghidra/Framework/SoftwareModeling/src/main/java/ghidra/program/model/pcode/PcodeBlock.java)
and [merge semantics](https://ghidra.re/ghidra_docs/languages/html/additionalpcode.html).

Old schema-1 exports remain replayable only for unconditional expression DAGs.
Their global address/sequence order is not instruction execution order; it
cannot reconstruct loops or branches. New P-code counts include block-contained
live operations. Counts from old/new export methods are not automatically
comparable and cannot establish a protection benefit.

## Validation and execution

1. Validate every node index without negative-index wrapping; check types,
   constants against storage widths, operation arity, unique definitions and
   no writes to constants or public inputs. Reject unmodeled operations anywhere
   in the export, including effects outside the return slice.
2. Validate block membership, complete operation coverage, reciprocal edges,
   unique entry with no predecessors, structural reachability, terminator
   position/degree and leading merge arities. Addresses are diagnostic metadata,
   never a substitute for missing CFG edges.
3. Compute dominators. A normal definition must dominate its use; within a block
   it must precede the use. Each merge input must be available at the end of
   its corresponding predecessor. Unresolved inputs and invalid SSA fail closed.
4. Enter a block with an explicit incoming edge and value environment. Read all
   merge values from the pre-entry snapshot, then install them simultaneously.
   Clear that block's ordinary outputs before replay to avoid stale definitions.
5. Execute scalar rules with width normalization and exact constant propagation.
   Follow a single edge only when the condition is an exact constant. Otherwise
   expand both edges independently. No test samples or guessed invariants prune
   paths. Every path must return; exhausting any bound rejects the entire answer.
6. Compose returned u32 expressions using conditional selects. Speculative
   expression evaluation is safe only because all admitted scalar operations are
   pure and total. Emit one C11 return, preserving the known public interface.

Supported payload widths are 8, 16 and 32 bits. Rules include unsigned
add/subtract, scale when an operand is an exact constant, bitwise operations,
copy/cast, extensions, unsigned comparisons and fixed logical shifts/subpieces.
P-code `CAST` copies bits; it is not a numeric C cast. Shift/count metadata may
have 8/16/32/64-bit storage. Oversized logical shifts produce zero without an
invalid C shift. Subpiece extraction must remain within its source. No native
wide data, vector intrinsics, signed comparisons/shifts, variable multiplication,
loads/stores, calls, indirect control flow or unmodeled effects are admitted.

## Fixed bounds and measurements

| Resource | Maximum |
| --- | ---: |
| Varnodes / static P-code instructions | 4,096 / 2,048 |
| Basic blocks | 256 |
| Block entries along one explored path | 64 |
| Total expanded block entries | 1,024 |
| Terminal paths | 64 |
| Evaluated scalar operations | 65,536 |
| Emitted C statements | 16,384 |
| Generated C bytes | 1,048,576 |
| Legacy DAG recursion depth | 128 |

These are analysis budgets, not performance/size acceptance limits for candidate
programs. Conditional paths can expand exponentially; even a terminating loop
may remain unsupported. A successful complete expansion represents every input
path within this trusted graph model. An exhausted expansion does not prove
nontermination or resistance to reconstruction.

Reports bind all adapter modules and the exporter. They retain export schema,
block/node/instruction counts, expanded blocks, maximum path length, constant and
symbolic branches, terminal paths, evaluated scalar operations, emitted statement
count and output bytes. Resource measurement keeps reconstruction time, Ghidra
time, whole-observer CPU/RSS and grading costs separate. Statement counts exclude
the final return and unused-parameter casts. Scalar-operation counts exclude phi
selection and control transfers, and include repeated loop/path evaluation.

## Verification boundary and validation protocol

The separate scorer compares generated C against the frozen original build input
over the entire admitted u32 domain. A model proof still trusts the C model,
solver, Ghidra and this adapter; it does not prove lifting from machine code.
Counterexample controls corrupt an answer or a merge choice. An unsupported
export, timeout or inconclusive grade is retained without a protection score.

`test_pcode_cfg.py` checks independently written C contracts and a separate
concrete graph interpreter, compile/run behavior at GCC/Clang O0/O2, and Clang
ASan/UBSan. Semantic controls include parallel edges and simultaneous self-loop
phi swaps. Malformed-graph and expansion-exhaustion controls must be rejected.
The existing scalar-rule and live-Ghidra integration tests still run.

Two additional observer validation shapes were reserved in the
[journal](journal/2026-11-10-pcode-cfg.md) before implementation: unsigned distance
and a five-step conditional recurrence. The
[manifest](../experiments/pcode-cfg-validation.json) builds these at GCC/Clang
O1/O2 with original/identity controls. Its `development` field selects the matrix
driver's ordinary execution mode; this does not reopen the separate reserved
algorithm corpus or permit adapter tuning on these validation outcomes.

The original GCC Jenkins artifact is a development recovery check. New exports
and grades get new directories. Old exports, statuses and resource observations
are never overwritten. Final resource trials run serially after builds/tests.
The next separate coverage question concerns wide/vector operations, whose
semantics cannot be inferred merely from their storage sizes.
