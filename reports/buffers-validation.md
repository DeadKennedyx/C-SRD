# First bounded pointer/buffer extension — 2026-11-10

This increment implements `buffers-u32-c11-v1` within C-SRD. It adds real
Clang-analyzed loads/stores and affine arithmetic across local intermediates,
while preserving ordinary pointer arguments and caller-visible storage.
The exact [contract](../docs/buffer-contract.md) and
[journal](../docs/journal/2026-11-10-bounded-buffers.md) define scope and failures.

## What is implemented

Named `uint32_t*`/`const uint32_t*` parameters, scalar uint32 parameters/locals,
literal accesses 0–15 or `*p`, add/subtract/literal scale, simple assignment and
one final return. Identity and affine strategies are supported. Pointer
parameters may alias, including partial overlap. Each pointer's minimum valid,
initialized, live prefix is reported as a caller precondition.

The pure graph is explicitly barred from memory regions. A separate ordered
emitter preserves stores and keeps scalar intermediates encoded. The verifier
reparses actual emitted C, checks parameter kinds and access footprints, then
asks whether returns or the entire final shared memory differ. Its SMT bases
are unconstrained, so it does not assume pointers are distinct. Unchanged cells
are part of the obligation. A failed or inconclusive check blocks output.

General pointer arithmetic, dynamic indexing, branches/loops in memory regions,
calls, allocation, signed/floating arithmetic and concurrency remain excluded.
The ordinary caller storage is not hidden. The optional source-level CBMC
checks do not establish correctness of arbitrary compiler-generated machine code.

## Correctness evidence

| Evidence | Actual result | Meaning |
| --- | --- | --- |
| Artifact validation | Six functions × identity and three affine seeds = 24 emitted-function obligations per host | Return and entire-memory equality proved under the shared-word model and caller assumptions |
| Focused memory tests | 12 tests passed on macOS and Linux, including multiple rejection/control cases | Aliases, larger footprints, signature changes, store corruption, untouched cells, deterministic output and compiled memory-only counterexample replay |
| Native differential matrix | 88 build cells; 4,363,480 function/memory comparisons | Clang 23.1.5 and GCC 16.2.0 on macOS ARM64 |
| Linux differential matrix | 88 build cells; 4,363,480 comparisons | Clang 18.1.3 and GCC 13.3.0 in Ubuntu ARM64 container |
| Independent CBMC | 24 actual affine-42 checks: six functions × four fixed alias layouts, all passed | Every initial uint32 value/scalar argument for each 32-word layout, with CBMC's independent C frontend and bounds/pointer checks |
| CBMC controls | Two additional positive checks, four deliberate program mismatches, two invalid-layout/footprint errors, one unavailable-tool control and one insufficient-unwinding control behaved as expected | Supplemental bounded evidence; errors and unavailable tools do not become proof |
| Regression | All 27 CTest groups validated on each host after focused reruns of corrected test fixtures | Native six optional subtests skipped; Linux nine skipped, including six CBMC-dependent tests because CBMC is not installed in that container |

The matrix uses eight identical/overlapping/disjoint pointer arrangements, 64
initialized words, nine edge values and 1,024 deterministic random cases per
layout/function. Every comparison checks the return and all 64 words, including
guards. Unused pointers also receive null. Seeds are 0, 42 and UINT64_MAX;
identity runs once. The 22 available compiler profiles per host include
O0/O1/O2/O3/Os/Oz/Og, full LTO, Clang ThinLTO, native CPU flags and both
ASan/UBSan profiles. Four catalog entries per host (PGO and explicit cross-target
profiles) are marked not run. No x86 or hosted-CI result is claimed.

Native CBMC is Homebrew 6.11.0, with Z3 for the 24 artifact checks and separate
SAT-backend controls. Each bounded harness fixes offsets to one of (0,0), (0,1),
(1,0), (0,16), initializes its whole object nondeterministically and asserts
return equality plus every final cell. These selected layouts are not all
possible C memory configurations. The mandatory C-SRD SMT check separately
ranges over all aliases admitted by its narrower memory model.

## Compiled-code audit and application costs

The static audit of [buffer_update](../benchmarks/arithmetic/buffer_update.c)
validated the actual preprocessed inputs for both compilers at O0/O2. Code
sections differed in all four pairs:

