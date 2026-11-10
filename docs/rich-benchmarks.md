# Rich benchmark corpus, version 1

## Problem and hypothesis

The original effort pilot mostly measured short arithmetic functions. Its runtime
target was a known sum already determined by public inputs. We need independent
functional contracts, more mixed arithmetic/bitwise work and untouched algorithm
families before evaluating new representations. Hypothesis: this corpus exposes
verification and reconstruction limits that the earlier examples did not.

## Contracts and controls

Every input is a `uint32_t`, and every function is named `kernel`. Packed words
make byte order explicit without extending the transformer to pointer arguments.
These are bounded kernels, not complete applications or cryptographic primitives.

| Split | Kernel | Contract |
| --- | --- | --- |
| Development | `crc32_byte(state, byte)` | Complemented IEEE CRC-32 state update by the low byte; same state convention as `zlib.crc32` |
| Development | `jenkins_word(state, word)` | Four little-endian bytes, Jenkins one-at-a-time updates and finalization, wrapping at 32 bits |
| Development | `morton16(x, y)` | Interleave the low 16 bits; x in even output positions, y in odd positions |
| Development | `rgb_luma8(rgb)` | `(77R + 150G + 29B) / 256`, integer truncation, low 24 bits interpreted as RRGGBB; no color-standard conformance claim |
| Reserved | `fletcher16_word(state, word)` | Canonical sums modulo 255, state low byte A and next byte B, four little-endian bytes; return `256B+A` |
| Reserved | `internet_checksum(first, second)` | Four network-order 16-bit words, one's-complement sum with end-around carry, complemented result |
| Reserved | `gray_decode32(gray)` | Invert the 32-bit binary-reflected Gray code |
| Reserved | `fnv1a_word(state, word)` | FNV-1a update of four little-endian bytes, arbitrary initial state, multiplication modulo 2^32 |

CRC has a separate nibble-table implementation, Morton a serial interleaver, and
RGB a shift/add implementation. The first two are algorithmic controls; the last
is algebraic. Wrong-polynomial CRC and a rare-input RGB mutation are negative
controls with explicit counterexamples. Distinct same-arity families provide
additional negative comparisons. The RGB mutation deliberately agrees on the
discovery fingerprint: the grader must still reject it.

The [manifest](../experiments/rich-benchmarks.json) fixes contracts, known answers,
sources, controls, splits and the existing 26-profile compiler catalog. No reserved
family recovery results may inform candidate or observer tuning. Correctness
validation of those families is allowed. Freeze the development protocol,
candidate hashes and tool versions before opening the reserved evaluation;
subsequent tuning requires a fresh reservation.

## Validation implementation

`tools/validate_benchmarks.py` admits each source using Clang, checks equivalence
controls through reparsed C and SMT, and requires negative controls to have both
a source-model counterexample and their declared compiled witness. It compiles
GCC and Clang at O0/O2 and optionally O1 with ASan/UBSan, with warnings as errors.
Separate [Python oracles](../tools/benchmark_oracles.py), edge vectors, single-bit
patterns, seeded random inputs, known answers and the CRC check string grade the
executables. Oracles are grader inputs, never inference inputs to observers.

```sh
python3 tools/validate_benchmarks.py --csrd build/csrd \
  --compiler clang=clang --compiler gcc=gcc --sanitizers \
  --output-dir experiments/runs/rich-validation-new
```

Use real compiler paths where `gcc` aliases Clang. The output directory must be
new. Reports retain command output, tool/source/input/output hashes, failures,
proof status and fingerprint confusion counts. Integration tests inject a faulty
original and a false negative witness to test the grader itself.

For development exploration, `run_matrix.py --matrix experiments/rich-benchmarks.json
--no-select ...` records every requested candidate without runtime/size screening.
It still requires correctness validation. Report CPU, wall time, RSS, query/trace
budgets, recovery accuracy, runtime and size together; unsupported observer cases
and timeouts cannot establish increased reconstruction difficulty.

## Interpretation and sources

Source-model proofs trust Clang extraction, the model and Z3; they do not prove
machine-code semantics. Differential tests sample executions. Fingerprints are
finite evidence. The independent Python oracles can also contain errors; positive
and negative controls reduce that risk without eliminating it. Results and the
first failed proof pilot are in [the validation report](../reports/rich-benchmarks.md).

Algorithm sources: [CRC recurrence](https://www.rfc-editor.org/rfc/rfc1952.html),
[Jenkins descriptions](https://burtleburtle.net/bob/hash/doobs.html),
[Internet checksum](https://www.rfc-editor.org/rfc/rfc1071.html),
[Fletcher background](https://www.rfc-editor.org/rfc/rfc1146.html), and
[FNV specification](https://www.rfc-editor.org/rfc/rfc9923.html). The canonical
modulo-255 zero used here is part of our contract; it is not a claim of complete
RFC 1146 protocol conformance. Implementations are small, original expressions
of these established algorithms. No novelty claim is made for the algorithms.
