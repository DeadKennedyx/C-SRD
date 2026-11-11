# Private declarations and declaration identity

## Observation and question

The first private-region prototype (`8b91925`) leaves initialized declarations
unchanged and excludes a function whenever local names shadow. It can transform
assignments around calls and loops, but cannot keep an initializer and its later
arithmetic in one encoded region. Does extending the scalar frame preserve all
outputs, enclosing scope and outside reference bindings while reducing these
artificial boundaries?

## Design and assumptions

The prototype uses declaration IDs instead of identifier spellings. It admits
single initialized, unqualified automatic/register uint32 declarations together
with assignments. Address-taken objects remain excluded throughout a function.
All ordinary outputs are restored before the next effect. Original declarations
are emitted in their original compound block, after encoded computation; writes
to pre-existing objects precede new declarations that could shadow their names.

The C11 basis is scope starting after a declarator and non-VLA automatic storage
lasting for the enclosing block, with initialization on execution of a
declaration ([WG14 N1570, 6.2.1 and 6.2.4](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf)).
Our inference is limited to pure finite regions of nonescaping scalars with
defined original execution. It does not justify moving effects or VLA lifetimes.

Wrapping every region in a new block is unsuitable: an original declaration
would disappear from the scope of later statements. Unchanged source bytes alone
also do not establish unchanged bindings. The candidate is reparsed, its output
declarations must occupy the same enclosing block, and every untouched
DeclRefExpr must still name the mapped original declaration. A deliberately
wrapped candidate that redirects a local reference to a global is a negative
control for both checks.

## Experiment protocol

- Prove every actual emitted frame against all scalar outputs, including two
  different objects with the same name; retain the existing uint32 SMT model.
- Exercise consecutive declarations, register storage, nested shadowing,
  multiple regions/functions, overwritten uninitialized objects, self-init
  exclusion, escapes, macros and compiler warnings.
- Compile and compare returns, full caller memory and ordered callback events
  with GCC/Clang at O0/O2/O3/Os and Clang ASan/UBSan on both available hosts.
- Run the matched original/identity/affine/copy linked workload, including LTO,
  with recorded resources and byte/opcode metrics. These do not replace a
  reconstruction or runtime-value observer for arbitrary calls/loops.

## Development observations

The first build exposed two unit-test call sites still treating the frame as
const after emission began recording exported declaration positions. Updating
the test fixture to the new API resolved that compile failure. The initial
frame, nested-shadowing, scope-redirection and self-initialization unit controls
then passed. Remaining validation and measurements are recorded below only
after execution.

The first strict compiled matrix failed for all 36 new-fixture cells: `local`
and `mix` were unused in generated C after their internal reads moved to
encoded temporaries. The original assignment fixture still passed its 36 cells.
The failed emitted C, transformation report and compiler diagnostics are kept
under `experiments/runs/private-declarations-development-20261110/initial*`
and `candidate-initial.c`, with the complete failed test log. We retained all
scalar outputs and added a discarded read only for initialized exported scalars;
the independent reader rejects discarded calls and other expressions. This
fix avoids weakening warning flags or silently deleting original declarations.

The subsequent native integration matrix passed both fixtures, including the
new nested-shadowing/event workload. The declaration fixture contains six
regions, seven admitted declarations, sixteen encoded arithmetic operations and
twenty-six conservative entry/exit conversions. Those counts are coverage,
not evidence of protection. Dead exported outputs are a possible future
conversion reduction, requiring separate liveness reasoning and validation.

## Regression outcome

Both hosts passed 31/31 CTest groups (native 409.53 s; Linux 224.63 s).
The two private fixtures together cover 144 compiler/profile/variant cells and
443,232 return/full-memory/ordered-event comparisons across hosts, counting each
deterministic matrix once. Optional tool-specific skips remain in the raw logs.
A final reporting-only addition made ordered input/output declaration IDs
explicit; three focused report/scope checks then passed per host. The code
transformer and validator were unchanged by that addition.

The native matched-cost pilot completed 40 variants and 280 executions; its
artifact checker bound 120 frame obligations and all raw resource records.
The affine/original median workload ratio ranged from 0.997 to 2.774 across ten
profiles, while identical-copy medians ranged from 0.973 to 1.005. All matched
output checksums agreed. This is no speedup or protection claim: compiler
differences remain, and reconstruction/value-recovery for the call/loop
workload is still unmeasured. The full two-host report follows separately.

Linux also completed 40 variants and 280 executions, with all checksums and its
120-obligation artifact check passing. Its affine workload ratios span
0.966–2.731 and copy-control medians 0.987–1.010. The two hosts therefore add
80 linked variants and 560 measured executions. All twenty affine profile
cases retain text/opcode differences. Some costs are substantial; no measured
protection advantage offsets them at this stage. The
[result report](../../reports/private-declarations.md) retains the complete
profile table and separate observer gaps. Broader integer semantics are next
coverage work; call/loop observers and conversion reduction remain explicit
followups rather than being counted as finished.

The frozen declaration evidence archive validated 2,545 files and retains both
transformer binaries, implementation sources and failed/successful generated C.
Existing version 0.6.0 archives were not regenerated or overwritten.
