# C-SRD

C11-to-C11 experimental compiler for semantics-preserving computational
representations. Built with C++17, Clang LibTooling and Z3. Generated programs
need no C-SRD runtime library. This is software-diversification research for
benign programs, not cryptographic protection or security-product evasion.

## Build and test

Linux requires CMake 3.20+, Clang/LLVM development libraries, Z3, Python 3,
GCC and Clang. The supported validation image supplies these dependencies:

```sh
docker build -f tools/Dockerfile -t csrd-dev:validation .
docker run --rm -v "$PWD:/work" -w /work csrd-dev:validation sh -c '
  cmake -S . -B build-linux -G Ninja -DCMAKE_PREFIX_PATH=/usr/lib/llvm-18 -DCMAKE_BUILD_TYPE=Release &&
  cmake --build build-linux --parallel 2 &&
  ctest --test-dir build-linux --output-on-failure'
```

For a native build, configure the installed LLVM/Clang and Z3 CMake/library
paths, then run `cmake --build build` and
`ctest --test-dir build --output-on-failure`. On macOS, Homebrew LLVM/Z3 and
the Xcode command-line tools are supported. GCC/Clang differential tests include
optimization and sanitizer configurations; optional external tools report skips.

## Use

```sh
build/csrd transform input.c -o output.c --seed 42
build/csrd transform input.c -o output.c --scope private-regions --seed 42
build/csrd analyze input.c --scope private-regions --report build/analysis.json
build/csrd --help
```

`--scope functions` is the default. It admits pure `uint32_t` arithmetic,
selected bitwise operations, selections, bounded loops and lookup tables, plus
a separate ordered byte/`uint32_t` buffer and contracted-call path. `--scope private-regions` selects
private integer declarations/assignments inside richer functions. Calls, loops
and memory boundaries outside those frames remain unchanged and are reported.
Unsupported syntax is diagnosed; failed translation validation prevents output.

The private integer model covers `_Bool` and standard signed/unsigned types
through 64 bits, with C promotions and selected casts/operators. It requires
8-bit bytes, 16-bit short, 32-bit int, 32/64-bit long and 64-bit long long;
signed semantics assume two's complement, modulo signed narrowing and arithmetic
negative right shift. Signed overflow is excluded. Execution validation currently
covers LP64 ARM64. This is not support for arbitrary C11 programs.

The buffer path admits 8-bit character types, bounded runtime indexes (0..255),
captured local pointer views and byte/word aliases. Reports state the required
initialized, live, aligned prefixes of ordinary storage. Arithmetic stays `uint32_t`; only
provably nonnegative, nonoverflowing byte promotions are admitted. Character
signedness and word byte order follow the frontend target. Signed byte narrowing
assumes modulo conversion. String literals and their storage are unchanged.
Verification compares the return and entire shared byte memory. Pointer
reinterpretation and unbounded indexing remain unsupported.

`--call-contracts tests/fixtures/calls.json` enables declared direct calls in
straight-line `uint32_t` functions. Callees may return `uint32_t` or `void` and take scalar or
bounded buffer arguments. Verification compares callees, arguments and all
pre-call memory at each event, then allows arbitrary shared memory/return values
before continuing encoded computation. Contracts assert synchronous execution,
no callbacks/reentry, retained pointers, nonlocal jumps, frame inspection or
invalidation of caller buffers. Callee implementations are not proved by their
declarations. Nested call expressions and varargs remain unsupported.

`--call-contracts tests/fixtures/guarded_calls.json` selects `opaque-guarded-v2`:
calls in branches and bounded loops, calls through explicitly contracted function-pointer
parameters, and direct self-recursion with a decreasing unsigned entry rank.
Code pointers and call interfaces stay ordinary. The verifier checks executed
target identities, arguments, pre-call memory and order, including when two
callback parameters designate the same function. No local code-pointer aliases,
mutual/indirect recursion, reentrant callbacks or mixing owned heaps with opaque
calls are admitted. Recursive contracts must cover the function's own buffer
footprint; self-calls must bind to that definition and sufficient stack storage is assumed.

Transformations use rank induction and preserve self-call events, with declared
maximum ranks through 32. For compiler-generated inlining, verification-only
`--recursion-observation bounded-body` compares returns, whole memory and external
events while excluding internal self-call events. It uses the stronger induction
proof when sufficient, otherwise checked body expansion across every entry-rank
partition, including all out-of-range inputs. This supplemental mode currently
requires a maximum rank of at most 8; it never weakens transformation validation.

