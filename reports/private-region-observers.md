# Private-region calls and loops: measurement checkpoint

Recorded 2026-11-10. Transformer baseline **`592ed99`, C-SRD 0.6.1**.
This closes the development measurement gap for the two existing private-region
fixtures before continuing the unfinished integer extension. The transformer was
held fixed. It does not establish support for transforming arbitrary callbacks,
loops or whole C programs.

**Result:** all measured compiled functions were reconstructed into C that passed
finite return/memory/event grading. Affine encoding increased some application
and observer costs, and caused two additional misses for a narrow runtime-value
observer. A broad software-protection advantage is **not established**. There is
no chosen cost/benefit threshold and no measurement of human understanding time.

See the [protocol](../docs/private-region-observation.md),
[journal](../docs/journal/2026-11-10-private-region-observers.md) and
[frozen evidence](private-region-observers-evidence-20261110/index.json).
Earlier buffer, assignment and declaration reports remain unchanged.

## Design and validation

Two fixtures: assignment regions, and declarations with nested shadowing. Each
contains `region_pipeline` and `region_outputs`. Compile shared libraries with
Linux ARM64 Clang 18 and GCC 13 at `-O0` and `-O2`. Compare original, identity,
affine seed 42 and a byte-identical library copy: **32 libraries / 64 functions**.
The exact compiler versions, commands, source/tool/binary hashes and environment
are recorded in the build manifest. These are shared-library measurements;
the earlier linked-application/LTO cost results have a different build scope.

The binary observer receives public parameter/return/callback types and symbols,
but no reference source, frame proof or encoding parameters. Ghidra high P-code
is lowered to C with explicit width masks, signed comparisons, ordered loads,
stores and calls, cyclic control flow and simultaneous phi updates. Unknown
operations, code-as-data, malformed graphs and unsupported pointer accesses are
rejected. The observer requires a three-word public buffer and the two declared
callbacks. This is a benchmark observer, not a general C decompiler.

Recovered C is graded separately, after observation. The oracle checks return
bits, all three caller words and ordered `record_event` values. It also varies
the implementation of `next_value` across three controlled behaviors. Grading
inputs include negative/zero/positive loop counts, modular boundaries, seeded
random values and the rare `x + 17 == 0` return path. The original compiled
function must agree with the independent oracle on these same grading inputs.

* **192/192** reconstruction attempts passed: three randomized fresh-process
  repetitions of every function artifact, one decompilation request per attempt.
* **196,608** recovered-function comparisons passed: 512 inputs per attempt,
  compiled independently with both GCC and Clang. Another 98,304 comparisons
  checked the original executables against the grading oracle.
* **18/18** deliberate-error controls were detected: 16 return, store, call-value
  and dropped-call mutations produced mismatches; two altered-loop controls hit
  the event bound (exit 70). This does not prove nontermination of those mutants.
* **72/72** saved, hash-bound emitted-frame SMT obligations replayed as `unsat`.
  Aggregate solver-process wall/CPU was about **1.30/0.81 seconds**, including
  launch overhead. These prove the private frames under their existing model,
  not the callbacks, loops, binaries or compiler as a whole.
* Eight observer regression tests passed on both the native host and Linux.
  They cover modular-coset fitting, held-out failures, malformed exports, effects,
  simultaneous loop-phi swaps and 2,660 signed-shift/extension comparisons per
  test execution. The four available frontend-disabled CTest groups also passed.

The existing transformer suite was not relabeled as newly rerun. Its earlier
GCC/Clang/sanitizer evidence remains in the declaration report. No source
transformation implementation changed in this checkpoint.

## Compiler survival and reconstruction effort

The affine assignment `region_pipeline` had **exactly the original function
bytes at `-O2` under both Clang and GCC**. The other 14 affine function/build
cases differed in both exact bytes and mnemonic sequences. Byte difference and
mnemonic difference are structural observations, not protection claims; exact
bytes include PC-relative encodings and mnemonic sequences omit operands.

Across the 16 matched affine function/build groups, median paired whole-Ghidra
CPU ratios ranged **0.81–1.17×**; identical-library controls ranged **0.87–1.12×**.
The adapter CPU range was **0.92–1.09×**, close to copy-control variation. These
three-repeat pilots do not establish a general reconstruction-cost increase.

The separate `decompileFunction` request timer exposes costs hidden by process
startup. The largest median paired request ratio was **2.22×**, for the Clang
`-O2` declaration loop: median request wall time was about **9.8 ms original**
and **21.8 ms affine**. That is a request wall-time observation, not isolated
native CPU, a failed reconstruction or evidence about human effort. Full raw
resource series, process/tree RSS, generated-operation/block counts and matched
ratios are retained. The OS disk cache was not flushed between fresh processes.

## Runtime values and memory

The final pass contains **1,152 complete, effect-validated traces in 96 groups**.
Each group uses six training and six untouched held-out inputs. Pipeline traces
use fixed loop counts zero and two; output-function traces vary both scalar
inputs. Callback mode is fixed to zero for this runtime protocol. Locations are
normalized by symbol, instruction offset and visit count, allowing comparison
across independent ASLR runs. Dynamic-loader lazy binding happens before entry.