| Build | Original text bytes | Affine text bytes | Ratio |
| --- | ---: | ---: | ---: |
| Clang 23 O0 | 92 | 236 | 2.565 |
| Clang 23 O2 | 32 | 68 | 2.125 |
| GCC 16 O0 | 100 | 212 | 2.120 |
| GCC 16 O2 | 32 | 80 | 2.500 |

These are code-section observations, not reconstruction-resistance results.
The memory interface is explicitly rejected by existing scalar-only recognition
runners; failure to support it is not evidence of protection.

The native cost pilot completed all builds first, then one excluded execution
per binary and seven randomized paired repetitions of 10 million calls. It
used original, identity, affine-42 and a byte-identical original copy. All 112
measured executions had matching output/write checksums; 16 warmups were
excluded. The loop mixes same-pointer and disjoint storage.

| Build | Baseline loop seconds, median | Affine wall-time ratio, median | Affine CPU ratio, median | Identical-copy wall ratio, median |
| --- | ---: | ---: | ---: | ---: |
| Clang 23 O0 | 0.183094 | 1.0185 | 1.0183 | 1.0009 |
| Clang 23 O2 | 0.045692 | 1.0113 | 1.0112 | 0.9988 |
| GCC 16 O0 | 0.192541 | 1.0012 | 1.0002 | 0.9997 |
| GCC 16 O2 | 0.045852 | 1.0121 | 1.0129 | 0.9997 |

These are whole-loop pilot costs including input generation, function calls and
checksum accumulation. They are not isolated operation latency or a general
overhead estimate. Raw samples, paired ranges, CPU time, process peak RSS and
source-compile/link wall times are retained. Median peak RSS was 1,294,336 or
1,310,720 bytes across variants; loader/page effects dominate this small program.
All linked file-size ratios were 1.0 despite differing text sizes. No per-call
memory-overhead conclusion follows. The Linux cost runner also passed a short
two-compiler O2 portability/checksum smoke; its timings are not used above.

## Failures retained and interpretation

* The first CBMC harness used an unrecognized nondeterministic-function name.
  Its SAT run timed out; its Z3 run reported a missing-body failure. Both are
  invalid-harness evidence, not a candidate mismatch. Corrected the helper and
  distinguished missing-body errors from semantic counterexamples.
* Two old regression expectations assumed all pointer functions were rejected
  and that the static audit admitted only pure functions. Updated the rejected
  type to pointer-to-pointer and the audit diagnostic; retained the initial logs.
* A new negative audit fixture lacked a final newline. Clang 18 rejected it
  before verification. Added the newline and reran the affected Linux group.
* The first cost-harness build failed because POSIX-only macOS headers hide
  `ru_maxrss`. Enabled the documented Darwin API extension in the measurement
  harness. No timing from that failed build is treated as data.

The complete initial regression runs had 25/27 native and 26/27 Linux groups
passing. The corrected affected groups passed on rerun, including the new
buffer audit and memory-only mutation test. Successful optional-group wrappers
must not be confused with execution of their skipped subtests.

## Reproduction and evidence

```sh
cmake --build build --parallel 4
CSRD_REQUIRE_BOTH_COMPILERS=1 ctest --test-dir build --output-on-failure
build/csrd transform benchmarks/arithmetic/buffer_update.c -o build/buffer-update.c \
  --seed 42 --report build/buffer-update.json
python3 tests/differential/buffers.py --csrd build/csrd \
  --report build/buffer-differential.json --output-dir build/buffer-evidence
CSRD_BUFFER_CBMC_EVIDENCE=build/buffer-cbmc-evidence \
  python3 tests/integration/test_buffer_cbmc.py build/csrd
python3 tools/measure_buffer_costs.py --csrd build/csrd \
  --compiler /opt/homebrew/opt/llvm/bin/clang --compiler /opt/homebrew/bin/gcc-16 \
  --iterations 10000000 --repetitions 7 --output-dir build/buffer-costs
```

Use new output directories. Exact commands, versions, source/driver/candidate
hashes, SMT obligations, CBMC traces, raw costs, failures and regression logs
are in [the evidence archive](buffers-evidence-20261110/evidence.tar.gz), with
[hash inventory](buffers-evidence-20261110/manifest.json) and
[validation summary](buffers-evidence-20261110/summary.json).

This is a demonstrated increase in supported C behavior. Memory-capable
reconstruction observers, broader index/control contracts and general pointer
verification remain open. The next language milestone is known direct calls
with explicit argument, memory-effect and environment summaries.
