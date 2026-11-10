# Validation matrix before candidate selection — 2026-11-09

Status: bounded implementation and validation completed. Initial protocol was
recorded before implementation runs; observed changes and outcomes follow.

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

The first linked prototype used a separate validation-only path in the existing
audit. A preprocessing counterexample test checks that this path really freezes
and verifies both build inputs before linking; it cannot skip validation and
still count a completed cell.

The first broader macOS run failed in GCC profile-use builds: moving the frozen
input between training and use changed GCC's recorded source locations. The
fix compiles a hash-checked stable-path copy in both phases while preserving
each phase's independently validated input. A targeted rerun passed. Probe
profile output was also moved into the experiment directory.

Review added three safeguards: ignore explicit NOP padding in the mnemonic
metric, reject nonfinite budgets, and require matching development seeds and
strategies for held-out evaluation. Harness generation now uses single-pass
template substitution and avoids a helper-name collision. The full macOS
extended run was already running during these final measurement hardenings:
retain it as a pilot, not evidence of the final selector's exact behavior.
Canonical runs use implementation commit b642282286aa and recorded source hashes.

The final focused suite ran 12 tests: native 11 passed plus one explicit GDB
availability skip; Linux 12 passed, including live recovery and step-limit
failure. Full suites passed 11/11 CTest groups on both native and Linux before
the final harness/metric refinements; focused tests were rerun after those edits.
Hosted CI subsequently passed Debug and Release, including the final core matrix
and debugger observer on x86-64:
[run 42740580787](https://github.com/DeadKennedyx/C-SRD/actions/runs/42740580787).

The macOS pilot completed 1,000 cells across 25 available profiles, with one
explicit x86 target gap. All source-model/build-input checks and paired
executions passed. The fixed observer recovered the known linear/XOR/popcount
families in 850 cells. It fitted a wrong linear model on the 150 rare-difference
control cells, then rejected it using the declared held-out challenge. These
are repeated configurations of five small functions, not 1,000 independent
algorithms or a universal recovery rate.

The initial runtime prototype found four held-out-validated affine recovery
locations in both original and affine calculate at O2, with identical instruction
step counts and no validated model from permuted labels. The learner received
training target values and traces, not the representation seed or parameters.
This is a negative protection result for a specified, easy-to-infer intermediate.

The [validation report](../../reports/validation-matrix.md) records canonical
runs: native core 240 completed cells, Linux extended 1,000 completed cells with
one explicit target gap, and held-out 72 completed cells. There were no failed
cells or paired execution discrepancies. In the final O0/O2 runtime experiments,
all original/affine/planned binaries allowed held-out recovery of the known sum.
At O0, the observer learned nontrivial encoding maps without seed/parameters;
at O2 all three used four instructions per execution. This rejects any inference
of protection from source complexity or surviving encoded instructions alone.

Timings are exploratory shared-host
samples: some native/Linux jobs overlapped. No speed improvement, statistical
significance, general decompiler resistance or memory secrecy is inferred.
