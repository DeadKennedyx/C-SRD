# M1 semantic contract

Let `P` be an accepted function with `n` arguments. Its domain is
`D = {0,...,2^32-1}^n`. The intended contract is
`T(P,s)(x) = P(x)` for every `x` in `D`, with termination and an empty external
effect trace on both sides. Functions have no externally visible memory writes,
calls, I/O, volatile accesses or atomic accesses. Writes to automatic locals and
by-value parameter objects are private. These restrictions make equal return
values sufficient **for this subset**, not for arbitrary C programs.

## Exact acceptance rules

* C11 parsed by Clang with `-std=c11 -pedantic-errors`. Keyword macros are
  accepted by the parser but conservatively prevent rewriting.
* A main-file function definition with a written prototype, no variadic
  arguments and no function attributes (including prior declarations).
* Return and named parameters have the unqualified canonical type `unsigned
  int`; `int` and `unsigned int` must both be 32 bits. On validated targets this
  includes `uint32_t` and its aliases. Targets with `uint32_t` implemented as a
  different integer type are conservatively unsupported.
* A single compound body, consisting only of single-variable initialized
  automatic declarations, simple `local = expression;` assignments, and one
  final `return expression;`. Explicit auto/register/static/extern storage, attributes and
  qualified locals or parameters are excluded. `(local)` assignment targets
  are accepted. Braced initializers, declaration lists and nested scopes are not.
* Expressions: initialized local/parameter references, nonnegative `int` or
  `unsigned int` literals, parentheses, unsigned 32-bit `+`, `-`, and `*` with
  at least one literal operand. Constant expressions such as `(2u+3u)` are not
  recognized as a literal multiplier. `3 * x` is supported; `3 * 5` is signed
  arithmetic and is rejected; `3u * 5u` is supported.
* Implicit lvalue-to-rvalue conversions and safe conversions of a nonnegative
  `int` literal to unsigned int are accepted. Wider arithmetic, explicit casts,
  enums, character constants, unary operators, shifts, comparisons, bitwise
  operations, comma/conditional expressions, compound assignments and calls are
  rejected. No expression is assumed safe merely because it could be folded.
* Every read refers to an object already initialized earlier in the region or
  to a parameter. A local is added to that set after its initializer validates.
* Macro invocations anywhere in the declaration/body, including empty
  expansions, prevent transformation. Preprocessor directives and pragmas in
  the function also prevent it. Raw Clang lexing finds directives in skipped
  branches. Macro definitions of generated type keywords (`unsigned`, `int`)
  anywhere in the translation unit conservatively disable rewriting.

Declarations from headers and unsupported function bodies are not rewritten.
If any statement fails, the whole function stays byte-for-byte unchanged, with
the first detected reason and a source location. The tool is deliberately
incomplete: rejecting safe programs is preferable to accepting uncertain ones.
Clang parse errors (including invalid C and prohibited extensions) abort output.

## Representation rules

All equations are in `R = Z/(2^32)`. Let `E(x)=a*x+b`, with odd `a`, and let
`i*a=1` in `R`. Decoding is `D(z)=i*(z-b)`.

| Operation | Encoded result | Why it is valid |
| --- | --- | --- |
| Constant `c` | `a*c+b` | Definition of `E` |
| `x+y` | `E(x)+E(y)-b` | Expands to `a*(x+y)+b` |
| `x-y` | `E(x)-E(y)+b` | Expands to `a*(x-y)+b` |
| `k*x` | `k*E(x)+(1-k)*b` | Expands to `a*k*x+b` |
| Return | `i*(E(x)-b)` | `i*a*x=x` |

An odd integer is relatively prime to 2^32 and therefore has a unique modular
inverse. The C++ implementation computes it by five Newton steps starting at
one: `i := i*(2-a*i)`. Each step squares the current error and doubles the
number of correct low bits. The implementation is unit tested; the general
inverse algorithm has not been mechanically proved here.

Generated constants have `u` suffixes and fit in 32 bits. All generated operands
are unsigned int on the admitted target. C's unsigned wraparound consequently
implements the ring directly, including subtraction underflow and large
products. There are no signed overflow assumptions, pointer manipulations or
extra evaluations of source expressions.

## Preservation argument and its limits

The invariant after every statement is: every live transformed local contains
`E` of its original value. Entry encoding establishes it for parameters. The
expression rules preserve it by structural induction; declarations and
assignments preserve it for subsequent statements. Final decoding recovers the
original return. Both programs terminate because their accepted bodies contain
only finitely many nontrapping unsigned operations.

This is a mathematical argument conditional on faithful AST analysis and C
emission. It is not an end-to-end mechanized proof of this implementation.
The independent solver contracts establish the algebraic identities; compiler
and differential tests exercise their realization. See [verification](verification.md).

Compile generated C with the same integer data model, compatible headers and
preprocessing environment. C-SRD currently uses the host Clang target and
records its triple; it does not accept arbitrary target/compile flags. Function
signatures, linkage and surrounding source are retained. No helper symbols are
introduced. Physical newline counts are preserved so later `__LINE__` uses are
stable, but comments and formatting inside accepted bodies are not preserved.

The contract covers transformed pure functions and their compatible callers,
not arbitrary whole-translation-unit environmental behavior. In particular,
changing the output filename/location can change `__FILE__`, include resolution
or external build inputs; compile in a controlled environment. Unchanged code
may itself have undefined behavior; C-SRD neither repairs nor verifies it.
Timing, object layout of inaccessible locals, debugging information and binary
identity are not observations in this functional contract. No constant-time or
side-channel-preservation claim is made.
