# Representation planning

Each live graph node has a versioned identity and a legal set of representations.
Arithmetic nodes allow identity/affine, bitwise nodes identity/XOR, selections
and tables all three, comparisons identity. Parameters are ordinary at entry;
constants are encoded at generation time. Branch conditions, comparison operands
and table indexes require ordinary inputs. The return has an ordinary sink.

One conversion event is charged for each producer/destination representation
needed by any consumer and different from the producer's representation.
Consumers share that conversion. This distinguishes region planning from the
`independent` baseline, which encodes/decodes every eligible operation separately.
Uniform `affine` and `xor` baselines retain their representation where legal and
convert at incompatible operations. `identity` still performs graph lowering,
so the original source remains the actual compiler/runtime baseline.

Let A be estimated scalar operations, C conversion events, and S materialized
temporaries (operation nodes plus conversions). Identity operations cost one;
affine arithmetic two; XOR AND/OR four, NOT one, other XOR operators two.
Affine encode/decode each cost two; XOR each one. A table of n entries costs
2(n−1) comparisons/selections. These are deliberately simple source-operation
proxies, not measured cycles, bytes or backend instruction counts.

| Objective | Primary score |
| --- | --- |
| `runtime` | A |
| `size` | S |
| `balanced` | A + 2C + S |

Lexicographic secondary objectives minimize C, ordinary operation nodes, then
a deterministic weighted label sum. Coverage requires at least
`ceil(eligible_arithmetic_and_bitwise_nodes * percentage / 100)` encoded nodes.
Selections/tables do not contribute to that denominator. Reports distinguish
source syntax counts, live graph operations, conversions and materializations.
Code emitted only to discard an unused parameter is not a graph operation.
`operations_without_decoding` counts operations executed by a native encoded
formula, not the length of a continuous encoded chain. Even the independent
baseline can score highly on that count while decoding every result; interpret
it together with internal conversions, encodings/decodings and ordinary value
nodes. Graph labels describe stored results; independent mode computes using a
temporary encoded representation and immediately stores the decoded result.

Graphs with at most 16 choice nodes use Z3 Optimize, requiring equal lower/upper
objective bounds before reporting `optimized`. Larger graphs, or inconclusive
exact solves, use three deterministic fully encoded starting assignments and
cost-improving single-node moves preserving coverage. This is a local heuristic,
reported as `heuristic` with a reason and **no global optimality claim**. More
than 512 live nodes is unsupported for planning. Every resulting artifact still
requires semantic validation, irrespective of planning quality.

The test suite compares all objective values with exhaustive assignment
enumeration on a small mixed graph. It also tests shared conversion savings
against independent encoding. This is evidence about implementation of the
declared proxy model, not proof that planned code is faster or novel. Solver
timeouts can change the selected feasible plan; fixed seed alone does not make
solver resource outcomes reproducible across machines. Record versions/budgets.

This release exposes multiple scalarizations, not a complete Pareto-front
enumerator. Experiments should compare conversions, measured time, text size,
compile/verification costs and structural metrics separately. Establishing a
contribution beyond known compatible encoding networks remains RQ9.
