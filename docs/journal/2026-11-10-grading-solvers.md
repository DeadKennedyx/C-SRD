# Grading optimized reconstructions: independent solver probes

## Observation and question (before experiments)

The completed Jenkins follow-up retained ten inconclusive grades for generated
Ghidra answers. The original-to-transformed source proofs succeed, but both
direct and transformed-input-to-answer monolithic queries time out. The two
representative final obligations are only about 5 KiB of SMT-LIB. Their input
domain is still the complete pair of u32 arguments, reparameterized into 16-bit
halves. An unknown grade cannot establish reconstruction difficulty.

Question: can different exact bit-vector simplification/solving strategies
discharge these unchanged obligations within a declared budget? If so, replay
the original frozen answers with explicit source/query bindings. Keep all
earlier measurements/statuses unchanged and report any new result separately.

## Planned probes and acceptance conditions

Use the first measured inconclusive limb answer for each O2 compiler from the
completed development study. Compare a small declared Z3 tactic portfolio and
an independent bit-vector solver; preserve every query, version, command, timeout
and error. The observer receives no reference source or new inference rule.
Include satisfiable incorrect-answer controls and independently checked known
bit-vector identities. Never interpret parser errors, unknown, process timeouts
or missing output as proofs. Source-to-SMT modeling and binary lifting remain
separate trusted boundaries even if two solvers agree.

Only integrate a backend or normalization change after useful measured results
and positive/negative controls. If the probes fail, record that failure and
investigate sound additional decomposition rather than increasing success claims.
Reserved reconstruction families remain unopened. Subsequent candidate search
continues to compare reconstruction resources, runtime and size without cost
ceilings.

## Sources checked

* [Z3 tactic composition](https://microsoft.github.io/z3guide/docs/strategies/tactics/)
  and [simplifiers](https://microsoft.github.io/z3guide/docs/strategies/simplifiers/).
* [Bitwuzla installation](https://github.com/bitwuzla/bitwuzla/blob/main/docs/install.rst)
  and [Python API](https://bitwuzla.github.io/docs/python/api.html). Installation
  will be isolated from the project's mandatory build dependencies and pinned
  to the actually used version.

## Results

The first portfolio completed 35 attempts. All 14 attempts on the two frozen
reconstruction queries returned unknown within the declared five-second solver
budget. All 14 positive rule checks returned unsat, and all seven wrong-borrow
controls returned sat. Bitwuzla 0.9.1 was installed in an isolated Python 3.14
environment; it is not a mandatory dependency. Raw queries, commands, backend
versions/hashes and resource records are retained in the experiment directory.

An exploratory manual 32-to-two-16-bit formula decomposition also failed to
resolve either reconstruction with Z3 or Bitwuzla. The subtraction and
wrong-borrow controls still returned unsat and sat respectively. Its rewrite
implementation has not received the universal per-primitive certification that
would be required for admission to the verifier. It is not integrated.

A second prototype used Z3's existing extraction/concatenation simplification,
sampled expressions to propose matches, and admitted a replacement only after an
unsat check. It tried abstract common expressions first; a refinement tried
their complete definitions after a failed abstract check. A third version used
more samples and repeated the traversal. These found some intermediate
identities, but neither final query was resolved. In particular, satisfiable
queries over arbitrary intermediate cut values are not counterexamples to the
public function: abstraction can discard relations between those values.
No version is integrated or used to reclassify historical answers.

These are exploratory adaptations of established
[simulation and SAT sweeping](https://people.eecs.berkeley.edu/~alanmi/publications/2006/iccad06_cec),
not a new verification technique. The experiment now makes one final bounded
probe with [ABC](https://github.com/berkeley-abc/abc), using Boolean circuits
exported from Z3's bit-vector lowering. The export must be checked independently
of the writer before a circuit result can grade a saved query. A second solver
still does not independently validate C modeling or binary lifting. The ABC
source revision and build are frozen with the experiment. No additional
protection conclusion is justified by these grading failures.

## Circuit export and first replay

ABC revision `25d4ee221b2a9ab5124f3a222bcdf6f922d3d8a3` resolved both
exploratory exported reconstruction circuits within five seconds. A direct
whole-circuit export/reimport equivalence check itself timed out. Replaced that
check with mandatory local contracts over the independently parsed truth tables,
plus complete acyclic wiring/interface binding to the original lowered DAG.
The actual Clang and GCC circuits then passed 13 and 14 distinct universal gate
contracts, respectively, and ABC again resolved them. This is still conditional
on the documented trusted lowering, binding checker and decision engines.

All 18 CTest groups passed on macOS and Linux. Early regression failures exposed
test assumptions about Z3's presentation of XOR and macOS's `/var` symlink;
the controls now locate the actual gate and compare resolved paths. The Linux
run preserved its failed log before the corrected run. These were test-fixture
assumptions, not an admitted incorrect circuit.

The first full saved-answer replay discharged all ten answer queries, but the
driver conservatively labeled all ten corrupted-answer controls inconclusive.
Inspection found a distinct ABC diagnostic for a trivially satisfiable mismatch:
`Networks are NOT EQUIVALENT. Output 0 trivially differs (different phase).`
The exact supported variants were confirmed in ABC's `cecCec.c`; the parser and
regression tests now accept those negative results without relaxing the positive
result protocol. The first replay fails its control acceptance criterion and is
retained. A fresh replay will follow the correction; earlier outputs are not
overwritten or silently regraded.

## Successful replay and decision

Implementation commits `eabc8bd` and `b69f68e` supply the optional helper,
independent gate reader/contracts, measured driver and frozen-answer replay.
The corrected run completed 23 cases: all ten saved answer mismatches unsat,
all ten corrupted-answer controls sat, two valid rules unsat, and the wrong-borrow
rule sat. The answers are two unique artifacts repeated five times each. Complete
replay wall medians were 1.886 seconds for Clang and 2.043 for GCC; these are
grader resources on native macOS, not observer resources or environment-matched
speedups against the earlier Linux timeouts.

The [report and hash-bound evidence](../../reports/circuit-grading.md) retain
every failed prototype/pilot, the successful queries, local proof obligations,
raw process measurements, frozen source bindings, test logs, tools and dependency
identities. No observer was rerun and no historical status was edited. We learned
that these limb answers had already reconstructed the functionality correctly.
Keep the representation as a correctness/cost baseline, with no established
protection benefit. Broader adapter coverage and subsequent candidate experiments
remain next; runtime/size ceilings are still not imposed.
