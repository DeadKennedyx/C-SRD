# Positional-width candidate comparison

## Observation and hypothesis (before implementation)

The richer corpus and bounded CFG observer are working. The two-16-bit-piece
candidate survived several optimizing builds but has not demonstrated increased
reconstruction effort. The GCC Jenkins baseline is now recoverable; unsupported
merges are no longer a reason to exclude that baseline. Four separate recurrence
validation grades remain inconclusive and must not be treated as protection.

Question: do four 8-bit pieces or eight 4-bit pieces change compiled structure,
successful reconstruction resources, application runtime or size relative to the
original, identity lowering and the existing two-piece implementation?

This explores an established positional representation, not a novel encoding or
secret-sharing method. Smaller pieces expose their constituent bits. The
experiment can fail to find a useful trade-off; it has no predetermined winner.

## Specification and first protocol

Add fixed `limbs8` and `limbs4` strategies. All generated storage remains u32;
each piece must stay in [0, 2^w-1]. Preserve the `limbs16` generated source as a
control. Carry intermediate values in the chosen representation across supported
arithmetic, bitwise, comparison, shift and select operations. Decode only at
return or a bounded lookup-index boundary. No new C language constructs, effects,
entropy source or seed-dependent behavior are introduced.

Use low-to-high carry/borrow arithmetic and direct piece movement for fixed
shifts. First try the same full-constant scale/carry recurrence generalized from
two pieces. A possible alternative is coefficient-digit convolution if proof or
execution measurements justify it; preserve the original prototype and failures
before any such change. Do not silently change the arithmetic to fit a proof.

Generalize the existing untrusted checkpoint hints to a width plus ordered piece
vector. The verifier must independently check source-to-graph lowering, actual
reparsed candidate fragments, every output piece's range, and the actual return.
Malformed width/dimension hints, missing carry/borrow, range overflow and wrong
returns must fail. Shared verification deadlines still apply; unknown never
permits publication of transformed C. Legacy 16-bit reports and evidence are
retained unchanged.

Before measuring: universal bit-vector rule obligations; boundary and deterministic
random differential tests for every operation; every legal shift count; GCC and
Clang O0/O2 plus ASan/UBSan; incorrect-rule and actual-output corruption controls;
Jenkins composition and independent proof-query replay where practical.

Then freeze implementations and compare original, identity, limbs16, limbs8 and
limbs4 on the four development families (CRC32 byte, Jenkins word, Morton16 and
RGB integer weighting). Use the existing broad compiler matrix, report-only
selection and all exclusions. Do not impose runtime/size ceilings. Measure
matched successful reconstruction attempts with unchanged observers; retain
timeouts, unsupported exports, wrong answers and grading gaps separately.
Reserved algorithm families stay closed. Run resource measurements serially
after builds/tests, preserving raw data and hashes. Algorithm variants can be
added as a subsequent declared comparison rather than confounded with width.

## Prior art consulted

* [Tigress EncodeData](https://tigress.wtf/encodeData.html) documents positional
  bignum codecs and byte/nibble splitting. Its documented operator coverage and
  C-SRD's verified u32 subset differ; this alone is not a novelty claim.
* [GNU MP integer internals](https://gmplib.org/manual/Integer-Internals) illustrates
  established positional limbs. Its arbitrary-precision sign/magnitude model
  differs from this fixed-width modulo-2^32 experiment.

Results, failed prototypes and subsequent decisions will follow below.

## Prototypes and observations

The first full-factor recurrence passed 168 independent arithmetic obligations,
but the actual generated-C checks timed out for dense coefficients. The operation
suite first failed at coefficient 3,521,782,525 for bytes and 2,186,250,713 for
nibbles. Direct saved probes confirmed the latter coefficient was provable for
bytes but inconclusive for nibbles. No inconclusive transformation wrote C output.
This separated a formula proof from the harder artifact proof.

I tried coefficient-digit convolution and preserved both generators and binaries.
This alternative still timed out: the first suite failures were coefficient
65,535 for bytes and 255 for nibbles. Its additional universal convolution
obligation was also inconclusive for nibbles. These outcomes did not refute the
arithmetic; they failed the current verification gate. I returned to the original
full-factor C formulas rather than increasing the deadline or accepting tests as
a substitute for proof.

A first per-digit carry proof reduced the problem, but byte coefficient
2,186,250,713 still timed out in digit 1. The saved report identifies that local
failure before the whole-function fallback also exhausted its budget. The
accepted decomposition separately proves the actual partial multiplication/add,
then the actual mask/shift extraction for an arbitrary u32 partial. A universal
telescoping identity connects the checked steps. Incoming carries are unrestricted
u32 values. Every digit range, metadata boundary and actual return remains checked.

This is an improvement to proof organization, not a new protection mechanism.
The generated full-factor formulas are unchanged. The final byte/nibble rule
suite has 172 obligations, including eight deliberately wrong rules that must
produce counterexamples. Mutation tests reject corrupted code and malformed
partial/carry hints. Reports preserve the nested obligations for independent
solver replay. Detailed contracts are in [the specification](../positional-widths.md).

## Validation before freezing the comparison

All 21 CTest groups passed on native macOS ARM64 and Linux ARM64. The full suites
took 161.65 and 87.91 seconds while overlapping; these are test-run durations,
not performance comparisons. Linux used Clang 18/GCC 13 and enabled live Ghidra
integration. The new operation suite covers 98 functions per width, including all
32 shift counts in both directions, edge/random execution, GCC/Clang O0/O2 and
ASan/UBSan, dense factors and independent nested-query replay.

The existing Jenkins `limbs16` candidate remains byte-identical to its earlier
frozen source: SHA-256
`557dbff695e80e6c9a8ee83832e746c5c9be95546a8e1f6d7d83de0298f5a675`.
No source-language support expansion or runtime dependency was added.

The failed prototypes, proof reports, logs, final rule queries and compiler
identities are retained under
`experiments/runs/positional-widths-development-20261110` for evidence packaging.
The [declared comparison](../../experiments/positional-widths-exploration.json)
was frozen after these checks. Its driver copies the frontend binary, records
bindings and runs the compiler matrix, chosen-query observer and Ghidra observer
sequentially. Development cases and budgets are fixed before their outcomes.

If reconstructed answers encounter inconclusive grades, a separate follow-up may
replay **all** measured inconclusive queries using the existing checked-circuit
driver, with its unchanged five-second ABC/eight-second stage budgets and negative
controls. That can resolve grading gaps; it must not change observer costs or
rewrite the initial grades. No reserved algorithm reconstruction is authorized
by this development comparison.
