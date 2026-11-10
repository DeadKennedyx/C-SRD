# Bounded wide-value and AArch64 vector reconstruction

## Problem, hypothesis and scope

The frozen positional-width study left nine build cells outside the observer's
model. Width and signed-shift errors hid a second layer of named vector
operations and constant-pool inputs. The hypothesis is that explicit semantics
for those operations will recover more equivalent functions. Unsupported
operations and proof timeouts are missing evidence, not protection successes.

This extends the independent Ghidra observer. It does not expand the C
transformer's accepted language, change the frozen binaries, or add a protection
technique. The public observer interface remains one to four u32 arguments and
one u32 result. [CFG validation and expansion bounds](pcode-control-flow.md)
remain in force. Earlier schema-1/2 exports stay replayable with their recorded
facts; the observer never invents missing vector names or memory bytes.

## Value model and lowering

Payloads have explicit widths of 1–16 bytes, including non-power-of-two widths.
A wide value is an ordered tuple of normalized unsigned 32-bit components,
least significant first. The final component may have fewer than 32 meaningful
bits. This is numerical significance order, independent of host byte order.
The output C uses only unsigned-int operations on the existing 32-bit ABI.

| Operation | Lowering and conditions |
| --- | --- |
| Copy, bit-preserving cast, bitwise operations | Copy or operate component by component; normalize the final component |
| Addition/subtraction | Propagate unsigned carry/borrow, discard overflow at the declared width |
| Multiplication | At least one exact constant operand; base-65536 schoolbook products, bounded u32 partial sums |
| Zero/sign extension | Copy low bits and fill high bits with zero or a mask derived from the original sign bit |
| Logical/arithmetic shifts | Exact constant count; combine adjacent components; counts at least the width produce zero or sign fill |
| `PIECE(high, low)` | Concatenate high bits above low bits; output width must equal their sum |
| `SUBPIECE(value, byte_offset)` | Exact byte offset, extraction entirely within the input; combine crossed word boundaries |
| Equality and unsigned comparisons | Compare normalized components from high to low |
| `MULTIEQUAL` | Select the complete value from the incoming edge slot, with simultaneous merge assignment |

No C shift reaches 32 bits. Sign extension and arithmetic right shift use
unsigned masks rather than implementation-defined signed C operations. General
multiplication and signed comparisons remain unsupported. Exact constant
propagation uses mathematical integers normalized to the declared width; no
sample-based inference establishes a constant.

These rules implement established [Ghidra P-code semantics](https://ghidra.re/ghidra_docs/languages/html/pcodedescription.html),
including the high/low order of `PIECE`, low-byte units of `SUBPIECE` and sign
fill for oversized `INT_SRIGHT`. [Additional P-code semantics](https://ghidra.re/ghidra_docs/languages/html/additionalpcode.html)
define bit-preserving `CAST` and incoming-edge merge selection.

## Explicit vector and memory facts

Schema 3 adds the language's symbolic user-op table and immutable mapped-byte
snapshots. New vector and memory facts are admitted only for the pinned Ghidra
12.2 `AARCH64:LE:64:v8A` language with memory model
`immutable-mapped-constants-v1`. User-op numbers are resolved through the
exported language table, never guessed from their numerical values.

Only these 64/128-bit operations are modeled:

* `NEON_ext`: select a vector-sized byte window from the concatenation of two
  vectors, with a fixed valid byte offset and byte lanes.
* `NEON_rev64`: reverse 1-, 2- or 4-byte lanes within each 64-bit block.
* `NEON_ushl`: independently shift unsigned 1-, 2-, 4- or 8-byte lanes. Each
  count is the signed least significant byte of its count lane. Negative counts
  shift right; nonnegative counts shift left. Oversized counts give zero. The
  complete count vector must be an exact known value.

Argument order and lane metadata follow the pinned installed AArch64 SLEIGH
source, `Ghidra/Processors/AARCH64/data/languages/AARCH64neon.sinc`.
[Arm's instruction reference](https://documentation-service.arm.com/static/6245c734b059dc5ff9a8bdab)
supplies the instruction semantics. Unknown user operations, dynamic vector
counts and malformed widths or lane metadata are rejected.

A nonparameter memory input may become a constant only when all its bytes lie
in one readable, initialized, nonwritable mapped block with no relocation in
the interval. The export retains the byte sequence, byte order, address, block
bounds and permissions. The adapter validates those fields and interprets the
bytes as little endian. Execute permission is recorded but does not determine
mutability: this Ghidra import marks some `.rodata` blocks executable.

The explicit experiment assumption is that these mapped bytes stay immutable.
There is no general memory read, pointer traversal, store, external call or
mutable-global model. Unresolved registers and missing snapshots are rejected.
Permissions and mapping metadata are trusted export facts, not proofs about an
arbitrary runtime environment.

## Validation and interpretation

`test_pcode_wide.py` generates actual C and compares its Clang-derived mismatch
formula against independently specified SMT operations. A free marker parameter
is constrained to the expected output component; UNSAT then proves equality for
all data inputs in that obligation. This checks 1,457 component obligations over
all 16 payload widths, selected extension/extraction shapes and shift boundary
counts. The wide multiply obligations use coefficient 65537, reduced to the
payload width; they are not a metatheorem over every coefficient or operation
sequence. Separate compiled checks compare 1,457 outputs on 113 vectors.

`test_pcode_vector.py` checks 554 actual-C component obligations, all valid EXT
offsets, all admitted REV64 lane sizes and boundary USHL counts. Compiled checks
compare 554 outputs on 70 vectors against independent integer oracles and,
on little-endian ARM64, native NEON intrinsics. Other hosts explicitly omit the
hardware comparison. Both suites compile with GCC/Clang O0/O2 and Clang
AddressSanitizer/UndefinedBehaviorSanitizer. Controls deliberately corrupt
concatenation, merge choices, signed shift, vector operations and constant bytes;
malformed graphs and unjustified facts must be rejected.

These tests and proofs validate particular lowering obligations under the
documented models. They do not verify the complete Python observer, C compiler,
Ghidra lifting, binary execution or every future graph. Whole-answer grading is
separate and retains counterexample, unsupported and inconclusive statuses.

For the comparison, freeze the observer after validation and repeat all 40 O2
cells, one warmup and five measured repeats, on the original frozen binaries.
Keep input/order seeds, source grader, budgets and environment unchanged. Save
new exports, answers, controls and resource measurements in a new directory.
Run measurements serially after builds/tests, and report grader CPU separately
from observer CPU. Any larger-budget query replay is a separate follow-up and
must not overwrite original grades or costs. See the
[journal](journal/2026-11-10-pcode-wide.md) for the scope refinement and retained
failed prototypes.
