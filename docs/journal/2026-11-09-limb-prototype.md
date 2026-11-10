# Positional two-piece prototype and stronger query control

## Observation and design before measurement

The richer corpus is validated. Existing affine/XOR graphs still convert at
operator-family boundaries. Implement one fixed positional two-limb candidate,
including arithmetic, bitwise work, comparisons and fixed shifts, and compare it
without runtime/size cutoffs. This is an established technique (see
[Tigress data encoding](https://tigress.wtf/encodeData.html)); novelty is unverified.
The seed deliberately does not diversify this first implementation.

In parallel, the old query observer's tiny model library cannot recognize rich
bit-linear functions. Add a separate fixed observer that learns an affine GF(2)
map from zero and single-bit queries. It receives the executable and public ABI,
not the family, seed, reference or oracle. More queries can reject an overfit
model; only the hidden full-function proof determines source-model equivalence.
Since correct variants have identical I/O, changing internal representation
cannot change the query complexity of this observer. It is a recognition control,
not a target to optimize against.

Prespecify the first exploratory run: four development families, original and
identity controls, affine/XOR/planned seed 42 and the fixed limb candidate, all
available extended compiler profiles, no selection ceilings. Retain transformation
failures and never compile unproved output. Measure bit-linear reconstruction at
32/65/128 queries and Ghidra recovery with fixed budgets. Do not open reserved
reconstruction tasks yet. CPU/RSS/wall measurements must run separately from
builds/tests. Failed matrix cells remain visible when measuring validated cells.

## Prototypes and deviations

The first implementation passed 82 arithmetic obligations, including a deliberately
wrong borrow. CRC, Morton and RGB emitted-source checks passed. Jenkins timed out
under XOR, planned and limb representations at 30 seconds; those are proof limits,
not wrong-output observations or protection successes.

An 88-function integration fixture exposed a second proof limit: scale by 65535.
Several generic solver tactic changes remained inconclusive. Exposing each
symbolic input as independent 16-bit low/high values let the polynomial solver
prove the same query in the local probe. Added this bijective reparameterization
as a general bounded fallback, preserving actual SMT queries and full-width
counterexample decoding. It does not trust the emitter's labels or narrow the
input domain. Retain both failed and successful probes in the experiment evidence.

The broad search also requires a driver change: retain every failed preparation
and continue measuring valid candidates. The matrix still reports failure;
effort measurement needs an explicit partial-matrix option and checks every
requested cell's validity and artifact hashes. This avoids silently dropping a
difficult function or treating unproved code as a measured candidate.

## Implementation checks before the matrix

Both native macOS and Linux passed all 16 CTest groups. The limb integration
fixture reparsed and proved 88 generated function contracts and executed GCC/
Clang comparisons at O0/O2 and O1 with ASan/UBSan. The emitted-mask mutation was
rejected. The bit-linear observer tests recovered XOR, rejected insufficient
basis budgets and detected/rejected nonlinear false fits. Matrix tests retained
an intentionally ineligible algorithm while measuring other valid variants.
The Jenkins proof timeouts persisted after input reparameterization; no generated
output was accepted for those attempts. The full development protocol and hashes
were frozen in [limbs-exploration.json](../../experiments/limbs-exploration.json)
before starting performance measurements.
