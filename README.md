# C-SRD

C11-to-C11 experimental compiler for semantics-preserving computational
representations. Built with C++17, Clang LibTooling and Z3. Generated programs
need no C-SRD runtime library. This is software-diversification research for
benign programs, not cryptographic protection or security-product evasion.

The engineering goal is a general-purpose C-to-C obfuscator: reusable passes
that operate on real program build configurations, with explicit coverage and
correctness contracts. Broad input support and resistance to reconstruction are
separate requirements. Evaluation tasks measure the resulting tool across programs;
they do not restrict its implementation to one algorithm or benchmark. The current
release remains a prototype with the scoped transformation coverage listed below.

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

Version 0.14.1 adds `--target TRIPLE`, `--sysroot DIRECTORY`, repeatable
`--include-dir DIRECTORY` and repeatable `--define NAME[=VALUE]` to all commands.
An explicit target never inherits the host SDK. Transformations and their emitted
C are parsed with identical settings; reports record the flags and header hashes.
`preprocess` uses Clang to freeze one build configuration into a `.i` file, retaining
line markers. This enables analysis of expanded macros without rewriting macro
definitions. Preprocessing itself is trusted compiler behavior, not formally proved.

For example, with a MinGW Windows sysroot installed:

```sh
build/csrd preprocess input.c -o build/input.i \
  --target x86_64-w64-windows-gnu \
  --sysroot "$(x86_64-w64-mingw32-gcc -print-sysroot)" \
  --report build/preprocessing.json
build/csrd transform build/input.i -o build/output.i --scope private-regions \
  --target x86_64-w64-windows-gnu \
  --sysroot "$(x86_64-w64-mingw32-gcc -print-sysroot)" \
  --seed 42 --report build/transformation.json
```

Frozen input/output must use the recorded target and configuration; `.i` files
are not portable source packages. This increment does not import compilation
databases, select every build configuration, or transform/link a multi-file project.
Those remain build-integration work; explicit target support does not expand the
set of arithmetic, memory or control-flow transformations.

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

`--call-contracts tests/fixtures/stdio_calls.json` selects `opaque-stdio-v3`:
caller-owned `FILE *` parameters and `fgetc`, `fputc`, `fflush`, `feof`, `ferror`
and `clearerr` in admitted branches and bounded loops. Library `int` results
require explicit conversion to `uint32_t`; `fputc` character arguments must be
proved nonnegative and representable as `int`. Handles and call interfaces stay
ordinary. Verification compares executed call order, stream identities (including
aliases), character arguments, pre-call user memory, return and final user memory.
Identical traces preserve external effects under coupled standard-library behavior.
Streams must be valid for each operation; all library-managed storage, including
`errno`, FILE internals and `setvbuf` buffers, must be disjoint from admitted user
memory. No interposition, reentry, concurrency, opening/closing, formatted/block
I/O or local handle aliases are admitted. EOF and error outcomes are included in
transformation validation.

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
| 10 | File/console I/O and ordered events | Scoped checkpoint measured; transfer-loop reconstruction proofs inconclusive |
| 11 | Networking, partial transfers and failures | Pending |
| 12 | Exact floating-point behavior | Pending |
| 13 | Thread-local/shared/atomic/volatile behavior | Pending |
| 14 | Multi-file builds, preprocessing, combined coverage | Explicit target/preprocessing support added; project integration pending |

Tests are executable contracts under `tests/`; compiler-profile catalogs and
benign programs are under `benchmarks/`. `tools/` contains verification,
differential execution, compiled-code comparison, Ghidra reconstruction and
bounded GDB value-recovery tooling. Write generated measurements to ignored
`build*/` directories. CPU/RSS, recovery correctness and application costs are
separate measurements; fingerprints and finite tests are not equivalence proofs.

The full Linux regression passed all 56 test groups. The stdio checkpoint
(0.14.0) passed 216,832 differential comparisons across
132 native and 88 Linux compiler/strategy cells, including available optimization,
LTO and sanitizer profiles. Checks cover returns, caller memory, file contents,
positions, status flags, errno and flush/close outcomes. Linux cases include real
read failures and immediate/deferred write failures. These tests do not establish
universal equivalence; transformation proofs use the explicit stream model above.

The compiled-code audit uses six functions, Clang 18/GCC 13, `-O0`/`-O2`, and
original, identical-copy, identity and affine variants: 96 binary cases. Ghidra
12.2 plus the revised adapter produced candidates for all 96; three repetitions
agreed. The original audit's eight stream-merge coverage gaps remain recorded.
Of 50 distinct reference/answer pairs, 39 passed source-model proofs and 11
transfer-loop answers remained inconclusive, including originals. This is a
solver limitation, not evidence of protection. All 50 answers passed 56,000
compiled oracle checks with both compilers; corruption controls were rejected
across 141,120 executions. No proof of binary lifting is claimed. GCC binaries
use native GCC preprocessing while source-model grading uses separately bound
Clang input; cross-preprocessor equivalence is not proved.

