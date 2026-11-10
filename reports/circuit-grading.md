# Saved reconstruction grading with checked circuits, 2026-11-10

## Result and interpretation

All **ten previously inconclusive measured Jenkins reconstructions** are
equivalent under their saved C-SRD bit-vector model. The checked-circuit replay
returned unsat for every mismatch query. All thirteen controls passed: ten
corrupted-answer comparisons and the wrong-borrow rule returned sat; two valid
arithmetic rules returned unsat. These ten reconstructions are repeated samples
of **two distinct answer artifacts**, not ten independent programs.

The earlier timeouts were a grading limitation. They do not establish failed
reconstruction or increased protection. The original [Jenkins study](compositional-validation.md)
remains the record of its original grader; this report adds an explicit follow-up.
Combining the new grades with that study gives 25 model-validated answers and
five unsupported adapter attempts out of its 30 measured Ghidra attempts.
The five unsupported GCC-original attempts remain unresolved.

Implementation commits: `eabc8bd` and `b69f68e`. The
[specification](../docs/circuit-validation.md) explains the checked export and
trust boundary; the [journal](../docs/journal/2026-11-10-grading-solvers.md)
records the unsuccessful prototypes and failed replay pilot.

## Question, methods and controls

Can a different exact decision engine discharge the frozen reconstruction
mismatches without changing the answers, reference functions or input domain?

Selected every measured inconclusive answer from the preceding development run;
excluded its warmups. The driver checked each prior grade report, SMT hash and
both frozen C-file hashes before execution. It preserved all original sources,
binary identities and observer measurements. No observer ran again or received
reference-source information. Reserved reconstruction families were not opened.

Z3 5.3.3 lowered each unchanged assertion to Boolean operations. The actual
exported circuit was then independently parsed and checked gate by gate against
that lowered DAG, including wiring, input order and output binding. Each local
contract ranges over every Boolean input combination. The Clang answer used
4,980 gates and 13 distinct contracts; GCC used 5,787 gates and 14 contracts.
Both circuits have 64 Boolean inputs. Gate counts describe this particular
lowering, not original machine instructions or reconstruction complexity.

ABC revision `25d4ee221b2a9ab5124f3a222bcdf6f922d3d8a3` ran
`strash; &get; &cec -m -T 5` after reading the validated circuit. Initialization
scripts were disabled. Each process stage had an eight-second wall budget;
ABC had a five-second approximate internal budget. Runs were sequential on the
native macOS ARM64 host after builds/tests. These budgets limit an experiment;
they are not application runtime or size cutoffs for candidate selection.

The ten saved corrupted answers each change a reconstruction's result by one.
The wrong-borrow rule provides another incorrect arithmetic control. No false
equivalence was accepted among those eleven cases. They are deliberate,
correlated controls, not an estimate of a general false-positive rate. Export
tests also reject changed truth rows, missing/forward wires, interface changes,
changed source queries and stale source/hash bindings.

## Grader resources

Five retained answer queries per compiler profile were replayed once each. Their
answer bytes repeat within a profile. Medians below are descriptive measurements
on a shared host, with no excluded new warmup and no speedup inference from the
old timed-out runs. The earlier grader ran in Linux; these new measurements are
native macOS, so they are also not an environment-matched timing comparison.

| Saved answer profile | Replay pipeline wall, s | Measured child CPU, s | ABC wall, s | ABC CPU, s | ABC peak process RSS, MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Clang O2 limbs16 | 1.886 | 1.751 | 1.605 | 1.598 | 23.906 |
| GCC O2 limbs16 | 2.043 | 1.898 | 1.758 | 1.746 | 24.297 |

Pipeline wall time includes driver, version lookup, export, gate validation and
solving, but excludes the initial query copy and final manifest/report I/O.
Child CPU sums measured subprocesses and excludes Python driver's own
CPU. Validation alone took median 0.104 and 0.118 seconds. Total replay wall
ranges were 1.876–1.912 and 2.020–2.063 seconds. macOS `wait4` reports peak process
RSS here, not sampled aggregate tree RSS; the latter is unavailable in these
native runs. Every stage's raw resource record is retained.

