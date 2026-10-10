# Frozen streaming trial runners

These files preserve the exact source SHA-256 recorded in the trial reports. They predate expanded `.nano-real` collection. Use the current `tests/` runners for future comparisons; these snapshots are evidence for reproducing the historical method.

From the repository root, archived imports require `PYTHONPATH="$PWD/tests:$PWD/tools"`. Cold comparisons use `--cold --compiler-stream --own-artifact-references` and the same explicit build-script contract. Full logs stay under the new private state directory. See `docs/harness-streaming-experiment.md` for sample counts, failures, missing coverage and promotion gates.
