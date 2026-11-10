# Positional-width comparison, 2026-11-10

**Result:** the byte and nibble representations are implemented and verified
under the admitted source model. Smaller pieces substantially increase some
application costs and some individual analysis stages, but this experiment does
not establish a useful protection gain. Successful paired Ghidra CPU medians
for the new variants range from 0.990× to 1.037× their originals; black-box query
requirements are unchanged. Coverage and grading gaps remain explicit.

## Question and implementation

Does representing each u32 as four bytes or eight nibbles increase measured
reconstruction effort enough to justify its application cost, compared with the
original, identity lowering and two 16-bit pieces? The experiment has no
predetermined winner and no runtime or size screening threshold.

Implementation commit: `572d600`. The [technical specification](../docs/positional-widths.md)
defines the formulas and verification argument; the [journal](../docs/journal/2026-11-10-positional-widths.md)
records failed prototypes and subsequent decisions. The new `limbs8` and `limbs4`
strategies use the existing admitted pure-u32 C subset. They keep intermediate
values split across operations, with explicit conversion at entry, return and
bounded lookup-index boundaries. They add no runtime library or C language
coverage. Seeds do not alter these fixed representations.

Whole-word constant-multiplication proofs timed out. Coefficient-digit
convolution also failed the proof budget. The accepted approach retains the
original full-factor C arithmetic and checks actual partial-product declarations,
then actual digit/carry extraction, and a separate telescoping identity. Carry
inputs are unrestricted u32 values. No deadline was increased and no failed
proof was accepted. The original 16-bit Jenkins candidate remains byte-identical.

## Correctness evidence

All **21 CTest groups passed on macOS ARM64 and Linux ARM64**, including live
Ghidra integration on Linux. Their wall times were 161.65 and 87.91 seconds during
overlapping execution; these are test durations, not performance comparisons.

The new integration suite covers 98 functions per width: arithmetic, dense
constant multiplications, all 32 legal counts for left/right shifts, comparisons,
selection, a bounded table, finite-loop lowering and composed operations. It
reparses and proves emitted artifacts, replays saved SMT queries independently,
and checks renamed locals and deliberate output corruption. GCC and Clang compile
and execute edge/random comparisons at O0/O2 and with ASan/UBSan.

The independent rule suite checks **172 universal bit-vector obligations**:
164 valid formulas return unsat for their mismatch query; eight deliberately
wrong formulas return sat. Compositional unit tests additionally exercise 21
general rejection/budget controls and 17 scale-hint/actual-code corruption
controls. These claims concern the stated semantic model and trusted tooling;
they do not certify the whole compiler or binary lifting.

```sh
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
python3 tools/verify_positional.py --report build/positional-rule-contracts.json
```

## Experimental method

The [prespecified protocol](../experiments/positional-widths-exploration.json)
uses CRC32 byte, Jenkins word, Morton16 and integer RGB weighting. Each has five
implementations: original, identity, limbs16, limbs8 and limbs4. The reserved
algorithm families remain closed for reconstruction.

The broad matrix completed **500 cells with zero failures** across 25 available
profiles. All candidate/build-input source checks passed under the model, and
linked-executable comparisons matched. The x86 execution profile was unavailable
on the ARM64 host. Profiles include GCC/Clang O0/O1/O2/O3/Os/Oz/Og, LTO/ThinLTO,
PGO, native-CPU flags and sanitizers. Comparisons always use the original under
the same compiler/profile. Runtime uses seven interleaved, paired samples of a
million harness iterations, including deterministic input generation.

The input/output observer uses query budgets 32, 65 and 128 with a five-second
wall budget. The Ghidra observer has a 60-second wall budget, 30-second analysis
budget and 15-second decompile budget. Both use five measured repeats and one
excluded warmup per cell, Clang/GCC O2, fixed order/input seeds and no CPU/RSS
ceiling. Source-model grading has a separate ten-second budget. Observer CPU,
wall time and RSS exclude grading; startup and process-tree work are included.
Aggregate sampled RSS can double-count shared pages and miss peaks.

The initial Ghidra run encountered long host timestamp gaps during a user
interruption which guest duration counters did not reflect. Its 157 completed
records and one partial trial are retained but excluded from primary resource
comparisons. Every Ghidra cell is repeated, preserving the binary/tool hashes,
arguments, seeds and budgets. A temporary `caffeinate -i` wrapper prevents idle
host sleep during the repeat. No outcomes determine which cells are repeated.

