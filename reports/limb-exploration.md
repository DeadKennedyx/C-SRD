# First positional two-piece exploration, 2026-11-09–10

## Question and protocol

Does keeping arithmetic/bitwise computation in two positional 16-bit pieces
change compiled structure and the resources needed for correct reconstruction?
The [frozen protocol](../experiments/limbs-exploration.json) compares original,
identity, affine, XOR, planned and `limbs16` variants on four development families.
There is no runtime/size selection ceiling. Reserved reconstruction families remain
unopened. This is exploratory work, not a protection guarantee or novelty claim.

Implementation: commit `2eac664`. Before the observer correction, all 16 CTest
groups passed on native macOS and Linux. Subsequent targeted boundary, observer,
size-audit and statistics tests also passed on both systems. Tests include 82
solver rule obligations, 88 reparsed generated-C function
contracts, GCC/Clang execution with sanitizers, an emitted-code mutant, nonlinear
query-model false fits and rejected invalid measurement artifacts.

## Compiler matrix

Ubuntu ARM64, Clang 18.1.3 and GCC 13.3.0 completed 525 validated build/execution
cells across 25 available profiles. The x86 profile was unavailable. Another 75
cells were explicitly blocked: Jenkins XOR, planned and limb transformations each
timed out in source verification, affecting 25 profiles per candidate. The matrix
retains overall `failed` status and never compiled those unproved candidates.
The three valid Jenkins variants were still measured. No failed cell is a
reconstruction result or a protection success.

Profiles include O0/O1/O2/O3/Os/Oz/Og, LTO/ThinLTO where supported, PGO, native CPU
flags and ASan/UBSan. Each measured runtime uses seven paired samples of one
million harness iterations. Timings include input generation and calls, on a
shared host without CPU pinning. They are not isolated function latency estimates.

| Candidate: limbs16 | Clang O2 runtime ratio | GCC O2 runtime ratio | Clang O2 linked text ratio | GCC O2 linked text ratio |
| --- | ---: | ---: | ---: | ---: |
| CRC byte update | 1.591 | 1.660 | 1.242 | 1.300 |
| Morton interleave | 1.049 | 1.090 | 1.086 | 1.067 |
| Integer RGB weighting | 1.004 | 1.004 | 1.000 | 1.000 |

Ratios use the original under identical build conditions as baseline. At O2+LTO,
CRC runtime ratios were 1.614 (Clang) and 1.713 (GCC); Morton 1.038 and 1.089.
Raw timings, other strategies and every profile remain in the evidence. These
numbers are implementation costs, not reconstruction costs.

Limb instruction-mnemonic sequences differed from matching identity controls in
25/25 CRC profiles, 25/25 Morton profiles and 17/25 RGB profiles. This metric
includes `main` and a surviving named kernel, ignores operands and padding NOPs,
and does not prove either machine data-flow identity or protection. Matching
sequences in the remaining RGB profiles prevent a general claim of compilation
survival.

**Post hoc measurement addition:** full executable sizes were often identical
despite more instructions. Added a read-only, hash-checked linked-section audit
using `tools/measure_code_size.py`, tested on both systems with a changed-binary
negative control. At GCC O2, CRC's total file size stayed 70,712 bytes while its
`.text` grew from 852 to 1,108 bytes. Linked text includes harness/runtime support
and padding; it is not an isolated kernel size. Section sizes also do not measure
runtime resident memory. This addition did not change candidates or the frozen
reconstruction protocol.

## Reconstruction measurements

Runs were serialized separately from builds/tests, with five measured repeats and
one excluded warmup per artifact/budget. Inference workers receive the public ABI
and binary; code follows a fixed algorithm and ignores path labels. This is not
OS isolation from grading files. Answers freeze before grading against the
original preprocessed build input. Grading resources are measured separately.

| Observer round | Measured attempts | Source-model recoveries | No candidate | Wrong candidate | Unsupported |
| --- | ---: | ---: | ---: | ---: | ---: |
| Bit-linear, three families and all six variants | 540 | 240 | 300 | 0 | 0 |
| Bit-linear, three valid Jenkins variants | 90 | 0 | 60 | 30 | 0 |
| Ghidra before count correction | 90 | 30 | 0 | 0 | 60 |
| Ghidra after count correction | 90 | 55 | 0 | 0 | 35 |

Warmups (126 query-observer attempts and 18 per Ghidra round) are excluded from
this table and every paired summary. Trials are repetitions of particular
artifacts, not independent samples of 810 programs.

**Query observations.** All validated CRC and Morton variants were reconstructed
at 65 and 128 queries; 32 was below this fixed observer's basis requirement.
Their lowest successful point in the tested grid was unchanged by representation.
RGB never fit this model. Jenkins fit the basis-only 65-query observations, but
all 30 submitted models were refuted; 128-query probes rejected them before
submission. The same behavior occurred in original and transformed versions.
This is model-class evidence, not protection of Jenkins or RGB. For correct
CRC/Morton limb reconstructions, median CPU ratios ranged from 0.977 to 1.064;
all eight bootstrap intervals included 1. Sampled aggregate-RSS median ratios
rounded to 1.000. The model receives identical I/O observations across equivalent
variants, so no increased query complexity is expected from representation alone.

