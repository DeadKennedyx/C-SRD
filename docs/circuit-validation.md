# Validating saved mismatch queries with a circuit checker

## Problem and hypothesis

A decompiler can produce a correct reconstruction that a particular equivalence
grader cannot resolve in time. Treating that timeout as failed reconstruction
would overstate protection. The hypothesis here is that a circuit equivalence
checker can resolve some saved bit-vector mismatches after exact Boolean
lowering. This changes the grader; the observer receives no new information.

`csrd-query-circuit` and `tools/verify_circuit.py` implement an optional research
path. It is separate from `csrd transform` and its mandatory validation gate.
ABC must be supplied explicitly; no ABC download or invocation occurs during
ordinary transformation or CTest. This path adds no supported C constructs.

## Theory of operation and trust boundary

For the one saved assertion Q, Z3 applies polynomial simplification and bit-vector
lowering to produce a Boolean mismatch B. A circuit output of zero for every
Boolean input establishes that Q is unsatisfiable, under Z3's lowering semantics.
The tool rejects quantifiers, uninterpreted function applications, non-Boolean/
bit-vector sorts, widths above 64 bits, and multiple assertions. File and node
limits bound admitted artifacts; these are not a security sandbox.

The exporter writes a combinational positive-cover BLIF network. An independent
reader then consumes the actual file. A fresh invocation derives the expected
Boolean DAG again from the original query. It requires identical input ordering,
a single output, complete unique drivers and an acyclic gate order. For every
gate, it compares the native Boolean operator against the parsed truth-table
cover for **all assignments to its local input wires**. Only unsat admits that
gate. Identical local obligations are cached with their ASTs retained; every
gate records the obligation it used. The final output connection is also checked.

Induction over this DAG binds the actual circuit output to the lowered formula.
This avoids another difficult whole-circuit comparison between two equivalent
Boolean presentations. No input samples or successful tests replace a gate
proof. Altering a truth row, query, connection or interface invalidates the
corresponding check. The checker interprets positive-cover cubes directly; it
does not reuse the exporter's operation-to-truth-table switch.

Only after validation does the driver run ABC's combinational equivalence
checker on the single-output mismatch circuit. It uses a fixed relative filename,
disables initialization scripts, records executable hashes and checks the exact
result protocol and process status. Timeout, nonzero exit, errors, conflicting
results or missing results remain inconclusive. The circuit/query bytes are
checked again after solving. New output directories prevent accidental evidence
replacement.

The trusted implementation includes the original C-to-SMT model when a query
came from C-SRD, Z3's lowering and gate solver, the DAG/binding checker, ABC and
its BLIF reader, and the host runtime. ABC supplies a different circuit decision
engine; this is **not an independent C frontend, machine-code equivalence proof,
or externally checked proof certificate**. A sat circuit result does not yet
provide public C inputs; the driver labels that limitation explicitly.

## Reproduction and evidence

Build the helper with the existing LLVM/Z3 configuration:

```sh
cmake --build build --target csrd-query-circuit
ctest --test-dir build -R saved_query_circuits --output-on-failure
python3 tools/verify_circuit.py --query saved-mismatch.smt2 \
  --circuit-tool build/csrd-query-circuit --abc /path/to/abc \
  --output-dir experiments/runs/new-circuit-check
```

The driver defaults to five seconds in ABC and eight seconds of wall budget for
each process stage. Solver budgets are experimental limits, not application
overhead cutoffs. Export, validation, solving and version lookup have separate
CPU/wall/RSS records. `total_wall_seconds` includes driver overhead through result
handling, but excludes the initial query copy and final manifest/report I/O;
`child_cpu_seconds` sums measured children. Native macOS records peak process
RSS; aggregate sampled tree RSS is available on Linux. These measurements must
not be added to observer costs or described as reconstruction effort.

Outputs include the unchanged query, circuit, lowered formula, native gate
bindings, every distinct local obligation, the gate-to-obligation index, complete
commands/logs, tool hashes/version output, resource records and an artifact hash
manifest in `report.json`. `unsat` and `sat` describe the saved SMT assertion.
`inconclusive` admits no equivalence conclusion.

For existing observer experiments, `experiments/grade_saved_answers.py` selects
measured inconclusive answers, excludes historical warmups, verifies the original
report/query/C-file hashes, and replays the saved mismatches plus their corrupted
answer controls. It writes a protocol before measurements and a separate report.
Historical observer records remain the record of the earlier grader.

## Background

Simulation, merging proven intermediate equivalences, rewriting and SAT-based
combinational checking are established techniques. See
[Mishchenko et al., ICCAD 2006](https://people.eecs.berkeley.edu/~alanmi/publications/2006/iccad06_cec)
and the [ABC project](https://github.com/berkeley-abc/abc). Z3 documents its
[bit-vector semantics](https://microsoft.github.io/z3guide/docs/theories/Bitvectors/)
and [tactic composition](https://microsoft.github.io/z3guide/docs/strategies/tactics/).
The adaptation here makes a saved-query experiment inspectable; no new
equivalence-checking method or protection property is claimed.
