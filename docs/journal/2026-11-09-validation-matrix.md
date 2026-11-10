# Validation matrix before candidate selection — 2026-11-09

Status: in progress. Initial protocol recorded before implementation runs.

The owner requested the broader evaluation matrix first, followed by compiled
candidate selection, meaningful instruction comparisons, measured reconstruction
and cost, and runtime observations. The motivating failures are the affine
`calculate` collapse and Clang's removal of the SWAR encoding. Changing only
source-level proxy costs would tune against an incomplete evaluator.

## Question and protocol

Can we reject incorrect, collapsed, over-budget or unassessed candidates without
turning byte differences into a protection claim? Reuse the independent emitted-C
and compiler-preprocessed-input verification gates. Link real executables with
runtime inputs, including LTO and profile-guided builds where available. Keep
per-profile controls, versions, hashes, commands, failures and missing tools.

The matrix will declare optimization, compiler, target, linking, instrumentation
and profiling factors. Core tests run every change; broader and held-out profiles
are separate. Source semantics-changing options are outside this contract.
Selection may use development profiles only; held-out results do not rerank.

The four increments are a bounded first implementation: candidate selection
using compiled observations; normalized instruction and LLVM SSA comparisons;
an independent automated reconstruction observer plus repeated paired costs;
and a bounded debugger observer over our own benign functions. Automated recovery
is not human analyst effort. Register/stack samples are not exhaustive memory
coverage. Runtime recovery must be scored against held-out observations, with
controls, rather than treating absent literal values as protection.

Acceptance requires real compilation/execution and failure controls: semantic
mutation, preprocessing changes, missing configurations, identity/collapse,
bad budgets, and attempted selection using held-out results. Preserve timeouts
and unsupported environments. Never require a transformation to survive in a
unit test: compiler outcomes are research observations.

## Implementation and results

To be completed with observed results, deviations and reproducible commands.
