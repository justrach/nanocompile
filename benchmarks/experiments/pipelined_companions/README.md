# Frozen guarded-companion trial

`runtime.patch` is relative to public commit `553b3c9d72c7b0a01b161298427e44cd0a37f3b8`; the compiled frozen binary hash is in `benchmarks/harness-pipelined-companions.json`. The archived comparison runner matches that report's source hash. Its raw executable map includes both Nano launchers and `.nano-real` originals. It predates the separate, canonical compiler-produced script map used by current runners to compare with direct Cargo.

Archived imports require `PYTHONPATH="$PWD/tests:$PWD/tools"` from the repository root. Use current runners for new experiments. Enable `--compiler-stream --pipelined-companions` with the explicit ring contract. This is a local opt-in experiment; do not describe its three cold pairs as general compiler superiority.
