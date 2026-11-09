# Software-protection scope and compiled-code audit — 2026-11-09

## Thinking and observations

The owner clarified that C-SRD should investigate automated protection of
legitimate software by making implementation reconstruction more costly. The
AES repository was an example, not a request to extend it. AV/security-detection
evasion is explicitly excluded. The owner selected the compiled-code audit as
the next increment and asked for scientific validation, including eventual
execution/memory observations, and journals for meaningful changes rather than
every small edit.

Earlier measurements show that source diversification can disappear during
optimization. Those historical observations are in
[the v0.5 report](../../reports/roadmap-validation.md); they are not reruns from
this entry. The existing evaluation runner is tied to a two-argument `kernel`
corpus. A standalone paired audit should support any admitted function name
and arity while retaining a narrow, explicit source contract.

## Doing and intended question

Implement `tools/audit_protection.py`, reusing the existing object-section
extractor and Clang/SMT frontend. No new obfuscation transformation, language
extension, debugger interference or detection-product integration is added.

Testable question: for a validated source pair, do the selected compiler and
optimization settings produce identical measured code-section bytes?

This is a prerequisite observation, not a hypothesis that different bytes
constitute effective protection. Reconstruction effort and memory exposure
remain explicitly unmeasured. Updating the charter and threat model records the
product objective without retroactively turning correctness evidence into
protection evidence.

## Prototypes and changes in reasoning

1. The initial prototype validated the source pair and directly compiled each
   source under matching flags. Eight focused tests passed, including identical
   controls and a behavior-changing candidate. This was a working prototype,
   not the final evidence boundary.
2. Review identified a gap: preprocessing may select different function bodies
   under `__OPTIMIZE__` or compiler-specific definitions. Matching flags between
   the pair does not guarantee that either build matches the frontend's model.
   A forced include of a model-checking header could itself change preprocessing.
3. The revised implementation compiles its integer-model guard separately,
   preprocesses each source with the actual build flags, validates each resulting
   function against the source model, and compiles the frozen `.i` file. Source,
   included-buffer and preprocessed-file hashes bind those stages. An explicit
   optimization-dependent negative control verifies rejection of the gap.
4. Additional controls reject changed local-header environments and absent
   emitted code. An empty code section cannot be counted as successful equality
   or successful diversification. All command failures retain incomplete/failed
   audit evidence.

## Experimental protocol and materials

Use the unchanged `calculate` fixture and its saved seed-42 affine candidate.
Also compile an identical-source control. Use actual Clang and GNU GCC, O0/O2,
the matching host frontend and LLVM object tools. Preserve the input hashes,
tool versions/hashes, preprocessed C, proof obligations, commands, object files,
disassembly and relocation dumps. Reuse existing compilation dependencies;
no package installation or external security scan is required.

Acceptance requires rejection of semantic mutations and build-dependent changes;
identity controls must report equal nonempty code-section bytes. Do not assert
that an affine candidate must survive or disappear under any compiler version.
Compiler outcomes are observations. Run the complete CTest suite after focused
tests because the object-metric helper is shared with the existing evaluation.

## Results and interpretation

The revised focused suite passed 11 tests with native Clang and GNU GCC. It
detects the optimization-dependent counterexample, retains its proof evidence,
and blocks compilation comparison for that build. Both full suites passed
10/10 CTest groups: native 62.17 s and Linux Release 12.13 s. These jobs and the
audits overlapped, so their command timings are not performance benchmarks.

The actual `calculate` audit found different code sections at O0 and identical
16-byte sections at O2 for both Clang and GCC in both environments. All source
and per-build preprocessing equivalence obligations passed under the model.
This is a negative finding for compiled diversity of this pair at O2. Neither
the larger O0 sections nor the successful proofs establish increased resistance
to reconstruction or memory analysis. No hypothesis of improved protection was
confirmed by these runs.

The [validation record](../../reports/protection-audit-validation.md) contains
commands, exact section sizes, links to raw reports, controls and source hashes.
The two environments share one arm64 host; no wider generalization is claimed.

## Limits and handoff

Code-section bytes include padding and do not resolve relocations or incorporate
other data sections. No final linked-binary equivalence or security guarantee is
claimed. This audit does not execute the measured function or collect memory
traces. A later dynamic study must specify observer access, reconstruction
success and effort; a literal-value scan alone is insufficient. The current
compiler still supports only its documented bounded pure-u32 subset.