**Ghidra observations.** Inspection of the first run found eight-byte constant
shift-count fields being rejected as wide data. The narrow correction accepts
those counts without accepting wide payload arithmetic. Its tests include
oversized counts and wrong-count counterexamples. The same binaries/protocol were
rerun under [a separately frozen correction](../experiments/limbs-observer-correction.json).
All remaining 35 gaps were unmodeled control flow or user operations; Clang's
vectorized forms expose operations this adapter does not handle. The GCC CRC limb
candidate was reconstructed, while the original remained outside adapter coverage:
there is no valid paired effort ratio for that case.

| Valid paired limb comparison | CPU ratio, median [exploratory 95% interval] | Sampled tree-RSS ratio, median [interval] |
| --- | --- | --- |
| Morton, GCC O2 | 0.996 [0.961, 1.055] | 0.919 [0.834, 1.133] |
| RGB, Clang O2 | 1.027 [1.024, 1.091] | 1.088 [0.789, 1.639] |
| RGB, GCC O2 | 1.017 [0.966, 1.092] | 0.888 [0.574, 1.953] |

The apparent Clang RGB CPU increase is an important negative control: original,
identity and limb executables have **the identical full binary SHA-256**,
`397ac2195c60254271f5dada6406e3db05560cd3de342f0d509a82a7fd7866b5`.
Even identity measured 1.050 [1.002, 1.069]. These differences cannot establish a
cost caused by changed instructions. Five shared-host repeats and their intervals
do not eliminate environmental, startup, ordering or instrumentation effects.
The summary tooling now flags identical-binary comparisons explicitly. Original
summaries are preserved; supplemental summaries add this flag without retiming.

Morton GCC increased exported P-code operations from 32 to 52 while still being
reconstructed in every repeat with no observed total CPU increase. Median target
decompile time was 13.77 ms original and 13.39 ms limb, versus seconds of total
tool CPU. Phase timing and setup costs must therefore remain visible alongside
overall cost; extra operations alone do not demonstrate harder reconstruction.

## Decision and evidence

Keep `limbs16` as a verified research baseline. It demonstrates multi-operation
two-piece computation and some surviving compiled differences, with measurable
application overhead. **This experiment does not establish increased
reconstruction difficulty or memory-analysis protection.** No candidate is selected
as a winner, and no cost threshold was imposed. Next: improve control-flow/SIMD
observer coverage and compositional proof scalability before relying on apparent
gaps, then compare additional representations with the same controls. Reserved
families remain available for a later frozen validation round.

[The evidence manifest](limbs-evidence-20261109/sha256.json) binds compressed raw
builds (including frozen inputs and executables), both Ghidra rounds, query runs,
resource samples, CSVs, proof probes, rule contracts, test logs and adapter versions.
The large raw matrix JSON is inside `matrix.tar.xz`; a readable
[matrix summary](limbs-evidence-20261109/matrix-summary.json) retains every cell.
[Linked sizes](limbs-evidence-20261109/linked-sizes.json) record the post hoc section
audit. Run identifiers retain the starting date; the repeated observer run
completed on November 10. The source baseline is `2eac664`; archived adapter and
statistics versions distinguish later measurement corrections. The frozen ARM64
`csrd` binary and Docker image identity are included. Dynamic toolchain/runtime
dependencies still require the documented matching environment.

## Reproduction and limits

```sh
# In csrd-dev:ghidra, with this checkout mounted as /work:
python3 tools/run_matrix.py --matrix experiments/rich-benchmarks.json \
  --csrd build-linux-release/csrd --compiler clang=clang-18 --compiler gcc=gcc \
  --objdump llvm-objdump-18 --profdata llvm-profdata-18 --tier extended \
  --strategies identity affine xor planned limbs16 --seeds 42 \
  --inputs 256 --iterations 1000000 --repetitions 7 --timeout-ms 30000 \
  --no-select --output-dir experiments/runs/new-limb-matrix

# A nonzero matrix exit retains failed candidates; inspect its full summary.
python3 tools/measure_code_size.py \
  --matrix-report experiments/runs/new-limb-matrix/matrix.json \
  --output-dir experiments/runs/new-limb-sizes

python3 tools/measure_effort.py \
  --matrix-report experiments/runs/new-limb-matrix/matrix.json \
  --csrd build-linux-release/csrd --allow-partial-matrix --observer ghidra \
  --headless "$CSRD_GHIDRA_HEADLESS" \
  --case crc32_byte --case morton16 --case rgb_luma8 \
  --profile clang-O2 --profile gcc-O2 \
  --variant original --variant identity --variant limbs16 \
  --wall-budgets 60 --repetitions 5 --warmups 1 --timeout-ms 30000 \
  --output-dir experiments/runs/new-limb-ghidra
```

Use the [observer protocol](../docs/effort-measurements.md) with
`--allow-partial-matrix` to measure explicitly requested validated cells. Failed
cells are still ineligible. Source-model equivalence trusts the frontend/model
and Z3; compiler/binary-lifter correctness is not proved. Multi-location runtime
recovery, human effort, x86 execution and reserved-family generalization remain
unassessed. The representation is positional splitting, not encryption or secret
sharing. A larger code footprint or source operation count is not success.
