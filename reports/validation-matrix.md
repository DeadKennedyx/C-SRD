# Linked validation matrix and recovery results — 2026-11-09

Implementation: `b642282286aa`. [Protocol](../docs/validation-matrix.md),
[source hashes](matrix-source-snapshot.json), [journal](../docs/journal/2026-11-09-validation-matrix.md).
These are observations on a small pure-u32 corpus, not protection guarantees.

## Delivered components

* `tools/run_matrix.py`: versioned profiles, capability probes, compiler-specific
  preprocessing validation, real linking/execution, LTO/ThinLTO/PGO, costs,
  source/algorithm/encoding controls, candidate screening and selected C export.
* `tools/experiment_support.py`: mnemonic comparison excluding NOP padding,
  pre-link Clang SSA relationships, paired timings, fixed black-box recovery.
* `tools/observe_runtime.py` and `tools/gdb_trace.py`: bounded debugger observation,
  affine recovery learned from labeled traces, held-out scoring and negative controls.
* Core CI plus weekly/manual extended experiments; explicit capability gaps.

## Actual checks

| Run | Scope | Completed build cells | Failed cells | Unavailable profiles |
| --- | --- | ---: | ---: | ---: |
| Final native core | macOS ARM64; Clang 23.1.5 / GCC 16.2.0 | 240 | 0 | 0 |
| Final Linux extended | Linux ARM64; Clang 18.1.3 / GCC 13.3.0 | 1,000 | 0 | 1 |
| Linux held-out | Two reserved functions; six O3/Oz/LTO profiles | 72 | 0 | 0 |
| Earlier macOS extended pilot | Before final metric/harness refinements | 1,000 | 0 | 1 |

The gap is the x86-only profile on the ARM64 machine; it was not counted as a
pass. The final three local runs performed **388,280 paired input/output
comparisons** against matched original executables (70,680 + 294,500 + 23,100).
Repeated vectors/configurations are included; these are not unique inputs or
independent algorithms. Every completed cell also passed its source-model and
build-input verification obligations. No machine-code proof is claimed.

Full suites passed **11/11 CTest groups** on native (72.08 s) and Linux (26.09 s).
The final focused suite then ran 12 tests: native 11 passed plus one explicit
missing-GDB skip (12.088 s); Linux all 12 passed (6.589 s), including live recovery
and step-limit failure. Those timings are test-run diagnostics.

