# Wide-value observer and grading follow-up, 2026-11-10

**Result:** the expanded observer reconstructed all **200/200 measured cases**
correctly under the source model after separate grading. All nine previous
unsupported build cells are covered, and both older unresolved answer contracts
are proved. Byte/nibble whole-observer CPU medians span **0.988–1.056×** baseline;
some local stages grow substantially, while recorded application costs remain
high. This establishes no useful protection winner on this development corpus.

This follows the [positional-width comparison](positional-widths.md), keeping
its compiler artifacts and results unchanged. The observer extension and saved-
query grading investigations have separate protocols and resource records.

## Question and implementation

Can explicit wide arithmetic, three AArch64 vector operations and immutable
constant-pool snapshots explain the previous observer's nine unsupported build
cells? Can a declared larger grading budget resolve its two remaining distinct
unproved answers? Neither question presupposes a protection benefit.

Implementation commit: `d4b872f`. The [technical contract](../docs/pcode-wide-values.md)
defines payload widths, unsigned component lowering, vector semantics, immutable
memory assumptions and conservative rejection. The
[journal](../docs/journal/2026-11-10-pcode-wide.md) records the original scalar-only
plan and the vector/constant refinement before the resource repeat. This is an
observer extension, not a change to the accepted C language or a new candidate
representation. Frozen application binaries remain those of the 500-cell study.

The first scalar prototype exposed unused-variable and unsigned-comparison
warnings under strict compiler flags. Its failed log and source are retained.
The first live vector pilot rejected constant-pool inputs because Ghidra marked
`.rodata` executable as well as readable. A diagnostic export showed the blocks
were nonwritable, initialized and relocation-free. The corrected contract records
execute permission without equating it with mutability; no permissions or bytes
are changed. Both pilots remain available. The corrected pilot produced 15/15
answers, with 14 source-model proofs and one inconclusive grade before follow-up.

## Correctness validation

All **23 CTest groups passed on macOS ARM64 and Linux ARM64**. Native skipped
three subtests: live Ghidra, Linux-only resource-budget accounting and live GDB;
Linux ran all three. The suite durations
were 342.82 and 275.59 seconds. The correctness suites overlapped, so these times
are not performance comparisons.

Each host checked **2,011 actual-C universal SMT obligations**: 1,457 wide-value
components and 554 vector components. Wide arithmetic covers all byte widths
through 128 bits, boundary shifts and selected cross-word shapes; its constant
multiplication obligations use 65537 reduced to each width. Vector obligations
cover all admitted EXT offsets and REV64 lane sizes, plus USHL boundary counts.
These are enumerated lowering obligations under the C/SMT models, not a proof
of the entire compiler, every coefficient, graph or binary lifting.

Compiled checks compare 1,457 wide outputs on 113 vectors and 554 vector outputs
on 70 vectors under GCC/Clang O0/O2 and Clang ASan/UBSan. Both ARM64 hosts also
compare vector outputs against native NEON intrinsics. Deliberate corruption
controls cover concatenation order, simultaneous wide merges, signed shift,
vector offset/lane/count semantics and constant bytes. Unsupported facts and
malformed inputs remain rejections.

```sh
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
```

## Earlier unresolved grades

The old run originally contained 120 proved answers, 35 inconclusive grades and
45 unsupported reconstructions. Its first five-second circuit follow-up proved
25 more answers, leaving ten unknown trial grades: two distinct answers with
four distinct saved SMT byte sequences.

The new grading-only investigation declared 30 seconds for all four queries,
then 120 seconds only if needed, with both distinct wrong-output queries and
three arithmetic controls at each used budget. **All four proved UNSAT at the
30-second tier**, in 5.7–9.3 seconds including circuit stages. All five controls
passed; no 120-second tier was used. Source, answer, binary, command and query
hashes remain linked to the historical trials. These were correct answers whose
proofs exceeded the earlier budget, not failed reconstructions.

The resulting historical interpretation is **155 proved reconstructions and
45 unsupported**, with no unknown grade in this cohort. This is a derived
follow-up; historical records and original observer/grader costs are unchanged.
It does not resolve unrelated grading gaps elsewhere in the project.

## Repeated observer experiment

The complete repeat is declared before results: four development functions,
Clang/GCC O2, five implementations, one warmup and five measured repeats per
cell. That is 240 attempts, of which 200 are measured. Input/order seeds,
frozen binary bytes, source grader and original observer budgets are unchanged.
The declared changes are the exporter, bounded value/CFG adapter and artifact
binding metadata. No resource or outcome threshold chooses cells for reporting.

