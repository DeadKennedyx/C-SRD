# Bounded wide-value observer and unresolved grade investigation

## Observation, question and protocol before implementation

The positional-width comparison left 45 measured observer rejections and ten
unknown grades (two distinct reconstructed answers). Their binaries, inputs,
answers, queries and budgets are frozen. The question is whether a more complete
independent observer and a separate grading investigation explain those gaps;
neither an unsupported operation nor a solver timeout is protection evidence.

Inspection before implementation found an additional layer: eight of nine
unsupported build cells contain `CALLOTHER` vector operations, and several refer
to non-parameter constant-pool inputs. A width error was masking those facts.
Only the Clang CRC32/limbs16 cell lacks that extra layer. We must not infer vector
semantics from numeric user-op IDs or guess values for unresolved memory inputs.

Implement explicit unsigned bit vectors of 1–16 bytes, `PIECE`, fixed arithmetic
right shift, and bounded existing scalar arithmetic on those values. Keep the
public u32 interface, C verifier language, path budgets and emitted-statement
budget unchanged. Represent wider values with u32 components, with no native
signed shift, implementation-defined signed conversion or C shift by 32.
`CALLOTHER`, loads, stores and non-parameter inputs remain conservative failures
pending an explicit architecture-specific contract. This increment is observer
coverage, not a new code-protection technique or expanded input-C support.

Validate against independently specified bit-vector formulas and concrete integer
oracles, malformed-width and deliberately wrong-operation controls, GCC/Clang
O0/O2 and sanitizers, and existing CFG tests including merge behavior. Include
non-power-of-two byte widths and cross-word offsets. First replay every unique
frozen O2 export, retaining answers and failures in a new directory. After tests,
freeze the observer and repeat all 40 original/candidate O2 cells with one warmup
and five measured repeats, unchanged binaries, order/input seeds and budgets.
Run resource measurements serially. Keep old evidence immutable.

Separately investigate all four distinct saved mismatch queries for the two
unproved nibble answers. Preserve initial failures. Try a declared finite solver
budget grid and controlled decomposition only with complete proof obligations;
tests never upgrade an unknown grade. Record grader time/CPU separately from
observer effort. New solver settings are follow-ups, not replacements for the
original budget or timings. Include the existing wrong-output controls and
general arithmetic controls. Any resulting proof remains under the source model
and its trusted components; no verified machine-code lifting is claimed.

Primary semantic reference: Ghidra's [P-code operation reference](https://ghidra.re/ghidra_docs/languages/html/pcodedescription.html)
defines concatenation/extraction and sign-filling right shift. Its
[additional operations reference](https://ghidra.re/ghidra_docs/languages/html/additionalpcode.html)
defines bit-preserving casts and predecessor-selected merges. Consulted before
implementation; these operations are established, not a novelty claim.

## Scope refinement after the first validated scalar prototype

The scalar prototype passed 1,457 independent actual-C/SMT obligations and
compiled checks, including every byte width. The first compile run failed on
unused temporary/type-limit warnings; its inputs and log remain retained. Those
were corrected before the broader run. This does not resolve the eight cells
whose next operation is `CALLOTHER`.

Before freezing any new resource comparison, extend the export with symbolic
user-op names from the pinned Ghidra language and explicit read-only mapped-byte
snapshots. Add only AArch64 little-endian `NEON_ext`, `NEON_rev64` and constant-
count `NEON_ushl`, on 64/128-bit vectors with declared lane widths. The installed
Ghidra 12.2 AARCH64 SLEIGH source supplies the argument order and lane-byte
metadata. [Arm's instruction reference](https://documentation-service.arm.com/static/6245c734b059dc5ff9a8bdab)
supplies instruction semantics, including USHL's signed low-byte shift count.

Reject writable/uninitialized/executable memory snapshots, relocations, wrong
endianness, unresolved input registers, unknown user-op names, dynamic vector
counts, malformed arity/widths and unsupported architectures. Preserve old schema
1/2 replay; require the new explicit schema for these new facts. The model is
frozen mapped constants, not general pointer/memory support. Validate the new
rules against independent scalar formulas, real ARM intrinsics where available,
and deliberately wrong controls before repeating the 40-cell study. The exporter
and these declared observer modules now change; binaries, C frontend and budgets
still do not. This refinement is recorded before those results, not backfilled
as the original scalar-only plan.

The grading-only investigation will use 30 seconds for all four remaining exact
query hashes, then 120 seconds only for unresolved hashes, with the two distinct
wrong-output queries and three generic arithmetic controls at each used budget.
Exact duplicate queries retain all their trial memberships. No original data or
budget is overwritten.

## Constant-snapshot pilot correction

The vector prototype passed 554 independent actual-C SMT obligations and five
compiler configurations comparing 554 outputs on 70 vectors with independent
integer oracles and actual ARM intrinsics. The live pilot still rejected memory
inputs. A retained diagnostic export showed `.rodata` was readable, nonwritable,
initialized and relocation-free, but also marked executable by this ELF import.
The first policy unnecessarily equated execute permission with mutability.

Allow the execute flag to be either Boolean value and preserve it in evidence;
continue requiring readable, nonwritable, initialized, in-block, relocation-free
mapped bytes. The explicit assumption is that those mapped bytes remain immutable
in this pure-function experiment. This admits no stores, writable globals,
pointer traversal or arbitrary external memory. The original pilot and exporter
snapshots are retained. Repeat validation with the corrected condition before
freezing resources. A permission flag is never silently rewritten.

## Validation and grading before the resource repeat

Final native and Linux correctness suites each passed all 23 CTest groups. Each
host checked 1,457 wide-value and 554 vector actual-C SMT obligations, the five
compiled configurations, ARM intrinsics, and deliberate wrong-operation
controls. Native skipped its optional live-Ghidra effort test; Linux ran it.
The suites overlapped, so their elapsed times are not performance comparisons.
Full logs and generated proof artifacts are retained under
`experiments/runs/pcode-wide-development-20261110/final-v3-{native,linux}`.

The corrected 15-cell Clang pilot produced all 15 answers: 14 source-model
proofs and one inconclusive RGB nibble grade. No unsupported operation remained
in that pilot. This is development feedback, not the forthcoming repeated cost
comparison. Keep both pilots and their implementation snapshots.

The separate grading investigation completed its declared 30-second tier: all
four remaining exact queries proved UNSAT in 5.7–9.3 seconds, and both wrong-
output plus three arithmetic controls passed. No 120-second tier was needed.
This resolves the ten old unknown trial grades, with no changed answers or
binaries. They exceeded the previous five-second circuit-grading budget; the
result is not evidence of failed reconstruction. Original resource records and
grades remain untouched. Retain the protocol, per-stage resources and query
bindings in `experiments/runs/pcode-wide-grading-20261110`.

Freeze this observer and run the complete 240-attempt repeat next, serially,
using `experiments/run_wide_observer.py`. Analyze all 200 measured attempts and
retain the 40 warmups. Replay all new inconclusive measured answers separately
with a 30-second checked-circuit budget, including their wrong-output controls
and the same arithmetic controls; do not rerun observers or charge grading cost
to reconstruction. No outcome or resource threshold will select which cells
are reported.
