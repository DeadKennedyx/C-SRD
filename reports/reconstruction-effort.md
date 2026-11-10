# Reconstruction effort: instrumentation and paired pilot

This increment measures how much work a **specified observer** spends producing
a reconstruction, and whether that reconstruction is correct. It adds CPU,
resident memory, queries, trace observations, budget sweeps, paired resource
ratios and a human-session recorder. Transformed-program correctness remains a
prerequisite; lower observer accuracy never permits incorrect generated C.

Implementation: [`5f50423`](https://github.com/DeadKennedyx/C-SRD/commit/5f504231a98a35367e8a97eeba02f72f9f50043b).
The [protocol](../docs/effort-measurements.md) specifies measurement scope,
statistical limits and commands. The [journal](../docs/journal/2026-11-09-effort-measurements.md)
records the question, declared pilot and a summary bug discovered during execution.

## Method and controls

The pilot uses fresh validated Clang 18/GCC 13 O2 Linux ARM64 builds of calculate,
XOR and a rotation function. All 30 builds, including identity/split controls,
validate successfully; 5,264 original-versus-variant differential comparisons
pass. The black-box sweep compares original, identity, affine seed 42 and the
opt-in affine/split variant. The decompiler and runtime sweeps omit identity.
There are five measured repetitions plus one excluded warmup per cell. Variant
order is randomized within matched blocks; analysis is serialized.

The measured Linux guest reports two logical CPUs with affinity `[0,1]`, Python
3.12.3 and kernel 6.8.0-117-generic. The development host reports Apple M5 and
16 GiB RAM; that is not a claim of exclusive physical hardware for the guest.
The container image ID is
`sha256:880358a74512e1deac327db13818f10e5b0cf8538f3490996952b8d379541f00`.
Ghidra 12.2 uses the pinned distribution and native ARM64 decompiler documented
in [the earlier audit](../docs/decompiler-audit.md).

Tools and inputs are hashed. The fixed observer receives a binary and known ABI;
reference source is withheld until grading. Its answer is frozen before
held-out queries or source verification. Grading CPU/time is recorded separately.
Known function names, process startup and warm filesystem caches are part of
this protocol. It does not measure unknown-symbol discovery or human reasoning.

## Black-box recovery

Across 240 measured attempts, 200 reconstructed C functions prove equivalent
under the source model; 40 candidates are refuted. The refuted candidates are
**all** XOR at the three-query budget, equally affecting originals and variants.
Basis probes cannot distinguish XOR from addition, and the declared first-fit
policy chooses the affine model. Its held-out return accuracy is 16.7% in this
pilot; the verifier also supplies a counterexample.

At 12 and 64 queries, every version of both functions is correctly recovered.
Calculate already succeeds at three queries. These are tested budget points,
not theoretical minimum query complexities. They show no added query requirement
from these transformations against this observer.

At the 12-query calculate/Clang O2 point, affine CPU cost is 0.996× its paired
original; affine/split is 1.019×. End-to-end observer CPU is about 19 ms, dominated
by process/harness overhead. The millisecond-scale values and polling resolution
do not support claims about isolated inference latency. Short-lived process RSS
samples vary; a missed sample is not a demonstrated memory saving.

## Ghidra recovery

The 120 measured attempts comprise 25 successful source-model reconstructions,
35 unsupported reconstructions and 60 outer wall-budget expirations. All
one-second attempts expire; this budget primarily tests startup/resource
handling, not transformation difficulty. At 30 seconds, calculate recovers in
both compilers except the Clang split variant, whose P-code remains outside the
adapter. Every rotation attempt at that budget is unsupported, including its
originals. These are known coverage gaps.

For calculate at the 30-second budget:

| Build and variant | Correct / attempts | Median paired CPU ratio | Exploratory 95% interval |
| --- | ---: | ---: | ---: |
| Clang O2, affine | 5 / 5 | 0.986× | 0.965–1.049× |
| Clang O2, affine/split | 0 / 5; unsupported | Unassessed | Unassessed |
| GCC O2, affine | 5 / 5 | 0.994× | 0.934–1.085× |
| GCC O2, affine/split | 5 / 5 | 0.985× | 0.955–1.041× |

These comparable successful runs show no established CPU increase. The
intervals describe five repeated pairs on individual artifacts, not unseen
programs or analysts. Unsupported cases receive no slowdown ratio. Full raw
wall/CPU/RSS samples, phase timings and outcome denominators are retained.

Sampled aggregate peak RSS also fails to establish an increase. For those same
successful comparisons, median paired ratios are 1.060× (Clang affine), 0.998×
(GCC affine) and 1.018× (GCC affine/split), with exploratory intervals
0.973–1.816×, 0.789–1.128× and 0.941–1.229× respectively. Median sampled peaks are
roughly 410–493 MiB across these cells. Sampling, shared pages and Java's memory
behavior limit interpretation; no memory ratio is assigned to unsupported pairs.

## Runtime recovery

The 180 measured attempts contain 135 successful held-out recoveries and 45
no-candidate outcomes. All three variants fail to fit a mapping with one
instruction observation per training trace; all succeed at 4, 16 and 64, for
each tested training count of 3, 4 and 8. The lowest tested successful point is
therefore **three training traces with four instruction observations each**,
equally for the original, affine and affine/split versions. Each frozen selected
mapping is scored on sixteen separate held-out inputs. Permuted-label negative
controls yield no fitted maps in this pilot.

With four training traces and a four-step limit, median paired CPU ratios are
1.014× for affine (exploratory interval 0.973–1.091×) and 1.039× for affine/split
(0.993–1.090×). At the 64-step setting, affine/split has a 1.024× ratio
(1.007–1.139×): there is a small observed cost of tracing farther in that fixed
protocol, but **successful recovery already occurs at four observations**.
This is not evidence of an increased minimum reconstruction requirement.

The task deliberately knows that its target is `x+y mod 2^32`. Calculate's public
return `3*(x+y)+11` already determines that sum, because 3 is invertible modulo
2^32. These are exposure/recovery controls, not a suitable confidentiality
challenge. General unknown-memory reconstruction remains outside this observer.

## Evidence and reproduction

The pilot contains **648 attempts: 540 measured and 108 excluded warmups**.
The [evidence index](effort-evidence-20261109/index.json) records file/archive
hashes. Archives retain binaries, frozen compiler inputs, all observed outcomes,
resource samples, query/trace data, logs, reconstructions, proofs and negative
controls. The archiver omits transient Ghidra project databases if present and
retains their hashes; none were present in this completed collection. The exact scoring executable is archived separately
and still requires the documented Linux ARM64 LLVM/Z3 libraries.

| Evidence | Summaries | Individual trials | Raw archive |
| --- | --- | --- | --- |
| Black-box | [JSON](effort-evidence-20261109/blackbox-summary.json) | [CSV](effort-evidence-20261109/blackbox-trials.csv) | [Archive](effort-evidence-20261109/blackbox.tar.gz) |
| Ghidra | [JSON](effort-evidence-20261109/ghidra-summary.json) | [CSV](effort-evidence-20261109/ghidra-trials.csv) | [Archive](effort-evidence-20261109/ghidra.tar.gz) |
| Runtime | [JSON](effort-evidence-20261109/runtime-summary.json) | [CSV](effort-evidence-20261109/runtime-trials.csv) | [Archive](effort-evidence-20261109/runtime.tar.gz) |
| Validated builds | [Command/provenance](effort-evidence-20261109/commands.json) | 30 linked cells | [Archive](effort-evidence-20261109/matrix.tar.gz) |

On the existing Linux image, from the repository root:

```sh
docker run --rm --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \
  -v "$PWD:/work" -w /work \
  -e CSRD_GHIDRA_HEADLESS=/work/experiments/runs/dependencies/ghidra_12.2_PUBLIC/support/analyzeHeadless \
  csrd-dev:ghidra python3 experiments/effort_pilot.py \
  --output-dir experiments/runs/effort-replication
```

For a clean installation, [Dockerfile.ghidra](../experiments/Dockerfile.ghidra)
pins/downloads/builds the dependency and sets the tool path inside the image;
omit the mounted dependency override above. Build the C-SRD executable inside
that environment first, following [getting started](../docs/getting-started.md).
The pilot driver builds its own matrix before measuring, so the verifier and
frozen inputs match. New output directories are required.

```sh
python3 experiments/archive_effort.py \
  --run-dir experiments/runs/effort-replication \
  --output-dir reports/effort-replication --csrd build-linux-release/csrd
```

CPU/RSS caps and arbitrary budget grids are implemented in the measurement CLI.
The real CPU/RSS exhaustion tests validate enforcement; this pilot collects
uncapped CPU/RSS costs and sweeps wall/query/step budgets. Hardware performance
counters, energy consumption and human results were not measured.

## Validation and an observed infrastructure failure

The complete suite passed **14/14 groups on macOS** (100.13 seconds) and
**14/14 on Linux** (59.64 seconds). The Linux run includes real GDB and Ghidra.
Logs: [macOS](effort-native-ctest.log), [Linux](effort-linux-ctest.log).

Hosted [correctness CI](https://github.com/DeadKennedyx/C-SRD/actions/runs/42756054197)
and [Ghidra CI](https://github.com/DeadKennedyx/C-SRD/actions/runs/42756054553)
passed for implementation commit `5f50423`. The follow-up fix's hosted runs were
still in progress at the [recorded status check](effort-ci-status.json); its
focused local tests completed as described below.

After all Ghidra trials were collected, its final summary failed when a timed-out
worker had no answer object. The raw trials were not lost or rerun. The fix in
[`baa34d8`](https://github.com/DeadKennedyx/C-SRD/commit/baa34d8) handles null answers
and adds a real 1 ms CLI-budget regression. The focused suite passed again:
[Linux seven tests; macOS six and one platform skip](effort-null-answer-validation.json).

The original failed report is preserved as `effort.before-resummary.json`.
`experiments/resummarize_effort.py` checks complete declared trial counts and
unchanged observer/input hashes, then records the changed postprocessing hashes
separately. Only statistics are regenerated. The runtime sweep uses the fixed
driver. This distinction remains in the evidence rather than being presented
as an uninterrupted successful run.

## Interpretation and remaining work

CPU, memory and runtime costs belong to the specified observer and workload.
Unsupported tools, wrong low-budget guesses and timeouts do not establish
general software protection. Human timing is **unassessed**: packet preparation,
active/wall timers, hashed submission snapshots and post-session source grading
are implemented and tested with synthetic sessions only.

The next engineering task is to close the independent P-code observer's merge
and wide-value gaps, then use a newly reserved corpus for a confirmatory study
with predeclared practical effect thresholds. Real analyst sessions are needed
before claiming increased human reconstruction time. Neither these measurements
nor the encodings establish memory confidentiality.
