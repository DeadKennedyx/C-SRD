# Research questions

These are open questions, not expected conclusions.

| Question | Operational measurement or planned experiment |
| --- | --- |
| **RQ1 — Representation diversity:** How many meaningfully different representations can be generated for supported C computations? | Count distinct representation families and normalized source/IR/machine-code forms separately; different affine parameters alone do not imply different algorithms. |
| **RQ2 — Encoded computation coverage:** What proportion of eligible computations execute without reconstructing ordinary intermediate representations? | Report eligible and transformed operator counts, operations without decoding, boundary conversions and internal conversions, with explicit denominators. |
| **RQ3 — Correctness:** Which C transformation classes can be mechanically verified, under which assumptions? | Track tested, bounded-model-checked, solver-proved and unverified obligations separately, including timeouts and counterexamples. |
| **RQ4 — Performance:** What runtime, code-size and compilation-time costs result? | Paired original/variant builds under identical conditions, repeated isolated execution, uncertainty estimates, symbol/text size and compilation cost. |
| **RQ5 — Algorithmic diversity:** Can the framework produce genuinely different computational strategies? | Use independently specified benign families such as population count, sorting and image filtering; distinguish changed algorithms from algebraic resyntax. |
| **RQ6 — Defensive recognition:** Can independent analyses recognize equivalent functionality? | Positive and unrelated negative controls, held-out inputs, confusion matrices, false matches and missed equivalences; fingerprints remain empirical. |
| **RQ7 — Compiler optimization:** Which structural differences survive normal optimization? | Compare source, normalized LLVM IR and machine code at `-O0` and `-O2` separately; measure canonicalization rather than assume persistence. |
| **RQ8 — Generalization:** Do observations hold across unrelated algorithms and compilation environments? | Use multiple benign algorithm families, compilers, versions and targets; the M1 arithmetic generator is not sufficient evidence. |
| **RQ9 — Novelty:** Does cross-region planning improve over established independent variable encoding? | Compare independent-operation, uniform-region and optimized graph assignments on conversion count, cost, verification and diversity; review prior encoding networks and compilers before novelty claims. |

Version 0.5 provides executable experiments for these questions: three
representations, graph planning baselines, per-artifact validation, serial/SWAR
low-byte population count and independent recognition/structure/timing reports.
The small curated corpus and limited targets are preliminary evidence only.
Generalization, calibrated planning benefits and novelty remain unresolved.
