# Fourteen coverage and measurement increments

Recorded 2026-11-10 after the user authorized the complete sequence. This refines
[the broader C roadmap](broader-c-support.md); it does not mark its proposed
capabilities implemented. The current baseline is commit `ac88803`.

The objective is useful, validated transformation support across every category
below, accompanied by actual protection measurements. Support and protection
are separate outcomes. A technique without worthwhile measured benefit may be
deferred and revisited; correctness failures may never be waived. Unknown or
unsupported observer outcomes are measurement gaps, not protection wins.

| Increment | Deliverable | Current evidence/status |
| --- | --- | --- |
| 1 | Buffer reconstruction, resource costs and runtime observation | Development checkpoint complete: [112/112 reconstructed artifacts and complete runtime recovery](../reports/buffer-reconstruction.md); no established protection advantage; calibration/application-cost followups remain explicit |
| 2 | Effect-aware selection and composition of regions in larger functions | [Declarations and shadowed locals validated](../reports/private-declarations.md); [call/loop observer pilot measured](../reports/private-region-observers.md): 192/192 tested reconstructions, 134/136 original versus 132/136 affine runtime target cases, stack/resource/application costs; wider profiles and stronger runtime observers remain follow-ups, no broad protection advantage established |
| 3 | Broader integer types, promotions and operators | Isolated unfinished prototype; next validation and measurement gate, not released support; signed/platform-sized interfaces enable later I/O work |
| 4 | Byte/string buffers, runtime indexes and richer pointers | Proposed; only fixed-index uint32 buffers exist |
| 5 | Known direct calls and explicit effect contracts | Proposed |
| 6 | Structs/unions, globals and persistent local state | Proposed; each admitted layout/state pattern needs a contract |
| 7 | Richer branches, exits and input-dependent loops | Proposed; existing pure branches/fixed unrolling are only a starting point |
| 8 | Allocation, failure and object lifetime | Proposed |
| 9 | Recursion, then indirect calls/callbacks | Proposed as separate prototypes within this increment |
| 10 | File/console I/O and ordered external-event contracts | Proposed |
| 11 | Networking, partial transfers and failure/environment models | Proposed; depends on types, byte memory, calls, control flow and I/O |
| 12 | Exact floating-point behavior within a declared model | Proposed |
| 13 | Thread-local then shared/atomic/volatile behavior | Proposed; signals require separate admission rules |
| 14 | Multi-file builds, preprocessing and realistic combined coverage | Proposed; integration fixtures also accompany earlier increments |

Every row requires an explicit language/environment contract, working automatic
transformation, negative controls, actual emitted-artifact validation, appropriate
GCC/Clang matrix checks, and reconstruction/runtime/size measurements. Record
tested, bounded-checked, proved-under-model, inconclusive and unsupported outcomes
separately. Whole-program acceptance is not transformed-code coverage.

Compare original, identity and candidate artifacts under matching builds. Keep
observer inputs separate from withheld reference source used for grading. CPU,
RSS, wall time, queries/traces and recovery correctness belong to analysis costs;
application costs and runtime data visibility are separate measurements. Preserve
failed prototypes, raw results and meaningful journal entries. No cost/benefit
threshold has been chosen: report tradeoffs before choosing one.

The fourteen rows are a development breakdown, not dates or a universal-C
completion promise. Further prototypes are expected where combinations expose
new semantic obligations. Do not close a row using evidence from an unrelated
or narrower contract. Deferred techniques retain their unsuccessful/inconclusive
evidence and explicit revisit conditions.
