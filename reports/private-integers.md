# Typed private integers: validation and measurement checkpoint

Recorded 2026-11-10/12. Base commit **`3c26935`**, C-SRD **0.7.0** prototype.
The implementation snapshot, frozen executables and measured libraries identify
the tested code independently of the publication commit. Earlier 0.6.1 observer
results remain a separate experiment.

This increment adds standard signed/unsigned scalar integer types through
64 bits, `_Bool`, promotions, conversions and selected operators inside private
declaration/assignment frames. It preserves surrounding calls, loops and memory
boundaries. It does not admit arbitrary C programs or prove those surrounding
effects. See the [contract](../docs/private-integers.md) and
[development journal](../docs/journal/2026-11-10-typed-integers.md).

**Result:** the scoped integer extension preserves tested behavior and its
private-frame obligations validate under the declared model. All compiled
artifacts were reconstructed successfully, and affine runtime values were
recovered more often than original values by the selected observer. Application
and some analysis costs increased. A worthwhile software-protection advantage
is **not established**; retain the coverage work and defer this affine strategy
as a protection candidate pending a different, measured cost/benefit result.

The [frozen evidence](private-integers-evidence-20261112/index.json) includes
successful measurements, unsuccessful prototypes, observer corrections and
per-file hashes. The reviewable [summary](private-integers-evidence-20261112/summary.json)
binds the matched build/reconstruction/runtime/cost reports.

## Correctness and implemented scope

Clang provides effective types, promotions and implicit conversions. Signed
operations use an explicitly declared two's-complement model, modulo signed
narrowing and arithmetic negative right shift. Equivalence is required on the
original's defined inputs, and the candidate must remain defined there. Original
signed overflow is not legalized. The tested execution targets are LP64 ARM64;
the declared 32-bit-long model has not received the same compiled matrix.

Affine representations use compatible odd multiplier/offset parameters at
1/8/16/32/64-bit widths. Same-width add/subtract/constant scaling and ordinary
narrowing can execute directly on encoded values. Boolean conversion, widening,
comparisons, bitwise operations and shifts currently need conversions. In the
mixed-width fixture, **21 of 35 counted operations** avoid decoding, with
**31 boundary and 73 internal conversions**. These source counts are neither
compiled instruction counts nor a confidentiality metric.

Actual emitted C is reparsed. The validator proves entry capture, an invariant
after each original statement and output restoration, forgetting all relations
except those just proved. A separate query rejects empty defined-input domains.
Checkpoint hints are untrusted. Failed monolithic and earlier compositional
prototypes, including timeouts, remain in the evidence. This is solver validation
under the model and its trusted implementation, not a verified C compiler or an
independently checked proof certificate.

* Linux passed **34/34 CTest groups**. After the saved-query export adjustment,
  four affected groups passed again. Optional external checks retain their raw
  skip/availability behavior; this does not claim new CBMC or Frama-C proofs.
* The integer fixture passed **56 native cells / 172,368 comparisons** and
  **36 Linux cells / 110,808 comparisons**. These compare returns, all three
  caller words and ordered callback events. The preceding assignment and
  declaration fixtures passed the same matrices as regressions.
* Correctness profiles include GCC/Clang O0/O2/O3/Os and available Clang O1
  AddressSanitizer/UndefinedBehaviorSanitizer builds; variants are identity and
  affine seeds 0, 42 and UINT64_MAX.
* Codec tests cover **196,608 exhaustive byte pairs** across three codecs and
  sampled width/boundary cases. **41 SMT rule/control obligations** pass on both
  hosts. Negative emitted-C controls cover overflow, signed comparison,
  narrowing, Boolean conversion, promotions, incomplete outputs and bad hints.
* The final observer regression suite passes **11 groups on each host**,
  including 2,048 compiled Boolean/numeric-byte comparisons per execution.
* All **288 saved SMT queries** replayed as expected: 264 `unsat` fragment
  counterexample queries and 24 `sat` nonempty-domain queries, spanning 24
  emitted frames. Aggregate solver-process wall/CPU time was **3.40 / 1.64 s**,
  including launch overhead. The `sat` answers establish inhabited domains,
  not equivalence by themselves.

## Matched artifacts and observer corrections

The pilot uses Linux ARM64 Clang 18.1.3 and GCC 13.3.0 at O0/O2. It compares
original, identity, affine seed 42 and byte-identical original-copy libraries:
**16 libraries / 32 function artifacts**. Each artifact is checked against an
independent Python effect oracle before observation: **16,384 comparisons** in
the build stage. The library/driver/source hashes, command lines, tool identities
and actual frame obligations are retained.

The binary observer receives public types and callback symbols, not reference
source, encoding parameters or validation hints. It exports Ghidra high P-code
and reconstructs C with explicit widths, ordered effects and simultaneous phi
updates. The independent grader runs after all observation attempts, checking
returns, memory and events under three callback behaviors. It is finite testing,
not whole-function proof or a measurement of human understanding time.

Two analysis defects had to be corrected before interpreting failures:

