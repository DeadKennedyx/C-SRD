# Verification and evidence

`csrd transform` reparses the generated source and verifies every changed
function before writing C. The whole-function path independently interprets the
original and candidate ordered region trees as 32-bit bit-vector expressions;
a mismatch query asks whether any input makes their returns differ. The
[compositional limb path](compositional-validation.md) instead validates the
source-to-graph mapping, actual emitted operations and actual return using an
inductive value/range invariant. Both terminate and have no external effects
under the accepted contract. This is per-artifact translation validation, not a
mechanized proof of the entire compiler.

| Status | Meaning |
| --- | --- |
| `proved-under-model` | Z3 returned unsat for the full input domain of the stated model, trusting parsing, analysis, symbolic execution and Z3 |
| `counterexample` | Z3 returned sat; report includes concrete inputs and both modeled outputs |
| `local-counterexample` | A compositional step failed; abstract operand values need not be reachable from function inputs, and no whole-function inequivalence is claimed |
| `inconclusive` | Timeout, unknown or solver failure; C output is blocked |
| `unsupported` | A required function/model is missing or outside the subset; no proof claim |
| `not-verified` | No applicable query was discharged, including skipped functions |
| `tested-pass` | Listed compiled executions agreed; finite empirical evidence |
| Bounded-model checked | Reserved for an actual model-checker run with explicit bounds; no CBMC result is claimed |

`csrd verify original.c candidate.c` also checks independent candidate files.
Arguments are paired by position, not spelling. It checks selected original
function definitions and ignores extra candidate functions; this is not whole
translation-unit equivalence. Different arity or unsupported code is not proved.
Header hashes from both files are recorded; standalone callers must confirm
compatible environments. Extra external behavior in unsupported code is outside
the contract.

Reports contain source/candidate SHA256, header-buffer hashes, target triple,
Clang/Z3 versions, seed/options, raw SMT-LIB mismatch obligations and hashes,
solver strategy, status and counterexamples. `output_written` distinguishes a
failed generated candidate from a saved artifact. A report is evidence tied to
bytes, not a signed certificate. Changing either file invalidates that binding.

The whole-function solver first uses polynomial simplification and direct bit-blasting/SAT,
with up to min(1000, timeout/4) milliseconds (at least one). If inconclusive,
it can next reparameterize each input as two independent 16-bit halves, a
bijection over the full domain, with at most another 1000 milliseconds. Remaining
budget is assigned to conditional-term lifting, simplification and SMT. That
path helps simplify affine decodes around branch selections.
Solver checks have bounded budgets; frontend parsing/graph construction is not
a whole-process wall-clock sandbox. Replay a raw query with equivalent tactics
if plain `check-sat` is slow. No independently checked proof certificate is
produced. A recognized limb partition first receives at most half the overall
budget for composition, leaving the remainder for this whole-function fallback.
Every local obligation and failed attempt is retained in the report.
[Z3 bit-vector theory](https://microsoft.github.io/z3guide/docs/theories/Bitvectors/).

The trusted computing base includes Clang's C semantics and AST, the subset
analyzer, the independent region interpreter, Z3's simplifier/tactics/solver,
and the host runtime. The planner/emitter are deliberately outside the semantic
interpreter, but parser/analyzer bugs could affect both sides. Concrete
counterexample replay, cross-compiler differential execution and sanitizers
exercise this boundary; none removes it completely.

## Rule contracts and testing

`tools/verify_rules.py` checks three affine identities, six XOR/bitwise identities,
five Newton low-bit steps (1→2→4→8→16→32), and six explicitly enumerated
multiplier round trips. A deliberately incorrect affine addition law must be
sat and records a real counterexample. Universal formulas range over the full
bit width; they are not random tests. Newton lemmas describe the mathematical
update, not the executable's entire implementation.

`tools/synthesize_rules.py` enumerates 27 coefficient triples per add/sub rule,
uses deterministic samples only for pruning, then submits each survivor to
universal 32-bit validation. It rediscovers known affine identities. This small
template search is not an e-graph implementation or evidence of novel encodings.

CTest covers numeric rules and boundary values; rejection/macro/path behavior;
proofs, mutations and compiled counterexample replay; exhaustive small-graph
planner optimality; algorithm-candidate rejection and compiled low-byte coverage;
defensive false matches; and two compiled differential suites. The expanded
suite exercises the original five representation strategies on branches, loops, tables,
comparisons, wraparound and bitwise operations. Each compiler uses `-O0`/`-O2`;
selected Clang configurations use ASan/UBSan. Release checks remain active.

The compiled-code audit adds a tenth CTest group. It validates each concrete
compiler/optimization preprocessed function against the source model, then
compiles that frozen input. Negative controls include compiler-dependent code,
changed behavior/headers, compiler failures and empty code sections. Its object
measurements establish neither machine-code equivalence nor resistance to
reverse engineering. See [audit evidence](../reports/protection-audit-validation.md).

The arithmetic corpus includes 24 deterministic generated functions, but it is
not a representative sample of real C software. Finite input/seed/target
coverage cannot establish universal implementation correctness. Native and
container results and failures fixed during development are recorded in
[the validation report](../reports/roadmap-validation.md).

## Other verification tools

CBMC, Frama-C WP and Alive2 are reviewed but not integrated or run in this
release. There are no placeholder success statuses for unavailable tools.

* [CBMC](https://diffblue.github.io/cbmc/cprover_documentation.html) can provide
  independent C-level harness checks with nondeterministic inputs and explicit
  loop-unwinding assertions. This is the next independent validation backend.
* [Frama-C WP](https://frama-c.com/fc-plugins/wp.html) needs ACSL contracts and
  discharged memory/arithmetic obligations. It becomes especially relevant when
  adding memory effects, which the current model excludes.
* [Alive2](https://users.cs.utah.edu/~regehr/alive2-pldi21.pdf) validates LLVM-level
  refinement under LLVM semantics and bounds. It cannot establish source-level
  preprocessing or Clang frontend correctness by itself.