These are **grader costs**, separate from reconstruction and application costs.
The frozen observer's median whole-process CPU was 6.638 seconds for the Clang
limb binary, versus 6.663 for its original and 6.732 for its identity control;
GCC limb was 6.730 versus 6.386 for identity. No new observer timing was taken.
The byte-identical Clang original/identity controls already showed timing/RSS
variation. The earlier application runtime ratios, 2.259 at Clang O2 and 2.420
at GCC O2, likewise remain unchanged. Correct recovery of these artifacts and
these small, noisy comparisons do not establish a protection benefit.

## Failed probes retained

* Six Z3 configurations and Bitwuzla 0.9.1 each received five seconds for the
  two representative frozen queries: all 14 attempts remained inconclusive.
  Their 14 valid-rule checks returned unsat and seven wrong-rule checks returned
  sat. The isolated Bitwuzla installation is not a mandatory dependency.
* Manual word decomposition and three sampled-match/proved-replacement
  prototypes found no complete reconstruction proof. They are exploratory,
  unintegrated artifacts; samples never authorized a replacement. Abstract
  intermediate countermodels are not public-input counterexamples.
* ABC resolved the first exported circuits, but a monolithic export/reimport
  validation query timed out. The implemented gate-by-gate contract checks
  resolved this validation problem. Earlier unchecked circuit results were
  not used to grade C reconstructions.
* The first full replay resolved all answers but failed its control criterion:
  the parser conservatively returned inconclusive for ABC's alternate
  diagnostic for trivially incorrect circuits. The exact negative formats
  were checked against ABC source and added to regression tests. That pilot
  remains archived; the successful run uses fresh directories and records.

All 18 CTest groups passed on native macOS and Linux ARM64. Full runs took
143.16 and 34.14 seconds. The final diagnostic-parser change also passed the
focused ten-test group on both platforms. Initial fixture assumptions about
Z3's XOR presentation and macOS path resolution failed during development and
were corrected; the failed Linux log is retained. The test counts do not imply
an independently verified compiler or representative software corpus.

## Reproduce

Use a checkout of implementation `b69f68e` with the documented Clang/Z3 build
dependencies. ABC can be rebuilt from its pinned revision:

```sh
git clone https://github.com/berkeley-abc/abc.git experiments/runs/abc
git -C experiments/runs/abc checkout --detach 25d4ee221b2a9ab5124f3a222bcdf6f922d3d8a3
make -C experiments/runs/abc -j4 ABC_USE_NO_READLINE=1
cmake --build build --target csrd-query-circuit
ctest --test-dir build -R saved_query_circuits --output-on-failure
```

In a fresh checkout, extract `frozen-inputs.tar.xz` from the evidence directory
at the repository root to restore the saved source/query/command records, then:

```sh
python3 experiments/grade_saved_answers.py \
  --prior-run experiments/runs/jenkins-composition-ghidra-linux-20261110 \
  --circuit-tool build/csrd-query-circuit --abc experiments/runs/abc/abc \
  --output-dir experiments/runs/new-saved-answer-replay
```

The [manifest](circuit-evidence-20261110/sha256.json) binds the
[protocol](circuit-evidence-20261110/protocol.json),
[summary](circuit-evidence-20261110/summary.json), complete replay, failed pilot,
exploratory probes, test logs, frozen inputs and native executables. ABC's license
is included. Native binaries require their recorded macOS/Z3 dependencies;
rebuild for another platform. The archive's per-file manifests permit byte-level
integrity checks without rewriting the historical evidence.

## Limitations and next decision

This proves the saved assertions unsatisfiable under the trusted C-to-SMT model,
Z3 lowering, gate checker and ABC. It is not independent C modeling, formal
binary equivalence, or an externally checked solver proof certificate. The
source models came from the original Linux-target frontend; their bit-vector
queries are replayed exactly. SAT results currently identify circuit mismatch
without reconstructing public C inputs.

Keep limbs16 as a verified research baseline, with its measured runtime and size
costs. The next bounded task is broader P-code merge/wide-value coverage, followed
by new representation/algorithm candidates under the same correctness,
reconstruction-resource and application-cost protocol. Human reconstruction,
broader memory-state inference, x86 and reserved-family generalization remain
unmeasured. No candidate is selected as a protection winner.