The whole-executable sizes initially masked some substantial instruction-count
growth. A labeled post hoc, read-only follow-up inspects `.text` and function
symbol sizes in the same frozen binaries. A missing LTO symbol is unavailable,
not zero bytes. No candidate or timing sample changes for this inspection.

## Compiled application costs

The following O2 rows are an accessible slice of the full 500-cell matrix, not a
selection of winning configurations. Runtime is the median of seven paired
candidate/original harness ratios; 1× is the original under that same profile.
These are tiny functions in a harness, not complete application benchmarks.

| Function | Compiler | Two 16-bit pieces | Four bytes | Eight nibbles |
| --- | --- | ---: | ---: | ---: |
| CRC32 byte | Clang | 1.589× | 2.770× | 4.108× |
| CRC32 byte | GCC | 1.662× | 2.744× | 4.154× |
| Jenkins word | Clang | 2.327× | 3.795× | 7.107× |
| Jenkins word | GCC | 2.487× | 3.918× | 7.774× |
| Morton16 | Clang | 1.046× | 1.131× | 1.147× |
| Morton16 | GCC | 1.067× | 1.207× | 1.363× |
| RGB weighting | Clang | 0.994× | 1.085× | 1.855× |
| RGB weighting | GCC | 0.999× | 1.113× | 1.916× |

The post hoc function-symbol sizes in those same binaries are:

| Function | Compiler | Original bytes | Two 16-bit pieces | Four bytes | Eight nibbles |
| --- | --- | ---: | ---: | ---: | ---: |
| CRC32 byte | Clang | 140 | 328 | 608 | 1,112 |
| CRC32 byte | GCC | 52 | 308 | 652 | 1,248 |
| Jenkins word | Clang | 72 | 308 | 632 | 1,392 |
| Jenkins word | GCC | 44 | 360 | 728 | 1,672 |
| Morton16 | Clang | 112 | 176 | 296 | 352 |
| Morton16 | GCC | 92 | 152 | 208 | 276 |
| RGB weighting | Clang | 44 | 44 | 76 | 236 |
| RGB weighting | GCC | 44 | 44 | 80 | 192 |

All 500 frozen binary inspections completed. A named kernel was absent in 28
builds, for example after inlining; the report preserves null symbol sizes there.
`.text` includes startup/harness code, while symbol sizes may include padding.
Neither metric proves instruction identity or analysis resistance.

The report also retains every compile/link command duration, transformation
duration, final source-validation command duration and conversion count. For the
four development cases, respectively 44, 33, 28 and 11 operations remain in the
selected representation: no internal conversion and no ordinary-value graph
node. The binary input functions use three entry/return conversions; unary RGB
uses two. Those are source-graph counts, not observations that machine registers
or memory conceal ordinary intermediate values.

## Input/output reconstruction

Among **600 measured attempts**, the observer produced 200 model-proved answers,
50 wrong answers and 350 no-candidate results; 120 warmups are excluded. CRC32 and
Morton were reconstructed at the same 65-query grid point for every
representation. Jenkins's wrong 65-query fits and RGB's absent fits also occur
for the originals. These are observer limitations shared by every variant.

For a deterministic observer restricted to function outputs, semantic equivalence
preserves its query/answer sequence. Representation can change the cost of
executing each query, but cannot change those outputs or add information. Thus
this experiment provides a useful negative control, not a protection gain.

## Ghidra reconstruction and separate grading

The clean repeat completed all 240 attempts: **200 measured and 40 excluded
warmups**. Adjacent host completion timestamps span 5.28–17.09 seconds, with no
gap over 90 seconds. This is a post hoc continuity diagnostic, not an OS-sleep
proof or a substitute for the recorded process resource measurements.

Initial grading gave 120 proved reconstructions, 35 inconclusive grades and 45
unsupported reconstructions. All 155 submitted answers had their deliberately
wrong result-plus-one control rejected by the source grader. No observer
execution error was recorded.

