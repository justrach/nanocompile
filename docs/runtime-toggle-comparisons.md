# Comparing one runtime control

`tests/project_pair_comparison.py` can compare two settings of one experimental control in a byte-identical runtime. Use this for a default-off candidate instead of copying the runner and replacing labels manually. The runner rejects different executable hashes, equal setting values, unsupported controls and unsupported values before creating benchmark state.

Supported controls are `NANOCOMPILE_PRODUCER_GRAPH_WORKERS` (0/4), `NANOCOMPILE_PRODUCER_SHARED_DIGESTS` (0/1) and `NANOCOMPILE_HASH_MISMATCH_STOP` (0/1). They require their corresponding experimental runtime; passing a control to an executable does not prove that the executable implements it. Production does not gain these experiments by adding the runner options.

For the parallel producer graph runtime, use the existing full-project controls and add:

```sh
python3 tests/project_pair_comparison.py "$runtime" "$runtime" "$project" \
  --state "$new_state" --output "$report" \
  --runtime-toggle NANOCOMPILE_PRODUCER_GRAPH_WORKERS 0 4 \
  --candidate-prime-marker 'graph: parallel producer roots' \
  --cold --runs 5 --jobs 8 --package harness --bin harness --probe-help \
  --own-artifact-references --minimum-cache-units 1099 \
  --source-date-epoch 1791423832 --thin-lto-producers \
  --rlib-frameworks --staticlib-companions \
  --build-script-contract "$contract" --bindgen-tools-file "$bindgen_tools"
```

Supply the actual frozen workload, runtime, native contract and tool selection used by the comparison. The command is a template, not a claim that an arbitrary checkout supports those controls. Native wrapper guards must match the new state's stable wrapper path.

The report records `runtime_control.name` and its baseline/candidate values, plus each build's actual `runtime_controls` and `trace_enabled`. Optional activation verification enables trace only for the excluded candidate prime, requires the marker in that log, and rejects the marker in every untraced build. Both primes are excluded from paired statistics. Complete build consoles remain in the private state directory with sizes and SHA-256 recorded in the report. Raw environments are not published.

Without `--runtime-toggle`, the existing two-binary comparison remains available. The method text describes executable identities using their recorded hashes rather than assuming they differ. These runner changes do not alter previously frozen experiments or their results. The older parallel-graph full trial retains its original runner and explicit report-label correction.

Before adopting a candidate, verify all full logs, source hashes, artifact bytes/modes and CLI results, then compare repeated untraced timings. Unit coverage in `tests/project_pair_controls.py` checks that the measured interventions agree with their declarations and that prime-only tracing cannot leak into measured builds. Real-build validation remains necessary for each experimental runtime.
