# Compositional verification and Jenkins follow-up, 2026-11-10

**Later follow-up:** [checked-circuit grading](circuit-grading.md) resolved all ten
saved inconclusive limb answers under the recorded model. The observations and
original grader statuses below remain the historical record.

## Result

The new verifier admits the previously blocked Jenkins limb candidate without
changing its generated C. All 17 test groups pass on macOS and Linux. A separate
development experiment completed 100 validated build cells, including the newly
admitted limb candidate across 25 profiles. **This is a verification improvement;
the follow-up does not establish increased reconstruction difficulty.**

Implementation: `fc5174c`. The [specification](../docs/compositional-validation.md)
explains source-to-graph validation, actual-fragment invariants and actual-return
validation. All three are mandatory for a compositional proof. The
[journal](../docs/journal/2026-11-10-compositional-validation.md) preserves the
constant-scale prototype failure and its correction. The
[measurement protocol](../experiments/limbs-composition-followup.json) was frozen
after correctness tests and before the follow-up measurements. There were no
runtime/size cutoffs; reserved reconstruction families remain unopened.

## Correctness and verification resources

The candidate SHA-256 before and after the verifier change is
`557dbff695e80e6c9a8ee83832e746c5c9be95546a8e1f6d7d83de0298f5a675`.
The earlier failed transformation report recorded this candidate hash despite
correctly withholding its C output. The new path discharges 41 obligations:
original-to-graph, 39 graph nodes, and the emitted return. Every operation proves
both positional value equality and 16-bit bounds for each piece.

The first prototype still timed out on one local scale operation and fell back
to the successful full-function proof. A stricter regression test exposed this
on both platforms. Expressing positional reconstruction as addition in the
invariant made polynomial normalization effective; the actual OR-based C return
remains independently checked. No source formula, input domain or timeout limit
was changed to obtain that result.

Validation includes 88 reparsed/generated-C contracts that explicitly require
composition, 13 graph/hint/range/dependency/return/budget controls, renamed Jenkins
locals/parameters, artifact hashes, Z3 CLI replay of recorded obligations, and
GCC/Clang execution at O0/O2 and O1 with ASan/UBSan. CLI replay uses the same
solver family; it is not an independently checked proof certificate. Full CTest
runs took 135.46 seconds on macOS and 38.56 seconds on Linux; these are test-run
durations, not controlled compiler-performance estimates.

Three alternating old/new attempts used the same Linux ARM64 environment,
30-second solver budgets and 40-second process budgets, without an excluded
warmup. The old executable is the frozen `2eac664` binary. The new executable
and both source snapshots are hash-bound in the protocol.

| Verifier | Outcomes | Process wall seconds | CPU seconds | Sampled tree RSS, MiB |
| --- | --- | --- | --- | --- |
| Whole-function baseline | 3/3 inconclusive; no C output | 30.039–30.070 | 30.014–30.026 | 151.906–160.414 |
| Compositional limb path | 3/3 proved under model; C output | 0.211–0.223 | 0.207–0.210 | 104.828–104.930 |

These are **verification** resources, not observer/reconstruction resources.
No completed-proof speedup ratio is estimated: the old attempts are censored
failures. The proof remains conditional on the frontend/model, partition checker
and Z3; compiler and machine-code equivalence are not proved.

## Compiler and application costs

The follow-up compares original, identity, affine seed 42 and limbs16 for Jenkins.
Clang 18.1.3 and GCC 13.3.0 completed 100 cells across 25 available profiles.
One x86 profile was unavailable on the ARM64 runner; the matrix status is
`completed-with-gaps`. Profiles include optimization levels, LTO/ThinLTO, PGO,
native CPU flags and sanitizers. XOR/planned remain outside this new proof path;
their earlier failures were neither rerun here nor relabeled.

| limbs16 versus original | Runtime ratio | Linked `.text` ratio | Whole executable ratio |
| --- | ---: | ---: | ---: |
| Clang O2 | 2.259 | 1.333 | 1.000 |
| GCC O2 | 2.420 | 1.374 | 1.000 |
| Clang O2 + LTO | 2.284 | 1.258 | 1.001 |
| GCC O2 + LTO | 2.407 | 1.280 | 1.001 |

Runtime ratios are medians of seven paired samples with one million harness
iterations per sample. They include input generation and calls on a shared host,
not isolated function latency. Linked text includes harness/runtime code and
padding. At Clang O2 it grew from 708 to 944 bytes; at GCC O2 from 844 to 1,160
bytes, while both whole executable sizes stayed unchanged.

Limb instruction-mnemonic sequences differ from the identity control in 25/25
profiles. The metric includes the kernel and main, ignores operands and padding
NOPs, and is structural evidence only. Compiler survival has measurable costs;
it is not a protection result.

