# Private computation regions inside larger functions

## Question and starting evidence

After `b4a5285`, whole-function unsigned scalar and fixed-index buffer paths
work, but a surrounding call, signed return or input-dependent loop excludes
many otherwise eligible computations. Affine buffer reconstruction has no
established worthwhile protection advantage. This increment expands correctness
coverage; it does not assume that the same encoding becomes stronger.

Hypothesis: a finite sequence of private unsigned assignments can be replaced
by an encoded implementation inside a richer function when every externally
visible scalar at the region exit is preserved and surrounding code is unchanged.

## First prototype, before implementation/results

Opt in through a separate scope. Start with contiguous plain assignments inside
compound statements, using unqualified automatic uint32 objects or parameters.
Declarations and other statements are boundaries. An address-taken object,
global/static state, macros, attributes, ambiguous shadowing and unknown
in-region effects are excluded. Surrounding pointer accesses, calls, branches
and loops are retained verbatim. No transformation crosses their boundaries.

Capture only values read before their first write. Keep intermediate arithmetic
encoded; materialize every written original scalar before leaving the region.
No private scalar can escape by address. A defined source execution supplies
initialized inputs; the transformation must not add new reads of overwritten
uninitialized objects. Generated identifiers come from the existing collision
avoidance discipline. Preserve physical line counts and unchanged source bytes.

Reparse the emitted full translation unit. Independently lower each actual
generated block to a scalar frame, checking its input/output set, declarations,
types and absence of other effects. Compare every output using the existing
shared-memory verifier with an internal synthetic output vector. This vector is
a proof device, never an emitted runtime buffer. Pointwise frame equality plus
unchanged surrounding code supports contextual equivalence under the private
object/source model; it is not a complete C concurrency/provenance/binary proof.

Tests must cover calls between regions, loops and early returns, private versus
escaped objects, read-after-write and overwritten uninitialized locals, multiple
outputs, identifier collisions, source lines and rejection controls. Verify
actual emitted blocks and corruptions, then GCC/Clang execution/event traces
under ordinary optimization and sanitizers. Report transformed regions and
operations separately from untouched syntax. Protection and application costs
need matched measurements after correctness succeeds.

## Initial implementation and correctness findings

The fixture contains two functions with external calls, pointer stores, a signed
interface, early return and an input-dependent loop. Three selected private
regions contain ten transformed arithmetic operations and eleven affine
entry/exit conversions. The surrounding statements stay byte-identical. Each
actual emitted frame passed its universal scalar-output obligation, including
transformation seeds 0, 42 and UINT64_MAX in the independent tests.

The event harness compares returns, complete three-word memory and the full
ordered event log, using 1,026 inputs and three scenarios. Four representation/
seed variants across GCC/Clang O0/O2/O3/Os and Clang ASan/UBSan produced 36 build
cells and 110,808 comparisons per host. These repeated executions are empirical
evidence; the same deterministic cases across builds are correlated.

The full macOS CTest run passed 31/31 groups. Linux initially passed 29/31:
two newly added test groups contained snippets without a final newline, which
Clang 18 rejected under strict C11 while Clang 23 accepted them. The fixture
correction preserves strict parsing. Both failed groups and the CLI regression
then passed on Linux and macOS. The original failure logs are retained. No
transformer semantic change was needed to resolve this test-input issue.

The next cost pilot uses the versioned compiler profile catalog: O0/O2/O3/Os
and O2 full LTO for GCC and Clang, seven randomized paired repetitions and
one million iterations of the same linked workload. Original/identity/affine
seed 42/identical-copy variants share build flags and a callback/state checksum.
Compilation and disassembly finish before resource collection. Record linked
text, surviving named opcodes, workload wall time, process CPU/RSS and build
time. Existing whole-function observers lack the needed call/loop semantics;
their unsupported scope is explicitly not a protection success.

Both cost runs finished: 40 linked variants and 280 executions per host, with
matching workload checksums. Twenty affine compiler/profile cases retained
different linked text and selected opcode sequences, including O2 and LTO.
The measured cost depends on the build: native O0 median time ratios reached
1.701, and the two LTO profiles were about 1.20–1.26 on both hosts. Several Linux
optimized ratios fell below one in this workload; no general speedup or
significance claim follows. The identical-copy controls and all individual
samples remain available in [the report](../../reports/private-regions.md).

The final artifact checks bound sixty frame obligations and 280 samples per
host to the corresponding C, executable, raw counter and paired summary records.
The archive verified 2,545 files, retaining initial failures and exact source /
binary snapshots. This is a working coverage prototype with measured costs.
Protection effort for call/loop functions remains unknown; do not interpret
that observer gap as a successful technique. Next: declaration/lifetime handling
and broader integer semantics, with effect-aware observers revisited as their
contracts become available.
