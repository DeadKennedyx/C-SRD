# Per-function reconstruction costs in persistent sessions

## Observation and question before implementation

The completed wide-value study recovered every measured answer under the source
model. Whole-process CPU stayed near six seconds, while Clang nibble Jenkins
target decompilation grew from 11.624 to 52.911 ms. Startup/import work can mask
per-function changes. We have not measured human understanding or the one-time
engineering work needed to extend an observer, and will not infer either here.

Question: with the same frozen binaries, semantic adapter and grading contract,
how much CPU, wall time and resident memory does each fresh reconstruction
request consume after a decompiler session has been initialized?

## Design and constraints

Keep all 40 development cells: four functions, Clang/GCC O2, original/identity/
16-bit/8-bit/4-bit representations. Keep original files and the previous cold-
process results immutable. Do not open reserved reconstruction outcomes or tune
a new representation. No runtime/size/analysis-cost cutoff selects results.

Use three independent sessions per cell, randomized complete matched blocks.
Each session imports one unchanged binary, opens one native decompiler process,
records the first request, and excludes 32 initial requests in total. Then
measure five batches of 32 requests. Reuse the program/interface but call
`flushCache()` before every request, retaining the same simplification style,
known symbol/u32 ABI and decompilation deadline. This is repeated analysis of
one function, not a simulation of a whole application or a guarantee that JIT
and heap activity have reached steady state. Batches within a session are not
independent sessions.

Use an external Linux collector with POSIX process CPU clocks to measure JVM
and native-decompiler CPU separately at acknowledged phase boundaries. Record
clock resolution, process identity/start time, and raw endpoints. Process
replacement or lost counters invalidate that phase's CPU accounting instead of
silently becoming zero. Sample RSS outside the measured processes; record
absolute retained memory, endpoints and sampling limits. Do not label RSS
differences as allocations or debugger secrecy. The existing reaping collector
retains whole-session totals, including startup and cleanup.

Run the unchanged Python reconstruction adapter in its own persistent process,
with corresponding batches and independent CPU/RSS boundaries. Retain every
distinct exported graph and generated answer by hash, plus the complete request
membership sequence. Repeated requests must execute; deduplication concerns
stored evidence and grading, never skips analysis work. Grade all distinct
answers against frozen original C only after resource measurement. Use the
existing source-model deadline and a separate declared 30-second checked-
circuit follow-up for every unknown query, with wrong-output and arithmetic
controls. Grade time is not reconstruction time.

The session exporter must preserve the frozen graph-export logic. Check its
shared source block and compare live exports/answers with the existing exporter.
Retain a no-work phase for measurement overhead and independent CPU/sleep/memory
controls for the collector. Test process loss and malformed protocols. Pilot
before freezing the full run; record any necessary refinement explicitly.

Summarize per-request costs from batch totals and paired ratios from session
medians. Keep all three session pairs and the five within-session batches. Do
not pool 15 correlated batches into 15 independent experiments or infer broad
statistical confidence from three sessions. Report cold historical totals
separately; session residual cost includes work outside measured phases and is
not automatically all startup. Reuse application costs from the bound matrix.

Primary references consulted before implementation: Ghidra's
[DecompInterface API](https://ghidra.re/ghidra_docs/api/ghidra/app/decompiler/DecompInterface.html)
documents persistence for one program, cache flushing, and automatic process
restart. Linux's [process CPU clock API](https://man7.org/linux/man-pages/man3/clock_getcpuclockid.3.html)
supports reading another process's CPU clock. These are established mechanisms,
not a novelty claim. Pin the installed language/runtime components before the
new experiment, rather than treating a version string as a full installation
identity.

## Prototype and pilot

The first live fixture recovered the same C as the cold observer, but its final
source check also inspected the fixture's signed `main`. The verifier correctly
rejected that unrelated interface. Moving `main` to a separate link harness fixed
the test; the failed test and log remain in the development evidence. The live
session, unchanged cold export and original kernel now agree under the source
model. Independent CPU-burn, sleep, retained-memory and disappeared-process
controls passed on Linux.

An eight-cell pilot used CRC/Jenkins, both compilers and original/nibble builds,
with two initial calls and two four-call batches. Every session completed with
stable process identities, valid counters and no RSS sampling errors. All eight
reconstructed C hashes match the previously measured observer's answers. Native
CPU was zero in every empty phase. These observations validate the apparatus;
the short, insufficiently warmed pilot is not the main cost comparison. The
full protocol above remains unchanged. Before the full run, the driver was also
corrected to use the existing shared effort lock, and malformed/reordered phase
and false request-count controls were added.

A second two-cell Jenkins pilot exercised the final evidence chain. Both answers
were correct under the model: one completed source grading and one required the
declared saved-query replay. Both output mutations were refuted; the replay's
one negative and three generic controls passed. The summary validated the full
request-to-graph-to-C-to-query chain. This pilot remains excluded from the main
resource comparison. Regression validation passed all 24 CTest groups on each
host. A final focused run also checked paired-session counting and explicit
unknown outcomes (six tests; Linux all exercised, macOS three Linux/live skips).
