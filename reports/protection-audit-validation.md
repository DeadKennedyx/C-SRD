# Compiled-code audit validation — 2026-11-09

This increment adds a paired object-code audit and clarifies C-SRD's legitimate
software-protection objective. It adds no new transformation, C language coverage,
debugger interference or security-product integration. The source state is
identified by [file hashes](protection-audit-source-snapshot.json); the listed
experiment base is a reference point, not a claim that new files existed there.
The publication parent also includes a preserved remote README-only edit; the
tested implementation hashes remain unchanged.

## Actual results

The original [calculate function](../benchmarks/arithmetic/calculate.c) and the
existing [seed-42 affine candidate](calculate-v05-seed42.c) passed source-model
equivalence validation. Every compiler/optimization-specific preprocessed
function also passed validation against its corresponding source model before
compilation of the frozen `.i` input.

| Environment/compiler | Optimization | Original code-section bytes | Candidate code-section bytes | Exact code-section byte match |
| --- | --- | ---: | ---: | --- |
| macOS / Clang 23.1.5 | O0 | 52 | 192 | No |
| macOS / Clang 23.1.5 | O2 | 16 | 16 | Yes |
| macOS / GCC 16.2.0 | O0 | 56 | 200 | No |
| macOS / GCC 16.2.0 | O2 | 16 | 16 | Yes |
| Linux / Clang 18.1.3 | O0 | 52 | 168 | No |
| Linux / Clang 18.1.3 | O2 | 16 | 16 | Yes |
| Linux / GCC 13.3.0 | O0 | 56 | 200 | No |
| Linux / GCC 13.3.0 | O2 | 16 | 16 | Yes |

Raw evidence: [macOS](protection-audit-macos.json),
[Linux](protection-audit-linux.json). These JSON files include commands, tool and
input hashes, proof obligations/results, extracted section hashes, disassembly
output and relocation dumps. Full generated artifacts remain in the ignored
`experiments/runs/protection-audit-20261109-{macos,linux}/` directories. Reproduction
uses new directories and regenerates those artifacts.

At O2, this example exhibits no measured code-section difference under any of
the four compiler/environment pairs. The source encoding therefore cannot be
credited with code-section diversity in these builds. At O0, different bytes
and larger sections do not establish greater reconstruction difficulty.
Memory exposure, execution-trace inference and reconstruction effort were not
measured. No performance or protection-strength claim follows from this audit.

Both OS environments used the same arm64 Apple M5 host. These are eight builds
of one source pair, not eight independent programs or cross-architecture evidence.
Objects include padding; relocations are not applied and other sections/linking
are outside the comparison. Source-model proofs do not prove the compilers or
the final machine code correct.

## Automated checks

The new `protection_audit` CTest group contains 11 focused tests. They cover
identity controls at O0/O2; a real generated candidate; artifact/hash binding;
a semantic mutation with counterexample; unsupported/extra functions; preserving
existing evidence; real warning-induced compiler failure; arbitrary function name
and unary interface; changed snapshots; optimization-dependent preprocessing;
empty emitted code; and mismatched local-header environments. Some tests have
multiple cases. No test requires an optimizer to erase or preserve the encoding.

| Run | Result | Observed wall time |
| --- | --- | --- |
| Native focused suite, actual Apple Clang and GNU GCC | 11 tests passed | 6.117 s |
| Full native CTest suite, both compiler families required | 10/10 groups passed | 62.17 s |
| Full Linux Release CTest suite, Clang 18 and GCC required | 10/10 groups passed | 12.13 s |

Logs: [native](protection-audit-native-ctest.log),
[Linux](protection-audit-linux-ctest.log). Trailing whitespace in the Linux
configure log is normalized for repository formatting. The full suites include the existing
compiled differential and selected sanitizer tests. Validation jobs and audits
overlapped on the host; elapsed times are diagnostic observations, not performance
benchmarks. This record does not claim a hosted CI outcome.

## Reproduction

Build with the existing [dependency instructions](../docs/getting-started.md).
The existing Docker image used here is identified in the source snapshot.

```sh
cmake --build build --parallel 4
CSRD_REQUIRE_BOTH_COMPILERS=1 ctest --test-dir build --output-on-failure
python3 tools/audit_protection.py benchmarks/arithmetic/calculate.c reports/calculate-v05-seed42.c \
  --csrd build/csrd --compiler /opt/homebrew/opt/llvm/bin/clang --compiler gcc-16 \
  --objdump /opt/homebrew/opt/llvm/bin/llvm-objdump \
  --output-dir experiments/runs/reproduce-protection-macos
```

```sh
docker run --rm -v "$PWD:/work" csrd-dev:roadmap sh -c \
  'cmake -S . -B build-linux-release -G Ninja -DCMAKE_PREFIX_PATH=/usr/lib/llvm-18 -DCMAKE_BUILD_TYPE=Release && cmake --build build-linux-release --parallel 4 && CSRD_TEST_COMPILERS=clang-18:gcc CSRD_REQUIRE_BOTH_COMPILERS=1 ctest --test-dir build-linux-release --output-on-failure'
docker run --rm -v "$PWD:/work" csrd-dev:roadmap python3 tools/audit_protection.py \
  benchmarks/arithmetic/calculate.c reports/calculate-v05-seed42.c \
  --csrd build-linux-release/csrd --compiler clang-18 --compiler gcc \
  --objdump llvm-objdump-18 --output-dir experiments/runs/reproduce-protection-linux
```

## Interpretation and next experiment

The negative finding supports auditing compiled artifacts before attributing
protection to source changes. The next protocol should define observer knowledge,
access and recovery tasks for a larger benign corpus, including runtime values
if memory analysis is studied. Source-level encoding counters and absence of
literal values in snapshots are insufficient measures of reconstruction effort.
