# Milestones and exit criteria

| Milestone | Status | Exit criterion / remaining work |
| --- | --- | --- |
| M0 — Foundation | Implemented | CMake, CLI, modular source, charter, semantics, architecture, literature comparison, testing and Linux CI configuration. Hosted CI execution is separate from local validation. |
| M1 — Automatic transformation | Implemented for the documented subset | Real LibTooling parse, conservative region analysis, deterministic affine computation, preserved function signature, generated C, GCC/Clang differential tests and recorded limitations. |
| M2 — Verification | Initial arithmetic contracts only | Add per-input translation validation, bind evidence to artifact hashes, report counterexamples, cover inversion implementation, and investigate CBMC/Frama-C/Alive2 in their proper scopes. |
| M3 — Planning | Not implemented | Versioned data-flow IR, representation labels, compatibility constraints, conversion edges and measured multi-objective selection; compare against M1 uniform encoding. |
| M4 — Defensive evaluation | Not implemented | Independent fingerprint classifier, confusion matrices with negative controls, normalized structural/CFG/IR/binary measures, controlled timing and size experiments. |
| M5 — C expansion | Not implemented | Add each operator/control/object feature only with its own contract, proof obligations, rejection tests and cross-compiler validation. |

The next engineering task is per-region bit-vector translation validation with
counterexample reporting and artifact-bound results. This should precede
expanding the arithmetic whitelist or implementing a representation optimizer.

Later modules have distinct semantic prerequisites:

* Data representations must preserve object lifetime, layout where observable,
  string length/encoding, embedded NULs, `sizeof`, array initialization, static
  storage and API boundaries. Runtime string reconstruction is not a general
  replacement for string literals. Secrets are not in scope.
* Control flow needs join-state compatibility, effects, boundedness/termination
  contracts and eventual loop invariants.
* Algorithmic variants need independently specified benign algorithms and
  genuine changes in computational strategy.
* Cross-region planning needs a baseline comparison and explicit conversion
  costs, not an assumption that fewer decodings confer secrecy.
* Synthesis/e-graphs need sound equalities under C/bit-vector semantics and
  independent validation of extracted programs. Cost estimates need calibration.

Before performance claims, add benchmark harnesses that measure original and
variant separately under identical optimization, include repetitions and noise
estimates, prevent dead-code elimination without changing the measured
computation, record compilation time and text size, and publish raw results.
