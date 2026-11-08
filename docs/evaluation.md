# Defensive evaluation

`tools/evaluate.py` is separate from transformation and optimization. Its
classifier receives output sequences only; it never uses a manifest's intended
equivalence as its prediction. Curated family labels are used only for scoring.
The default corpus includes independent linear-arithmetic, XOR/Boolean and
minimum implementations, an unrelated subtraction, and a deliberately rare
one-input arithmetic mutation. These tiny functions are controls, not a
representative application benchmark.

Discovery fingerprints use 81 boundary pairs and a configurable seeded random
sample. Held-out fingerprints use a different random seed and also an explicit
challenge pair `(0x43535244, 0)` for the rare mutation. Equality of output digests
predicts a match. SHA256 collisions are not the principal limitation: equal
outputs on sampled inputs can hide a functional difference. The rare mutant
demonstrates that limitation. The hand-chosen challenge is an adversarial test,
not unbiased out-of-distribution accuracy evidence. Reports include TP/TN/FP/FN
and each false match or missed equivalence for all pairs.

For every source and generated variant, the tool measures:

* Clang AST counts, operator histograms and a name/literal-insensitive AST shape
  hash. CFG metrics use reachable blocks, unique edges and cyclomatic E−N+2.
  The adjacency hash retains Clang block numbering; it is not graph isomorphism.
* LLVM instruction histograms where Clang emits LLVM IR, plus raw IR hashes.
  Histograms lose ordering and data dependencies and cannot establish equality.
* Object code-section byte counts/hashes and disassembled instruction histograms.
  Whole single-function `.text`/`__text` includes padding; relocations are not
  applied. This is not final executable size or universal machine-code equivalence.
* One elapsed object-compilation measurement, separate transformation/validation
  elapsed time and separate standalone verification elapsed time.
* Repeated execution samples and medians/IQR, with ratios to the untransformed
  source under exactly the same compiler/optimization. Compilation and input
  generation occur outside timing. Separate object compilation without LTO
  prevents call-site inlining; a printed checksum makes results observable.

The timing harness warms each binary, precomputes 4096 input pairs, then measures
calls plus array indexing and accumulation using a monotonic clock. It shuffles
variant order deterministically across repetitions. It does not subtract harness
overhead, pin a CPU, disable frequency scaling or claim nanosecond precision from
short kernels. Report raw samples; repeat isolated runs before making performance
claims. Optimization may erase source differences, and a lower proxy cost may
not improve measured performance.

Default comparisons cover original, uniform affine, independent encoding and
planned code, both `-O0` and `-O2`, supplied compilers, seed 42, 1024 random inputs
per split, seven timing repetitions and one million calls per repetition. All
flags, versions, artifact hashes, costs and samples are recorded. Run directories
must be new and preserve generated C, proof reports, driver, objects and LLVM IR.

Source structural difference, IR difference, object-code difference, algorithmic
difference and observable equivalence are separate quantities. For example,
distributing a multiplication changes syntax but is not a new algorithm. The
opt-in serial/SWAR low-byte population-count module provides an explicit known
algorithmic comparison; it is validated separately, not inferred from hashes.
