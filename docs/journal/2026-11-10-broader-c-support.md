# One development sequence for broader C-SRD support

Status: single development direction selected; milestones proposed and coverage
implementation pending.
Stage: background review and milestone specification.
Observation type: current repository inspection and prospective planning.
Related: [coverage plan](../broader-c-support.md), MEM-01/02, COV-01–09,
VER-01 and the existing validation tasks. Starting commit: `042e2ec`.

## Decision and scope correction

An initial uncommitted draft proposed a Tigress comparison backend alongside
C-SRD development. The user corrected the scope to one development sequence:
broader C-SRD support informed by Tigress's published designs. The drafts were
revised before any Tigress adapter was implemented, installed or executed.
There is no external Tigress backend or comparison milestone in the active plan.

## Thinking, doing and questions

The current pure-u32 model excludes ordinary memory-using and effectful functions.
Existing compiler and diversification research can guide extensions; its
guarantees do not transfer automatically to our implementation. The practical
question is whether explicit memory/call boundaries let C-SRD transform useful
computations while preserving all admitted observable behavior.

This change records the single-track milestones, dependencies and completion
evidence. The next implementation work is the bounded pointer/buffer contract,
memory-aware analysis and actual transformation, with validation integrated.
We want to learn which effects and verification assumptions become necessary,
how much computation stays encoded, and what survives optimized compilation.
No new coverage or protection result has been obtained by writing this plan.

## Evidence and references

The [prior-art review](../prior-art.md) already credits Tigress for related data
representations. The [persistent-session study](../../reports/persistent-sessions.md)
found increased local analysis costs with successful reconstruction throughout
and continuing JVM warmup effects. These are existing observations, not evidence
for new memory/call support.

Primary designs reviewed on 2026-11-10:
[developer architecture](https://tigress.wtf/developers.html),
[EncodeData](https://tigress.wtf/encodeData.html),
[Flatten](https://tigress.wtf/flatten.html),
[Virtualize](https://tigress.wtf/virtualize.html) and
[LowerType](https://tigress.wtf/lowerType.html). They inform analysis, representation
boundaries, control state and numerical-contract questions. They are published
design references, not successful local Tigress experiments.

## Implementation order and safeguards

Start with bounded pointer/buffer loads and stores using ordinary caller-visible
memory. Then add known direct calls and I/O boundaries, selected allocation
patterns, input-dependent loops/recursion, signed arithmetic, exact floating
point and concurrency through separate contracts. Split the older combined
allocation/recursion/signed backlog item so each has independent completion
evidence. Accepted input and actually transformed coverage must remain distinct.

Every increment includes correctness contracts, artifact validation, compiler
checks and measurements. Investigating independent memory verification is part
of the first increment. In the inspected shell, CBMC and Frama-C were not found
on PATH; their availability in other environments remains unestablished.
Preserve the existing pure-function validation gate and explicitly label the
evidence level of any new contract.

The old warmup issue is a measurement-calibration requirement when interpreting
future cost experiments. It does not become a separate development workstream.
Keep resource runs serialized and freeze observer/protocol choices before
reserved evaluation. Failures of an observer to support a new construct do not
establish protection.

## Validation of this planning change

`git diff --check` passed. A local link-target check covered all seven changed
Markdown files and found all 151 local targets; coverage task IDs and removal
of the superseded draft paths were also checked. This is documentation
validation only. Compiler tests and performance experiments were not rerun
because this change modifies no implementation or experimental artifacts.

## Handoff

MEM-01/02, COV-06 and VER-01 form the first coverage milestone. Begin with its
precise memory assumptions, observable-state comparison and bounded prototype.
Declare fixture/seed/budget details before experiments, record material failed
attempts, and update the supported semantic contract only when the required
implementation and evidence exist. No deadline, performance result or universal
C support claim is made by this planning change.
