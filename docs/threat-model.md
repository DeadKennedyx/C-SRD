# Software-protection and correctness model

C-SRD is a semantics-preserving diversification experiment for benign C
programs, with the goal of measuring resistance to implementation reconstruction.
The protected asset is proprietary implementation detail, not a stored password
or cryptographic key. The current release has no demonstrated confidentiality
or resistance guarantee. Its principal correctness threat is compiler
unsoundness: accepting an
expression with the wrong width, changing an effect, mishandling a macro,
introducing a collision, or misreporting limited evidence as a proof.

The current controls are conservative AST acceptance, unsigned type checks,
whole-function rejection, explicit def/use initialization checks, no new
identifier collisions, source-location diagnostics, deterministic parameters, independent
compiler runs, sanitizer runs and separately stated arithmetic obligations.
These controls reduce risk; they do not establish a verified compiler.

The defensive analyst may inspect source, constants, generated binaries and
execution traces, select inputs, and apply compiler simplification or symbolic
reasoning. Affine parameters are deliberately recorded in the manifest. They
are recoverable and are not keys protecting confidentiality. Reduction of
conversion count is an efficiency/representation metric, not secrecy evidence.

Distinguish three observer models:

* A static observer can inspect the distributed binary, constants and disassembly.
  Code-section comparison is an initial observation, not an estimate of effort.
* A dynamic observer can choose inputs and inspect execution, registers and memory.
  The current implementation does not measure ordinary-value residence, inhibit
  observation or claim that encodings remain unrecoverable.
* An observer controlling the process or machine can inspect conversion routines
  and modify execution. C-SRD supplies no separate trust boundary that protects
  secrets from this observer.

Any future effort study must state the observer's knowledge, tools, time budget,
success criterion and negative controls. Report unsuccessful transformations and
timeouts, not just favorable examples. The [protection contract](protection.md)
defines the initial compiled-code audit and subsequent evidence requirements.

Future functional recognition should use independently selected fingerprints,
multiple equivalent implementations and unrelated functions. False positives
and false negatives must both be measured. Matching fingerprints do not prove
equivalence; divergent traces can provide concrete counterexamples.

Out of scope: antivirus/EDR evasion, anti-debugging, malicious payloads, stealth
loaders, credential hiding and cryptographic security claims. No security-product
output is an optimization objective. Timing/side-channel equivalence is also
outside the current functional contract.

The compiler tool is a development prototype, not a hardened service for
hostile uploads. Clang can read included files and uses local toolchain assets.
Run any future untrusted-source service in an appropriately isolated environment
with resource limits; this repository does not implement that service.
