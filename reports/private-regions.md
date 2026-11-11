# Private-region prototype: correctness and matched application costs

Status: first assignment-region prototype validated on macOS ARM64 and Linux
ARM64. The [contract](../docs/private-regions.md) supports partial transformation
inside richer functions. It does not establish a protection advantage or close
every acceptance task in coverage increment 2.

## What the new implementation actually transforms

The two-function fixture contains pointer loads/stores, external calls, a signed
interface, an early return and an input-dependent loop. C-SRD selects three
private assignment regions containing ten arithmetic operations. In affine mode
these operations stay encoded, with eleven total entry/exit conversions. Every
written scalar is checked, and surrounding source bytes stay unchanged.

The new option is `--scope private-regions`; default whole-function behavior is
preserved. Region inputs are only values read before their first write, so a
local overwritten before its first read does not acquire an uninitialized read.
Escaped/qualified/global/static objects, shadowing, macro-containing functions
and unmodeled region expressions are conservatively excluded.

This broadens where arithmetic can be transformed. It does not transform the
networking, allocation, floating-point or concurrency behavior of an application
merely because that behavior remains elsewhere in its source.

## Actual correctness evidence

* Actual emitted blocks passed their all-input scalar-frame obligations under
  `private-u32-frame-c11-v1`. Synthetic output vectors cover every written value;
  no synthetic memory is emitted at runtime. Changed scalar outputs produced a
  counterexample even when the synthetic return stayed equal. Six controls
  rejected missing outputs, extra effects, returns and invalid initialization /
  arithmetic. These are model proofs, not whole-C or binary proofs.
* Each host passed 36 compiler/profile/variant cells and 110,808 comparisons of
  return values, all three memory words and full ordered event logs. The matrix
  used identity and affine seeds 0, 42 and UINT64_MAX; GCC/Clang O0/O2/O3/Os and
  Clang ASan/UBSan. Across hosts: **72 cells and 221,616 comparisons**, counting
  each deterministic matrix once rather than adding repeated reruns.
* macOS passed all 31 CTest groups. Linux initially passed 29/31; two new groups
  had C snippets without a final newline. Correcting those fixtures retained
  strict C11 parsing. Both failed groups and the CLI regression then passed on
  both hosts. Optional dependency-specific checks remain explicit in raw logs.

## Matched linked-build pilot

The source is preprocessed separately with each compiler/profile before
transformation. Original, identity, affine seed 42 and an identical binary copy
share their compiler flags and workload. All builds/disassembly precede timing.
Each profile has seven randomized paired repetitions of one million workload
iterations, including calls, deterministic inputs, memory updates and an event
checksum. All matched output/checksum comparisons passed.

Each host completed **40 linked build variants and 280 measured executions**
across ten profiles. Both evidence checkers validated the artifacts, unchanged
context, 60 recorded frame obligations per host, raw resource records and paired
arithmetic summaries. This checker is not a second C model or solver proof.

The table gives median paired affine/original workload wall ratios and whole
linked text-size ratios. `1.20` means 20% higher under that pilot condition.
Text includes the unchanged harness, helpers and padding; workload time is not
isolated arithmetic latency.

| Compiler/profile | macOS time / text | Linux time / text |
| --- | --- | --- |
| Clang O0 | 1.701 / 1.404 | 1.635 / 1.269 |
| GCC O0 | 1.303 / 1.411 | 1.385 / 1.313 |
| Clang O2 | 1.077 / 1.113 | 0.987 / 1.085 |
| GCC O2 | 1.016 / 1.211 | 0.955 / 1.064 |
| Clang O2 LTO | 1.258 / 1.161 | 1.263 / 1.105 |
| GCC O2 LTO | 1.200 / 1.215 | 1.200 / 1.081 |
| Clang O3 | 1.087 / 1.113 | 0.988 / 1.084 |
| GCC O3 | 0.985 / 1.211 | 0.954 / 1.064 |
| Clang Os | 1.087 / 1.115 | 0.979 / 1.085 |
| GCC Os | 1.208 / 1.254 | 1.007 / 1.061 |

Native compilers: Clang 23.1.5 / GCC 16.2.0. Linux compilers: Clang 18.1.3 /
GCC 13.3.0. The identical-copy median time ratios span 0.985–1.005 on macOS and
0.989–1.007 on Linux. Process CPU, sampled RSS, individual times, build times,
sizes and opcodes remain in the [raw evidence and summary](private-regions-evidence-20261110/summary.json).
CPU includes process startup; sampled RSS can miss peaks and is not a measure
of hidden application values. No significance or generalization claim is made.

All twenty affine compiler/profile cases had different linked text and different
selected opcode sequences, including O2/LTO. **Surviving differences do not prove
harder reconstruction.** The existing whole-function observers do not model
these calls/loops; reconstruction and runtime-value recovery remain unmeasured
for this fixture. The earlier affine buffer results establish no protection
winner and are not relabeled as evidence for this larger contract.

## Reproduction and remaining work

```sh
cmake --build build --parallel 4
CSRD_TEST_COMPILERS=/opt/homebrew/opt/llvm/bin/clang:/opt/homebrew/bin/gcc-16 \
  CSRD_REQUIRE_BOTH_COMPILERS=1 ctest --test-dir build --output-on-failure

python3 experiments/measure_private_regions.py --csrd build/csrd \
  --compiler clang=/opt/homebrew/opt/llvm/bin/clang \
  --compiler gcc=/opt/homebrew/bin/gcc-16 \
  --objdump /opt/homebrew/opt/llvm/bin/llvm-objdump \
  --output-dir experiments/runs/private-regions-cost-native-20261110

docker run --rm -v "$PWD:/work" -w /work csrd-dev:ghidra \
  python3 experiments/measure_private_regions.py --csrd build-linux-regions/csrd \
  --compiler clang=clang-18 --compiler gcc=gcc --objdump llvm-objdump-18 \
  --output-dir experiments/runs/private-regions-cost-linux-20261110
```

Use fresh output directories for new measurements. Run cost studies serially,
without concurrent builds/tests. The experiment lock protects cooperating
measurement tools, not unrelated host activity. Exact commands, seeds, tool
hashes, preprocessed inputs, emitted code, binaries, samples and initial failures
are retained. The [archive validation](private-regions-evidence-20261110/archive-validation.json)
verified **2,545 files**; source snapshots and both transformer binaries are
also frozen. Baseline repository commit before this prototype is `b4a5285`.

Next engineering work: admit initialized declarations while preserving scope
and lifetime, then expand integer typing and conversion rules. Observer support
for call/loop effects and runtime intermediate recovery is an explicit deferred
measurement task, not a successful protection result. The
[fourteen-increment sequence](../docs/coverage-increments.md) remains in progress.