The record/state path admits named, padding-free structs/unions with 1..16
`uint32_t` fields, bounded record-pointer views, and mutable file-scope scalar or
record objects. Public storage and initializers stay ordinary; arithmetic between
loads and stores is diversified. Proofs compare return values and persistent
state from equal incoming states. Globals denote distinct complete objects;
record pointers designate complete records, while scalar pointers may alias
fields. Aligned word-only accesses use an exact word projection of byte memory;
small index ranges are proved before enumeration. Nested/padded records, bitfields,
whole-record assignments, local statics and TLS remain outside this increment.

The control-flow path admits call-free memory branches, early returns and
`for` loops with fresh `uint32_t` counters, `++`, and immutable scalar trip limits
bounded by 32. Private locals can be declared inside these bodies. Verification
checks guarded memory effects and every loop exit; finite expansion is never
silently truncated. Break/continue and while loops are excluded; conditional
calls require the separate `opaque-guarded-v2` contract above.

The owned-heap path admits local, nonescaping `uint32_t` arrays of at most 32
elements through `malloc`, `calloc`, positive-size `realloc` and `free`. It
checks every allocation outcome, initialized reads, bounds, aliases, lifetime
and cleanup on every return. Private heap values stay encoded; caller memory
and return values remain ordinary. Zero-size `malloc`/`calloc` can succeed or
fail; zero-size `realloc`, pointer-address observations and mixing heap objects
with opaque calls are excluded. Standard C11 library behavior is assumed.
Allocator events are matched by executed order across branches.

Verification normally compares allocator events as well as returns and public
memory. Compilers can eliminate private allocations, remove `free(NULL)` or
replace `realloc(NULL, n)` with `malloc(n)`. The verification-only option
`--heap-observation successful-private` provides a separate, narrower comparison:
all allocations succeed and allocator events are excluded. It never applies to
transformation validation, and its results do not cover allocation failures.

For `n`-bit integers, affine encoding is `E(x) = a*x+b mod 2^n`, with odd `a`.
Addition, subtraction and constant scaling can remain encoded. The seed selects
reproducible parameters; it is not a secret key. Emitted C is reparsed and checked
against explicit semantic models. Solver success is proof under those models and
their assumptions, not proof of the compiler, machine code or whole environment.

## Coverage roadmap

Each increment needs implementation, negative controls, compiler checks and
matched reconstruction/runtime/size measurements. Parsing a construct or leaving
it unchanged does not count as transforming it. These are scoped increments,
not a promise of universal C support.

| # | Increment | State |
| --- | --- | --- |
| 1 | Buffer reconstruction and runtime observation | Scoped checkpoint measured |
| 2 | Private regions inside larger functions | Scoped checkpoint measured |
| 3 | Integer widths, promotions and operators | Scoped checkpoint measured |
| 4 | Byte/string buffers, runtime indexes, richer pointers | Scoped checkpoint measured |
| 5 | Direct calls and effect contracts | Scoped checkpoint measured |
| 6 | Structs/unions, globals, persistent state | Scoped checkpoint measured |
| 7 | Branches, exits, input-dependent loops | Scoped checkpoint measured; two reconstruction proof gaps |
| 8 | Allocation, failure and lifetime | Scoped checkpoint measured; four reconstruction coverage gaps |
| 9 | Recursion and indirect calls | Scoped checkpoint measured; four affine value-fitting gaps |
| 10 | File/console I/O and ordered events | Pending |
| 11 | Networking, partial transfers and failures | Pending |
| 12 | Exact floating-point behavior | Pending |
| 13 | Thread-local/shared/atomic/volatile behavior | Pending |
| 14 | Multi-file builds, preprocessing, combined coverage | Pending |

Tests are executable contracts under `tests/`; compiler-profile catalogs and
benign programs are under `benchmarks/`. `tools/` contains verification,
differential execution, compiled-code comparison, Ghidra reconstruction and
bounded GDB value-recovery tooling. Write generated measurements to ignored
`build*/` directories. CPU/RSS, recovery correctness and application costs are
separate measurements; fingerprints and finite tests are not equivalence proofs.

The recursion/callback checkpoint (0.13.0) passed 52 Linux test groups in the
full regression and the subsequently added evidence-checker group separately
(eight evidence-link tests, also passed natively). Six benign fixtures passed
43,633,920 differential comparisons: 132 native and 88 Linux compiler/strategy
cells, including available `-O0`, `-O1`, `-O2`, `-O3`, `-Og`, `-Os`, `-Oz`, LTO
and sanitizer configurations. Tests compare returns, all caller memory, external
state and executed callback events; all four callback bindings and eight buffer
alias layouts are exercised.

