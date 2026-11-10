# Compiled validation and observer protocol

This is a bounded experiment suite for the admitted pure-u32 subset, not an
all-C protection guarantee. It implements the next four research steps around
the existing transformer; it does not add a new encoding or extend C coverage.

## Matrix and evidence boundary

[The versioned matrix](../experiments/matrix.json) declares five development
cases, two held-out cases and 26 build profiles. Each profile specifies compiler,
optimization, LTO, profiling, instrumentation, CPU and target constraints.
Executable overrides select installed versions. Reports record tool hashes,
versions, targets and commands; link probes print linker versions.

The [richer corpus](rich-benchmarks.md) reuses this profile catalog with eight
separate algorithm families. `--no-select` enables report-only exploration without
cost cutoffs. Failed candidate preparations remain explicit cells and do not stop
other variants from being measured; the overall matrix still reports failure.

`tools/measure_code_size.py --matrix-report MATRIX --output-dir NEW_DIRECTORY`
adds a read-only linked-section audit to a finished matrix. It checks tool/binary
hashes, retains invalid cells as omissions, and compares `.text`/`__text` sizes
against the original. Whole linked text includes the harness, runtime support and
padding. It complements total executable bytes, which may hide code growth through
alignment; it is not an isolated function-size or runtime-RSS measurement.

* **Core:** GCC/Clang O0, O2, and O2 with full LTO. O0 is diagnostic; both O2
  and both O2-LTO profiles are mandatory for candidate selection.
* **Extended:** core plus O1/O3/Os/Oz/Og, Clang ThinLTO, GCC O3 LTO, instrumented
  PGO, native CPU settings, ASan/UBSan and architecture-constrained probes.
* **Held-out:** difference/minimum functions, frozen development seeds/strategies,
  and O3/Oz/LTO profiles. These functions were previously used in correctness
  tests; they are held out from this selection run, not historically unseen by
  the developers. This run does not rerank candidates.

This is a declared set, not an exhaustive Cartesian product or pairwise covering
array. PGO+LTO, arbitrary pass sequences, Windows/MSVC and arbitrary applications
remain outside this first matrix. Cross-target work requires matching frontend,
compiler, headers and execution environment. An ARM host does not count an x86
compile probe as executed x86 validation. Missing tools/options/targets are
`unavailable`, never passes. A profile that passes its capability probe but fails
an actual candidate is a failure. The manifest's `deferred` list records other
absent capabilities.