Ghidra analysis/decompile budgets remain 30/15 seconds inside a 60-second whole-
observer wall budget. Source grading has a separate ten-second solver budget.
CPU, wall time and RSS include observer startup and its process tree but exclude
grading. Sampled tree RSS can miss peaks and double-count shared pages. Trials
run serially after correctness tests and pilots, inside the recorded Linux
ARM64 image. A temporary `caffeinate -i` wrapper prevents idle host sleep.

All new measured inconclusive answers are replayed separately using exact saved
queries, a declared 30-second checked-circuit budget and 35-second stage budget.
Identical query bytes share one replay while retaining every trial membership;
those memberships are not independent timing samples. Wrong-output and generic
arithmetic controls accompany the replay. Larger grader costs never become
observer costs or evidence of attacker effort.

```sh
caffeinate -i docker run --rm --name csrd-wide-observer-20261110 \
  -v "$PWD:/work" -w /work csrd-dev:ghidra \
  python3 experiments/run_wide_observer.py \
  --prior-repeat experiments/runs/positional-widths-ghidra-repeat-20261110 \
  --output-dir experiments/runs/pcode-wide-observer-20261110

python3 experiments/grade_wide_observer.py \
  --observer-run experiments/runs/pcode-wide-observer-20261110 \
  --circuit-tool build/csrd-query-circuit \
  --abc experiments/runs/solver-probes-20261110/abc-src/abc \
  --output-dir experiments/runs/pcode-wide-observer-grading-20261110
```

Use a fresh output directory when repeating commands. Native grading uses the
recorded macOS ARM64 circuit/ABC tools; observer execution uses the frozen Linux
frontend and Ghidra 12.2. Reproducing another target requires its own toolchain
and validation record.

## Completed outcomes

All 240 attempts completed, including 40 excluded warmups. The **200 measured
attempts initially gave 160 proofs and 40 inconclusive source grades**, with
zero unsupported reconstructions and zero wrong candidates. All 200 deliberately
wrong result-plus-one controls were rejected. The 40 unknown trials represent
eight distinct answer artifacts and 15 distinct exact query byte sequences.

The separate 30-second replay proved all 15 saved query variants UNSAT. All
eight distinct wrong-output queries and three arithmetic controls passed.
Individual answer replays took 0.958–8.932 seconds including circuit stages.
The complete 26-query follow-up used 54.183 seconds of wall time and 50.245
seconds of child CPU, including controls. Those are grader costs, not observer
costs, and repeated memberships in one query group are not additional timings.

| Cohort / grading stage | Proved under source model | Inconclusive grade | Unsupported observer |
| --- | ---: | ---: | ---: |
| Old observer, initial grading | 120 | 35 | 45 |
| Old observer, earlier 5-second replay | 145 | 10 | 45 |
| Old observer, new 30-second investigation | 155 | 0 | 45 |
| Expanded observer, initial grading | 160 | 40 | 0 |
| Expanded observer, separate 30-second replay | **200** | **0** | **0** |

All 155 previously recovered trials remain recovered. All 45 previously
unsupported trials now yield proved answers. The matched binaries and budgets
are unchanged. Host completion gaps were 5.10–17.10 seconds, with none above 90
seconds; this is a continuity diagnostic, not a substitute for process timing.

## Reconstruction cost versus application cost

Ratios compare a candidate with its matching original within the new observer
run. Each CPU/RSS ratio is the median of five paired measurements after grading;
all five pairs succeeded. Runtime and symbol sizes are reused from the same
frozen binaries in the earlier matrix, not newly timed here. The
[complete trade-off table](pcode-wide-evidence-20261110/tradeoffs.csv) includes
all 40 cells, identity/16-bit controls, absolute CPU/wall/RSS, per-function stages
and exploratory bootstrap intervals.

| Function | Compiler | Byte CPU | Nibble CPU | Nibble sampled RSS | Nibble runtime | Nibble / original symbol bytes |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| CRC32 byte | Clang | 1.034× | 1.037× | 1.002× | 4.108× | 1,112 / 140 |
| CRC32 byte | GCC | 1.032× | 1.056× | 0.930× | 4.154× | 1,248 / 52 |
| Jenkins word | Clang | 1.020× | 0.996× | 1.191× | 7.107× | 1,392 / 72 |
| Jenkins word | GCC | 1.023× | 1.020× | 0.842× | 7.774× | 1,672 / 44 |
| Morton16 | Clang | 1.006× | 1.011× | 1.127× | 1.147× | 352 / 112 |
| Morton16 | GCC | 0.990× | 1.015× | 1.164× | 1.363× | 276 / 92 |
| RGB weighting | Clang | 1.002× | 0.988× | 0.903× | 1.855× | 236 / 44 |
| RGB weighting | GCC | 0.995× | 0.991× | 1.022× | 1.916× | 192 / 44 |

