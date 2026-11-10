# Richer benchmarks and subsequent candidate search

## Observation and objective, before execution

The effort pilot did not show an increased minimum query/trace budget. Its
runtime target, calculate's intermediate sum, is already determined by public
inputs and output. A more useful next experiment requires richer functions and
whole-function reconstruction tasks, with known observer coverage and held-out
families. The user requests continued candidate research after that foundation.

No finite experiment establishes a "perfect" technique. Preserve the broad
search objective and record trade-offs, failed hypotheses, unsupported tools,
correctness gaps and reproducible improvements. Until a deployment budget is
chosen, explore cost/effort trade-offs without inventing a winning threshold.

## Initial corpus design

Development: an IEEE CRC-32 byte update, four-byte Jenkins mixing, 16-bit Morton
interleaving, and defined integer RGB weighting. Reserved algorithm families:
Fletcher-16 state update, Internet checksum, Gray decoding and FNV-1a update.
All inputs are u32 values with fully defined behavior; buffers are represented
by explicitly ordered packed words. These are bounded kernels, not full
applications or newly discovered algorithms. Every function uses the neutral
symbol `kernel`. Existing preprocessing strips source line directives before
matrix compilation; future observer configurations must not provide family IDs
or oracle results as inference inputs.

Check original functions against separate Python/reference-library oracles,
boundary inputs, known answers and independent C implementations. Positive
controls include bit-serial versus table-driven CRC and serial versus parallel
Morton interleaving. A shift/add RGB version is only an algebraic control.
Negative controls include a wrong CRC polynomial, a rare-input mutation and
unrelated same-arity functions. Preserve counterexamples and false fingerprints.

The reserved families may receive correctness/ABI checks. Do not use their
reconstruction outcomes to tune an observer or candidate, then call them an
untouched holdout. Freeze the development protocol and candidate hashes before
opening reserved evaluation; subsequent rounds need a new reservation.

## Candidate research sequence

After corpus validation: improve wide-value/merge observer coverage, then add
verified representations using multiple words and an observer able to combine
locations. Extend existing planning rather than claiming it is absent. Compare
algorithmic alternatives and established transformation families, retaining
unencoded and identity controls. Candidate proof failures remain failures;
unsupported analysis is never a protection win. Any novel claim needs a prior-art
comparison and measured benefit on reserved tasks.

Sources: [CRC format and recurrence](https://www.rfc-editor.org/rfc/rfc1952.html),
[Internet checksum](https://www.rfc-editor.org/rfc/rfc1071.html),
[Bob Jenkins' hash descriptions](https://burtleburtle.net/bob/hash/doobs.html).
Implementation, validation outcomes and deviations will be appended as observed.

## First validation finding

The initial native pilot admitted all 13 C implementations. CRC nibble-table and
Morton serial/parallel equivalence controls passed, but the RGB shift/add control
was inconclusive after its 30-second proof budget. Preserve that pilot and its
SMT obligation. Investigate a general verifier normalization: constant unsigned
left shift is multiplication by a power of two modulo 2^32. This allows the
existing polynomial simplifier to compare algebraic forms. Add machine-checked
obligations for all 32 legal shift counts, wraparound and incorrect-rule tests;
do not change the benchmark to avoid the proof problem.

The user selected broad exploration without a fixed runtime/size overhead
ceiling. Subsequent candidate reports must retain cost/effort trade-offs rather
than silently applying the matrix's default candidate-selection ceilings.

## Validation outcome

The general normalization fixed the RGB proof. Native macOS and Linux each
completed 78 builds/executions, including both compilers at O0/O2 and O1 with
ASan/UBSan. Each checked 165,180 oracle comparisons on correct implementations,
proved three equivalence controls and rejected two mutants. The 12 false
fingerprints per environment are the intended rare RGB mutation; they are not
evidence of correct equivalence. All 15 CTest groups passed in both environments.
Full data, the failed pilot and commands are in
[the report](../../reports/rich-benchmarks.md).

Interpretation: the corpus hypothesis found a real verification limit and
confirmed that a finite fingerprint can misclassify a wrong function. It has not
yet supplied reconstruction or protection results. No reserved reconstruction
outcomes were inspected. Next, measure development variants, improve observer
coverage and test a multi-word representation with explicit correctness rules.
