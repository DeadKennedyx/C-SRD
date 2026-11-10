# Fixed-index buffer contract: buffers-u32-c11-v1

This is the first bounded C1 implementation contract. It extends the existing
pure-function model through a separate ordered memory path. It does not change
the meaning of proofs for previously supported pure functions.

## Admitted programs and domain

* A prototyped `uint32_t` return, scalar `uint32_t` parameters, and named
  `uint32_t *` or `const uint32_t *` parameters. Equivalent typedefs are accepted
  under the existing 32-bit unsigned-int host model. Pointer qualifiers, array
  parameter declarators, attributes, pointer locals and pointer assignments are
  excluded in this increment.
* Straight-line initialized scalar declarations, scalar assignment, stores and
  one final return. Expressions contain unsigned addition, subtraction and
  literal multiplication. Loads/stores use `p[0]` through `p[15]`, or `*p`.
  Indexes must be integer literals, not runtime variables. Other control flow,
  operators, calls, global accesses, escapes, volatile/atomic objects and
  concurrency remain excluded for functions with pointer parameters.
* Each pointer with accesses denotes valid, aligned, live, nonvolatile and
  nonatomic uint32 storage for
  the reported minimum number of elements (`maximum accessed index + 1`). The
  prefix must lie within one live array object (a scalar suffices for a one-word
  prefix); physically adjacent unrelated objects do not suffice. The admitted
  prefix is initialized. Stores require writable objects. These are
  caller preconditions, not runtime checks inserted by C-SRD. An unused pointer
  requires zero elements and can be null. Accessed pointers cannot be null.
* Pointers may designate the same or overlapping storage. There is no assumed
  `restrict` or distinctness. Accesses to globals or caller locals through the
  admitted pointers are covered when these same preconditions hold.
* The ordinary-memory boundary is preserved: loads enter an encoded scalar
  region and stores/returns leave it. Pointer values and external storage are
  never encoded. Private scalar locals cannot escape.

## Observable behavior and validation

For every admitted scalar input, initial memory and pointer-alias arrangement,
original and candidate must have equal returns and equal entire final memory.
Equality of whole memory includes untouched regions. Finite straight-line
execution terminates under the domain assumptions. Nonvolatile reads alone
within an expression can be evaluated in either order; no calls or writes can
occur inside expressions. Stores retain full-expression sequence order.

The verifier reparses actual emitted C with Clang. It models one shared SMT
array from mathematical word addresses to 32-bit bit-vectors. Each pointer
parameter has an unconstrained integer base. Access `p[k]` selects or stores at
`base(p) + k`; independently chosen bases include equal and offset aliases.
This abstraction covers all defined aligned uint32 accesses in this subset;
it is not a general C pointer/provenance or byte-memory model. Pointer values
are never compared, converted or exposed by admitted programs.

The candidate must have matching parameter kinds/constness and require no
larger prefix of any pointer than the original. Its post-state is evaluated
sequentially from the same initial array. The obligation asks whether either
the return or final array differs. UNSAT is `proved-under-model`, conditional
on the frontend, model, solver and caller preconditions; SAT is a counterexample;
timeout is inconclusive. Output requires a successful actual-artifact check.
The current pure graph cannot remove or reorder memory effects.

Only identity and affine emission are initially admitted. Algorithm replacement,
other representation strategies and control-flow candidates are explicitly
rejected for this path. Unsupported functions remain unchanged with a reason.
No option weakens the validation gate.

## Prespecified validation

Use seeds 0, 42 and UINT64_MAX. Compile separate original/candidate objects with
available GCC and Clang at O0/O2/O3/Os and supported LTO profiles, plus Clang
ASan/UBSan. Exercise edge values and deterministic xorshift32 data, same-pointer,
partially overlapping and disjoint buffers. Compare every cell including guards,
not just returns. Include unused/null pointers without dereferencing them.

Negative verification controls change only a store, clobber an otherwise
untouched cell, reorder alias-sensitive accesses, change a literal index,
increase a footprint, or change the signature. Require detection and replay a
memory-only counterexample. Check conservative rejection of dynamic indexes,
pointer arithmetic, escapes, calls, control flow and unsupported qualifiers.

An independent CBMC harness investigation is supplemental evidence, with exact
object sizes, pointer configurations and unwinding checks reported explicitly.
It does not replace the mandatory SMT post-state check or imply arbitrary C
coverage. Existing pure-function reconstruction observers do not accept
this memory interface. A [separate buffer observer](buffer-reconstruction.md)
now reconstructs ordered loads/stores and validates final memory; its admitted
binary operations and runtime sampling scope are explicit.

Published reference: [Tigress EncodeData](https://tigress.wtf/encodeData.html)
motivates explicit handling of aliases and representation boundaries. This
implementation uses ordinary external memory and claims no new encoding law.
