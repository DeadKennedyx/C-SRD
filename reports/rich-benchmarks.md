# Rich corpus validation, 2026-11-09

Eight contracts and five alternate/control implementations passed the corpus
protocol on native macOS ARM64 and an Ubuntu ARM64 container. This validates a
benchmark foundation; it does not establish protection or reconstruction cost.

| Environment | Compilers | Builds executed | Matching oracle comparisons on equivalent implementations |
| --- | --- | ---: | ---: |
| macOS ARM64 | Clang 23.1.5, GCC 16.2.0 | 78 | 165,180 |
| Ubuntu ARM64 | Clang 18.1.3, GCC 13.3.0 | 78 | 165,180 |

Each implementation ran at O0, O2 and O1 with ASan/UBSan under both compilers.
The same deterministic vectors were reused across configurations; these are not
330,360 unique randomly sampled inputs. No sanitizer or warning failures occurred.
Each environment also proved the three equivalence controls under the source
model and produced counterexamples for both incorrect controls. All compiled
negative controls disagreed at their declared witness.

Per environment the fingerprint comparisons produced 18 true positives, 222
true negatives and 12 false positives, with no false negatives. The 12 false
matches came from the deliberately rare RGB mutation compared with each correct
RGB form across six builds. Proof and witness checks rejected it. These designed
controls illustrate sampling failure; their frequency is not a real-world false
positive rate estimate.

The initial native pilot failed: the RGB shift/add equivalence obligation timed
out at 30 seconds. Its report is retained. A general unsigned-left-shift to
power-of-two multiplication normalization allowed the polynomial simplifier to
prove the equivalence. Separate SMT obligations check every legal shift count
0..31 for every 32-bit operand; integration tests cover wraparound and a wrong
multiplier. This improves proof coverage without weakening the admitted semantics.

Commands (all output directories are new):

```sh
cmake --build build --parallel 2
python3 tools/validate_benchmarks.py --csrd build/csrd \
  --compiler clang=/opt/homebrew/opt/llvm/bin/clang --compiler gcc=gcc-16 \
  --sanitizers --output-dir experiments/runs/rich-native-validation-20261109

# In csrd-dev:ghidra, mounting this checkout as /work:
cmake --build build-linux-release --parallel 2
python3 tools/validate_benchmarks.py --csrd build-linux-release/csrd \
  --compiler clang=clang-18 --compiler gcc=gcc --sanitizers \
  --output-dir experiments/runs/rich-linux-validation-20261109
```

[Raw evidence](rich-evidence-20261109/sha256.json) contains complete per-environment
archives (including executables and command output), the failed pilot, summary
JSON and the validator as it existed during measurement. Subsequent hardening
added tool-mutation checks and rejection of reused output directories; the corpus
contracts and oracle data did not change. All 15 CTest groups passed on
[macOS](rich-evidence-20261109/native-ctest.log) and
[Linux](rich-evidence-20261109/linux-ctest.log), including faulty-original and
false-witness tests. The compiler catalog has 26 declared profiles, but
this corpus-contract validation used only the six configurations listed above.
Reserved families received correctness checks only. Cross-architecture results,
human effort, live multi-location reconstruction, novelty and a successful
protection candidate remain unestablished by this experiment.
