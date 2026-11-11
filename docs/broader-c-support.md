# Broader C-SRD support informed by published designs

Status: single development sequence; first bounded C1 slice implemented under
[buffers-u32-c11-v1](buffer-contract.md). Later stages remain proposed. Recorded
2026-11-10; [buffer evidence](../reports/buffers-validation.md) records actual
results. The [fourteen-increment breakdown](coverage-increments.md) refines the
sequence. An opt-in [private-region prototype](private-regions.md) now selects
assignment arithmetic inside richer functions without modeling or transforming
their surrounding effects. This plan does not replace the M0–M5 evidence record.

## Objective and scope

Extend C-SRD's Clang-based compiler to transform useful computations inside
functions with richer types, memory and effects. Use Tigress's published
analysis, representation and control-flow designs as references, credit their
sources, and validate the actual C-SRD implementation under explicit contracts.

There is one development sequence. Tigress is a literature/design reference;
this plan introduces no Tigress executable dependency, external transformation
backend or Tigress comparison project. Correctness checks, compiled-code audits
and reconstruction measurements are acceptance work within each coverage
milestone. The unit of success is an actual supported transformation, not merely
parsing a larger input file.

## Milestones and completion evidence

| Stage | C-SRD deliverable | Evidence required to complete it | Backlog |
| --- | --- | --- | --- |
| C1 — Pointers and bounded buffers | Memory-aware analysis and transformations around admitted uint32 loads/stores, with ordinary caller-visible memory | Equal return and observable memory; unchanged untouched regions; alias, index and access-order controls; actual emitted-C validation and GCC/Clang/sanitizer checks | MEM-01/02, COV-06, VER-01 |
| C2 — Direct calls and I/O boundaries | Known direct calls and explicit effect/environment summaries inside admitted functions | Correct arguments, returns, memory modifications and ordered events; corrupted/reordered-call controls; conservative rejection of unknown effects | COV-01 |
| C3 — Dynamic allocation | Selected allocation/deallocation patterns and object-lifetime tracking | Allocation-failure paths, bounds, ownership/lifetime and alias effects preserved under the declared environment | COV-08 |
| C4 — Input-dependent loops and recursion | Control-flow/state modeling beyond literal-loop expansion; separate recursion increment with per-call state | Loop invariants or explicitly bounded obligations, preserved effects/progress, recursion-state checks and depth/bound-failure controls | COV-02/09 |
| C5 — Signed integer operations | Selected signed types/operations under explicit C semantics | Boundary and negative-value cases; promotions/conversions and defined-input conditions; no new signed overflow or invalid shifts | COV-07 |
| C6 — Floating-point operations | A separately specified exact floating-point model and supported transformations | Rounding, exceptional values, signed zero and relevant environment effects accounted for; no substitution of approximate arithmetic under an exact contract | COV-04 |
| C7 — Concurrency | First explicit thread-local/shared distinction, then admitted shared-memory transformations | Atomicity, synchronization, memory ordering, reentrancy and observable-execution constraints, with concurrency-specific controls | COV-05 |

C1's first fixed-index, straight-line slice is implemented; dynamic indexes and
general region selection remain outside it. Each later stage starts from a bounded
contract and prototype; a row does not imply support for every use of that
feature. C4's loop and recursion additions are separate increments, and C3/C5
have independent acceptance evidence. No delivery dates, staffing commitments
or universal-C completion promise have been invented.

## C1: the first concrete extension

Start with caller-provided bounded `uint32_t` storage. Specify valid-object,
length, initialization, alignment and lifetime conditions before rewriting.
Eligible computations encode after loads and decode before stores. This allows
ordinary callers to keep their existing memory representation and interfaces.
It does not claim that the stored caller data is hidden.

Extend the semantic model to describe reads and writes in program order, along
with returned values. Track declaration identity, possible aliases and address
escapes. Unknown writes invalidate affected facts or exclude the region. Do
not assume `restrict` or nonaliasing without a justified contract. Include
same-object/overlapping-access, boundary-index and zero-length controls wherever
the admitted domain permits them; do not execute undefined originals as tests
of equivalence. Check memory outside the intended write region as well.