As declared in the journal, **all 35 measured inconclusive grades** were replayed
with the existing checked-circuit path, preserving the original trial, candidate,
binary, source, command and SMT hashes. ABC received the unchanged five-second
solver budget and each stage an eight-second wall budget. This proved 25 saved
answers; ten remained inconclusive. All 38 controls passed: 35 wrong-output
queries and three arithmetic controls. The seven distinct answer artifacts and
13 distinct saved queries reflect repeated runs, not 35 independent programs.
Original grades and resource measurements are not rewritten.

After that separate follow-up, the outcome is **145 proved reconstructions, ten
inconclusive grades and 45 unsupported reconstructions**. Every table entry below
represents five repeats with the same outcome. R = reconstructed and proved
under the source model, U = observer unsupported, I = grading inconclusive.

| Function | Compiler | Original | Identity | 16-bit | 8-bit | 4-bit |
| --- | --- | --- | --- | --- | --- | --- |
| CRC32 byte | Clang | U | U | U | R | R |
| CRC32 byte | GCC | R | R | R | R | R |
| Jenkins word | Clang | R | R | R | R | I |
| Jenkins word | GCC | R | R | R | R | R |
| Morton16 | Clang | U | U | U | U | U |
| Morton16 | GCC | R | R | R | R | R |
| RGB weighting | Clang | R | R | R | R | U |
| RGB weighting | GCC | R | R | R | R | I |

Unsupported results comprise 25 `PIECE`, 15 varnode-width and five `INT_SRIGHT`
rejections. Several affect the original too. They describe the current observer's
coverage, not a proven barrier to reverse engineering.

The remaining unknowns are Clang/nibble Jenkins and GCC/nibble RGB, five repeats
each: two distinct answer artifacts and four distinct saved queries. A subsequent
finite check grouped identical answers after validating every trial binding. Each
answer and its wrong-output control were compiled with GCC/Clang O0/O2 and Clang
ASan/UBSan. The original, answer and independent Python oracle matched on 2,644
Jenkins inputs and 2,126 RGB inputs; every wrong-output result differed. All 20
compiled configurations passed their expected checks. **These ten proof grades
remain inconclusive.** The later grader and finite-check work are not charged to
the reconstruction observer or counted as additional observer queries.

## Measured reconstruction costs

Successful paired ratios require both candidate and original to have a proved
answer, using the derived grades above. Each row has five matched repeats.
CPU includes waited process-tree user/system time; wall includes headless startup;
RSS is peak process RSS. Sampled process-tree RSS and all raw samples are also
retained in the evidence. There are no ratios for an unsupported baseline or an
unproved candidate.

| Function / compiler | Representation | CPU ratio | Wall ratio | Peak RSS ratio | CPU 95% bootstrap interval |
| --- | --- | ---: | ---: | ---: | --- |
| CRC32 / GCC | Bytes | 1.031× | 1.043× | 0.940× | 1.002–1.053 |
| CRC32 / GCC | Nibbles | 1.033× | 1.014× | 1.183× | 0.986–1.087 |
| Jenkins / Clang | Bytes | 1.014× | 1.028× | 0.940× | 0.999–1.055 |
| Jenkins / GCC | Bytes | 1.037× | 1.031× | 0.973× | 0.983–1.097 |
| Jenkins / GCC | Nibbles | 1.030× | 1.030× | 0.979× | 0.997–1.060 |
| Morton / GCC | Bytes | 1.008× | 1.006× | 0.944× | 0.975–1.074 |
| Morton / GCC | Nibbles | 1.004× | 0.990× | 1.051× | 0.969–1.070 |
| RGB / Clang | Bytes | 0.990× | 0.950× | 1.036× | 0.966–1.021 |
| RGB / GCC | Bytes | 0.994× | 1.036× | 0.996× | 0.964–1.040 |

The intervals describe repeated-run noise on these artifacts. They are not
population confidence bounds, independent program samples or multiplicity-adjusted
tests. A few-percent CPU change or one higher RSS point is not evidence of broad
software protection. JVM startup dominates this observer's overall duration.

Individual stages do show additional work. For GCC Jenkins, median Ghidra target
decompilation time grows from 16.54 ms in the original to 24.95 ms for bytes and
49.97 ms for nibbles. The Python reconstruction stage grows from 0.90 ms to
1.92/3.14 ms; exported P-code nodes grow from 31 to 485/1,001. Those stage wall
times are recorded by the observer and are not separate CPU measurements.
Full observer CPU is approximately 6.20/6.35/6.36 seconds, while application
runtime rises to 3.918×/7.774×. This is a real distinction between increased local
analysis work and a large end-to-end reconstruction cost; neither proves a
human analyst would take longer to understand the algorithm.

