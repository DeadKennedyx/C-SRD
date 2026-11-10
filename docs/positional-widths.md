# Byte and nibble positional prototypes

## Problem and hypothesis

The existing two-piece representation does not establish a protection benefit.
The next experiment varies one factor: pieces of 16, 8 or 4 bits. The hypothesis
is that piece width can change optimized code and reconstruction cost. It may
instead only increase application overhead. The comparison includes the original
function and identity lowering, and imposes no runtime or size ceiling.

`--strategy limbs8` uses four u32 locals per represented value; `limbs4` uses
eight. These are normalized pieces, not packed byte arrays. Both use the existing
pure-u32 frontend contract and admit no pointers, effects or new C constructs.
The seed does not affect these fixed representations. `split-scale` composition
is rejected, and the automatic cost planner does not select these strategies.

```sh
build/csrd transform benchmarks/arithmetic/calculate.c -o /tmp/calculate.c \
  --strategy limbs8 --report /tmp/calculate.json
```

## Representation and operation rules

Let w be 4 or 8, B = 2^w and N = 32/w. A value x is represented by digits
a_i in [0,B-1], least significant first, such that
`x = sum(a_i * B^i) mod 2^32`. Entry extracts digits using fixed shifts and masks;
return joins them. All generated arithmetic uses the frontend's 32-bit unsigned
target model. The parameter and return ABI remains unchanged.

Addition propagates carry from low to high digits. Subtraction propagates a
borrow computed from `a_i < b_i + borrow`. Bitwise operations work independently
on digits. Fixed shifts move whole digits and combine neighboring partial digits;
zero shifts have a separate path and no C shift count reaches 32. Comparisons
inspect the most significant unequal digit. Selection tests all condition digits
and selects each output digit. Read-only lookup payloads stay split; their bounded
index requires an explicit decode, which is reported.

For constant multiplication by k, with c_0 = 0:

```
p_i     = a_i*k + c_i       (unsigned 32-bit arithmetic)
z_i     = p_i & (B-1)
c_(i+1) = p_i >> w          (except the discarded final carry)
```

Wrapping a partial product is valid: the discarded multiple of 2^32 contributes
zero to the final value modulo 2^32. This claim is checked with bit-vector
obligations, not a no-overflow assumption.

## Translation validation

The [compositional validator](compositional-validation.md) first checks the
original function against the proposed ordinary data-flow graph. It then checks
each actual reparsed C fragment against that graph, including every output digit's
range, and finally the actual return expression. Widths and digit counts are
validated; declaration names are rebound by position. Hints remain untrusted.

Dense constant multiplications made whole-word and initial digit-level checks
time out. The accepted prototype checks each scale digit in two parts:

1. Execute the actual first declaration and prove `p_i = a_i*k + c_i` for an
   arbitrary normalized input digit and **unrestricted u32 carry**.
2. Replace the proved partial product with an arbitrary u32 symbol, execute the
   actual remaining digit/carry declarations, and prove
   `(z_i + B*c_(i+1) - p_i)*B^i = 0 mod 2^32`, plus `z_i < B`.

A separate universal algebraic obligation checks the telescoping identity:

```
sum((z_i + B*c_(i+1) - a_i*k - c_i)*B^i)
  = sum(z_i*B^i) - k*sum(a_i*B^i)             (mod 2^32)
```

With c_0 = c_N = 0, the proved digit equations establish the whole-word invariant.
The last weight discards the carry beyond bit 31. The checker requires complete
ordered steps, a checked first-declaration partial, a literal-zero final carry,
and no hidden dependencies between fragments. Reports retain the nested actual-C
obligations, algebraic bridge, hashes and rebound partial/carry names.

The shared deadline is unchanged: all width proposals together receive at most
half the overall verification budget; each local query gets at most one second.
Unknown prevents publication unless the independent whole-function fallback
proves the actual candidate. The partition checker, C semantic model and solver
remain trusted; this is not an independently certified compiler proof.

## Validation and experiment protocol

`tools/verify_positional.py` checks universal formulas for both widths, including
all fixed shifts and deliberately wrong carry, borrow, factor and telescoping
rules. Integration tests cover 98 function contracts, boundary/random executions
under GCC and Clang, O0/O2 and ASan/UBSan, dense factors, renamed declarations,
independent SMT replay and actual-C corruption. Unit tests corrupt proof hints,
ranges, partials, carry operations and return values. The unchanged 16-bit emitter
is a regression control.

The development comparison uses CRC32 byte, Jenkins word, Morton16 and integer
RGB weighting. It records compiler capabilities and gaps, correctness, linked
function structure/size, paired runtime, compilation and verification cost, and
fixed-observer reconstruction resources and outcomes. Reserved algorithm families
remain closed for reconstruction. Observer limits, grading failures and timeouts
are reported separately from successful reconstruction effort.

This is established positional arithmetic. [Tigress EncodeData](https://tigress.wtf/encodeData.html)
documents related representations, including byte/nibble splits; [GNU MP's
integer model](https://gmplib.org/manual/Integer-Internals) uses positional limbs
for arbitrary precision. Neither smaller pieces nor more operations demonstrates
confidentiality. A memory observer can combine pieces; that capability requires
its own evaluation. See the [research journal](journal/2026-11-10-positional-widths.md)
for prototypes, failures and measurement decisions.
