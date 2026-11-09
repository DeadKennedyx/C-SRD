# Contributing

Follow the evidence-driven cycle in the [technical specification](README.md).
Start by identifying the current process stage and one specific problem. Record
observations and alternatives, state a falsifiable hypothesis, define constraints
and a repeatable protocol, then implement and analyze the result. A failed or
inconclusive experiment must remain visible in the record.

Use a dated [research journal entry](docs/journal/README.md) for material
decisions, assumptions and deviations. Label retrospective reconstructions.
Connect work to [acceptance criteria](README.md#acceptance-criteria-and-traceability)
and [backlog dependencies](docs/backlog.md). Proposed metrics and future tasks
must not be presented as completed experiments. The issue and pull-request
templates provide a consistent handoff format.

Build with CMake and run CTest before proposing a change. Keep generated C
independently compilable as C11. Use Clang's AST/type information for language
decisions; source lexing is only for preprocessing boundaries and replacement.

A new rule needs an explicit domain, unsigned/signed and promotion conditions,
representation compatibility, a numeric implementation, a C emission rule,
machine-checkable arithmetic obligations where applicable, boundary cases,
rejection cases and GCC/Clang differential validation. Any change expanding
accepted C must update `docs/semantics.md` and include a counterexample that the
old restriction prevented or a proof of the new rule's safety.

Treat `tested`, `bounded-model checked`, `proved under assumptions` and
`unverified` as different statuses. Reports must identify real commands,
versions, seeds, hashes, test populations and exclusions. Never infer a full
compiler proof from successful unit tests or SMT algebra checks. Retain checks
in Release builds and make solver `unknown` or timeout fail explicitly.

Use small components and avoid speculative frameworks or unimplemented CLI
options. Keep source, IR, binary, algorithmic and behavioral claims separate.
Update the literature comparison before asserting novelty. The initial test
corpus and new examples must remain benign and respect the research charter.

Keep Git authorship and repository credentials appropriate to this personal
project. Do not commit tokens, private keys, local credential configuration or
unrelated account information. Historical reports remain immutable evidence;
if history metadata changes before publication, preserve a content-identity map.
