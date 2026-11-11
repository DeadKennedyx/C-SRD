# Private-region observation protocol

Protocol `private-region-observation-v1`, baseline `592ed99` (C-SRD 0.6.1).
Measure the existing assignment and declaration/shadowing fixtures before adding
integer coverage. These are benign, controlled experiments, not general claims
about protection of arbitrary C programs.

## Question and hypotheses

Does affine private-region transformation increase automated reconstruction or
known-value recovery effort relative to the same original, after compilation?
The null is equal recovery success with no demonstrated useful effort increase.
Different instructions, a timeout, and an unsupported observer are not successes
for protection. Correctness is a separate gate that cannot be waived.

## Artifacts and controls

Use both `tests/fixtures/private_regions.c` and `private_declarations.c` with
Clang/GCC, initially `-O0` and `-O2`. Compare original, identity, affine seed 42,
and an identical-byte original copy. Later profiles extend rather than replace
this development pilot. Preprocess with the actual compiler and options before
transformation. Preserve source hashes, actual candidate frame-validation
reports, executable tool hashes, compile commands, libraries and observer output.

Shared-library exports preserve public entry points without disabling inlining
inside the functions. This is a distinct build scope from the previous linked
application/LTO cost pilot; their timings must not be mixed. The public target
and callback signatures are supplied to observers. Reference source and encoding
parameters are withheld from the reconstructor.

## Reconstruction

Export Ghidra high P-code, ordered operations, reciprocal CFG edge slots, parameter
types and resolved direct callback identities. Recover a C state machine with
simultaneous phi updates, unsigned fixed-width arithmetic, ordered memory access,
calls and loop edges. Reject unknown effects, malformed graphs, unsupported
operations and pointer uses. Do not silently drop them. A bounded execution
budget prevents accidental nontermination during grading.

Grade the recovered artifact on held-out, deterministic boundary/random inputs,
negative/zero/positive loop counts and controlled callbacks. Compare return bits,
all caller memory words and the complete ordered callback event sequence. Vary
callback behavior independently of reconstruction. Deliberately wrong returns,
stores, call arguments/order and loop behavior must be detected by controls.
This is finite differential testing, **not a formal whole-function proof**.
Ghidra's recovered semantics are themselves part of what is being tested.
Success means an executable implementation of the observed behavior was
reconstructed. It does not mean that original variable names, source structure,
or a human-readable algorithm explanation were recovered. Those are different
tasks and are not timed by this protocol. The event trace consists of ordered
`record_event(value)` values, including the record generated inside `next_value`;
it is not a general operating-system interaction trace.

Record cold decompilation and adapter wall/CPU/RSS separately, queries, generated
size, operation/block counts, completion/budget statuses and grading correctness.
Randomize paired artifact order; retain identical-byte controls and repetitions
when making effort comparisons. A single pilot timing cannot establish a speed
penalty or a human reverse-engineering difficulty claim.
“Fresh process” means a new Ghidra/JVM invocation, not a flushed OS disk cache.
The copy control has identical protected-library bytes; its driver is linked
separately to the copy's pathname.

## Runtime values

Step controlled Linux executions with GDB. Observe low 32 bits of general
registers, 64 bytes at SP and declared caller memory. No SIMD or exhaustive heap
coverage is claimed. Include callback/loop execution and distinguish instruction
visits; align training and held-out traces within a fixed loop-count scenario.
Record additional sampled stack depth relative to target entry, including
callbacks. This is separate from whole-process RSS and excludes the caller frame
and non-stack memory; it can reveal small frame changes that RSS cannot resolve.
Set `LD_BIND_NOW=1` for tracing so dynamic-linker lazy resolution happens before
target entry. Callback implementations remain observable application code.
Validate final return, full memory and events before using a trace.

Fit `observed = a * known_target + b (mod 2^32)`, with odd `a`, using training
values only. Solve modular congruences even when target differences are even;
record non-unique parameter classes instead of claiming recovery of the actual
encoding parameters. Constant training labels are insufficient variation.
Evaluate untouched held-out values, location availability and permuted-label
controls. Targets are named intermediates selected in advance; this measures
known-value recovery, not autonomous discovery of program purpose. Retain
misses, false models, inconclusive models and scope-specific counts.

Report debugger and fitting wall/CPU/RSS separately, steps, traces, candidates,
validated targets and false matches. Application runtime/size remain separate.

## Sources and decision

[Ghidra P-code operation reference](https://ghidra.re/ghidra_docs/languages/html/pcodedescription.html)
defines the operation semantics; high P-code includes decompiler-inferred call
arguments and SSA merges. No raw-call-to-C substitution is assumed sound.

Close this measurement checkpoint only with reproducible observations or a
specific documented observer limitation. A limitation remains an open measurement
gap. Record failed prototypes and revise the protocol explicitly when evidence
shows that the observer, rather than the transformation, is causing a miss.