## Evidence and decision

The [combined summary](positional-widths-evidence-20261110/summary.json) contains
all build rows, original and derived observer outcomes, paired distributions,
proof chains, finite checks and input hashes. The
[archive index](positional-widths-evidence-20261110/index.json) identifies raw
matrix, observer, interrupted-run, proof, finite-check and prototype archives.
All **31,210 archived files** were checked byte-for-byte against their manifests;
see [validation](positional-widths-evidence-20261110/archive-validation.json) and
[SHA-256 index](positional-widths-evidence-20261110/sha256.json).
The unchanged ABC/circuit binaries and licenses are referenced by hash from the
previous circuit evidence package. No human-session data are included.

No representation is selected as a protection winner and no cost cutoff is
introduced. The evidence supports narrower statements: smaller pieces can
survive optimization, increase code size, and add work to particular analysis
stages. They do not increase the fixed output-only observer's information needs;
the measured end-to-end Ghidra costs remain close where both answers are proved.

The next engineering task is to expand the independent observer's bounded
`PIECE`, signed-shift and wide-value semantics with corruption controls, then
repeat the same frozen binaries. The two unresolved grading contracts need a
separate proof investigation. Only after those coverage gaps are resolved should
we compare additional representation or algorithm candidates. Multi-location
memory inference, human analysis and other architectures need their own protocols.

## Reproduction and interpretation boundaries

The comparison driver requires the recorded Linux ARM64 image with Clang 18,
GCC 13, LLVM tools and Ghidra 12.2. It freezes a frontend binary and runs the
matrix and observers serially. A fresh output directory is required:

```sh
python3 experiments/run_positional_widths.py \
  --csrd build-linux-release/csrd \
  --headless experiments/runs/dependencies/ghidra_12.2_PUBLIC/support/analyzeHeadless \
  --output-dir experiments/runs/widths-fresh
```

The interruption-specific repeat reuses the original completed matrix and
input/output study. The driver checks their bindings before launching the saved
Ghidra command with a new output directory:

```sh
python3 experiments/repeat_positional_ghidra.py \
  --prior-run experiments/runs/positional-widths-comparison-20261110 \
  --output-dir experiments/runs/widths-ghidra-fresh
```

The follow-ups run **after** observer measurements finish, without changing their
inputs. `measure_linked_sizes.py` and `check_positional_answers.py` use the Linux
environment; circuit replay uses the recorded macOS ARM64 tool pair:

```sh
python3 experiments/measure_linked_sizes.py \
  --matrix-report experiments/runs/positional-widths-comparison-20261110/matrix/matrix.json \
  --output-dir experiments/runs/widths-sizes-fresh
python3 experiments/grade_saved_answers.py \
  --prior-run experiments/runs/positional-widths-ghidra-repeat-20261110/effort \
  --circuit-tool build/csrd-query-circuit \
  --abc experiments/runs/solver-probes-20261110/abc-src/abc \
  --output-dir experiments/runs/widths-grading-fresh
python3 experiments/check_positional_answers.py \
  --matrix-report experiments/runs/positional-widths-comparison-20261110/matrix/matrix.json \
  --effort-report experiments/runs/positional-widths-ghidra-repeat-20261110/effort/effort.json \
  --circuit-dir experiments/runs/widths-grading-fresh \
  --output-dir experiments/runs/widths-finite-checks-fresh
```

The read-only `summarize_positional_widths.py` validates the bindings before
deriving updated grades and matched resource summaries. `archive_positional_widths.py`
packages raw evidence, verifies each included file and preserves analysis-script
snapshots. Their full arguments and dependencies are exposed by `--help`.

Unsupported P-code, incorrect answers, observer timeouts and inconclusive grading
remain separate outcomes. Larger code, slower execution and grading difficulty
are insufficient to establish increased reconstruction effort. These observers
do not measure human understanding, algorithm naming, multi-location memory
inference, debugger resistance, secret storage or general software protection.
The reserved families and other architectures require separate evaluations.