All 4,608 runtime traces matched independent return/memory/stream-state/call-event
oracles. The protocol uses 24 vectors, two initial EOF states and a 1,024-step cap
(maximum observed: 477). Library interiors are stepped over. This runtime corpus
covers successful I/O and EOF on Linux/glibc; recovery on failure paths and aliased
stream handles remains unmeasured. Four unexecuted target/layout cases per variant
are excluded explicitly. Affine fitting recovered 90/92 intermediate cases versus
89/92 originals, and every variant recovered all 48 public-return cases. No
informative negative control validated; 16 constant-label cases per variant have
uninformative shuffled controls and are excluded from false-positive counts.
Three fitting repetitions agreed; artifact/proof bindings and oracles were checked.

Ordinary intermediates were visible in 2,120/2,184 affine target/trace pairs versus
2,170/2,184 originals. Static reconstruction uses no target executions; fitting uses
known labels, with 12 training and 12 heldout traces per initial state. Fit replays
make no new queries. Missing fixed-location fits do not establish that values are
hidden. These experiments do not measure blind discovery or human effort, and
**no useful protection advantage was demonstrated on this corpus**.

Median matched `-O2` ratios against originals on Linux ARM64:

| Compiler | Adapter CPU | Fit CPU | Fit peak RSS | Application CPU | Function bytes |
| --- | --- | --- | --- | --- | --- |
| Clang 18 | 1.01 | 1.39 | 1.16 | 1.009 | 1.37 |
| GCC 13 | 1.01 | 1.57 | 1.25 | 1.027 | 1.70 |

Adapter CPU includes Python startup and excludes Ghidra (six matched functions).
Fit ratios use twelve function/initial-state pairs; affine fitting took median
246/298 ms including startup and trace loading. Copy-control fit CPU ratios were
1.007/0.993. Application timing uses seven repetitions of one million calls, with
real stdio and target flushes inside the clock; preparation and content checksums
are outside it. Copy-control application ratios were 1.002/1.000. Cold Ghidra CPU
ratios were 1.009/0.994, with only one collection per binary. None of the twelve
optimized affine cases retained identical function bytes or opcode sequences;
eleven identity controls retained identical bytes. Structural change did not
prevent reconstruction or value recovery.

Run the stdio checks and a reconstruction collection inside the Linux validation
environment, with Ghidra installed and `GHIDRA_HEADLESS` pointing to `analyzeHeadless`:

```sh
ctest --test-dir build --output-on-failure -R 'stdio_call|stdio_observation|pcode_memory|buffer_runtime|observer_evidence_links'
python3 tools/audit_buffer_reconstruction.py --csrd build/csrd \
  --headless "$GHIDRA_HEADLESS" --compiler clang=clang-18 --compiler gcc=gcc \
  --source tests/fixtures/stdio_calls.c --call-contracts tests/fixtures/stdio_calls.json \
  --repetitions 1 --output-dir build/stdio-matrix
```

Run collectors serially. Use the resulting `reconstruction.json` with
`tools/replay_buffer_observers.py` (three adapter repetitions), then its `replay.json`
with `tools/grade_byte_reconstruction.py --corpus stdio`. Run
`tools/observe_buffer_runtime.py --corpus stdio --step-limit 1024`, binding both
reports with `--reconstruction-report` and `--replay-report`. Use its `runtime.json`
with `tools/replay_buffer_fits.py` (three repetitions). Finally run
`tools/measure_byte_costs.py --corpus stdio` (seven repetitions, one million calls)
and `tools/inspect_region_binaries.py` against the same collection/replay.
`tools/check_buffer_evidence.py` checks these reconstruction/runtime bindings and
replays saved fits. Each tool exposes `--help`; generated reports record commands,
seeds, budgets, implementation hashes and precise observation scopes. Outputs belong
under ignored `build*/` directories, with original failed attempts retained.

The same tools accept `--corpus byte`, `call`, `record`, `control`, `heap` and
`dispatch` for earlier scoped fixtures. Heap and recursion grading have the
supplemental observation modes described above; keep strict reports unchanged.
Ghidra ARM64 signed-byte lifting requires the checked overlay produced by
`tools/patch_ghidra_signed_byte.py`. The networking increment remains pending,
including partial transfers, EOF/failures and matched correctness/recovery/cost
measurements. The immediate build-integration task is compilation-database import
and a multi-file driver, followed by broader reusable transformation passes.

