# Private declarations, shadowing and context bindings

This extends coverage increment 2 from private assignments to single initialized
uint32 declarations and shadowed local names. The source-level contract is
[private-u32-frame-c11-v2](../docs/private-regions.md). Baseline implementation:
`8b91925`; transformer version for this extension: `0.6.1`.

## What changed

The new two-function fixture exercises declarations in nested blocks and loop
bodies, register locals, external callbacks, an early return and caller memory.
Six regions contain seven admitted declarations and sixteen arithmetic
operations; all sixteen execute on encoded temporaries in affine mode. There
are twenty-six conservative boundary conversions. Pointer accesses, callbacks
and loop control are unchanged, not newly verified by this extension.

Declaration IDs separate same-spelled objects. New source declarations retain
their enclosing block and storage class. The independent reader reparses the
emitted C, checks every scalar output and verifies the mapped bindings of all
untouched declaration references. A deliberately added block redirects a local
reference to a global without changing outside bytes; both scope validation and
the binding audit reject it. Changed initializer values produce a counterexample.

The proof covers all uint32 frame inputs under the private-object and defined-C
assumptions. Scope admission and binding checks are trusted compiler analyses,
not a mechanized proof of the entire C language or compiler. No binary or
arbitrary external-effect proof is claimed.

## Validation record

The initial compiler matrix caught unused exported locals after their internal
reads had moved to encoded temporaries. The failed C and diagnostics are retained.
The correction uses discarded reads only for initialized exported scalars; a
discarded call is rejected. Warning flags remain enabled. The research
[journal](../docs/journal/2026-11-10-private-declarations.md) records this decision.

Both macOS ARM64 and Linux ARM64 passed **31/31 CTest groups**. Optional
dependency-specific skips remain explicit in the raw logs. After adding the
unambiguous input/output declaration IDs to JSON, three focused report/scope
checks also passed on each host; the transformation and validation core were
unchanged by that final reporting addition.

Each fixture passed 36 compiler/profile/variant cells per host: identity plus
affine seeds 0, 42 and UINT64_MAX; GCC/Clang O0/O2/O3/Os and Clang ASan/UBSan.
Across the original assignment and new declaration fixtures on both hosts this
is **144 cells and 443,232 comparisons** of return, all caller memory and ordered
event logs. The newly admitted declaration fixture accounts for 72 of those
cells and 221,616 comparisons. Repeated runs are not added to those totals.

The validation suites also exercise frame splitting, overwritten uninitialized locals,
scope redirection, incorrect initializers, omitted outputs, discarded calls and
unsupported effects. The integration controls cover address escapes, macros,
unsupported types and multiple/self-referential declarations.

## Matched application costs

Each host completed 40 linked original/identity/affine/copy variants and 280
executions: ten compiler profiles, seven randomized paired repetitions, one
million workload iterations per execution. All matched state/event checksums
agreed. Both artifact checkers passed, binding 120 recorded frame obligations
and 280 raw resource records per host. These checks are evidence consistency
checks, not independent binary proofs or solver replays.

The table gives median paired affine/original **workload time / linked text
size** ratios. A ratio of 2.00 is twice the baseline. The workload and text
include the unchanged harness and callbacks.

| Compiler/profile | macOS time / text | Linux time / text |
| --- | --- | --- |
| Clang O0 | 2.774 / 1.774 | 2.434 / 1.529 |
| GCC O0 | 2.544 / 1.858 | 2.195 / 1.668 |
| Clang O2 | 0.997 / 1.236 | 0.982 / 1.209 |
| GCC O2 | 1.337 / 1.762 | 1.282 / 1.225 |
| Clang O2 LTO | 1.542 / 1.292 | 1.981 / 1.281 |
| GCC O2 LTO | 2.498 / 1.920 | 2.731 / 1.299 |
| Clang O3 | 1.038 / 1.234 | 0.990 / 1.208 |
| GCC O3 | 1.308 / 1.762 | 1.300 / 1.225 |
| Clang Os | 1.027 / 1.240 | 0.966 / 1.209 |
| GCC Os | 1.606 / 1.842 | 1.549 / 1.249 |

Native tools were Clang 23.1.5 / GCC 16.2.0; Linux tools were Clang 18.1.3 /
GCC 13.3.0. Both hosts use ARM64. Identical-copy median workload ratios span
0.973–1.005 natively and 0.987–1.010 on Linux. This small development pilot
supports no statistical significance, speedup or generalization claim.
CPU, sampled RSS, build times, source/binary hashes and individual paired times
are retained in the [frozen evidence](private-declarations-evidence-20261110/summary.json).
The archive validator checked **2,545 files**. Both exact transformer binaries,
implementation snapshots, generated C, compiler inputs, raw samples and initial
failure artifacts are retained. Historical version 0.6.0 archives remain intact.

All twenty affine compiler/profile cases differed in linked text and selected
opcode sequences. **No reconstruction advantage follows from those differences.**
The measurements show substantial costs in some configurations; this extension
has not demonstrated a protection benefit to offset them. PGO, other target
architectures, whole-function reconstruction and runtime-value recovery remain
outside this pilot.

## Reproduction

```sh
cmake --build build --parallel 4
CSRD_TEST_COMPILERS=/opt/homebrew/opt/llvm/bin/clang:/opt/homebrew/bin/gcc-16 \
  CSRD_REQUIRE_BOTH_COMPILERS=1 ctest --test-dir build --output-on-failure

build/csrd transform tests/fixtures/private_declarations.c \
  --scope private-regions --seed 42 -o build/private-declarations.c \
  --report build/private-declarations.json

python3 experiments/measure_private_regions.py --csrd build/csrd \
  --fixture private_declarations.c \
  --compiler clang=/opt/homebrew/opt/llvm/bin/clang \
  --compiler gcc=/opt/homebrew/bin/gcc-16 \
  --objdump /opt/homebrew/opt/llvm/bin/llvm-objdump \
  --output-dir experiments/runs/private-declarations-cost-native-20261110

docker run --rm -v "$PWD:/work" -w /work csrd-dev:ghidra \
  python3 experiments/measure_private_regions.py --csrd build-linux-regions/csrd \
  --fixture private_declarations.c --compiler clang=clang-18 --compiler gcc=gcc \
  --objdump llvm-objdump-18 \
  --output-dir experiments/runs/private-declarations-cost-linux-20261110
```

Use new output directories, and run measurements after builds/tests with no
competing research jobs. The workload includes callbacks, memory and input
generation; text size includes the linked harness and padding. Process CPU/RSS
include startup and sampled RSS may miss peaks. Paired observations and copy
controls must be inspected before drawing a performance conclusion.

## Protection status and next work

This extension does not establish a protection advantage. Whole-function
reconstruction and runtime-value recovery for these call/loop fixtures remain
measurement gaps. Byte differences and application overhead are not substitutes
for those measurements. The earlier successful affine-buffer recovery remains
negative protection evidence under its narrower contract.

Next work is broader integer semantics and appropriate effect/call observers.
Dead outputs offer a possible conversion reduction, but require a separately
validated liveness analysis. The [fourteen increments](../docs/coverage-increments.md)
remain in progress; unrestricted C support is not implied.
