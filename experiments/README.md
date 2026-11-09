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
