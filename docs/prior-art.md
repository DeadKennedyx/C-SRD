# Prior-art comparison

Reviewed from the primary sources linked below on 2026-11-07. This is a focused
initial review, not a systematic literature survey. Published guarantees belong
to their stated systems and assumptions; none automatically transfers to C-SRD.

| Approach / source | Technique and supported constructs | Assumptions, correctness evidence and limits | C-SRD comparison and novelty status |
| --- | --- | --- | --- |
| [Tigress EncodeData](https://tigress.wtf/encodeData.html) | Changes integer-variable representations, including odd-multiplier affine encoding, and computes with encoded intermediate values. | The documented transformations have specific type/alias and codec requirements. An encoding identity alone is not a proof of every compiler rewrite. | Direct prior art for M1. Neither affine encoding nor maintaining encoded intermediates is claimed novel. C-SRD currently narrows the accepted C grammar and makes evidence/reporting explicit; comparative benefits are unmeasured. |
| [Tigress EncodeArithmetic](https://tigress.wtf/encodeArithmetic.html) | Replaces integer arithmetic with mixed Boolean-arithmetic identities. | Identities apply under appropriate integer semantics; interaction with the rest of C still requires care. | Distinguishes instruction/expression expansion from choosing a consistent value representation. M1 does not implement MBA patterns or claim that syntactic complexity is algorithmic novelty. |
| [LLVM analysis and transform passes](https://llvm.org/docs/Passes.html) | IR analyses and transformations including propagation, simplification and control/data-flow optimization. | LLVM semantics, target assumptions and each pass's preconditions govern legality; a pass listing is not a formal correctness proof. Optimizations can erase source differences. | C-SRD operates at C source level and must measure resulting IR and machine code independently. No new LLVM optimization is claimed. |
| [Alive2, Lopes et al., PLDI 2021](https://users.cs.utah.edu/~regehr/alive2-pldi21.pdf) | Bounded translation validation of LLVM optimizations with SMT reasoning. | LLVM-level refinement and bounded reasoning have their own UB and scope assumptions; they do not cover arbitrary source preprocessing. | A potential downstream validator, not a substitute for a C contract. Not integrated in M1; no extension of its guarantees is claimed. |
| [Frama-C WP](https://frama-c.com/fc-plugins/wp.html) | Deductive verification of C against ACSL contracts using weakest preconditions, memory models and external provers. | Correct contracts, model choices and discharged obligations are required; annotations and proof work are substantial for richer programs. | Potential source-level validation route. M1 has no ACSL proof integration and claims no new deductive-verification method. |
| [CBMC / CProver](https://diffblue.github.io/cbmc/cprover_documentation.html) | C/C++ bounded model checking, assertions, safety checks and loop unwinding into decision procedures. | Environmental assumptions and unwinding bounds matter; a successful bounded check must not be generalized beyond its scope. | Well suited to future original/variant harnesses. M1 has no CBMC result; finite random tests are not bounded model checking. |
| [egg, Willsey et al., POPL 2021](https://arxiv.org/abs/2004.03082) | Extensible e-graphs and equality saturation, including e-class analyses and cost-based extraction. | The client supplies a language, sound rewrites and analysis/cost definitions; equality saturation does not itself establish C rewrite legality. | Candidate infrastructure for representation synthesis and planning. Neither e-graphs nor equality saturation is new here; a C-aware planner's value remains untested. |
| [Demissie, Ceccato and Tiella, 2015](https://profs.scienze.univr.it/~ceccato/papers/2015/spro2015.pdf) | Implementation and assessment of data obfuscation with residue number coding, including operations performed in encoded form. | Residue-domain interpretation and supported operations must be respected; the paper reports its own implementation/cost experiment, not a universal guarantee for C-SRD. | Prior art for alternative computational representations and their overhead evaluation. C-SRD's modulo-2^32 affine baseline is a different representation choice, not a novel encoded-computation concept. |
| [CompCert and its proof development](https://compcert.org/doc/) | Verified translation from CompCert C through compiler passes to assembly; mechanized semantic preservation. | Guarantees are relative to the formal language/target semantics and trusted components. The supported C language is explicitly defined. | A model for stating contracts and proof boundaries. C-SRD is not a verified compiler and has no comparable end-to-end theorem. |
| [Chow, Eisen, Johnson and van Oorschot, 2002](https://crypto.stanford.edu/DRM2002/whitebox.pdf) | Encoded transformations and networks of compatible input/output encodings in white-box DES research. | A specialized cryptographic implementation and attack context; the paper explicitly states absence of security proofs for its proposed methods. | Composition of compatible encodings is established prior art, relevant to RQ9. C-SRD makes no key-hiding claim and does not implement this cipher construction. |
| [Larsen, Homescu, Brunthaler and Franz, IEEE S&P 2014](https://ics.uci.edu/~perl/publication/diversity_sok/) | Systematization of automated software diversity approaches, design choices and tradeoffs. | Systems differ in threat model, program coverage, performance and guarantees; the survey does not make them interchangeable. | Places C-SRD among existing diversification systems. Its focus is explicit correctness evidence and defensive recognition; originality of any future planner requires a direct comparison. |

## Current novelty assessment

M1 is a research baseline assembled from established ideas: Clang AST analysis,
unsigned modular affine encoding, conservative source rewriting and differential
testing. The code is useful without a claim of new mathematics or a new security
property. Formal rule checks and reproducible reporting improve inspectability
but do not by themselves demonstrate a research contribution.

RQ9 must compare at least (1) independent operation encoding, (2) a uniform
function representation like M1, and (3) an optimized graph assignment under
identical workloads. Compatible encoding networks already appear in prior
white-box research, so mere conversion cancellation is not a sufficient novelty
claim. A contribution would need a precise new method or a defensible empirical
finding, compared against relevant existing systems.

Follow-up review should inspect the original affine/MBA infrastructure papers
cited by Tigress, verified source-transformation tools, recent representation
planning/superoptimization work, and reproducible defensive recognition studies.
No benchmark numbers from those systems are copied into C-SRD's own results.

## Version 0.5 update (2026-11-08)

The table above records the initial M1 comparison. C-SRD now has per-artifact
bit-vector translation validation, graph planning, defensive evaluation and a
bounded C extension; none inherits another system's correctness guarantees.
CBMC, Frama-C and Alive2 remain unintegrated. Local comparisons now include
independent, uniform and planned strategies, but no head-to-head Tigress study
or evidence of research novelty has been produced.

The [Z3 bit-vector guide](https://microsoft.github.io/z3guide/docs/theories/Bitvectors/)
includes population-count validation by comparing bit-field aggregation with
bit summation. C-SRD's low-byte serial/SWAR candidates are a narrow application
of known methods, not new algorithms. Its finite coefficient search likewise
rediscovers known affine laws and is not equality saturation.

[Z3's objective documentation](https://microsoft.github.io/z3guide/docs/optimization/combiningobjectives/)
distinguishes lexicographic combination from Pareto enumeration. C-SRD exposes
three explicit proxy scalarizations with lexicographic tie objectives and a
deterministic local-search fallback. It does not claim a complete Pareto front,
an optimal scalable optimizer, or cost estimates calibrated to machine cycles.