References: [GCC options](https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html),
[Clang PGO](https://clang.llvm.org/docs/UsersManual.html#profile-guided-optimization),
[LLVM LTO](https://llvm.org/docs/LinkTimeOptimization.html). Options that change
the semantic contract are not silently added as stress tests.

## Running the suite

Use Python 3.10 or newer and the existing C-SRD build. The experiment scripts
use the Python standard library; GDB is needed only for live observation.

```sh
python3 tools/run_matrix.py --csrd build/csrd \
  --compiler clang=clang-18 --compiler gcc=gcc --objdump llvm-objdump-18 \
  --profdata llvm-profdata-18 --tier core \
  --seeds 42 7 --output-dir experiments/runs/core-new

python3 tools/run_matrix.py --csrd build/csrd \
  --compiler clang=clang-18 --compiler gcc=gcc --objdump llvm-objdump-18 \
  --profdata llvm-profdata-18 --tier extended \
  --seeds 42 7 --output-dir experiments/runs/extended-new

python3 tools/run_matrix.py --csrd build/csrd \
  --compiler clang=clang-18 --compiler gcc=gcc --objdump llvm-objdump-18 \
  --profdata llvm-profdata-18 --tier holdout --seeds 42 7 \
  --selection experiments/runs/core-new/matrix.json \
  --output-dir experiments/runs/heldout-new
```

Homebrew equivalents are `/opt/homebrew/opt/llvm/bin/clang`, `gcc-16` and LLVM's
`llvm-objdump`/`llvm-profdata` paths. Output directories must be new.
Repeatable `--case` and `--profile` filters select declared subsets and are
recorded. A filtered run does not claim coverage of the full matrix.
`--strategies` defaults to identity/affine/planned; XOR is also implemented.
Identity controls are mandatory. Non-identity strategies use every `--seeds`
value; identity uses one control per algorithm.
The planner retains its default 50% encoded-operation requirement. Coverage is
not matched across strategies in this matrix, so these runs do not isolate the
effect of coverage or establish that the planner is globally optimal.

`--inputs` adds random vectors to edge cases. Timings use `--iterations`
(default 200000) and `--repetitions` (default 5, minimum 3). Exploratory budgets
are `--max-runtime-ratio` 2 and `--max-size-ratio` 1.5.
Exit 1 means failure; exit 0 means completed, potentially with explicit gaps.
`--require-selected-profiles` makes missing selected profiles nonzero too.
Invalid CLI/output-directory use returns 2. Partial evidence is preserved.

## 1. Candidate selection using compiled results

Each case includes original, identity, affine/planned variants and declared
algorithm candidates with their own unencoded identity controls. The transformer
validates actual emitted C. Per compiler/profile, the runner verifies the source
pair, preprocesses using real flags, validates both frozen functions against
their source models, builds separate function/harness objects and links them.
Runtime harness inputs prevent constant-input elimination of the entire task.
LTO can inline the function; no noinline/volatile barrier is inserted.

PGO trains on declared inputs and validates training and profile-use
preprocessing independently. A stable compiled-input path satisfies GCC's
profile-location checks. Training/merge artifacts are retained.
Paired discovery and held-out vectors, including a declared rare-difference
challenge, execute the linked binaries. Any behavioral mismatch fails the cell.

Selection accepts completed development cells only. Every required profile must
show a mnemonic-sequence difference from the original; encoded candidates must
also differ from their algorithm's identity control. Measured costs must fit
the budgets in every required profile. The smallest worst observed paired
runtime ratio chooses among eligible candidates, with identifier tie-breaking.
Timings are noisy, so selection is not guaranteed identical across experiments.

Rejected candidates/reasons remain in `matrix.json`. Selected C and its hash
are exported to `selected/<case>.c`. Empty selection is a valid negative result.
This is an external experiment driver: the C++ planner still uses its documented
source-level cost model. The rule screens candidates for investigation, not
protection strength. Mnemonic changes may be trivial; meaningful operand-only
changes may be conservatively missed.

## 2. Instructions and data dependencies

Linked disassembly retains operands/addresses. Comparison excludes nop/nopl/nopw
padding and uses mnemonic
sequences in `main` and the surviving named function; `main` is still measured
if LTO removes that separate function. Other helpers/runtime functions are
outside this structural metric. Whole binary size/hash are also recorded.

Clang non-PGO cells retain pre-link optimized LLVM IR and a normalized SSA body
preserving operand/label relationships while renaming temporary values. This
textual structural metric is not a complete LLVM parser, graph-isomorphism
test, semantic proof, or post-LTO data-flow model. GCC IR and Clang PGO IR are
explicitly unmeasured by this first adapter.

## 3. Costs and independent reconstruction

Timings interleave originals/variants in seeded shuffled order. Each repetition
checks output checksums under the same runtime input seed. Reports retain all
samples, paired ratios, median/range, binary sizes and build command durations.
Selection uses the worst observed paired ratio. Timings include input generation
and are shared-host observations, not isolated latency or statistical evidence
of speed improvement. Repeat on controlled deployment hardware before making
performance claims. Sanitized costs are separate profile measurements.

The fixed black-box observer receives only executable access and arity. Basis
queries fit an unsigned affine function; a small predeclared library tests
low-byte population count, XOR and unsigned minimum. It never reads seeds,
encoded source, compiler metrics or truth labels. Frozen models are scored on
separate inputs. Reports preserve query counts, elapsed time, successful recovery
and false models. This measures one automated method, not human effort or
arbitrary decompiler resistance. Finite matches are not universal proofs.

Fingerprint confusion matrices use family labels only after classification.
The rare-difference control exposes finite-sampling false matches. Its explicit
challenge is not a random discovery or evidence that arbitrary rare differences
will be found.

## 4. Runtime observation and recovery

```sh
python3 tools/observe_runtime.py \
  --matrix-report experiments/runs/core-new/matrix.json \
  --case calculate --profile clang-O2 \
  --variant original --variant affine-42 \
  --output-dir experiments/runs/observation-new
```

GDB runs only binaries matching completed matrix artifact hashes. The adapter
supports little-endian AArch64/x86-64, ordinary non-LTO builds and two-argument
functions. It samples at each instruction from entry to return or step limit:
low 32 bits of general registers and 64 bytes at SP. SIMD, heap, all memory,
other threads and paths outside eight chosen executions are not covered.
No debugger interference or modifications to the tested C are introduced.

The task is recovering `x+y mod 2^32`. Four labeled training traces fit
invertible maps `observed=a*target+b` at matching instruction-offset/visit/
register-or-stack locations. The learner receives neither seed nor encoding
parameters. Four separate traces score recovery, false models and absent
locations; permuted training labels are the negative control. This is a
controlled known-intermediate task, not extraction of an unknown algorithm.
Its target may be recoverable directly from inputs or return values.

Literal-presence counts are separate. Incidental equal values/caller stack
residue do not prove a source variable was stored there; absence does not prove
secrecy. Step limits and debugger failures are not successful protection.
The observer uses [GDB's memory API](https://sourceware.org/gdb/current/onlinedocs/gdb.html/Inferiors-In-Python.html).

Build [the validation image](../experiments/Dockerfile.validation) and mount
the checkout at `/work`. Docker tracing may need container-local
`--cap-add=SYS_PTRACE --security-opt seccomp=unconfined` for the child process.
Missing GDB returns `unavailable`/exit 2; incomplete traces fail. No system-wide
debugger configuration needs changing.

## Reproducibility

Keep implementation/matrix hashes, tool versions, frozen inputs, proof reports,
profiles, binaries, disassembly, samples and traces. Never overwrite earlier
experiments. Journal significant protocol changes and negative findings.
New adapters must declare observation models, capability probes, controls and
failure states before their measurements participate in candidate selection.
