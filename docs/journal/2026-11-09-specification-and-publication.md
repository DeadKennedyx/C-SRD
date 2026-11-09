# 2026-11-09 — evidence-driven specification and personal publication

Stage: retrospective analysis, specification and publication preparation.
This entry was written during preparation of the first GitHub push. It is not a
contemporaneous journal of the earlier compiler implementation or its experiments.

## Thinking, doing and questions

* **Thinking:** the working prototype needs a specification that makes its
  problem, model, decisions and evidence understandable without the development
  conversation. Broader C support must remain a separate research commitment.
* **Doing:** inspect code/reports, restructure the README, preserve a usage guide,
  add journaling/protocol/task templates and prepare the repository for the
  maintainer's personal GitHub account.
* **Want to do:** publish reproducible research engineering with explicit failure
  conditions and traceability, then investigate an independent C-level backend.
* **Want to know:** do the specification's claims match the source and reports;
  can another researcher run the same checks; which observations actually support
  representation planning and which remain confounded?
* **Discovered:** historical evidence supports a restricted prototype, not full C
  coverage. Conversion counts do not establish runtime benefit. Finite behavioral
  fingerprints have a demonstrated false-match control. See the sources below.

## Observations and evidence sources

The inspected [semantic model](../semantics.md) covers pure uint32 functions,
limited control and local literal tables. The [region IR](../../include/csrd/ir.hpp)
has no general memory or external-effect model. The
[validator](../../src/verification/translation.cpp) compares original and
reparsed emitted regions; it shares Clang and subset analysis with the frontend.

The [2026-11-08 record](../../reports/roadmap-validation.md) reports 9/9 native
and Linux Release test groups, finite differential comparisons and scoped SMT
obligations. Its [native](../../reports/roadmap-macos-evaluation.json) and
[Linux](../../reports/roadmap-linux-evaluation.json) measurements show false
fingerprint matches and optimized-away source differences. Those are historical
observations; writing this specification does not count as another run.

Background: [prior-art review](../prior-art.md), [research questions](../research-questions.md),
[RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) and
[RFC 8174](https://www.rfc-editor.org/rfc/rfc8174). The project owner supplied
the evidence-driven methodology and journal prompts. No organizational
affiliation or independently verified effectiveness of that methodology is implied.

## Problem, alternatives and decision

Problem: the repository needs a buildable, evidence-linked specification for
its implemented restricted transformer, distinct from proposals for broader C.

Alternatives considered for documentation:

* Keep only an installation README: useful for execution but insufficient to
  expose hypotheses, constraints and decision rules.
* Describe the entire future C language scope as one implemented specification:
  inconsistent with the current model and observed evidence.
* Specify the current baseline and link separate experiments/backlog entries:
  selected because its claims can be checked against existing artifacts.

This is a documentation/traceability decision, not a new compiler experiment.
H-01 in the README is a retrospective formulation of the existing representation
experiment. No claim of prospective preregistration is made.

## Protocol and implementation deviations

Inspect the semantic model, arithmetic/graph/validation code, actual CLI and raw
reports. Check local document links and compare summarized numeric results with
their JSON sources. Exercise documented transform/verify commands using the
existing build, and inspect the publication identity and destination.

The maintainer created the remote repository and supplied the personal email
`juan.dw.ft@gmail.com`. SSH authentication through `github-personal` identified
`DeadKennedyx`. The remote advertised no refs at inspection. Unpublished commit
author/committer metadata was normalized to that personal identity. Every old
commit's tree hash was checked unchanged; dates/messages and raw reports were
preserved. [Publication history](../../reports/publication-history.json) maps
historical report IDs to personal-history IDs without rewriting measurements.

An outdated M1-only experiment-directory description was found and updated to
describe the actual v0.5 measurements and their limitations. The previous usage
instructions remain available in [getting started](../getting-started.md).

## Interpretation and handoff

Fresh publication validation on 2026-11-09: `cmake --build build --parallel 4`
reported no build work, and all nine CTest groups passed in 58.07 seconds.
The documented calculate transform and standalone verification succeeded;
Clang and GNU GCC compiled the emitted example as C11 with warnings treated as
errors. Document links/fences and the issue-template YAML passed local checks.
Every file in the historical roadmap source snapshot matched its mapped
personal-history implementation commit. Author/committer identities and reachable
historical content were checked against the requested personal publication scope.
Raw records: [CTest](../../reports/publication-2026-11-09-ctest.log) and
[command smoke check](../../reports/publication-2026-11-09-smoke.json).
These are new correctness/publication checks, not a rerun of the performance study.

Support is limited to the admitted model. The observed 16 planned versus 42
independent conversion events aggregate different coverage choices; a fair
coverage-controlled planning experiment is still proposed. The explicit rare
input explains the zero-error held-out control and prevents interpreting it as
general classifier accuracy. No new performance or formal-proof result is added
by this publication task.

Publication completion requires remote main to match the pushed local commit;
GitHub Actions status must be observed separately and must not be inferred from
the historical local test record. The next research tasks are in
[the backlog](../backlog.md). A new memory-support specification must compare
observable memory changes, not merely reuse the current return-value query.
