# Roadmap and implementation status

Version 0.5 implements a bounded experimental slice of every M0–M5 milestone.
This does not close the research questions or imply broad C11 support.

| Milestone | Delivered | Remaining research/engineering |
| --- | --- | --- |
| M0 | Repository, CMake, real CLI, charter, semantics, prior-art comparison, CI configuration and local Linux validation | Hosted CI execution requires a remote workflow run |
| M1 | Clang AST transformation, affine encoded intermediates, unchanged public interface, deterministic parameters and independently compilable C11 | Larger real-world pure-function corpus and more targets |
| M2 | Mandatory reparsed-artifact translation validation, compositional limb invariants with checked source-to-graph mapping, optional checked-circuit replay of saved queries, hashes/header environment, SMT obligations, concrete counterexamples and replay, inverse/XOR contracts | General reconstruction grading; independently checked certificates; CBMC source-level backend; Frama-C/Alive2 integration where appropriate |
| M3 | Versioned data-flow graph, compatibility/coverage constraints, conversion sharing, three cost objectives, exact small-graph solving and labeled heuristic fallback | Cost calibration, better scalable optimization, complete Pareto exploration and independent prior-system comparisons |
| M4 | Independent fingerprints, positive/negative/rare controls, confusion matrices, AST/CFG/LLVM/object metrics, measured compile/verification/runtime/text-size comparisons and raw reports | Held-out applications, more targets, repeated isolated performance studies and stronger defensive semantic analysis |
| M5 | XOR/bitwise rules, fixed shifts, unsigned comparisons, selections, assignment-only branches, exact finite loops and bounds-checked local literal lookup arrays | Memory contracts, richer control flow and operators, expanded rejection/proof coverage before each addition |

Later-module prototypes are also present: compile-time encoding of local lookup
payloads; pure control-flow lowering; serial versus SWAR low-byte population
count; graph representation planning; bounded coefficient-template synthesis
with universal validation. Each has a narrow documented domain. The synthesis
experiment rediscovers known laws and does not implement equality saturation.

Strings, character buffers, escaping arrays, mutable/static object layouts,
pointer aliasing and calls remain outside the model. Runtime string replacement
must not be added without handling length/encoding, embedded NULs, sizeof,
storage duration, pointer lifetime and API requirements. Encoding is not secret
storage. General loops require termination/effect contracts or invariants;
arbitrary algorithm replacement requires independent specifications and proofs.

The active protection study has a [larger reserved corpus](rich-benchmarks.md)
and verified [16-bit](limb-representation.md) and [8/4-bit](positional-widths.md)
positional representations. The [width comparison](../reports/positional-widths.md)
completed 500 build cells, 600 measured output-only attempts and 200 measured
Ghidra attempts. The [wide/vector observer follow-up](../reports/pcode-wide-values.md)
closed all nine unsupported build cells and separately resolved the two older
unproved answer contracts. Its complete repeat recovered 200/200 measured
answers under the source model after grading. Byte/nibble whole-observer CPU
medians span 0.988–1.056 times baseline, while some per-function stages grow
and application overhead reaches 7.774 times baseline. No protection winner or
cost limit was selected. The [persistent-session study](../reports/persistent-sessions.md)
then separated native/JVM/adapter costs across 120 sessions. All 33 distinct
answer contracts were recovered under the model, while nibble native CPU grew
2.7–39.9 times baseline per request. These are measurable automated-analysis
costs, with application overhead and millisecond absolute native costs; no
general protection winner follows. JVM CPU continued to decline across batches,
so next check a declared longer-warmup grid on development controls, then freeze
the sampling protocol before evaluating reserved families. Multi-location runtime
inference and human analysis require
separate protocols. Bounded
[CFG/merge reconstruction](../reports/pcode-control-flow.md) now recovers the
unchanged GCC Jenkins baseline; four reserved recurrence grades remain
inconclusive despite passing finite execution checks. The
[newly admitted Jenkins comparison](../reports/compositional-validation.md) had
reconstruction-grading timeouts. A separate [checked-circuit replay](../reports/circuit-grading.md)
resolved all ten saved limb answers: they were correctly reconstructed under the
source model. This closes that grading gap without demonstrating a protection benefit.
Independent C-level validation with unwinding assertions and planner cost calibration remain
open backend tasks. No solver timeout, small benchmark result,
source difference or recovered known rule answers RQ1–RQ9 by itself.