1. The installed Ghidra 12.2 language modeled an AArch64 signed-byte load into W
   as zero-extension. The first real pass graded only 81/96 reconstructions
   correctly, including failures of original/copy controls. A hash-gated,
   isolated language overlay fixes that constructor. Hardware tests cover all
   256 byte values at three offsets, including the zero upper X-register half:
   768 hardware cases and 1,536 reconstructed comparisons. The original language
   failed 768 reconstructed comparisons; the overlay failed none.
2. The next pass reached 93/96. The three remaining failures repeated one affine
   Clang O0 pipeline. Its exported constant 255 had high datatype `bool`; the
   adapter interpreted a numeric byte, whereas Ghidra's Boolean C printer emits
   `true`. Schema 6 preserves that type and normalizes only explicitly typed
   Boolean constants. Numeric byte 255 is unchanged. Old exports/runs are kept.

The final follow-up uses the corrected observer uniformly, unchanged program
binaries, **1,024 grading inputs and seed 20261112**, replacing the development
passes' 512-input grading. The fixtures informed these corrections; this is a
development follow-up, not a blind benchmark. A preceding launch-only failure
with an incorrect Ghidra path is also retained and excluded from conclusions.

## Reconstruction result

**96/96 attempts passed finite effect grading**: three shuffled fresh-process
repetitions of each function artifact, **196,608 recovered comparisons** under
GCC and Clang, and another **98,304 checks of the original against the oracle**.
All **9 deliberately incorrect controls** produced mismatches. Those controls
test the grader; they are not nine independent protection failures.

Across eight matched affine function/build groups, median paired whole-Ghidra
CPU ratios were **0.983–1.089×**, versus **0.977–1.042×** for identical-library
controls. Adapter CPU ratios were **0.987–1.082×**, versus **0.965–1.022×** for
copy controls. Three repetitions do not establish a general cost penalty.

The separate decompiler-request timer shows local increases hidden by startup.
The largest paired median ratio was **2.606×**, for Clang O0 `region_outputs`:
median request times were **17.0 ms original / 50.1 ms affine**. The O0 pipeline
measured **18.7 / 55.5 ms**, with a paired median ratio of **2.588×**. A ratio of
medians need not equal the median paired ratio. Every answer still reconstructed
correctly. Request wall time is not isolated native CPU or human effort. Full
process/tree RSS, operation/block counts and raw resource samples are retained;
fresh JVM processes do not imply a flushed disk cache.

All eight affine function/build cases differed from originals in both exact
function bytes and mnemonic sequences, including O2. Thus some structural
differences survived optimization here, yet reconstruction still succeeded.
Exact bytes include PC-relative encodings, and mnemonic sequences omit operands;
neither comparison proves a semantic or algorithmic difference.

## Runtime-value recovery

All **576 traces in 48 groups** completed and matched the full effect oracle.
Each group uses six training and six held-out inputs, with pipeline loop counts
zero/two and callback mode zero. Recovery targets include 1/8/16/32/64-bit values;
signed values are scored by their bit patterns. These are known-target,
single-location affine fits, not autonomous semantic recognition.

| Variant | Recovered target/build/scenario cases | Insufficient variation | Failed held-out models | Permuted-label false matches |
| --- | ---: | ---: | ---: | ---: |
| Original | 129 / 156 | 8 | 10 | 0 |
| Identity | 138 / 156 | 8 | 1,116 | 0 |
| Affine 42 | 141 / 156 | 8 | 7,112 | 0 |
| Original copy | 129 / 156 | 8 | 10 | 0 |

The eight insufficient-variation cases are included in the denominator: constant
training labels cannot identify an invertible affine relation. They are not
protection successes. A failed held-out model is a register/stack/memory-location
guess that fit training labels but failed at least one test input. Many correlated
locations can fail for one target; these counts are not numbers of independently
misclassified functions or a population false-positive rate. Of the 7,112 affine
failures, **7,004 concerned one-bit values**, 92 sixteen-bit values and 16
thirty-two-bit values. Zero matches for the selected permuted-label control does
not establish a universally zero false-match rate.

| Target width | Cases per variant | Original recovered | Identity recovered | Affine recovered |
| --- | ---: | ---: | ---: | ---: |
| 1 | 12 | 4 | 6 | 4 |
| 8 | 20 | 20 | 20 | 20 |
| 16 | 12 | 12 | 12 | 12 |
| 32 | 56 | 48 | 48 | 50 |
| 64 | 56 | 45 | 52 | 55 |

The affine builds expose more recoverable target cases overall. Additional
materialized encoded/decoded intermediates are a plausible explanation, but
this experiment does not establish that causal mechanism. A missed target may
require combining locations or using the successfully reconstructed program;
neither stronger recovery method nor a human study was run here.

Fitter CPU ratios range **1.35–7.28×**, with process-RSS ratios **1.23–4.45×**.
Each scenario has one fitting process, so these are descriptive pilot ratios,
not confidence intervals. More trace-processing work did not yield a lower
overall recovery rate. The two-iteration pipeline illustrates stack and fitting
costs separately:

