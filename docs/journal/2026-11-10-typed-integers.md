# Typed private integer frames: protocol and development journal

Baseline: `592ed99`. Increment 3 requires real integer semantics beyond the
existing unsigned-32 model. The planned prototype carries Clang's effective
expression types and conversions through a separate typed scalar IR. It retains
private-region scope/binding/effect boundaries; the pure-u32 and buffer paths
keep their existing models.

The contract targets standard C integer types up to 64 bits, 8-bit bytes,
16-bit short, 32-bit int, 32/64-bit long and 64-bit long long. Plain-char
signedness is recorded. Signed representation, out-of-range signed conversion
and negative right shifts use the explicitly declared two's-complement,
modulo-conversion, arithmetic-shift model. These are
[documented GCC choices](https://gcc.gnu.org/onlinedocs/gcc/Integers-implementation.html),
not universal C11 guarantees. Clang compatibility will be tested; it is not
inferred from GCC documentation. Generated model guards prevent common ABI/char
configuration mismatches. C11's promotions, conversion and undefined signed
overflow distinctions follow [WG14 N1570, 6.3 and 6.5](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf).

Hypothesis: typed modular representations can preserve all scalar outputs on
the original's defined inputs while keeping same-width addition/subtraction/
constant scaling encoded. Compatible low-bit affine parameters also permit
direct encoded narrowing. Widening and unsupported direct encoded operations
require explicit conversions. Signed restoration will avoid out-of-range
signed casts in generated runtime arithmetic.

Verification must check `original_defined => candidate_defined && equal_outputs`,
retain the input-domain obligation, and reject an empty original domain. This
does not repair undefined input programs or prove the surrounding environment.
Negative controls must include candidate overflow, wrong signed comparisons,
wrong promotions/narrowing, missing outputs and source-model mismatch.

Planned evidence: independently checked representation rules, actual emitted-C
SMT validation, boundary/differential/event tests under GCC/Clang optimization
and sanitizer profiles, then matched reconstruction/runtime/cost measurements.
No broader coverage or protection result is claimed before these experiments.

Resumed after the private-region observation checkpoint (`3c26935`) was published.
The existing u32/private-scope regressions passed with the typed engine. New
codec checks exhaust 196,608 byte pairs across three selected codecs; sampled
width/boundary checks cover 1/8/16/32/64 bits. Emitted-C checks admit selected
64-bit arithmetic and reject wrong signed comparison, narrowing and newly
introduced signed overflow. These do not establish the full proposed coverage.

The first mixed-width fixture timed out during frame validation and no output
file was written. The query and report are retained in
`experiments/runs/typed-integers-prototype-20261110`. Do not bypass this gate or
call the fixture verified based on the smaller tests.

First simplification to investigate: restore a negative signed value as
`-1 - (mask - raw)` using bounded casts. Unlike `MIN + (raw - sign)`, `-1-y`
is representable for every signed long-long y. Both formulas restore the same
value on their guarded branch; the former may simplify candidate-definedness
obligations. Recheck emitted code and the retained fixture before drawing any
conclusion about verification performance.

Development follow-up: that formulation and incremental Z3 simplification still
timed out. A first compositional attempt isolated the difficulty to mixed signed
widening. Restoring values with bounded casts/complement plus a polynomial model
of complement discharged it, but conditional arithmetic still timed out.
Direct probes of the saved conditional query found simplify/SAT, qfbv and
pull-cheap-ite inconclusive at five seconds; conditional-term expansion followed
by polynomial simplification returned unsat. The resulting actual-C validator
now proves all three mixed-width fixture frames. These are development observations,
not a benchmark of solver superiority.

The verifier checks an untrusted complete scalar-state invariant after every
source statement. It havocs everything except the proved relation before the
next check. It never substitutes the emitter's formulas for reading the emitted
C. Wrong/omitted hints are rejected by composition; whole-frame checking may
still validate correct C independently. Failed local invariants are distinguished
from actual input counterexamples. Saved queries include the tactic needed for
independent replay. The complement normalization is independently compared with
SMT `bvnot` among 41 integer rule/control obligations.

The first native compiled matrix passed 56 compiler/profile/seed cells for the
integer fixture (172,368 return/memory/event comparisons), and the two preceding
fixtures passed the same matrix. This alone establishes no protection result.
Linux regression and matched observer measurements are the next gate. Their
protocol is documented in [the typed-integer contract](../private-integers.md).
The runtime observer now has explicit target widths and full64 register/stack
views; low32 recovery alone would not measure the new wide intermediates.

Linux passed all 34 CTest groups; after the saved-query export change, four
affected groups passed again, including standalone query replay. The integer
fixture passed 36 Linux compiler/profile/seed cells and 110,808 return/memory/
event comparisons. The new observer's ten test groups passed. No new CBMC or
whole-program proof is claimed by these results.

Measurement setup deviation: the local `csrd-dev:ghidra` image contains the
analysis dependencies but requires the existing Ghidra installation mounted
separately. The first reconstruction invocation used a missing executable path,
producing 96 launch errors and no actual analyses. These are retained in
`typed-integers-reconstruction-20261110`, excluded from protection conclusions.
The corrected invocation mounts the installed distribution at `/opt/ghidra`
and uses its `support/analyzeHeadless` executable. Both runs use the same frozen
candidate build manifest; no candidate was selected based on the failed launch.

The first actual reconstruction run produced 96 answers, but effect grading
accepted only 81. All 15 mismatches were in Clang O0 cases, including original
and byte-copy controls. One initial event differed by 1,024, consistent with
treating signed byte -1 as unsigned 255 in the test workload. Inspection of the
saved high P-code and native disassembly located the discrepancy at `LDURSB W`.
The installed Ghidra 12.2 AArch64 source uses `zext(*:1 ...)` for its unscaled/
unprivileged 32-bit signed-byte load constructor. This conflicts with
[Arm's instruction semantics](https://support.arm.com/documentation/ddi0602/2021-06/Base-Instructions/LDURSB--Load-Register-Signed-Byte--unscaled--).

An isolated language overlay changes that constructor to sign-extend the byte
to 32 bits and then zero-extend to the full X register. The original installation
and first measured answers stay unchanged. `patch_ghidra_signed_byte.py` requires
the exact original source checksum and writes a separate copy/patch manifest.
The instruction-control harness exhausts all 256 byte values at offsets -1/0/+1,
checks actual CPU outputs including the zero upper register half, then grades
reconstructed C under GCC and Clang. The unpatched observer reproducibly fails
128 values per offset/compiler. This is a dependency/observer defect, not a
protection result. Any corrected-observer comparison must be a fresh, explicitly
labeled run on the same frozen candidate binaries; it is not a blind holdout.

### 2026-11-12 follow-up: observer corrections before interpretation

The signed-byte overlay passed all 768 hardware control cases and all 1,536
reconstructed-C comparisons under the two compilers. The unpatched language
failed 768 of those reconstructed comparisons. The fresh matched pass improved
from 81/96 to 93/96 tested reconstructions. The remaining three failures were
repetitions of the same affine Clang O0 pipeline, not three independent problems.

Inspection of that export found a byte constant 255 with Ghidra high datatype
`bool`, compared with a Boolean result. The adapter treated it as a numeric byte;
Ghidra's own `PrintC::pushBoolConstant` prints any nonzero Boolean literal as
`true`. The exporter now preserves the inferred Boolean type alongside the raw
constant. Schema 6 reconstruction normalizes only explicitly Boolean-typed
one-byte constants. Numeric byte 255 stays 255; old schema 5 exports keep their
previous interpretation. This is a type-directed high-level reconstruction rule,
not a claim that raw machine or P-code byte constants universally mean Boolean.

Eleven observer regression groups passed on both hosts, including 2,048 compiled
Boolean/numeric-byte control comparisons per execution. The actual previously
failing artifact passed 1,024 new-seed inputs with both compilers (2,048 recovered
comparisons), with its original executable checked against the independent effect
oracle first. Source and candidate binaries have not changed since the initial
build. Observer sources are frozen separately before the complete matched rerun.

The rerun uses 1,024 inputs and seed 20261112, with all variants receiving the
same patched language and typed adapter. These inputs are unseen by that frozen
observer execution, but the fixture family informed observer development. Retain
the original 81/96 and 93/96 runs and label the final result as a development
follow-up. Neither observer defect is evidence of protection. Runtime recovery,
application costs and query replay remain the next measurements at this point.

The completed follow-up accepted all 96 reconstructions across 196,608 recovered
comparisons, with nine deliberately incorrect effect controls detected. All 576
runtime traces completed and passed effect checks. Known-target recovery was
129/156 original, 138/156 identity and 141/156 affine; eight targets per variant
had insufficient training variation. Affine produced 7,112 failed held-out
location models, mostly one-bit guesses, while recovering more target cases.
These are not independent function-classification errors or a protection win.

Application overhead was substantial: affine median wall ratios 4.962/4.057 at
Clang/GCC O0 and 1.374/1.921 at O2. All 288 saved obligations replayed with their
expected answers. Compiled differences survived in all eight affine function/
build pairs, but none prevented executable reconstruction. The
[checkpoint report](../../reports/private-integers.md) records all costs, widths,
observer limits and reproduction commands. Keep the validated integer
infrastructure; defer a protection claim for this affine candidate. Byte-memory
coverage is next, under a separate contract and measurement gate.

Publication housekeeping corrects the CLI's stale assignment-only help text.
This changes no transformation rule or measured program binary. The pre-change
implementation/executables and the help-only follow-up are retained separately;
the frozen measurement data are not regenerated or relabeled.
The native/Linux rebuilt CLIs passed their integration group; the Linux rebuild
also reproduced all eight measured transformed sources byte for byte. The final
evidence archive retains both executable identities and the exact help-text diff.