Introduce effect-aware region selection so an admitted function can contain
ordinary memory boundaries around transformed computations. Every exclusion
must remain visible. Unsupported calls are not admitted by this first memory
increment merely because some arithmetic around them looks pure.

The first implementation reparses emitted C and requires a shared-memory SMT
post-state check. An optional CBMC adapter supplies independent C-level evidence
for explicitly selected finite layouts, with bounds checks, unwinding assertions
and negative controls. Further coverage requires its own acceptance policy;
finite tests remain finite tests. This validation is part of C1.

## C2–C5: calls, lifetimes, control and integer semantics

Known call summaries must describe argument/return representations, reachable
memory and external effects. Decode at ordinary interfaces where required and
preserve observable call order. I/O needs controlled-environment event traces,
not only equal final return values. Callbacks, indirect calls, unknown callees
and hidden state require explicit admission rules rather than guessed effects.

Allocation contracts cover successful and failed allocation, deallocation and
object lifetime. Do not assume allocation always succeeds. Define observable
object identity; raw addresses from independent executions are not an adequate
equivalence oracle. Additional allocation families or escaping heap objects need
their own coverage checks.

An input-dependent loop can be transformed by maintaining the relationship
between original and transformed states, effects and progress. The transformer
does not need to predict when every input will finish. Bounded unrolling alone
establishes only its declared scope. Recursion adds separate per-activation state
and explicit depth/resource assumptions. Signed operations require their own
promotion, conversion, overflow and shift rules; unsigned wraparound laws do not
automatically supply them.

## Published designs informing the implementation

These are design references, not locally reproduced Tigress results:

* [Developer architecture](https://tigress.wtf/developers.html): separation of
  analysis, transformation infrastructure and representation codecs. Adapt the
  ideas within Clang rather than treating the OCaml/CIL implementation as a
  LibTooling component.
* [EncodeData](https://tigress.wtf/encodeData.html): alias-aware treatment of
  integer pointers/arrays and documented field-insensitive struct limitations.
  Use these as concrete questions for C-SRD's memory/escape model.
* [Flatten](https://tigress.wtf/flatten.html) and
  [Virtualize](https://tigress.wtf/virtualize.html): control-flow and execution-state
  representations relevant to richer functions. Any C-SRD adaptation must
  preserve its own declared C11 semantics and demonstrate its own benefit.
* [LowerType](https://tigress.wtf/lowerType.html): an example of conversions at
  function and memory boundaries. Its documented float-to-fixed conversion is
  approximate and range-limited; it does not establish exact IEEE equivalence.

The initial floating-point objective remains exact behavior within a declared
model. A numerical-error tolerance would be a different, explicitly accepted
research contract. Concurrency likewise needs its own memory-model and
observable-execution reasoning; a transformation that introduces threads does
not establish support for arbitrary concurrent C input.

## Acceptance work inside every milestone

Declare the exact supported constructs, assumptions, benign fixtures, seeds,
budgets and compiler profiles before running each experiment. This roadmap is
not a complete preregistered experiment manifest. Retain actual generated C,
commands, hashes, counterexamples, failed prototypes and meaningful journals.

Compare original and C-SRD variants under matching build conditions using the
existing GCC/Clang profile catalog, including optimized/LTO and sanitizer checks
where available. Keep strict-C11 compatibility and explicit unavailable states.
Measure actual transformed coverage, application runtime/size and analysis
costs separately; assess broad tradeoffs before choosing cost ceilings.

The current pure-u32 grader and observer interface must be extended when a new
contract exceeds their scope. Unsupported observer input is a coverage gap, not
evidence of increased protection. Preserve tested, bounded-checked,
proved-under-model, counterexample and inconclusive outcomes distinctly. Return
equality alone cannot certify memory or I/O behavior.

Use development controls for the existing warmup-calibration issue when making
new persistent-cost comparisons. Serialize resource measurement after builds
and tests. Freeze the relevant transformation/observer/sampling protocol before
opening reserved outcomes. Extend runtime observation to admitted memory tasks
as coverage permits; analyzer RSS and program-value exposure remain distinct.
No new claim about human effort follows without a human study.

Credit established research and preserve earlier experiments. The
[research charter](research-charter.md), [semantic contract](semantics.md) and
[backlog](backlog.md) remain the authoritative boundaries until new implemented
contracts replace them explicitly.
