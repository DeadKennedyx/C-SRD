# Software-protection contract

## Problem and objective

Automate semantics-preserving diversification of legitimate C software and
measure whether the resulting implementation requires more effort to
reconstruct. This continues C-SRD; the owner's AES project was a motivating
example and is not a development target. The objective was clarified on
2026-11-09 to exclude AV and security-detection evasion explicitly.

The assets are implementation details. Encoding is not encryption, and neither
large seeds nor unreadable source establish secrecy. A debugger can observe the
program's computations and conversions. The current prototype does not prevent
debugging or provide an isolated execution environment.

## Separate claims and acceptance evidence

| Claim | Required evidence | Current status |
| --- | --- | --- |
| Defined behavior preserved | Explicit semantic contract, emitted-C validation, compiled differential tests | Implemented for the bounded pure-u32 subset |
| Source representation changed | Source hashes and AST-aware measurements | Implemented |
| Compiled representation differs | Paired compiler/flags, raw objects, extracted code-section hashes and disassembly | Initial audit below; byte difference alone is insufficient |
| Reconstruction requires more effort | Prespecified observer/tools/budget, correctness-scored reconstruction tasks, controls, held-out corpus | Not assessed |
| Ordinary intermediate values have less exposure | A precise observation model and measurements of optimized execution, including conversion boundaries | Not assessed |
| Secrets remain inaccessible to a controlling debugger | A separate security model and justified trust boundary | Not provided |

Different instruction bytes can reflect padding or layout changes. Equal raw
code-section bytes do not prove whole-program equivalence: relocations, other
sections and linking can matter. A source-level count of encoded operations
does not establish what registers or memory contain after optimization.

## Initial compiled-code audit

`tools/audit_protection.py` compares an original and a candidate file, each
containing one admitted pure function with the same name and parameter count.
There is no special function name or fixed arity. It uses Clang through C-SRD
for analysis, reparses and verifies the candidate, then preprocesses both files
with identical flags for every selected compiler and optimization setting.
Each preprocessed function is validated against its original source model before
the frozen `.i` input is compiled. Conditional compilation can depend on the
compiler or optimization level; matching flags alone does not close that gap.
It never executes the compiled programs or queries security products.

```sh
build/csrd transform benchmarks/arithmetic/calculate.c -o build/calculate.c \
  --seed 42 --report build/calculate.json
python3 tools/audit_protection.py benchmarks/arithmetic/calculate.c build/calculate.c \
  --csrd build/csrd --compiler clang --compiler gcc \
  --objdump llvm-objdump --output-dir experiments/runs/calculate-audit
```

Use actual GNU GCC, rather than an OS-provided alias, when comparing compiler
families. On Homebrew, paths such as `/opt/homebrew/opt/llvm/bin/clang`, `gcc-16`
and `/opt/homebrew/opt/llvm/bin/llvm-objdump` identify the installed tools.

`--compiler` may be repeated. `--optimization O0|O1|O2|O3|Os` may be repeated;
the default is O0 and O2. `--timeout-ms` sets the source verifier budget, default
10000. The output directory must be new. Existing inputs/directories are never
overwritten. A failed validation or compilation leaves a failed report, rather
than a successful protection assessment. Exit 0 means the audit completed,
including observations of identical bytes; exit 1 means an incomplete/failed
audit, and exit 2 indicates invalid CLI arguments or an unavailable output path.

The directory preserves analysis/verification JSON, preprocessed `.i` files,
build-specific proof results, object files, disassembly, relocation dumps and
command results. `audit.json` records source/object/tool hashes, tool versions,
compiler target strings, exact flags and elapsed command times.
The comparison is the `.text` or `__text` object section, including padding;
relocations are not applied. Instruction histograms are descriptive only.
Memory exposure and reconstruction effort remain explicitly `not-assessed`.

Both files must use compatible target and header environments. Compilation
uses host toolchains with fixed C11 flags and a separately compiled integer-model
guard; cross-compilation, custom build
flags, linking, LTO and whole-application audits are not implemented. Input and
header snapshots are checked against the verification evidence. Objects are
measurements of the selected builds, not a machine-code equivalence proof.

## Subsequent work

The next experiments should establish matched encoded coverage and actual
compiled costs, followed by independently scored functionality reconstruction.
Dynamic observation needs its own protocol: define the observer's access to
inputs, instructions, registers and memory; define which intermediate values
or computation the observer must reconstruct; score correct recovery and effort
against the original under matched conditions. Do not equate absence of a
literal byte pattern with inability to infer a value. No debugger interference
or claim of preventing observation is part of that experiment.
Broader C support requires contracts for memory modifications and calls before
rewriting those regions. The ability to parse a larger application must not be
reported as protection of every function in that application.

No objective rewards failed antivirus/rule detections, debugger interference,
stealth loading or malicious behavior. Source and binary artifacts remain
available to the evaluator, and negative findings remain part of the record.
