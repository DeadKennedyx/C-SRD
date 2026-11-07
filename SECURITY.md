# Security and correctness reports

C-SRD is an experimental compiler tool, not a confidentiality mechanism or a
production hardening system. Affine parameters are visible and recoverable.
Do not use it to store credentials or cryptographic secrets.

A transformation that changes defined behavior is a correctness defect. Report
a minimal benign input, seed, tool/Clang versions, target, command lines,
original/generated outputs, and a failing input or counterexample. Please omit
private source, credentials and unrelated data. No remote issue tracker or
private disclosure address has been configured for this local repository.

The project excludes malware-specific features, antivirus/EDR evasion,
anti-debugging and stealth loaders. Defensive experiments use functional and
structural analysis, never security-product non-detection as an objective.

Clang processes includes from the local environment. The CLI is not sandboxed
and is not intended as a hostile-source upload service. Its functional contract
does not include execution timing, side-channel behavior or output binary secrecy.
