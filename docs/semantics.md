# Semantic contract: pure-u32-c11-v2

This document defines the existing pure path. Functions with admitted pointer
parameters use the separate [buffers-u32-c11-v1 contract](buffer-contract.md):
fixed-index loads/stores, straight-line affine arithmetic and equality of return
plus entire final memory. Each function's report identifies its semantic model.
The restrictions below remain unchanged for the pure path.

For each accepted function P with n arguments, D is `{0,...,2^32-1}^n`.
The required relation is equality of returned values for every input in D,
termination on both sides, and an empty external effect trace. Automatic local
writes and by-value parameter writes are private. Equal return values establish
the relevant behavior only because this subset excludes external memory writes,
I/O, calls, volatile/atomic accesses and concurrency.

## Acceptance rules

* Clang parses `-std=c11 -pedantic-errors` on the host target. Both `int` and
  `unsigned int` must be 32 bits; canonical `uint32_t` must be unsigned int.
* Main-file prototyped definitions, named unqualified uint32 parameters/return,
  no varargs, parameter storage modifiers or function/parameter attributes.
  Equivalent typedefs are accepted. Signatures and linkage remain unchanged.
* Automatic initialized single-variable uint32 declarations at function top
  level, simple assignments to initialized locals/parameters, one final return.
  No declarations inside branches/loop bodies, shadowed loop-index names,
  explicit storage classes, scalar qualifiers or braced scalar initializers.
* Parentheses; nonnegative int/unsigned-int literals; unsigned 32-bit add,
  subtract, multiplication with one literal operand; bitwise AND/OR/XOR/NOT;
  shifts with literal counts 0–31; unsigned comparisons; uint32 ternary results.
  Literal-to-unsigned and comparison-result-to-unsigned conversions are modeled.
  General multiplication, division, dynamic shifts, signed/wider arithmetic,
  enum/character values, explicit value casts and compound assignments are rejected.
* A `(void)x;` statement may discard a pure initialized uint32 reference. This
  keeps pruned parameter uses warning-clean. Other cast statements are rejected.
* `if/else` may contain assignments and supported nested control only. Conditions
  are supported expressions. Early returns, break/continue and effects are rejected.
* Loops must be `for(uint32_t fresh=0; fresh<N; ++fresh)` (postincrement also
  accepted), with literal N in 0–32. The index cannot be assigned in the body.
  Nested loops need fresh function-wide names; each is exactly unrolled. The
  graph budget limits total expansion. There are no general loop invariants.
* Local automatic arrays contain 1–16 uint32 elements with literal initialization;
  const elements and implicit zero-fill are allowed. No designated initializers,
  writes, pointer escapes, address operations or sizeof uses are accepted.
  An index upper bound must be less than the table length. Bounds derive from
  literals, masks, right shifts, comparisons, selections, table contents, and
  non-wrapping upper bounds for addition/constant scale. Unknown bounds are MAX.
  Branch bounds merge by maximum. At loop entry ordinary scalar bounds are
  invalidated; immutable active induction-variable bounds survive. Zero-trip
  loops restore incoming bounds. Thus first-iteration facts cannot unsafely
  justify a later array access.
* Every scalar read refers to an initialized local or parameter, checked through
  Clang declaration identity. Global reads, pointers, calls, floats, VLAs,
  inline assembly, volatile/atomic operations and concurrency are rejected.
* Macro expansions (including empty macros), directives and pragmas within the
  function prevent rewriting. Clang raw lexing also sees skipped directives.
  Macros for generated keywords `unsigned`, `int`, `void` disable rewriting.
  Generated temporary names avoid all preprocessor identifiers and raw source names.

Rejection leaves the complete function body unchanged, with the first located
diagnostic. Invalid C aborts the translation unit. Resource-limit rejections
also remain unchanged; proof failure for a candidate aborts C output entirely.
Unchanged functions are not thereby verified or repaired.

## Representation laws

Affine arithmetic is in R = Z/(2^32). `E(x)=a*x+b`, odd a, inverse i with
`i*a=1`; `D(z)=i*(z-b)`.

| Ordinary operation | Encoded implementation |
| --- | --- |
| c | a*c+b, evaluated at transformation time |
| x+y | E(x)+E(y)-b |
| x-y | E(x)-E(y)+b |
| k*x | k*E(x)+(1-k)*b |
| decode | i*(z-b) |

Odd a is relatively prime to 2^32. Five Newton updates `i=i*(2-a*i)`, starting
at 1, double correct low bits from 1 to 32. Solver-checked low-bit lemmas support
this argument; they are not a mechanized proof of the C++ inversion code.

XOR representation uses `X=x^m`, `Y=y^m`, and is its own inverse:

| Ordinary operation | XOR-encoded implementation |
| --- | --- |
| x^y | X^Y^m |
| x&y | (X&Y)^((X^Y)&m) |
| x\|y | (X\|Y)^((X^Y)&m) |
| ~x | ~X |
| x<<k | (X<<k)^(m<<k)^m |
| x>>k | (X>>k)^(m>>k)^m |

Shifts require k<32 and logical unsigned semantics. XOR arithmetic and affine
bitwise operations are not falsely treated as native: the graph inserts ordinary
conversions or chooses another representation. Comparisons and selection
conditions are ordinary values; selection payloads may share any representation.
Table payload literals can be encoded at compile time. Cross-representation
conversion composes decode/encode and is shared per producer/destination.

All generated constants are in uint32 range with `u` suffixes; generated
arithmetic is unsigned int under the admitted model. No signed overflow or
undefined shift is introduced. Source effects are absent and pure expression
values are materialized once, so expanded formulas cannot duplicate side effects.

## Preservation and scope

Each graph value labeled R represents R(original value). Entry conversion and
encoded constants establish this invariant; operation laws and compatible
selection payloads preserve it; the return is converted to identity. Assignment
versioning and pure branch merging preserve dependencies. Exact finite unrolling
preserves termination. These are mathematical arguments conditional on correct
implementation, supplemented by validation of each actual emitted artifact.

The optional algorithms count only the low eight bits of a unary uint32 input.
Serial extraction and SWAR field aggregation are distinct known algorithms.
An explicit request selects a candidate; the original need not have a particular
name or spelling, and replacement is rejected unless the full-input equivalence
query succeeds. This is not automatic discovery of arbitrary algorithms.

Compile in the same target/data model and compatible preprocessing environment.
The tool records source and included-buffer SHA256 hashes. Its reparse maps the
candidate at the original path and checks unchanged dependencies. Output paths
can change later include resolution or untransformed `__FILE__`; the report is
not a proof about arbitrary builds. Physical newline counts are preserved for
later `__LINE__`. Timing, debug information, binary identity, inaccessible local
layout and side-channel behavior are outside the contract. No constant-time or
confidentiality claim is made.
