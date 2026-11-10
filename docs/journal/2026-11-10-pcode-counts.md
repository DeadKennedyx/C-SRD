# P-code shift-count width correction

## Observation

The first richer Ghidra run used the frozen adapter from `2eac664`. Several
original and candidate functions reported an unsupported eight-byte varnode.
Inspection of GCC O2 RGB exports showed that all data values were four bytes;
the eight-byte nodes were constants holding shift counts 8 and 16 and a return
address marker. The adapter attempted to materialize the count through its
restricted data-value path before interpreting it as metadata.

## Hypothesis and bounded fix

Interpret a constant shift/subpiece count independently of the data width. Keep
data-value widths restricted to 1/2/4 bytes. A count at least as large as the
payload width must retain the P-code shift's zero result, not become undefined C
or wrap to a smaller count. Do not admit wide arithmetic, SIMD, merges, calls or
effects as part of this correction. Source:
[Ghidra P-code operation reference](https://ghidra.re/ghidra_docs/languages/html/pcodedescription.html).

## Validation and experimental design

Wait for the frozen run to complete before changing its adapter. Retain that
run and the old adapter verbatim. Add positive tests for 64-bit count fields,
oversized counts, subpiece truncation and wrong-count counterexamples. Wide data
and nonconstant/malformed counts must still fail closed. Prove the generated C
against independent expected expressions. Then rerun the same Ghidra protocol
on the same binaries, with five measured repetitions and one excluded warmup.
This is an observer correction, not a new protection treatment. Reserved families
remain unopened, and earlier unsupported outcomes remain historical evidence.

## Implementation check

The bounded correction passed the decompiler test group on macOS and Linux:
five tests passed and the opt-in live-Ghidra test was skipped in each invocation.
The subsequent real Ghidra experiment supplies the live evidence. The first
frozen run completed with 30 source-model recoveries and 60 unsupported measured
attempts; five repeats per artifact. The corrected adapter and unchanged
protocol are bound in [the correction manifest](../../experiments/limbs-observer-correction.json).

## Result and interpretation

The repeated run completed with 55 source-model recoveries and 35 unsupported
measured attempts. All remaining gaps involve control flow/user operations. The
same compiled bytes were used in both rounds. This confirms that five artifact
groups' previous failures were count-handling gaps, not protection effects.

An additional control exposed why small timing changes need caution: Clang RGB
original, identity and limbs16 binaries were byte-identical, yet median paired
CPU ratios were 1.050 for identity and 1.027 for limbs16. Even their exploratory
five-repeat intervals excluded 1. Added explicit binary-identity annotations to
summary tooling with tests; retained original summaries and produced supplemental
annotated versions without changing raw measurements. Do not attribute these
differences to changed program instructions. Details and raw evidence are in
[the exploration report](../../reports/limb-exploration.md).
