# Compositional validation of emitted limb C

## Problem and scope

Long compositions can time out even when each representation law is simple.
The first Jenkins limb candidate hit the 30-second whole-function solver budget.
The compositional validator checks a sequence of smaller obligations over the
actual reparsed candidate. It admits no additional C constructs, changes no limb
source formula, and does not treat standalone rule proofs as artifact proofs.

Both `transform` and standalone `verify` can use this path automatically. No new
CLI option or trusted certificate is required. Other representations retain the
whole-function portfolio. An arbitrary equivalent program need not fit the
proposed partition; failure of this method does not imply inequivalence.

## Invariant and argument

For graph node i, let its ordinary value be v_i and its proposed candidate pieces
be L_i, H_i. The checked invariant is:

```
0 <= L_i <= 65535
0 <= H_i <= 65535
v_i = L_i + 65536*H_i (mod 2^32)
```

Under these ranges, positional addition also equals `L_i | (H_i << 16)`. The
solver keeps addition in polynomial form; the emitted C still uses OR at the
return and that actual expression must pass its own obligation.

1. **Source to graph.** Convert the proposed graph to an ordinary ordered region
   and compare it with the original using the independent region interpreter.
   This checks lowering, assignment versions, selections, unrolling and pruning.
   A wrong graph cannot justify a proof of the original program.
2. **Entry and constants.** Check actual parameter-splitting declarations and
   literal pieces against the graph reference/constant. Parameters are paired
   by ABI position. Both piece bounds must hold for every public input.
3. **Every operation.** Replace each distinct operand-piece storage location with
   an arbitrary 16-bit symbolic value, zero-extended to the modeled C width.
   Shared locations share one symbol. Interpret the actual fragment declarations
   and check the output's positional value and both bounds. The fragment can
   read only these operand locations and its own newly declared locals.
4. **Exit.** Interpret all remaining declarations and the actual final return,
   using arbitrary normalized pieces of the graph result. Check returned-value
   equality to their positional value.

Induction along the acyclic graph establishes the invariant for every actual
execution, then the exit establishes the returned result. The admitted language
is pure and terminating, so the existing external-effect/termination contract
also applies. Normalization is necessary: decoded equality alone can allow
overlapping bits that break subsequent arithmetic.

## Untrusted hints and conservative rejection

The emitter records declaration positions and which temporary or constant holds
each output piece. For independent candidate files the verifier obtains a
proposed partition from the same emission recipe, then rebinds the hint names
to actual candidate declarations by position. Names/comments are not evidence.
The candidate is parsed independently by Clang; no C text is parsed by regex.

The validator requires a well-formed topological graph, complete monotonically
ordered checkpoints, unique immutable candidate declarations, and a final return.
No assignment or hidden read of an earlier auxiliary value can cross a checkpoint.
An output piece must exist at that point. The validator never trusts a graph
node, parameter association, range, or equation merely because a hint says so.

Generating incomplete or wrong hints may make this method fail. It cannot permit
output unless the source-to-graph, every local invariant, and exit obligations
all succeed. The lowerer and emitter supply proposals and remain outside the
semantic proof boundary. Clang, the analyzer, region interpreter, graph-to-region
adapter, partition checker and Z3 remain trusted implementation components.
This is not a mechanically verified compiler or independently checked proof
certificate.

## Budgets and evidence

The compositional attempt uses at most half the per-function verification budget.
Source-to-graph and each local solver call receive at most one second and no more
than the remaining compositional budget. Context construction/reporting are not
a whole-process resource sandbox. If composition fails, the existing portfolio
may use the remaining overall budget. Unknown is never success.

Reports contain the actual graph, rebound candidate declarations/checkpoints,
source-to-graph query, every local query, return query, statuses, solver strategies
and SHA-256 for each SMT-LIB obligation. Whole-source and include hashes retain
their existing bindings. Failed compositional attempts remain under
`prior_attempts` if the whole-function fallback is used.

A `local-counterexample` records a countermodel to an abstract invariant. Its
operand values need not be reachable from public inputs, so it is not reported
as a whole-function counterexample. A successful fallback may prove the entire
function despite a failed local invariant; its proof method is reported
separately.

Tests cover graph/hint corruption, lost carry, wrong return, hidden dependencies,
non-normalized pieces, immutable-state requirements, exhausted budgets, renamed
candidate locals and independent SMT replay. The existing 88 generated operation
contracts require this path explicitly. A newly admitted candidate still needs
compiled differential tests and separate reconstruction measurements.

See the [journal](journal/2026-11-10-compositional-validation.md) for failed
prototypes and measured results. This is an application of inductive invariants
and translation validation, with no claim of methodological novelty.
