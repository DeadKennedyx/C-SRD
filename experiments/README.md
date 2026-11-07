# Experiment protocol

Reserve `experiments/runs/` for local raw artifacts (gitignored). Check selected
results into `reports/` only with the command, source/configuration hash,
compiler/tool versions, seed set, input population and interpretation limits.
The differential runner can write JSON via `--report` and prints every tested
compiler/configuration; it fails on a mismatch or missing required compiler.

Current reports concern M1 correctness and arithmetic obligations. No runtime
overhead, binary diversity, algorithmic diversity or recognition accuracy has
been measured. Future performance runs must compile and time original/variant
separately under identical conditions and report repetitions and uncertainty.
Future recognition runs need independent positive/negative controls and held-out
inputs with false-match and missed-equivalence counts.
