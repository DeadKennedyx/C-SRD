# Algorithm and encoding survival at O2 — 2026-11-09

Status: exploratory experiment completed; next engineering work proposed.
Stage: analysis and solution search. This entry was written after the runs;
it is not a preregistered experiment or a new transformation implementation.

## Thinking, doing and questions

The owner asked what to improve after the affine `calculate` example became
identical to its original at O2. I want to determine whether that observation
also holds for the existing algorithm candidates before recommending a larger
implementation. I ran the current serial and SWAR population-count candidates
with identity and planned representations. The question is whether compiled
differences come from the algorithm, the encoding, or both. The discovery is
that the answer depends on the candidate and compiler; details follow below.

The earlier [audit](2026-11-09-protection-audit.md) is the motivating negative
result. LLVM documents algebraic simplification in
[InstCombine](https://llvm.org/docs/Passes.html#instcombine-combine-redundant-instructions).
This is background, not evidence identifying the exact pass responsible here;
we have not traced the optimization pipeline.

## Protocol and alternatives

Use the existing [popcount8](../../benchmarks/algorithms/popcount8.c) function,
which counts set bits in the low byte and ignores higher input bits. Generate
four candidates: serial or SWAR, each with identity or planned representation,
seed 42, default balanced objective and 50% planned encoded coverage. Serial
expresses individual bit contributions; SWAR combines small groups of bits
with masks and shifts. Both are existing algorithms, not novelty claims.

Audit every candidate against the original using O2 with Clang and actual GNU
GCC in macOS and Linux. Compare identity and planned candidates of the *same*
algorithm as an additional control: a difference from the original alone
cannot establish that the encoding contributed anything. Compare only matched
compiler binaries and flags. All runs use the same arm64 host; compiler version
and OS differ together, so these are four configurations, not four independent
replications or a causal estimate of OS effects.

The existing transform validates emitted C. The audit also verifies the source
pair and both compiler-preprocessed functions under the pure-u32 model before
compiling frozen inputs. It measures code-section hashes, sizes and instruction
histograms. It does not execute these functions. No new differential execution,
performance benchmark, independent reconstruction or dynamic trace was run.

## Results

The [summary and artifact hashes](../../reports/algorithm-survival-20261109/summary.json)
link eight full audit reports, four generated candidates and transformation
reports, generation commands, and disassembly/relocation dumps. All 16 paired
compiler comparisons completed; all source and build-specific equivalence
obligations passed under the model. The raw object/preprocessed files remain in
the ignored experiment directory and can be regenerated with the protocol below.
The archived reports contain their hashes and exact commands; they are not a
machine-code correctness proof.

Code-section sizes in bytes:

| O2 configuration | Original loop | Serial identity | Serial planned | SWAR identity | SWAR planned |
| --- | ---: | ---: | ---: | ---: | ---: |
| macOS Clang 23.1.5 | 56 | 56 | 120 | 40 | 40 |
| macOS GCC 16.2.0 | 64 | 64 | 160 | 44 | 160 |
| Linux Clang 18.1.3 | 68 | 68 | 120 | 44 | 44 |
| Linux GCC 13.3.0 | 40 | 64 | 164 | 44 | 168 |

Equal sizes alone do not imply equal bytes. The relevant hash comparisons are:

* Serial identity matched the original's code-section bytes only on macOS
  Clang. On Linux Clang it differed despite matching size and instruction
  histogram, illustrating why byte difference is a weak metric.
* Serial planned differed from serial identity in all four configurations.
  Their instruction histograms also differed. Inspection of the macOS Clang
  disassembly shows extra conditional selects and arithmetic, rather than
  only padding changes. Whether these make recovery harder remains untested.
* SWAR identity differed from the original in all four configurations.
* SWAR planned produced exactly the same code-section bytes as SWAR identity
  on both Clang configurations. The two GCC configurations retained a difference.
  Thus comparing only against the original would misattribute the Clang SWAR
  difference to encoding when the unencoded algorithm gives the same code.

These are candidate-specific observations. One selected function, one seed and
one optimization setting do not establish a general survival rate. Larger code
does not establish greater reconstruction difficulty. The smaller SWAR code
does not establish faster execution. Padding, relocations and other data
sections limit code-section comparisons; linking and LTO were not tested.

## Decision and next task

Keep O2 as an experimental requirement and extend to actual release settings.
The next increment should make candidate selection aware of compiled results:

1. Preserve the original, the unencoded form of each algorithm, and its encoded
   form as three separate controls. Retain negative results.
2. Add optimized-IR and instruction/data-flow comparisons to distinguish
   algebraic collapse, register/layout changes and remaining computations.
3. Evaluate a declared small matrix of strategies and seeds on several benign
   functions. A seed is a reproducibility input, not a protection score.
4. Require correctness, measured compiled differences and a stated runtime/size
   budget before taking a candidate into an independently scored reconstruction
   study. Use held-out functions for subsequent validation.

Only then evaluate whether reconstruction actually takes more effort. Runtime
observation must separately define which intermediate values an observer must
recover from inputs, instructions, registers and memory. Surviving instructions
do not prove that ordinary values are absent or hard to infer.

This motivates PROT-04 in [the backlog](../backlog.md). The current planner
optimizes source-level proxy costs; this experiment does not change its behavior.
Neither turning optimization off nor adding complexity by itself supplies the
missing evidence. No universal optimizer-resistant transformation is claimed.

## Reproduction

Implementation baseline: `c73f0a2535692313c67befc591ce9a6ee1f42d73`.
Build the existing native and Linux Release binaries first, as documented in
[the audit validation record](../../reports/protection-audit-validation.md).
Use a new directory for every rerun; existing audit directories are rejected.

```sh
set -eu
experiment_dir=experiments/runs/algorithm-survival-repeat
mkdir "$experiment_dir"
for algorithm in popcount8-serial popcount8-swar; do
  for strategy in identity planned; do
    candidate_dir="$experiment_dir/$algorithm-$strategy"
    mkdir "$candidate_dir"
    build/csrd transform benchmarks/algorithms/popcount8.c \
      -o "$candidate_dir/candidate.c" --algorithm "$algorithm" \
      --strategy "$strategy" --seed 42 --report "$candidate_dir/transformation.json"
    python3 tools/audit_protection.py benchmarks/algorithms/popcount8.c \
      "$candidate_dir/candidate.c" --csrd build/csrd \
      --compiler /opt/homebrew/opt/llvm/bin/clang --compiler gcc-16 \
      --objdump /opt/homebrew/opt/llvm/bin/llvm-objdump \
      --optimization O2 --output-dir "$candidate_dir/macos"
    docker run --rm -v "$PWD:/work" csrd-dev:roadmap \
      python3 tools/audit_protection.py benchmarks/algorithms/popcount8.c \
      "$candidate_dir/candidate.c" --csrd build-linux-release/csrd \
      --compiler clang-18 --compiler gcc --objdump llvm-objdump-18 \
      --optimization O2 --output-dir "$candidate_dir/linux"
  done
done
```

The local Docker image used was
`sha256:2d50bbf53b37ce1dba6ebf4d3cf540850ead773387044e995adaf497a63d76e3`.
Future toolchain versions may legitimately produce different code. Audit the
actual deployed compiler/target/flags before making claims about a release.
