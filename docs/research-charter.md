# Research charter

**Verified Semantic and Representation Diversification for C Programs** studies
whether benign computations can take different internal forms while preserving
an explicit observable-behavior contract. It separates correctness, diversity,
cost and defensive recognizability as independent outcomes.

The software-protection objective, clarified on 2026-11-09, is to automate
diversification of legitimate software and investigate whether it increases
the effort required to reconstruct its implementation. The current C-SRD
repository remains the implementation target. Other projects are examples,
not targets for modification. Correctness validation supports this objective;
passing validation alone does not establish protection.

Protection claims require a stated observer, assets, access and measurement.
Encoded source intermediates are not evidence that ordinary values never appear
in optimized registers or memory. A debugger controlling the process can inspect
the executable and its conversion operations. Neither the seed nor affine
parameters are secret keys. See the [protection contract](protection.md).

The original unit of study is a pure unsigned 32-bit function within an explicit
bounded subset. A separate [buffer contract](buffer-contract.md) now admits
straight-line fixed-index uint32 memory operations, with return and whole-memory
validation. Existing pure-function reconstruction studies do not establish
results for this new interface. Treatments include affine/XOR representations, graph planning and
selected known algorithm replacements. The baseline is the original source
compiled under the same compiler, target, flags and environment. Identity graph
lowering is an additional baseline. There is no claim of a new encoding scheme
or a verified whole compiler.

Research integrity requirements:

* Record all seeds, corpus construction, rejected regions, versions and flags.
* Keep failed tests and inconclusive proofs visible; never label them successful.
* Separate measured source/IR/machine-code differences from algorithmic changes.
* Use held-out benign benchmark families for eventual generalization claims.
* Publish negative results, false matches and missed equivalences alongside
  positive results; do not optimize a classifier and evaluate it on the same set.
* Compare planning against independent-operation encoding and uniform-region
  encoding, controlling for compiler optimizations and verification costs.
* Treat multi-objective tradeoffs as Pareto comparisons, not one unexplained score.
* Cite prior work before discussing originality. New engineering combinations
  are not automatically research novelty.

Excluded objectives are malware-specific transformations, security-product
evasion, anti-debugging, stealth loading, and antivirus/YARA non-detection.
No encoding here is a secret-storage mechanism. Credentials and cryptographic
secrets must remain outside this research mechanism.

Executable M0–M5 prototypes and preliminary experiments are present. Claims
about scalability, generalization or novelty still require broader experiments
and comparisons. The rare-input recognition challenge is explicitly curated;
it is a negative control, not unbiased held-out accuracy evidence. See
[questions](research-questions.md) and [prior art](prior-art.md).
