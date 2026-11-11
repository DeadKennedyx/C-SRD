# Private scalar regions: private-u32-frame-c11-v1

This opt-in prototype transforms arithmetic assignments inside richer C11
functions. The original whole-function mode remains the default. This is partial
transformation support, not a new general verifier for surrounding C features.

```sh
csrd transform input.c -o output.c --scope private-regions --seed 42 --report decision.json
csrd analyze input.c --scope private-regions --report eligibility.json
```

Only `affine` and `identity` strategies are admitted in this scope. Algorithm
replacement and control-flow candidates are rejected. Ordinary `csrd verify`
still verifies its existing whole-function subsets; it does not accept this
scope. Private-frame validation is mandatory during transformation.

## Source and context contract

Eligible regions are contiguous plain assignment statements that are direct
children of a compound block. Targets and references must be unqualified,
automatic `unsigned int` objects (including compatible uint32 typedefs) or
parameters on the existing 32-bit-int target model. Registers are ordinary
private scalars. Supported expressions are literals, parentheses, references,
unsigned addition/subtraction and literal multiplication, with checked implicit
conversions. General multiplication, signed arithmetic, explicit casts and other
operators remain boundaries for this prototype.

Initialized declarations, loads/stores, calls, returns, conditions and loop
control are left unchanged. Regions can occur inside compound loop/branch
bodies. No evaluation crosses those statements. Every address-taken scalar is
excluded throughout its function, even if its address escapes only later.
Globals, statics, qualified/atomic variables, attributed objects and shadowed
local names are excluded. Functions with macro expansions, directives or inline
assembly are conservatively excluded, as are function attributes. Diagnostics
record unchanged statement boundaries. Regions split at 32 assignments, 16
written scalars or a cumulative arithmetic budget of 256 (a single admitted
expression remains subject to the parser/depth/solver limits).

The surrounding execution must be defined C with available automatic storage,
no asynchronous/nonlocal observation of private objects, no stack/code
introspection and no dependence on physical addresses, instruction counts or
timing. Concurrency, signals and environment-specific behavior need separate
contracts; this prototype does not certify them by leaving their syntax intact.
Inputs read by a region must be initialized on that executed path. A local
overwritten before its first read is not an input and is never newly read by
the transformation.

Preserving an ordinary call as an opaque boundary does not infer its effects or
establish a call-summary model. The contextual argument relies on its inability
to observe the private, nonescaping scalar objects during a finite region. All
written scalars have their ordinary values again before the next call, memory
access, branch or loop-control evaluation. A function containing a network call
may therefore have eligible private arithmetic without that network operation
itself being transformed or formally modeled.

## Operation and validation

1. Clang identifies private objects by declaration identity and scans compound
   blocks for eligible assignment sequences. A reference read before its first
   write becomes a region input. Every written scalar becomes an output,
   including values unrelated to the enclosing function's return.
2. The emitter captures inputs once, computes with affine temporaries, and
   decodes every output at the region exit. New identifiers avoid the raw lexer
   and preprocessor identifier sets. It preserves physical newline counts.
3. Outside-region source bytes must be exactly the original bytes. Source
   offsets and fragment hashes bind the replacement to the selected statements.
4. Clang reparses the actual emitted translation unit with the same target and
   headers. An independent frame reader accepts only its declared input/output
   objects, initialized local temporaries and supported arithmetic. Extra calls,
   memory operations, outputs, missing outputs and unknown statements fail.
5. Original and candidate frames place all outputs in a synthetic output vector.
   The existing SMT memory engine checks equality of the entire vector for every
   32-bit input. This vector is only a proof device; generated code contains no
   synthetic buffer or runtime dependency. A counterexample, timeout, unsupported
   candidate, parse error or changed environment prevents writing output.

The report labels a discharged obligation `proved-under-model` for the private
scalar frame. Contextual composition uses equal entry/exit state and unchanged
surrounding effects; it does not prove an arbitrary external function, loop
termination, C pointer provenance, the C compiler or the emitted binary.
The Clang frontend, eligibility analysis and model implementation are trusted.
Finite differential event tests are additional empirical evidence.

## Measurements and next prototype

The [first validation and cost report](../reports/private-regions.md) records
the completed two-host tests and matched application pilot, including failures.

Report region count, transformed operations and entry/exit conversions separately
from untouched statements and function acceptance. Compiler byte differences are
not protection. The current whole-function reconstruction observers do not
model arbitrary calls/loops; an unsupported observation is a measurement gap.
Reconstruction cost, application cost and runtime visibility need appropriate
matched artifacts before closing this increment's protection evaluation.

The next prototype can extend initialized declarations and lifetime-preserving
scope handling, or stronger effect summaries, after the current frame and event
tests hold. The [fourteen increments](coverage-increments.md) retain separate
milestones for transforming memory, direct calls, loops and external I/O.
