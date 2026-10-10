# Whole-build tracing and future experiments

Capture a real Cargo library workload with both Nano and kache:

```sh
python3 tools/build_trace.py capture -- \
  zig-out/bin/nanocompile /absolute/path/to/project \
  --kache /absolute/path/to/kache --package harness-adapters \
  --state /tmp/new-private-build-capture --output /tmp/build-capture.json \
  --jobs 8 --runs 3 --cold-runs 3 \
  --native-clang --proc-macros reported \
  --proc-macro-producers --executable-producers
python3 tools/build_trace.py analyze /tmp/build-capture.json --output /tmp/build-analysis
```

Use producer and reported-macro options only when appropriate to your workload's declared inputs. Omit native-clang for ordinary Rust-only comparisons. The state directory must be new. Cache clearing and target deletion affect only that dedicated state directory.

The capture saves complete Cargo verbose logs, Cargo HTML timings, build-script output/stderr, cache event slices, private daemon logs, and individual compiler-wrapper argv/cwd/stdout/stderr records. Native executable frontends preserve inherited stdin and loader environment; the kache basename retains Cargo native wrapper recognition. Request elapsed time and child CPU usage are recorded with separate files per invocation, avoiding concurrent append races. A stable wrapper and capture environment are used across cold and warm builds; switching log destinations does not change compiler-cache keys.

Open `index.html` to filter comparisons by crate, native file, phase or job type. Load `trace.json` in Perfetto to inspect overlapping Cargo and compiler-request intervals. `analysis.json` includes matching-job medians and kache service stage summaries; `next-experiments.md` generates a concrete brief from observed interval gaps and requires correctness and untraced benchmark gates for future variations.

These are **diagnostic builds**. Capturing output buffers streams until compiler completion, verbose logging adds overhead, Cargo unit timings have centisecond precision and approximate alignment, and request CPU excludes kache daemon work. Per-job durations overlap and depend on scheduling. Summing them does not establish critical-path savings. Kache hit `compile_time_ms` can describe the original stored compilation, so stage summaries exclude it for hits and duplicate entries. Request comparisons group crate/native names and job types; Cargo comparisons additionally distinguish version, features and target. Kache service events remain separate from request spans because timestamp/crate matching is not always unique. Direct Cargo has full build logs and Cargo units, but no per-compiler frontend records. Nano cache events are aggregate unless per-request stderr supplies a decision; missing stages or counterparts are unknown.

Full logs and argv stay under the private state directory (0700); they can contain local paths and compiler-emitted configuration. The analysis does not embed raw logs or environment values. Review any report before sharing it. Run the same comparison **without `--trace-builds`** for speed claims. Compare each implementation's repeated output against its own cold hashes; kache path remapping and Nano's native scanner can change debug representation between implementations.

Verification: `python3 tests/build_trace_capture.py` checks exact argument and stream preservation, inherited stdin/environment, nonzero exits, signals, parallel record ownership, fallback execution and safe handling of missing comparison counterparts. It runs in Linux/macOS CI.

## Captured Harness example

[Sanitized nine-build capture](../benchmarks/harness-build-trace.json) covers the real Harness adapters snapshot at `32b41cb0bff55e3c9cbfab3012acec2b179ad199`, including its pre-existing dirty sources, Rust 1.97.1, kache 1.0.0, production Nano and eight jobs. One cold pair and two warm rounds are diagnostic observations, not repeated cold speed evidence. All 187 Cargo units were captured each build. Cold requests for both wrappers include 169 Rust, 24 native and 10 probe invocations; warm Nano still issues those calls, while warm kache issues 167 Rust and three probe calls, with zero native frontend calls.

Ring's `run-custom-build` median is 1.28s for Nano versus 0.05s for kache in these two warm rounds. Kache records 187 local hits, and ring's raw local-hit event includes a `native_bundle_audit` key field. Native artifacts still match its own cold outputs. These observations are consistent with native bundle reuse; they do not alone prove the exact implementation or safe input-discovery rules. Nano records 167 Rust and 24 native hits while repeating the native requests. The next candidate should investigate safe bundle-level native reuse and validate source/header/assembly includes, toolchain and environment changes before attempting to omit that work.

Early cold Rust requests also show roughly a one-second Nano startup gap. Measure installed-toolchain fingerprinting and concurrent request coordination directly before changing identity validation. The [generated future-variation brief](build-trace-next-experiments.md) ranks the observed gaps and defines acceptance gates. Full local logs remain in `/tmp/nanocompile-build-trace-final-20261010`; the private report retains argv-record references. Public data excludes raw output, argv, cwd and diagnostic strings. Recreate the filtered HTML and timeline from the sanitized capture with the analyzer.