Ghidra 12.2 plus the adapter reconstructed all 96 Clang/GCC `-O0`/`-O2` binary
cases. Of these, 93 passed the strict self-call-event model; GCC inlining changed
three recursive cases' internal traces. The separate bounded-body comparison
proved their return/memory/external-event obligations under its model. The original
strict failures remain recorded. Three adapter repetitions agreed. All 54 distinct
reference/answer pairs passed 60,480 compiled checks with both compilers;
corruption controls were rejected across 131,040 control executions. These results
do not prove binary lifting or compiler correctness.

All 4,608 runtime traces matched independent return/memory/state/event oracles.
They use 24 vectors, two alias layouts and a 1,024-step cap (maximum observed: 267).
Child calls execute normally but their interiors are stepped over; this measures
the root activation, including any compiler inlining. Absent recursive values on
base/out-of-range paths are excluded from scoring. Affine fitting recovered
100/104 intermediate target cases versus 98/104 originals; all variants recovered
48/48 public-return cases. No negative control validated, and three fitting
repetitions agreed. The fixed-location fitter cannot join every path-dependent
location: some missed original values were literally visible on every trace.
These misses are observer limitations, not evidence of protection.

Ordinary intermediate values appeared in 1,880/2,240 affine target/trace pairs
versus 2,192/2,240 original pairs. Static reconstruction required no target
executions; runtime fitting uses known labels, with 12 training and 12 heldout
traces per layout. Replaying fits makes no new target queries. Neither analysis
measures blind algorithm discovery or human effort. No useful protection advantage
was demonstrated on this corpus.

Median matched `-O2` ratios against originals on Linux ARM64:

| Compiler | Adapter CPU | Fit CPU | Fit peak RSS | Application CPU | Function bytes |
| --- | --- | --- | --- | --- | --- |
| Clang 18 | 1.01 | 1.31 | 1.11 | 1.038 | 1.35 |
| GCC 13 | 0.99 | 1.61 | 1.25 | 1.216 | 1.58 |

Adapter CPU includes Python startup and excludes Ghidra; ratios use six matched
functions per compiler. Fit ratios use twelve function/layout pairs; optimized
affine fitting took median 215 ms (Clang) / 246 ms (GCC), including startup and
trace loading. Identical-copy fit CPU ratios were 0.99/0.99. Application timing
uses seven repetitions of one million calls; copy-control ratios were 1.000/1.001.
Cold Ghidra CPU ratios were 1.01/1.05 with only one collection per binary, so
startup/noise limits interpretation. One of twelve optimized affine cases retained
the baseline opcode sequence (operands excluded); none retained identical function
bytes. Eight optimized identity controls retained identical bytes.

Reproduce buffer/call/record/control measurements with `tools/audit_buffer_reconstruction.py`,
`tools/replay_buffer_observers.py`, `tools/grade_byte_reconstruction.py`,
`tools/observe_buffer_runtime.py`, `tools/replay_buffer_fits.py` and
`tools/measure_byte_costs.py`; use `--corpus call` for call execution tools and
`--call-contracts tests/fixtures/calls.json` for call reconstruction, or
`--corpus record` for record execution tools. Control measurements use
`--source tests/fixtures/memory_control.c` for reconstruction and `--corpus control`
for execution tools. Runtime/cost/binary tools accept `--replay-report` to bind a
revised observer to the original frozen matrix, retaining inconclusive grades.
Record reconstruction supplies public
types/global names to Ghidra and assumes stable, resolved loader bindings. Each exposes
`--help`. Ghidra ARM64 signed-byte lifting requires the checked
overlay produced by `tools/patch_ghidra_signed_byte.py`. Generated artifacts stay
under ignored `build*/` paths; the repository keeps no measurement archives.

Heap measurements use `--source tests/fixtures/owned_heap.c`, `--corpus heap`
and supplemental `--heap-observation successful-private`. Recursion/callback
measurements use `--source tests/fixtures/guarded_calls.c`,
`--call-contracts tests/fixtures/guarded_calls.json`, `--corpus dispatch` and a
supplemental replay with `--recursion-observation bounded-body`. Keep strict
reports unchanged. Run correctness checks with:

```sh
ctest --test-dir build --output-on-failure -R 'guarded_call|observer_evidence_links'
```

`tools/check_buffer_evidence.py --reconstruction-report MATRIX --replay-report REPLAY
--runtime-report RUNTIME --output RESULT` validates artifact/proof bindings,
repetition coverage and runtime oracles, and replays the saved fits. Run collectors
serially in the same environment. The next increment is scoped file/console I/O
with ordered events, EOF/error paths and the same correctness and measurement gates.

Maintainer: [DeadKennedyx](https://github.com/DeadKennedyx),
`juan.dw.ft@gmail.com`. [MIT license](LICENSE).