Byte/nibble wall-time medians range from 0.973× to 1.052× and sampled-tree RSS
medians from 0.842× to 1.246×. RSS is noisy: the GCC RGB identity control uses
byte-identical binaries, yet its individual paired RSS ratios span 0.409–2.363×.
Memory-ratio fluctuations cannot establish a protection effect. The GCC nibble
CRC CPU median of 1.056× has an exploratory five-repeat interval of
0.983–1.109×; this is not evidence for a reliable large increase.

Some local stages did increase. Clang Jenkins target decompilation rose from
11.624 to 52.911 ms for nibbles; adapter expansion rose from 0.928 to 3.232 ms.
Its reconstructed C grew from 26 to 592 emitted statements. Whole-observer CPU
includes process startup/import and is about six seconds, so that aggregate
masks much of the per-function difference. Conversely, Clang CRC's original
vector lowering emits 891 statements versus 601 for nibbles: reconstruction
size is not monotonic in representation width. Neither count measures human
understanding or recovery of an algorithm name.

The observer makes one target-decompile request and zero training-input queries
per attempt. No new input/output query experiment was run; the earlier
bit-linear query results remain unchanged. No runtime or size cutoff was used
to choose a winner.

## Evidence and reproduction

The [validated summary](pcode-wide-evidence-20261110/summary.json),
[archive index](pcode-wide-evidence-20261110/index.json),
[per-file hash manifest](pcode-wide-evidence-20261110/file-manifests.json.gz),
[archive validation](pcode-wide-evidence-20261110/archive-validation.json) and
[package hashes](pcode-wide-evidence-20261110/sha256.json) retain the complete
repeat, both query follow-ups, unit proof artifacts, compiled checks, controls,
pilots, failed prototypes, commands, source snapshots and raw resource samples.
Original matrix/binary and native circuit-tool packages are referenced by hash,
not rewritten or duplicated. Transient Ghidra project databases are excluded
with their hashes retained; binaries and exports remain available.

```sh
python3 experiments/investigate_width_grades.py \
  --prior-circuit experiments/runs/positional-widths-circuit-replay-20261110 \
  --circuit-tool build/csrd-query-circuit \
  --abc experiments/runs/solver-probes-20261110/abc-src/abc \
  --output-dir experiments/runs/pcode-wide-grading-20261110

python3 experiments/summarize_wide_observer.py \
  --observer-run experiments/runs/pcode-wide-observer-20261110 \
  --prior-repeat experiments/runs/positional-widths-ghidra-repeat-20261110 \
  --prior-circuit experiments/runs/positional-widths-circuit-replay-20261110 \
  --old-query-replay experiments/runs/pcode-wide-grading-20261110 \
  --new-query-replay experiments/runs/pcode-wide-observer-grading-20261110 \
  --development experiments/runs/pcode-wide-development-20261110 \
  --output experiments/runs/pcode-wide-observer-summary-20261110.json
```

These are the recorded commands; use fresh destinations for reruns. Archived
protocols retain `/work` and the recorded native checkout paths. Restore those
mount/path conventions or regenerate protocols for another checkout. Individual
saved SMT obligations can be replayed independently of those path conventions.

## Limits of interpretation

This is a known-interface observer on four development functions, not an
unbiased application sample. Five repeated executions of one artifact estimate
execution noise; they are not five independently protected programs. Results
remain conditional on the source model and trusted Clang/Ghidra lifting,
adapter, solvers and fixed immutable-memory assumption. The archive records
supplemental Ghidra language files at packaging time; the original resource
protocol binds decompiler components and version, not the entire installation.

CPU and RSS here measure automated analysis resource use. RSS does not measure
exposure of intermediate values in a debugger. This increment collects no new
runtime memory traces, human analysis times, function-discovery effort or
multi-function application results. Reconstructing an equivalent C expression
also does not mean recovering the author's original source or algorithm name.
Those require separate protocols and success criteria.

## Next engineering task

Freeze this observer and add a declared persistent-session comparison that
separates per-function analysis from process startup, while retaining this cold-
process baseline. Include identical-artifact controls, independent correctness
grading and CPU/RSS accounting for the native decompiler as well as the host.
Then evaluate the frozen protocol on reserved algorithm families before tuning
another representation. Keep application runtime and size in the same table;
no cost ceiling or protection winner follows from the present experiment.
