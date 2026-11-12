# Typed private integer frames: private-integer-frame-c11-v3

This extension retains the [private-object and unchanged-context contract](private-regions.md).
It transforms finite scalar declaration/assignment regions; surrounding calls,
loads/stores, branches and loops remain ordinary C. It does not turn the program
into a verified whole-program memory, I/O or concurrency model.

The admitted types are unqualified automatic standard C integer types and
compatible typedefs: `_Bool`, signed/unsigned/plain char, short, int, long and
long long. The target model requires 8-bit bytes, 16-bit short, 32-bit int,
32/64-bit long and 64-bit long long. Clang supplies effective expression types,
integer promotions, usual arithmetic conversions and plain-char signedness.
Enums, extended integer types, volatile/atomic objects and floating point are
excluded. A generated static assertion checks the recorded data model.

The signed model explicitly assumes two's complement, modulo conversion for
out-of-range conversion to signed types, and arithmetic right shift of negative
signed values. These are [documented GCC choices](https://gcc.gnu.org/onlinedocs/gcc/Integers-implementation.html),
not guarantees for every ISO C11 implementation. Compatibility with particular
Clang builds is tested separately. The model does **not** define signed overflow,
negation of the minimum signed value, or invalid signed left shifts. Equivalence
is required only where the original computation is defined; the candidate must
also be defined there. Empty original defined-input domains are rejected.

Supported expressions include integer literals/references, parentheses,
integral casts, addition, subtraction, multiplication by a constant, unary
plus/minus, complement, bitwise AND/OR/XOR, logical NOT, comparisons, conditional
expressions and shifts with a constant count below the promoted left width.
Signed left shifts require a nonnegative operand and a representable result.
The original conditional expression evaluates only its selected branch. Generated
unsigned arithmetic may evaluate both encoded branches because those operations
are total. General multiplication, division/remainder, short-circuit AND/OR,
increment and compound assignment remain boundaries.

## Representation and conversions

One odd 64-bit multiplier `a` and offset `b` supply compatible representations
at widths `n ∈ {1,8,16,32,64}`:

`E_n(x) = (a*x+b) mod 2^n`.

Addition, subtraction, negation and constant scaling use the affine laws directly.
Narrowing to an ordinary integer width takes the low encoded bits, without
decoding, because reduction commutes with these modular affine maps. `_Bool`
conversion instead tests whether the ordinary value is nonzero; taking a low bit
would be incorrect. Widening, bitwise operations, comparisons and shifts currently
decode and re-encode. The report counts these conversions separately.

All stored encoded temporaries are unsigned long long, explicitly masked to the
represented width. Six Newton steps compute the inverse modulo 2^64. Negative
signed outputs use bounded casts and `~(mask-raw)` in a guarded branch; this
avoids relying on an out-of-range signed cast in generated restoration. Signed
widening and right shifts use this restoration and the declared implementation
model. No runtime support library is required.

## Compositional translation validation

The emitter proposes checkpoints after entry capture and each original source
statement. A fresh copy temporary makes each cut identifiable even for a
constant-only assignment. These copies can be removed by normal optimization.
The hints are not evidence: the validator resolves their declarations and cuts
against the reparsed emitted C and proves every fragment.

The invariant relates **every initialized source scalar** to a distinct initialized
unsigned-64 candidate temporary:

`temporary = zero_extend(E_width(source_bits))`.

The entry fragment establishes this relation. Each subsequent candidate fragment
must remain defined and re-establish it whenever the corresponding original
statement is defined. After a successful check, the verifier forgets all other
correlations: original scalars become arbitrary values, candidate scalars become
arbitrary values except for the proved encoding relation. This is a conservative
overapproximation of reachable states. It can reject a valid implementation, but
does not assume an unchecked fragment is correct. Finally, actual output
restoration must be defined and return all original scalar values.

All source statements and all candidate statements are covered exactly once;
candidate cuts must increase, mappings must be complete, and all ordinary output
bindings/types/scopes are checked. A failed hint may fall back to a whole-frame
query within the remaining budget. A local invariant countermodel is not labeled
a reachable program counterexample. Timeout or unsupported arithmetic prevents
output unless another complete validation succeeds.

Reports retain the nonempty defined-domain query, checkpoint relations, individual
SMT obligations and tactics, failed attempts and artifact hashes. The model uses
`(2^n-1)-x` for bitwise complement; a separate generic bit-vector check compares it
with `bvnot`. Z3's conditional-term expansion exposes polynomial cancellation
before bit-vector solving. Solver success is `proved-under-model`, with Clang,
the model, checker and solver trusted; this is not an independently checked
proof certificate or a proof of the C compiler/machine code.

## Measurement gate

`private_integers.c` is a benign mixed-width workload using the existing three-word
buffer and two callback interfaces. Its signed arithmetic is range-safe for the
declared full u32 input domain and finite test loop counts. An independent Python
oracle checks return values, all three memory words and ordered callback events.
Correctness tests include GCC/Clang optimization profiles and Clang sanitizers.

Protection measurement compares original, identity, affine seed 42 and a byte-copy
control under matching builds. The initial observer pilot uses Linux ARM64
Clang/GCC at O0/O2, three fresh-process reconstruction repetitions, six training
plus six held-out runtime observations per scenario, and
seven application-cost repetitions of one million workload iterations. These
choices are a development pilot, not a universal build/observer claim.

The first reconstruction passes used 512 grading inputs. Two observer corrections
require a new matched run on the frozen candidate binaries: an isolated Ghidra
signed-byte instruction overlay and type-directed Boolean constants in exported
high P-code. The final follow-up uses 1,024 inputs and seed 20261112. Although
the seed is new, the fixtures informed these corrections, so this is a development
follow-up, not a blind benchmark. Original, identity, affine and copy controls all
receive the same corrected observer. The original failed runs are retained.

The extended observer records full64 as well as low32 general registers and
4/8-byte views within 64 bytes of stack, plus the three low32 caller words.
Targets have explicit 1/8/16/32/64-bit widths and signed values are graded by
their bit patterns. No SIMD or exhaustive heap/stack coverage is claimed. Missing
locations and insufficiently varying targets remain measurement gaps. It still
requires known intermediate labels and fits one-location affine maps, rather than
autonomously discovering semantics. False models and permuted-label matches are
reported. Human effort remains unmeasured.

A match on a one-bit target supplies very little evidence: only two values exist,
and many unrelated locations can agree by chance on a small held-out set. Report
results by width, with failed held-out models and permuted-label controls, rather
than treating all matches as equally informative or as recovered secret keys.

The [matched measurement checkpoint](../reports/private-integers.md) records
the completed development comparison. It establishes no worthwhile protection
advantage for this affine prototype. Further coverage keeps its own correctness
and measurement gate; these results cannot substitute for new memory or effect
contracts. See the [development journal](journal/2026-11-10-typed-integers.md)
for failed prototypes and observer corrections.
