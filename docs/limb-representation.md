# Two-piece positional representation prototype

## Problem, hypothesis and scope

Affine and XOR representations repeatedly convert at mixed-operation boundaries.
The `limbs16` prototype instead represents one u32 as two u32 locals containing
16 bits each. Hypothesis: carrying the pieces across arithmetic and bitwise work
changes compiled data flow and may change measured reconstruction effort. This
must be measured against original and identity-lowered controls. It is not an
assumption of protection, nor is positional splitting secret sharing.

`csrd transform input.c -o output.c --strategy limbs16 --report report.json`
selects this fixed representation for a whole admitted graph. The seed is accepted
but does not change it; reports say so. It is not yet a choice in the cost-based
planner. `split-scale` composition is rejected. Existing frontend restrictions
and mandatory emitted-source verification still apply. A proof timeout prevents
output, even when individual mathematical rules have passed.

## Mathematical contract

Let B = 65536. Encode x as L = x mod B, H = floor(x/B); decode as L | (H << 16).
Both pieces are maintained in [0, B-1], with every C operation evaluated as
unsigned 32-bit arithmetic under the documented target model.

| Operation | Low piece | High piece |
| --- | --- | --- |
| Addition | `(Lx+Ly) mod B` | `(Hx+Hy+floor((Lx+Ly)/B)) mod B` |
| Subtraction | `(Lx-Ly) mod B` | `(Hx-Hy-[Lx<Ly]) mod B` |
| Constant scale k | `p mod B`, where `p = Lx*k mod 2^32` | `(Hx*k+floor(p/B)) mod B` |
| AND/OR/XOR | Corresponding operation on low pieces | Corresponding operation on high pieces |
| Complement | `Lx XOR (B-1)` | `Hx XOR (B-1)` |

Fixed shifts move bits across the piece boundary; counts 0, 16 and 31 have
explicit paths without shifting by 32. Ordering compares high pieces first and
low pieces on a tie. Equality checks both pieces. Selection tests whether either
condition piece is nonzero. Table payloads remain split; the bounded table index
is an explicit internal decode. Parameters split at entry and the return joins
at exit. Constants split at generation time. No entropy calls, pointers, new
external effects or runtime library dependencies are introduced.

The scale proof uses two universal lemmas: distribution over `L+B*H`, and
reassembly of arbitrary partial products `p+B*q` from `p mod B` and
`(q+floor(p/B)) mod B`. This establishes the formula for every 32-bit k without
assuming no intermediate overflow.

## Implementation and evidence requirements

`src/codegen/limbs_emitter.cpp` consumes the same admitted data-flow graph and
emits collision-safe locals for each pair. Conversion sharing follows graph
reuse. Counts describe explicit source operations and conversions; they do not
measure machine-level exposure. A half can itself equal the full original value
for small inputs, and comparison results remain directly readable.

`tools/verify_limbs.py` supplies 82 solver obligations: roundtrip/place value,
arithmetic, scale lemmas, bitwise work, every legal shift count, comparisons,
selection and a wrong-borrow counterexample. Integration tests reparse and prove
88 generated function contracts, compile them under GCC and Clang at O0/O2 and
O1 with ASan/UBSan, and compare boundary/random executions. An actual emitted
mask mutation must also be rejected. Rule proofs alone never permit output.

The general verifier can reparameterize its symbolic input into two independent
16-bit halves after a direct query is inconclusive. This is a bijection over all
u32 inputs, not a smaller test domain. The report retains the actual final SMT
query and reconstructs counterexample inputs as full u32 values. Timeout budgets
are divided among solver attempts; no unknown result is accepted.

## Prior art and interpretation

Positional arithmetic is established multi-precision arithmetic. Tigress documents
both positional `bignum` representations and bit-slice codecs. This prototype's
narrow focus is explicit u32 contracts, independent emitted-C validation and
measured compiler/observer behavior; no novelty or superiority has been shown.
[Tigress EncodeData](https://tigress.wtf/encodeData.html)

Inspect original, identity and limb candidates under the declared compiler
matrix. Compare successful reconstructions at matched budgets, while retaining
coverage gaps, wrong answers and proof failures. A debugger that combines both
pieces can recover the value; measuring only absence from a single location
would be an inadequate test. Multi-location runtime inference and human studies
remain separate unfinished tasks.
