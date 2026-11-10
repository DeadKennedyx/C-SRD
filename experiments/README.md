# Experiment protocol

The [technical specification](../README.md) defines the current research problem
and model. Experiments follow observation, hypothesis, design, execution,
analysis and revision. A new [journal entry](../docs/journal/README.md) records
the protocol before running; retrospective descriptions must say so.

## Before execution

1. State one testable question, domain, competing explanations and decision rule.
2. Identify experimental units: source functions, artifacts, compiler settings
   and repeated timing samples are different units and may be correlated.
3. Select treatments and the untransformed original baseline. Include identity
   lowering where it helps separate representation effects from graph lowering.
4. Specify corpus/input selection, seeds, matched coverage where relevant,
   compilers, targets, flags, bounds, repetitions and planned metrics.
5. Define positive controls, unrelated negatives and deliberately faulty cases.
   Explain manual challenges and other selection effects.
6. Record assumptions, nuisance variables, exclusion rules and what would count
   as failure, rejection or inconclusive evidence. Do not silently omit timeouts.

## Execution and data collection

Reserve `experiments/runs/` for local raw artifacts (gitignored). Evaluator and
synthesis run directories must be new. Retain originals, generated C, proof
reports, commands, versions, hashes, outputs, counterexamples and timing samples.
Record deviations as they occur. Check selected evidence into `reports/` with
enough provenance to reproduce it; do not manufacture missing observations.

The implemented commands are:

```sh
python3 tests/differential/run.py --csrd build/csrd --report build/differential.json
python3 tests/differential/expanded.py --csrd build/csrd --report build/expanded-differential.json
python3 tools/verify_rules.py --report build/rule-contracts.json
python3 tools/synthesize_rules.py --output-dir experiments/runs/rule-search
python3 tools/evaluate.py --csrd build/csrd --compiler clang-18 --compiler gcc \
  --objdump llvm-objdump-18 --output-dir experiments/runs/evaluation
```

Use installed compiler/objdump paths on the host; setup is in
[getting started](../docs/getting-started.md). Differential discovery prints
missing families; set `CSRD_REQUIRE_BOTH_COMPILERS=1` when both are required.
The standalone evaluator fails when an explicitly requested compiler is absent.

For analysis cost, use the [reconstruction effort protocol](../docs/effort-measurements.md).
It adds paired process-tree CPU/RSS, wall time, query/trace/resource budget grids,
correct and incorrect recovery, separate grading cost and human-session recording.
Application runtime benchmarks and analyzer effort remain distinct measurements.

To investigate a grader timeout without changing an observer, use the optional
[checked-circuit replay](../docs/circuit-validation.md) and
`grade_saved_answers.py`. It binds saved C files and queries, records a protocol
before execution, checks corrupted-answer controls and reports grader resources
separately. The [first result](../reports/circuit-grading.md) resolved correct
reconstructions that the earlier grader could not prove in time.

For the wide/vector coverage follow-up, `run_wide_observer.py` repeats all cells
of the completed positional-width Ghidra study while checking frozen inputs and
declaring observer changes. `grade_wide_observer.py` replays every inconclusive
measured answer with a separate 30-second circuit budget. It deduplicates exact
query bytes and retains all trial memberships and controls; shared results are
not independent grading-time samples. `summarize_wide_observer.py` validates the
source/query/report chain before deriving statuses and paired cost tables.
Commands and limitations are in the [follow-up report](../reports/pcode-wide-values.md).
Always use fresh directories and keep tests/builds separate from resource runs.

## Analysis and reporting

Preserve tested, bounded-checked, proved-under-model, unsupported and inconclusive
statuses. Report transformation coverage and denominators so unchanged programs
cannot masquerade as successful diversification. Compare return behavior only
within the pure contract; future memory/effect experiments need richer observations.

Measure source, CFG, LLVM IR, object code, algorithmic strategy and behavior
separately. Compiler optimization can erase source changes. Record false matches
and misses, not accuracy alone. Fingerprints and their hashes are evidence, not
proofs. A curated challenge is not an unbiased held-out benchmark.

Compile original/variant separately under identical conditions. Keep input
generation and compilation outside runtime timing. Retain repetitions and raw
samples, report noise and avoid interpreting small differences as speedups
without an appropriate analysis. Proxy conversion/operation costs are not cycles.
Report failed hypotheses and alternatives worth pursuing.

The v0.5 [validation record](../reports/roadmap-validation.md) now includes
correctness, recognition, structure, compile/verification time, runtime and code
size measurements. These replace the earlier M1-only measurement scope; they do
not establish novelty or general performance benefits. The next controlled
experiments are [EXP-01 and EXP-02](../docs/backlog.md).

## Handoff

A completed experiment should provide its question, methods, results, limitations,
interpretation and reproducible entry point in a scientific-style report. Link
the journal and resulting backlog decision. Do not change the success criterion
after seeing the data without explicitly recording a new exploratory analysis.