| Build | Sampled stack bytes, original → affine | Fitter CPU ratio | Fitter RSS ratio |
| --- | ---: | ---: | ---: |
| Clang O0 | 128 → 1,200 | 4.97× | 3.72× |
| GCC O0 | 112 → 944 | 6.46× | 4.35× |
| Clang O2 | 64 → 96 | 1.35× | 1.23× |
| GCC O2 | 64 → 112 | 2.05× | 1.78× |

Observed stack depth is relative to target entry and includes callbacks. The
observer reads full64/low32 general registers, 4/8-byte views within 64 bytes at
SP and three caller words. It has no SIMD or exhaustive stack/heap coverage.
Debugger, fitter and application resource measurements remain separate.

## Application costs and decision

Seven shuffled repetitions of each library produced **112 executions**, each
with one million workload iterations. Return/memory/event checksums matched.
These are matched shared-library calls, not the earlier linked/LTO experiment.

| Build | Affine runtime ratio | Affine CPU ratio | Whole-library text-size ratio |
| --- | ---: | ---: | ---: |
| Clang O0 | 4.962× | 4.961× | 5.524× |
| GCC O0 | 4.057× | 4.058× | 6.472× |
| Clang O2 | 1.374× | 1.374× | 1.627× |
| GCC O2 | 1.921× | 1.921× | 2.315× |

These are median paired ratios. Copy-control runtime medians were 0.986–1.002×.
Peak application process RSS was constant at 18,350,080 bytes; that coarse
counter does not establish zero memory overhead. Stack sampling shows a separate
increase. Affine library compilation took **18–98 ms** and transformation plus
validation **70–72 ms** in the single build pass; these are not stable compiler
performance estimates.

This closes increment 3's **development measurement checkpoint**, not a claim
to all integer operations, compilers or programs. Keep the typed IR, compatibility
rules and validator as coverage infrastructure. Do not promote the present
affine prototype as effective protection on this evidence. The next scoped
coverage task is byte buffers and checked runtime indexes, with its own alias,
bounds, lifetime and observer contracts before measurement.

## Reproduction and remaining limits

Use the repository's LLVM/Clang/Z3 CMake build and validation container. The
recorded ARM64 dependency image is
`sha256:880358a74512e1deac327db13818f10e5b0cf8538f3490996952b8d379541f00`.
It required the retained Ghidra 12.2 installation mounted separately at
`/opt/ghidra`; the Dockerfile's usual versioned installation path is different.
GDB tracing requires `--cap-add SYS_PTRACE --security-opt seccomp=unconfined`.
The repository is mounted at `/work`. Output directories below must be new.

```sh
cmake --build build
ctest --test-dir build --output-on-failure
python3 tools/audit_region_observers.py prepare --csrd build/csrd \
  --compiler clang-18 --compiler gcc --profile O0 --profile O2 \
  --fixture integers --grade-cases 512 --output experiments/runs/integer-build
```

For the corrected Ghidra language, use a writable copy and then mount it over
`/opt/ghidra/Ghidra/Processors/AARCH64/data/languages` for observer runs. The
patcher requires the exact recorded original source hash; it must not silently
patch a different Ghidra version.

```sh
python3 tools/patch_ghidra_signed_byte.py \
  --language-dir /opt/ghidra/Ghidra/Processors/AARCH64/data/languages \
  --output experiments/runs/integer-language
/opt/ghidra/support/sleigh experiments/runs/integer-language/AARCH64.slaspec
python3 tools/check_ghidra_signed_byte.py --ghidra /opt/ghidra/support/analyzeHeadless \
  --expect correct --output experiments/runs/integer-instruction-controls
python3 tools/audit_region_observers.py reconstruct \
  --build experiments/runs/integer-build/build.json \
  --ghidra /opt/ghidra/support/analyzeHeadless --repetitions 3 \
  --grade-cases 1024 --grade-seed 20261112 --output experiments/runs/integer-reconstruction
python3 tools/observe_region_runtime.py --build experiments/runs/integer-build/build.json \
  --output experiments/runs/integer-runtime
python3 tools/measure_region_costs.py --build experiments/runs/integer-build/build.json \
  --output experiments/runs/integer-costs
python3 tools/replay_region_frames.py --build experiments/runs/integer-build/build.json \
  --output experiments/runs/integer-proofs
python3 tools/inspect_region_binaries.py --build experiments/runs/integer-build/build.json \
  --output experiments/runs/integer-binaries
```

The current observer pilot covers one fixture family, affine seed 42, Linux
ARM64 and O0/O2 shared libraries. O3/Os correctness checks do not replace missing
O3/Os/LTO observer runs. Other architectures/data models, larger loops, varied
callback modes during runtime tracing, stronger recovery and human effort remain
unmeasured here. Affine encoding provides no cryptographic confidentiality.
The publication corrects a stale CLI help description after freezing the
implementation; measured source/binaries and the help-only follow-up remain
separately identifiable in the evidence.
Both native/Linux rebuilds passed the CLI integration group, and the rebuilt
Linux tool regenerated byte-identical source for all eight measured transformed
libraries. This follow-up does not replace the earlier full regression record.