## Benign AES recognition checkpoint (0.14.0)

`tools/audit_crypto_recognition.py` compares pinned tiny-AES-C AES-256 builds
with current C-SRD output and a no-crypto input/output control. It uses the seven
Windows x64 profiles and rule revisions from the
[published hidden-tiny-aes methodology](https://deadkennedyx.github.io/ST_M1CH43L/posts/hide-encryption-signatures-from-analysis-part-2.html),
with a separate runtime-input harness: GCC 16.2 `-O0/-O2/-Os/-O2 -flto` and
Apple Clang 17 `-O0/-O2/-Os`, linked with MinGW. Sources, rules, capa signatures,
tool versions, commands, hashes and raw findings are recorded. This is a fixed
recognition experiment; scanner feedback does not select transformations.

The completed run used YARA 4.5.8 and capa 9.4.0/Vivisect. Each cell counts builds
with an AES-specific match; these are crypto classifications, not malware verdicts.

| Implementation | Yara-Rules | findcrypt-yara | crypto-detection | capa/Vivisect |
| --- | --- | --- | --- | --- |
| Stock tiny-AES-C | 7/7 | 7/7 | 7/7 | 7/7 |
| C-SRD raw-source output, unchanged | 7/7 | 7/7 | 7/7 | 7/7 |
| No-crypto control | 0/7 | 0/7 | 0/7 | 0/7 |

All 84 scanner invocations completed. Both transformation scopes leave all 20
original functions unchanged; paired Windows binaries are byte-identical.
Native preprocessing permits two `KeyExpansion` regions, totaling five encoded
index-arithmetic operations, with contextual proofs under the integer model.
The AES tables and rounds remain unchanged. That partial transformation is not
included in the Windows table: the frontend has no cross-target configuration,
and its native LP64 output must not be treated as Windows LLP64 output.

Native original/pass-through/partially transformed cases passed 4,690 executions
against OpenSSL 3.6.4, comparing complete key-schedule/IV state between variants,
plus 84 upstream known-answer checks, including Clang ASan/UBSan builds. Only
the six proper upstream tests are called; its verbose demonstration uses a
16-byte key even under AES-256. These tests cover fixed 64-byte buffers and do
not prove arbitrary AES executions. Windows binaries were scanned, not executed.
No protection advantage is demonstrated, and the historical Part 1/2 variants
were not rerun. The seven compiler profiles are not independent program samples.

Reproduce on the macOS toolchain above (MinGW, GCC 16, LLVM Clang, OpenSSL and
YARA installed); `--fetch` downloads only pinned public sources/rules/signatures:

```sh
python3.12 -m venv build-aes-recognition/venv
build-aes-recognition/venv/bin/python -m pip install 'flare-capa==9.4.0'
python3 tools/audit_crypto_recognition.py --fetch \
  --output build-aes-recognition/reproduction --deps build-aes-recognition \
  --capa build-aes-recognition/venv/bin/capa \
  --mingw-sysroot "$(x86_64-w64-mingw32-gcc -print-sysroot)"
python3 tests/integration/test_crypto_recognition.py
```

The local completed artifacts are in `build-aes-recognition/run-2/`; the initial
run is retained in `run-1/`. The latter exposed missing capa library signatures
and GNU strip reinserting PE timestamps. The runner now supplies pinned signatures
and `SOURCE_DATE_EPOCH=0`, checks the PE layout, and records errors separately
from negative matches. Five automated measurement-control tests pass. Scanner
results and native transformation coverage must remain separate when extending
this experiment.

The subsequent 0.14.1 build-compatibility check in
`build-frontend-targets/checkpoint-2/` exercises the new target/preprocessing path.
It validates two Windows `KeyExpansion` regions (five index-arithmetic operations)
under the LLP64 model, and compiles original/transformed inputs in all seven
Windows profiles: 14 builds. Windows execution and new recognition measurements
are not claimed. Native preprocessing/transformation passes 2,010 executions
against the saved OpenSSL references, preserving full key-schedule/IV state, and
36 upstream known-answer checks across `-O0`, `-O2` and ASan/UBSan configurations.
Six frontend integration tests cover LP64/LLP64 differences, header/definition
settings, provenance and failure handling. All nine selected native regression
groups pass. All 58 Linux CTest groups also pass with LLVM 18; nine optional checks
were skipped there (one MinGW, six CBMC and two live Ghidra checks). The native
MinGW test ran successfully. This advances build compatibility, with AES
transformation coverage still limited to index arithmetic.
