# Research charter

**Verified Semantic and Representation Diversification for C Programs** studies
whether benign computations can take different internal forms while preserving
an explicit observable-behavior contract. It separates correctness, diversity,
cost and defensive recognizability as independent outcomes.

The unit of study is a pure unsigned 32-bit function within an explicit bounded
subset. Treatments include affine/XOR representations, graph planning and
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
