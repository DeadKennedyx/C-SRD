# Verification status and methodology

Verification is part of the development gate. Transforming a file does not
automatically verify that file: its manifest says
`not-verified-for-this-input`. Status labels must retain their scope.

| Status | Evidence required | Current scope |
| --- | --- | --- |
| Tested | Listed inputs, seeds, compiler versions, configurations and actual results | Representation C++ implementation, CLI rejection behavior, generated arithmetic corpus and emitted C |
| Bounded-model checked | Explicit bounds, environmental assumptions and successful model-checker run | None; CBMC has not been integrated or run |
| Formally proved under assumptions | Precisely stated semantics/assumptions and discharged obligations | Three bit-vector arithmetic identities checked by Z3 for all 32-bit symbols; six concrete-multiplier round-trip identities for all values/offsets, trusting Z3 |
| Not yet verified | No applicable evidence | Complete AST-to-C implementation, arbitrary new inputs, cross-region optimizer, unsupported C constructs |

The SMT files pose negations of equalities as existential counterexample
queries. `unsat` means no counterexample exists in the full 32-bit domain of
that formula; this is not random testing or enumeration at a small width.
Addition, subtraction and scaling are checked for symbolic `a,b,x,y,k`. Oddness
is unnecessary for those three identities, but necessary for decoding.
Round-trip checks explicitly list six multipliers rather than imply coverage of
every odd multiplier. A missing-offset correction is deliberately checked as a
negative control and produces a saved `sat` counterexample.

These obligations are independently written specifications. They do not parse
or prove the C++ implementation, emitted C, preprocessing behavior, compiler
backend, or Newton inversion for all multipliers. Z3's simplifier/solver are in
the trusted computing base; no separately checked proof certificate is emitted.
Timeouts, `unknown`, malformed output and failed obligations cause a nonzero
exit. [Z3's bit-vector guide](https://microsoft.github.io/z3guide/docs/theories/Bitvectors/)
documents the fixed-width theory used here.

## Empirical pipeline

1. Run numeric identity and affine rule tests on boundary values and deterministic
   `mt19937` inputs. Assertions are ordinary checks, so Release builds retain them.
2. Exercise the actual CLI against unsupported types, operators, effects,
   macros/directives, initializations, source errors, seed errors and path aliases.
3. Transform the fixture and 24 deterministic generated straight-line functions
   at seeds 0, 42 and 18446744073709551615. Check that expected functions really
   transformed, so a no-op transformer cannot pass the suite accidentally.
4. Compile original and variant as separate objects under each compiler and
   optimization setting, using identical flags apart from symbol renaming.
5. Compare every function on 81 boundary pairs and 20,000 seeded random pairs.
   A failure reports function name and exact input. Clang sanitizer builds use
   ASan and UBSan with recovery disabled, covering original and variant.
6. Save compiler identity, corpus hash, variant hashes, seeds, flags, input
   count, comparison count and test costs. The harness costs do not establish
   relative performance of either implementation.

The generated functions share a grammar and are not an independent real-world
benchmark population. Three seeds are not exhaustive representation coverage.
Equal results on finite inputs are evidence only. The XOR negative control is
currently an unchanged-code fixture; no recognition accuracy is reported.

Run commands are in [README](../README.md). Actual checked results, missing tools
and platform differences belong in [the validation record](../reports/m1-validation.md).
CI must require both compiler families instead of silently accepting a missing
GCC installation. Locally, missing families are printed as `SKIP` unless
`CSRD_REQUIRE_BOTH_COMPILERS=1`. Missing Z3 excludes its CTest test at configure
time and must be reported; it is installed in CI.

## Next validation layer

Implement translation validation of each accepted IR pair against a bit-vector
specification, with source locations and counterexamples, then connect that
result to the exact source/configuration hashes. A CBMC harness can separately
compare generated C to its original with nondeterministic parameters; unwinding
assumptions must remain explicit when loops eventually appear. CBMC unwinds C
programs into solver queries, while Frama-C WP discharges ACSL obligations via
weakest preconditions and selected memory models.
[CBMC documentation](https://diffblue.github.io/cbmc/cprover_documentation.html),
[Frama-C WP](https://frama-c.com/fc-plugins/wp.html).

Alive2 is relevant after compiling to LLVM IR, where its translation-validation
scope and UB/refinement model apply. An LLVM-level result cannot by itself prove
the source preprocessing or AST rewrite. See
[Alive2: Bounded Translation Validation for LLVM](https://users.cs.utah.edu/~regehr/alive2-pldi21.pdf).
