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

The separate [buffer path](buffer-contract.md) interprets ordered loads/stores
over one shared symbolic array with unconstrained pointer bases, then compares
both returns and whole final memory. Matching pointer types and no larger
candidate access footprint are prerequisites. This covers aliases under the
declared valid-object/initialization contract, not general C pointer semantics.

| Status | Meaning |
| --- | --- |
| `proved-under-model` | Z3 returned unsat for the full input domain of the stated model, trusting parsing, analysis, symbolic execution and Z3 |
| `counterexample` | A mismatch was found; memory reports also include abstract pointer bases and initial/final cells, even when returns are equal |
| `local-counterexample` | A compositional step failed; abstract operand values need not be reachable from function inputs, and no whole-function inequivalence is claimed |
| `inconclusive` | Timeout, unknown or solver failure; C output is blocked |
| `unsupported` | A required function/model is missing or outside the subset; no proof claim |
| `not-verified` | No applicable query was discharged, including skipped functions |
| `tested-pass` | Listed compiled executions agreed; finite empirical evidence |
| `bounded-checked` | Supplemental CBMC run succeeded for its exact finite object/layout harness; not universal C coverage |

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

The optional [saved-query circuit path](circuit-validation.md) uses Z3's Boolean
lowering, an independent parser with universal gate contracts, and ABC's
combinational checker. It replays an existing model query. This supplies another
decision engine, not independent C modeling or machine-code validation. It is not
called by `csrd transform`; its `sat` result does not yet reconstruct public C
counterexample inputs.

An optional CBMC adapter now checks bounded buffer layouts. Frama-C WP and
Alive2 remain unintegrated. Unavailable tools never produce success statuses.

* [CBMC](https://diffblue.github.io/cbmc/cprover_documentation.html) is invoked by
  `tools/verify_buffers_cbmc.py`. It parses the original and emitted C itself,
  compares returns and every cell of a finite shared object, and checks bounds,
  pointer safety and unwinding assertions. Pointer offsets are explicitly
  selected; each result covers only that layout with arbitrary initial words
  and scalar inputs. Actual affine artifacts and negative controls were checked
  with CBMC 6.11.0; see the [buffer evidence](../reports/buffers-validation.md).
  This optional check is independent of C-SRD's C interpreter and does not
  replace the mandatory all-alias symbolic-memory gate.
* [Frama-C WP](https://frama-c.com/fc-plugins/wp.html) needs ACSL contracts and
  discharged memory/arithmetic obligations. It becomes especially relevant when
  expanding beyond the current fixed-index memory contract.
* [Alive2](https://users.cs.utah.edu/~regehr/alive2-pldi21.pdf) validates LLVM-level
  refinement under LLVM semantics and bounds. It cannot establish source-level
  preprocessing or Clang frontend correctness by itself.