| Variant | Recovered target/build/scenario cases | Misses | False held-out models | Permuted-label false matches |
| --- | ---: | ---: | ---: | ---: |
| Original | 134 / 136 | 2 | 0 | 0 |
| Identity | 134 / 136 | 2 | 0 | 0 |
| Affine 42 | 132 / 136 | 4 | 0 | 0 |
| Original copy | 134 / 136 | 2 | 0 | 0 |

The GCC `-O2` declaration loop's `local` value was missed on both observed
iterations in **every** variant. The affine Clang `-O2` declaration loop added
the same two misses. These are misses of a single-location invertible-affine
fitter. They do not show that the values cannot be recovered by combining
locations or analyzing the successfully reconstructed implementation. No such
stronger recovery experiment or human study was performed here.

The fitter solves modular congruences when known values occupy an even residue
class. It records non-unique parameter classes instead of pretending to identify
the original multiplier. Constant training labels are classified as insufficient
variation. This corrects a limitation of the older odd-difference-only method;
old reports and the old fitter were preserved.

For the two-iteration declaration loop:

| Build | Sampled additional stack bytes, original → affine | Fitter CPU ratio | Fitter process-RSS ratio |
| --- | ---: | ---: | ---: |
| Clang O0 | 64 → 144 | 1.97× | 1.69× |
| GCC O0 | 64 → 128 | 2.44× | 1.89× |
| Clang O2 | 80 → 96 | 1.33× | 1.19× |
| GCC O2 | 80 → 96 | 1.49× | 1.25× |

Stack depth is sampled relative to target entry and includes callbacks; it
excludes the caller frame, heap and non-stack memory. The observer sees low32
general registers, 64 bytes at SP and three caller words. It has no SIMD or
exhaustive memory coverage. Fitting is given known intermediate labels: it does
not discover program purpose autonomously. Debugger, fitter and application
resources are reported separately. More trace processing is not automatically
more difficulty understanding the implementation.

## Matched application costs

Seven randomized repetitions of each library produced **224 executions**, each
with one million workload iterations. Return/memory/event checksums matched.
Numbers below are median paired wall ratios and whole-library `.text` ratios.

| Fixture | Build | Runtime | Text size |
| --- | --- | ---: | ---: |
| Assignments | Clang O0 | 1.423× | 1.556× |
| Assignments | GCC O0 | 1.450× | 1.735× |
| Assignments | Clang O2 | 1.033× | 1.181× |
| Assignments | GCC O2 | 1.001× | 1.142× |
| Declarations | Clang O0 | 2.156× | 2.006× |
| Declarations | GCC O0 | 1.961× | 2.434× |
| Declarations | Clang O2 | 0.937× | 1.417× |
| Declarations | GCC O2 | 1.006× | 1.508× |

Copy-control runtime medians ranged **0.922–1.012×**. Do not interpret the small
optimized differences as reliable speedups. CPU measurements follow the same
pattern and are saved separately. Peak process RSS was constant at 18,612,224
bytes in this pilot; that coarse counter includes process/launch effects and
does not establish zero memory overhead. Stack sampling supplies a separate,
more sensitive measurement. Affine library compilation took about 14–27 ms;
end-to-end transformation plus validation took about 25–38 ms. Those are single
build timings, not stable compiler performance estimates.

## Reproduction and remaining limits

Use the existing [validation](../experiments/Dockerfile.validation) and
[Ghidra](../experiments/Dockerfile.ghidra) images, with the repository mounted at
`/work`. GDB runs require ptrace permission. The retained run used image
`sha256:880358a74512e1deac327db13818f10e5b0cf8538f3490996952b8d379541f00`.
The frozen native/Linux 0.6.1 compiler executables are also retained in the
earlier declaration evidence. Build 0.6.1 from `592ed99` or extract the matching
Linux executable before using these commands. Output directories must be new.

```sh
python3 tools/audit_region_observers.py prepare --csrd build-observer-linux/csrd \
  --compiler clang-18 --compiler gcc --profile O0 --profile O2 --output experiments/runs/region-build
python3 tools/audit_region_observers.py reconstruct --build experiments/runs/region-build/build.json \
  --ghidra /opt/ghidra_12.2_PUBLIC/support/analyzeHeadless --repetitions 3 --grade-cases 512 \
  --output experiments/runs/region-reconstruction
python3 tools/observe_region_runtime.py --build experiments/runs/region-build/build.json \
  --output experiments/runs/region-runtime
python3 tools/measure_region_costs.py --build experiments/runs/region-build/build.json \
  --output experiments/runs/region-costs
python3 tools/replay_region_frames.py --build experiments/runs/region-build/build.json \
  --output experiments/runs/region-proofs
python3 tools/inspect_region_binaries.py --build experiments/runs/region-build/build.json \
  --output experiments/runs/region-binaries
python3 tests/integration/test_region_observers.py
```

O3/Os/LTO, additional architectures, other seeds and wider callback/loop/value
observers are not measured by this new observer pilot. Previous correctness and
application-cost evidence at those profiles does not substitute for these
missing observer runs. Whole-function equivalence remains empirically tested;
frame proofs retain their explicit private-object assumptions.

The next coverage task is the isolated integer prototype: specify and validate
promotions, conversions, signed defined-input conditions and widths, then give
its new fixtures the same correctness/protection/cost gate before expanding
again. The two-location runtime recovery follow-up remains explicit; the two
extra single-location misses must not be promoted into a general protection claim.