## Fixed reconstruction observers

Both observer runs used five measured repetitions and one excluded warmup,
serialized after builds/tests. The fixed observer receives the binary and public
ABI. Grading occurs afterward against the matched original frozen build input;
its resource cost is separate. This is code-enforced separation, not OS isolation.

| Observer | Measured attempts | Recovered under source model | Wrong answer | No candidate | Grading inconclusive | Unsupported reconstruction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bit-linear query model | 120 | 0 | 40 | 80 | 0 | 0 |
| Ghidra/P-code | 30 | 15 | 0 | 0 | 10 | 5 |

Warmups (24 query-model and 6 Ghidra attempts) are excluded. Attempts are repeated
measurements of particular artifacts, not independent programs.

The query model behaves the same for original, identity, affine and limb variants:
32 queries cannot supply its full basis; 65 fit that basis but produce incorrect
models; 128 expose the inconsistency before submission. The basis-only models
scored about 3.65% on the separate execution-grading inputs and were refuted by
source-model counterexamples. This is a model-class limitation affecting the
original too, not evidence of protection or increased query complexity.

Ghidra recovered original and identity Clang candidates and identity GCC
candidates. The GCC original reaches unsupported control-flow/effect operations
in the adapter. The limb variants yield C, but all ten direct equivalence grades
time out. They are retained as **grading inconclusive**, not failed
reconstructions or proven protection.

| Ghidra artifact | Exported P-code operations | Median target decompile, ms | Median whole observer CPU, s | Median sampled tree RSS, MiB | Grading outcome |
| --- | ---: | ---: | ---: | ---: | --- |
| Clang O2 original | 28 | 8.692 | 6.663 | 447.547 | Proved |
| Clang O2 identity | 28 | 6.455 | 6.732 | 431.609 | Proved |
| Clang O2 limbs16 | 124 | 12.117 | 6.638 | 450.453 | Inconclusive |
| GCC O2 original | 19 | 14.100 | 6.187 | 495.801 | Adapter unsupported |
| GCC O2 identity | 28 | 9.862 | 6.386 | 466.492 | Proved |
| GCC O2 limbs16 | 154 | 16.040 | 6.730 | 412.988 | Inconclusive |

These descriptive resource medians include unsuccessful/ungraded attempts.
They are not successful-reconstruction cost ratios. Target decompilation is
milliseconds within seconds of total observer CPU, much of it setup. Sampled
aggregate RSS can miss peaks and count shared pages more than once. Larger
P-code graphs and modest phase-time differences do not establish a general
increase in correct reconstruction cost.

The Clang original and identity executables are byte-identical. Their differing
CPU/RSS samples provide a direct measurement-noise control; those differences
cannot be attributed to changed program instructions. Raw summaries explicitly
flag these comparisons.

## Separate grading-chain probe

After the frozen observer run completed, selected the first measured inconclusive
limb answer for each O2 compiler. The proposal was to validate through the exact
transformed build input: original = transformed input, then transformed input =
fixed reconstructed answer. Both links would be required; the observer would
receive no extra information. Used 30-second solver budgets per link, retained
hashes/queries and checked the existing corrupted answers.

Both original-to-transformed links proved (about 0.22 seconds process wall time).
Both transformed-to-reconstructed links remained inconclusive at 30 seconds.
Both corrupted-answer checks found counterexamples. This failed probe does not
resolve the grader limitation. The original observer records and statuses remain
unchanged; no reconstruction was promoted to success.

## Reproduce and next decision

```sh
cmake --build build -j 2
ctest --test-dir build --output-on-failure
build/csrd transform benchmarks/rich/development/jenkins_word.c \
  -o build/jenkins-limbs.c --strategy limbs16 --timeout-ms 10000 \
  --report build/jenkins-proof.json
```

The [evidence manifest](composition-evidence-20261110/sha256.json) binds complete
raw matrices, source/build inputs, executables, observer attempts, CPU/RSS samples,
queries, failed prototypes, the grading probe, test logs and driver scripts.
[The frozen driver](composition-evidence-20261110/run.py) contains exact Linux
commands for all phases. It requires the documented `csrd-dev:ghidra` ARM64 image,
matching dynamic dependencies and a checkout mounted at `/work`; use fresh output
paths when rerunning. See the readable
[matrix summary](composition-evidence-20261110/matrix-summary.json) and
[resource summary](composition-evidence-20261110/proof-resources-summary.json).

Keep the verified limb implementation as a research baseline. Next resolve
grading of optimized limb reconstructions and the remaining observer coverage
gaps before ranking further representation candidates. Memory-location inference,
human understanding, x86 results and reserved-family generalization remain
unmeasured. No candidate has been selected as a protection winner.
