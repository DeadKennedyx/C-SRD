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

Future work is tracked in [the backlog](../backlog.md). External issue numbers
and review outcomes belong here only after those events actually occur.
