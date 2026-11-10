# Research journal

The journal records the reasoning and evidence behind specifications and changes.
It complements executable tests and raw reports; it does not replace them.
Record meaningful hypotheses, prototypes, decisions, failures and findings.
Routine edits and mechanical fixes do not each need a journal entry; group them
under the substantial experiment or change they support.

Use a new dated entry for a research question, experiment or material deviation.
State whether observations are contemporaneous, retrospective or proposed. Link
source/configuration identities, commands, raw outputs, counterexamples and
limitations. A failed experiment is a result; a timeout is inconclusive. Correct
an interpretation with a dated follow-up rather than silently altering its data.

Every entry addresses five prompts:

1. What am I thinking?
2. What am I doing?
3. What do I want to do?
4. What do I want to know?
5. What did I discover?

The [entry template](TEMPLATE.md) also captures initial observations, alternatives,
background sources, testable questions, protocol, materials, data, deviations,
analysis and handoff. Do not backfill plans as though they were preregistered.
When useful, attach a cause diagram or dependency graph; clearly label untested
causal explanations and estimates.

| Entry | Stage | Evidence scope |
| --- | --- | --- |
| [2026-11-09 — specification and personal publication](2026-11-09-specification-and-publication.md) | Retrospective analysis, specification and publication preparation | Existing source/reports plus a fresh correctness and command-smoke run; no new compiler functionality or performance study |
| [2026-11-09 — software-protection scope and compiled-code audit](2026-11-09-protection-audit.md) | Scope clarification, prototype, negative controls and validation | New paired audit; distinguishes compiled differences from unmeasured reconstruction effort and memory exposure |
| [2026-11-09 — algorithm and encoding survival at O2](2026-11-09-algorithm-survival.md) | Exploratory analysis and next-increment selection | Four existing popcount candidates across four compiler configurations; separates algorithm differences from encoding differences |
| [2026-11-09 — validation matrix before selection](2026-11-09-validation-matrix.md) | Protocol, implementation and validation | Linked build matrix, compiled screening, fixed reconstruction observer and bounded debugger recovery |
| [2026-11-09 — decompiler and control-flow experiment](2026-11-09-decompiler-control-flow.md) | Hypothesis, bounded prototype and fixed observer | Ghidra reconstruction, source-model scoring, parity-split controls and expanded benign corpus |
| [2026-11-09 — reconstruction effort measurements](2026-11-09-effort-measurements.md) | Instrumentation, fixed observers and paired pilot | CPU/RSS accounting, observation and resource budgets, recovery accuracy, controls and human-session recorder |
| [2026-11-09 — richer benchmarks](2026-11-09-richer-benchmarks.md) | Corpus design, failed proof pilot and validation | Eight contracts, reserved families, independent oracles, deliberate false fingerprints and report-only exploration |
| [2026-11-09 — two-piece prototype](2026-11-09-limb-prototype.md) | New representation and query observer | Positional arithmetic, proof bottlenecks, preserved failed candidates and a prespecified broad development comparison |
| [2026-11-10 — P-code count correction](2026-11-10-pcode-counts.md) | Measurement adapter correction and repeated comparison | Wide constant counts distinguished from wide data, original-run preservation and unchanged binaries |
| [2026-11-10 — compositional validation](2026-11-10-compositional-validation.md) | Verification hypothesis, failed scale prototype and validated correction | Actual emitted fragments, untrusted graph/partition hints, range invariants, independent SMT replay and newly admitted Jenkins candidate |

Future work is tracked in [the backlog](../backlog.md). External issue numbers
and review outcomes belong here only after those events actually occur.