[Hosted CI run 42740580787](https://github.com/DeadKennedyx/C-SRD/actions/runs/42740580787)
passed Debug and Release on `ubuntu-24.04`, including the Release core matrix and
runtime observer. [Saved job metadata](matrix-ci-b642282.json) records successful
steps. GitHub documents this label as
[x64](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
The local ARM64 gap remains explicit; CI is separate evidence, not retroactive
coverage of that local cell. Full CI artifacts are attached to that run.

## Compiled selection and reconstruction

The selector exported unencoded SWAR popcount for further investigation in both
final local development runs. Its algorithmic difference survived the required
builds and met the observed budgets; the fixed library observer still identified
its functionality. This is not an encoding-protection success.

The rare-difference negative-control case also had structurally eligible
candidates (native planned seed 7; Linux affine seed 7). Its recognition failure
was already present in the original and is not attributed to diversification.
The selector does not reward observer failures. Other cases had no eligible
candidate under all required builds/budgets. See every rejection reason in the
[summary](matrix-evidence-20261109/summary.json).

The fixed observer recovered functions on held-out inputs in 204/240 native,
850/1,000 Linux development, and 72/72 held-out cells. The remaining development
cells were all copies/configurations of the known rare-difference control.
They fitted an incorrect affine model on training inputs, rejected by the
declared held-out challenge: 36 native and 150 Linux false fitted models.
This is not a general recovery rate or a decompiler evaluation.

For each two-argument development profile, fingerprints yielded:

| Input set | True matches | True nonmatches | False matches | Missed equivalences |
| --- | ---: | ---: | ---: | ---: |
| Discovery | 96 | 108 | 72 | 0 |
| Held-out including the known rare-difference challenge | 96 | 180 | 0 | 0 |

Each row compares 276 pairs, including repeated variants from the same family.
The false matches mean unrelated functions agreed on the sampled inputs.
The explicit challenge removes this known blind spot; it does not guarantee
detection of arbitrary rare differences. Unary popcount has no unrelated unary
control in this small matrix and cannot estimate unary false-match rates.

## Runtime result: encoding remained recoverable

Linux Clang traces used four labeled training executions and four different
held-out executions for each original/affine/planned calculate binary.
The target was `x+y mod 2^32`. The learner received neither seed nor encoding
parameters. It fitted invertible affine maps at instruction/register/stack
locations and checked recovered values on all four held-out traces.

| Build | Variant | Instructions per execution | Held-out-validated recovery locations |
| --- | --- | ---: | ---: |
| O0 | Original | 13 | 18 |
| O0 | Affine seed 42 | 42 | 78 |
| O0 | Planned seed 42 | 37 | 114 |
| O2 | Original | 4 | 4 |
| O2 | Affine seed 42 | 4 | 4 |
| O2 | Planned seed 42 | 4 | 4 |

All six experiments recovered the target. There were no false fitted models
on these held-out traces and no validated model with permuted training labels.
Multiple locations can be copies of the same value; the counts are not
independent secrets or measures of protection strength. At O0 the learner found
nontrivial affine mappings, despite the extra instructions. At O2 the measured
trace structure was the same across the three implementations.

This controlled known-intermediate task is deliberately limited. It does not
show that arbitrary functionality is recoverable, nor measure human difficulty.
It shows that the tested encoding did not prevent this observer from recovering
the specified intermediate. Absence of a literal value would not establish
inability to infer it.

## Reproduction

Use new output paths. Native final run:

```sh
python3 tools/run_matrix.py --csrd build/csrd \
  --compiler clang=/opt/homebrew/opt/llvm/bin/clang --compiler gcc=gcc-16 \
  --objdump /opt/homebrew/opt/llvm/bin/llvm-objdump \
  --profdata /opt/homebrew/opt/llvm/bin/llvm-profdata \
  --tier core --inputs 128 --iterations 300000 --repetitions 5 --seeds 42 7 \
  --require-selected-profiles --output-dir experiments/runs/repeat-native
```

Linux used local image `csrd-dev:validation`,
`sha256:3c0781d557e82c93835aeb39ab8b6263cae1f00c7402719c96802e904f121d60`.
It extends the earlier development image with GDB/lld. A fresh dependency recipe
is in [Dockerfile.validation](../experiments/Dockerfile.validation); package
repositories can change, so this recipe is not a bit-reproducible image lock.

```sh
docker run --rm -v "$PWD:/work" csrd-dev:validation \
  python3 tools/run_matrix.py --csrd build-linux-release/csrd \
  --compiler clang=clang-18 --compiler gcc=gcc --objdump llvm-objdump-18 \
  --profdata llvm-profdata-18 --tier extended --inputs 128 \
  --iterations 300000 --repetitions 5 --seeds 42 7 \
  --output-dir experiments/runs/repeat-linux

docker run --rm -v "$PWD:/work" csrd-dev:validation \
  python3 tools/run_matrix.py --csrd build-linux-release/csrd \
  --compiler clang=clang-18 --compiler gcc=gcc --objdump llvm-objdump-18 \
  --profdata llvm-profdata-18 --tier holdout --inputs 128 \
  --iterations 300000 --repetitions 5 --seeds 42 7 \
  --selection experiments/runs/repeat-linux/matrix.json \
  --output-dir experiments/runs/repeat-heldout

for level in O0 O2; do
  docker run --rm --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \
    -v "$PWD:/work" csrd-dev:validation python3 tools/observe_runtime.py \
    --matrix-report experiments/runs/repeat-linux/matrix.json \
    --profile "clang-$level" --variant original --variant affine-42 \
    --variant planned-42 --output-dir "experiments/runs/repeat-observer-$level"
done
```

Build/check entry points:
`cmake --build build --parallel 4`,
`ctest --test-dir build --output-on-failure`,
`python3 tests/integration/test_matrix.py build/csrd`.
The Linux equivalents use `build-linux-release` inside the image.

## Evidence and limitations

[Evidence index and hashes](matrix-evidence-20261109/summary.json) link compressed
measurement reports, generated C and final build-input proof/frozen-input archives,
and complete runtime-observer directories. Read gzip JSON with
`gzip -dc reports/matrix-evidence-20261109/native-core.json.gz`.
The Linux extended archive replaces large full-runtime disassembly command
stdout with hashes and paths; all measured function/main instructions remain
in its records. The unabridged report, binaries, complete disassembly and PGO
training artifacts remain under the ignored local experiment directories.
The index retains the unabridged report hash. CI uploads its own raw artifacts.

Some native/Linux jobs overlapped on one ARM host. Costs are interleaved paired
shared-host samples, not isolated benchmarks or significant speed improvements.
Five development functions, two known held-out functions, two seeds and a
finite profile set do not establish robustness against future compilers.
Semantic proof covers the supported source model, not the compiler, linker,
trusted harness, debugger or arbitrary machine-code execution.

No independent decompiler, human analyst study, general symbolic-execution
adapter, post-LTO data-flow model, Windows/MSVC adapter or exhaustive memory
observer is implemented. The next useful extension is an independent decompiler
or symbolic-reconstruction task with a prespecified success criterion and
budget, evaluated on a broader benign corpus. More complicated source alone
would not address the negative results above.
