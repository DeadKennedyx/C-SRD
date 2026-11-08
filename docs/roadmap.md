# Roadmap and implementation status

Version 0.5 implements a bounded experimental slice of every M0–M5 milestone.
This does not close the research questions or imply broad C11 support.

| Milestone | Delivered | Remaining research/engineering |
| --- | --- | --- |
| M0 | Repository, CMake, real CLI, charter, semantics, prior-art comparison, CI configuration and local Linux validation | Hosted CI execution requires a remote workflow run |
| M1 | Clang AST transformation, affine encoded intermediates, unchanged public interface, deterministic parameters and independently compilable C11 | Larger real-world pure-function corpus and more targets |
| M2 | Mandatory reparsed-artifact translation validation, hashes/header environment, SMT obligations, concrete counterexamples and replay, inverse/XOR contracts | Independently checked certificates; CBMC source-level backend; Frama-C/Alive2 integration where appropriate |
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

The next engineering task is an independent C-level validation backend with
explicit unwinding assertions, followed by a larger held-out benign corpus and
calibration of planner cost proxies. No solver timeout, small benchmark result,
source difference or recovered known rule answers RQ1–RQ9 by itself.
