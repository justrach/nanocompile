# Actual full-Harness source edits

`tests/harness_full_source_edits.py` builds the full `harness` executable from a disposable copy of the actual dirty Harness snapshot. It changes two existing source locations: the CLI description in `apps/harness/src/main.rs`, then the shared `version_triple` parser in `crates/proto/src/lib.rs`. The parser edit changes handling of trailing whitespace; a separately linked probe checks the library produced by each full application build. The final scenario restores both original files.

This runner is prepared; it has not yet produced a completed full-app source-edit result. Do not substitute earlier adapters-library results for this workload.

Each build starts with a clean Cargo target. Timed edits retain compiler caches from previous scenarios. Every Nano and kache edit is then repeated with an empty cache at identical paths, outside the timed comparison. The historical-cache and fresh-cache outputs must match in Rust libraries, macro dylibs, compiled build scripts, native objects/archives and final executable bytes and permissions. Fresh-cache references must record zero cache hits. Reverts must also match the implementation's initial artifact bytes. Runtime checks require the expected CLI description and parser behavior. The original project remains untouched, and all undeclared snapshot sources must retain their hashes.

Use a frozen executable and contract that match the intended runner. For the local guarded SQLite candidate:

```sh
python3 tests/harness_full_source_edits.py \
  /tmp/nano-sqlite-guarded-20261011/bin/nanocompile \
  /tmp/nanocompile-three-directions/harness-variants-verified/project \
  --kache /tmp/nanocompile-kache-pinned-installer/kache \
  --source-date-epoch 1791423832 --jobs 8 \
  --native-artifacts --proc-macros reported \
  --proc-macro-producers --executable-producers --thin-lto-producers \
  --build-script-contract benchmarks/experiments/build_script_execution/sqlite-harness-contract.json \
  --retain-artifacts --state /tmp/new-full-harness-edits \
  --output /tmp/full-harness-edits.json
python3 tools/build_trace.py verify-logs /tmp/full-harness-edits.json \
  --state /tmp/new-full-harness-edits
```

Do not run this alongside another timed benchmark. Private state retains complete Cargo consoles with hashes and independent reference files. Failed rows and a terminal failure reason remain in the report. The sequence contains eighteen full builds, including fresh-cache correctness references; each scenario's timed result is one sample, so repeat the complete sequence in a new state directory before claiming a reliable edit speed advantage.

The reported-macro policy and explicit execution contracts retain their existing input assumptions. This is local cache testing with warm, unflushed OS filesystem caches; fetching, daemon startup and correctness probes are outside build timing. R2 is excluded. The application is exercised with `--help`; GUI behavior is outside this benchmark. Use a separate diagnostic [whole-build capture](build-tracing.md) to rank remaining compiler requests, Cargo script intervals and bypasses before implementing another variation.
