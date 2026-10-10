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

Each private capture now includes `cargo.log` and `manifest.json`: byte counts and SHA-256 hashes for every captured file, plus compiler-record and Cargo-unit counts. This makes the captured evidence auditable. Capture coverage explicitly distinguishes direct Cargo console/timings from wrapped compiler records; this does not trace every subprocess or filesystem access.

Run `python3 tools/build_trace.py verify-capture /tmp/new-private-build-capture/capture/1` to detect missing, added, truncated or changed captured files. The manifest checks integrity; it does not authenticate logs against an adversary who can rewrite the manifest.

`experiments.json` provides ranked, structured instructions for future variations: the observed gap, sample counts and ranges, a hypothesis, the next measurement, and correctness and repeated benchmark gates. Pass that file together with the frozen baseline revision and relevant private records to the next experiment. A ranked interval gap remains a diagnostic lead, not a promised whole-build speedup.

The brief selects up to twelve candidates; `analysis.json` retains every comparison. [Example structured instructions](../benchmarks/harness-build-trace-experiments.json) come from the published Harness capture. That capture predates the physical Rust memo optimization; reproduce each observation on the current baseline before treating it as a remaining bottleneck.

These are **diagnostic builds**. Current frontends forward streams live and retain byte-arrival ranges, preserving metadata notifications used by Cargo pipelining. Historical captures buffered streams until compiler completion. Verbose logging and live capture still add overhead, Cargo unit timings have centisecond precision and approximate alignment, and request CPU excludes kache daemon work. Per-job durations overlap and depend on scheduling. Summing them does not establish critical-path savings. Kache hit `compile_time_ms` can describe the original stored compilation, so stage summaries exclude it for hits and duplicate entries. Request comparisons group crate/native names and job types; Cargo comparisons additionally distinguish version, features and target. Kache service events remain separate from request spans because timestamp/crate matching is not always unique. Direct Cargo has full build logs and Cargo units, but no per-compiler frontend records. Nano cache events are aggregate unless per-request stderr supplies a decision; missing stages or counterparts are unknown.

Current compiler records include byte-contiguous `.chunks` ranges and `capture_complete`; verification rejects incomplete or orphaned streams. The analyzer adds observed metadata-notification instants to Perfetto timelines. These are receipt times of complete messages, not proof of filesystem publication or critical-path savings. Historical records have no such timestamps.

Full logs and argv stay under the private state directory (0700); they can contain local paths and compiler-emitted configuration. The analysis does not embed raw logs or environment values. Review any report before sharing it. Run the same comparison **without `--trace-builds`** for speed claims. Compare each implementation's repeated output against its own cold hashes; kache path remapping and Nano's native scanner can change debug representation between implementations.

Verification: `python3 tests/build_trace_capture.py` checks exact argument and stream preservation, inherited stdin/environment, nonzero exits, signals, parallel record ownership, fallback execution and safe handling of missing comparison counterparts. It runs in Linux/macOS CI.

## Captured Harness example

[Sanitized nine-build capture](../benchmarks/harness-build-trace.json) covers the real Harness adapters snapshot at `32b41cb0bff55e3c9cbfab3012acec2b179ad199`, including its pre-existing dirty sources, Rust 1.97.1, kache 1.0.0, production Nano and eight jobs. One cold pair and two warm rounds are diagnostic observations, not repeated cold speed evidence. All 187 Cargo units were captured each build. Cold requests for both wrappers include 169 Rust, 24 native and 10 probe invocations; warm Nano still issues those calls, while warm kache issues 167 Rust and three probe calls, with zero native frontend calls.

Ring's `run-custom-build` median is 1.28s for Nano versus 0.05s for kache in these two warm rounds. Kache records 187 local hits, and ring's raw local-hit event includes a `native_bundle_audit` key field. Native artifacts still match its own cold outputs. The [pinned-source inspection and ablation](kache-build-script-ablation.md) now verify that kache caches build-script execution. The native_bundle_audit marker itself audits rlib archives; it is a separate mechanism. Nano records 167 Rust and 24 native hits while repeating the native requests. The next candidate should investigate safe bundle-level native reuse and validate source/header/assembly includes, toolchain and environment changes before attempting to omit that work.

Early cold Rust requests also show roughly a one-second Nano startup gap. Measure installed-toolchain fingerprinting and concurrent request coordination directly before changing identity validation. The [generated future-variation brief](build-trace-next-experiments.md) ranks the observed gaps and defines acceptance gates. Full local logs remain in `/tmp/nanocompile-build-trace-final-20261010`; the private report retains argv-record references. Public data excludes raw output, argv, cwd and diagnostic strings. Recreate the filtered HTML and timeline from the sanitized capture with the analyzer.

## Follow-up capture: opt-in execution prototype

A six-build diagnostic session tested an uncommitted explicit-input build-script cache prototype on the same Harness workload. All 187 Cargo units were recorded in each build. Nano captured 203 compiler/probe requests in both cold and warm builds; kache captured 203 cold and 170 warm. Every warm artifact set matched its implementation's own cold hashes. All six capture manifests verified successfully.

Ring's execution prototype bypassed with `LinkedToolchainDirectory`: the installed SDK/header tree contains linked directories that its current identity collector refuses. This prototype has not established a speed improvement. The next implementation should record link selection and resolved input contents, detect retargeting and target edits, and preserve fallback execution. Then test actual source/header/assembly edits and rerun untraced alternating comparisons against the accepted runtime and kache. Keep this candidate separate from production until those checks pass.

The private diagnostic session and analysis are `/tmp/nano-ring-contract-trace-20261010` and `/tmp/nano-ring-contract-analysis-20261010`. This describes local prototype evidence, not a released build-script cache feature.

## Current archive-chain candidate capture

The [latest sanitized capture](../benchmarks/harness-archive-chain-trace.json) uses the atomic execution-cache prototype and explicit archive-chain contract documented in [the execution experiment](build-script-execution-experiment.md). All nine private capture manifests verified; every build contains 187 Cargo units. Nano has 179 compiler/probe records in cold and warm runs, versus kache's 203 cold and 170 warm. Native child tools inside Nano's real script execution are outside the frontend capture, so request-count differences do not prove less native compilation on cold builds. Warm events independently confirm 167 Rust hits and one execution-bundle hit, and all repeated outputs match their own cold hashes.

Ring's warm run-custom-build interval is 0.150s for Nano and 0.045s for kache over two diagnostic samples. Early cold requests show roughly 0.37s positive Nano interval gaps. Profile these remaining costs directly before another change: the warm script's mutable input snapshot, live helper/tool/SDK selection, installed stamp validation, verified blob restoration and atomic publication; and the first Rust identity plus request coordination. Overlapping Cargo/request gaps cannot be added to predict whole-build savings.

[Structured instructions](../benchmarks/harness-archive-chain-experiments.json) preserve the exact configuration, binary and report hashes, analyzer hash, artifact-validation mode and sampling counts. [The next-variation brief](archive-chain-next-experiments.md) names the observed leads and required gates. Full console, streams, argv, cwd and build-script logs remain private in `/tmp/nano-archive-chain-trace-20261010`; the interactive local report is `/tmp/nano-archive-chain-public-analysis-20261010/index.html`. Separate [untraced repeated benchmarks](../benchmarks/harness-archive-chain-execution.json) provide the speed observations.

## Live default-pipelining capture

The [nine-build live capture](../benchmarks/harness-live-pipelining-trace.json) records all 187 Cargo units each build. Nano has 179 compiler/probe records per wrapped build, kache has 203 cold and 170 warm. Each wrapped build contains 135 complete observed metadata notifications, retained as timeline instants. All nine manifests pass byte counts, hashes, record ownership and contiguous stream-chunk validation. Every repeated output matches its implementation's own cold reference. Nano's warm Rust/script coverage remains 167/one hits while logging live.

Full logs stay in `/tmp/nano-live-default-trace-20261010`; the sanitized report omits raw decisions, private record references and capture directories. Recreate the private filtered report with `tools/build_trace.py analyze`; the local public preview is `/tmp/nano-live-default-public-analysis-20261010/index.html`. [Structured future instructions](../benchmarks/harness-live-pipelining-experiments.json) and [the brief](live-pipelining-next-experiments.md) rank remaining observed interval gaps. First cold units retain roughly 0.4s diagnostic gaps in this single cold pair; reproduce and instrument startup/identity costs before changing validation. Diagnostic durations overlap and do not establish critical-path savings or replace the separate repeated untraced benchmarks.

## Failure records and reproducible handoff

The comparison runner records each full console's relative path, byte count and SHA-256, even without compiler tracing. Verify those bytes with:

```sh
python3 tools/build_trace.py verify-logs /tmp/build-capture.json --state /tmp/new-private-build-capture
```

With `--bin harness --probe-help`, reports include final file permissions and probe outcomes. An execution error is saved before the runner stops; it cannot silently lose the completed build's timing row. Repeated file modes and artifact bytes must match the same implementation's cold reference. The report's `completed` and `failure` fields distinguish a finished session from a stopped one. Historical reports lack these additional fields.

The analyzer lists excluded builds and omits failed compilation, executable-probe and artifact-validation samples from optimization comparisons. Structured experiment instructions retain the reproducible timestamp, binary target, probe policy and session outcome, plus a one-cause implementation instruction and explicit rollback criteria. Inspect the generated observations before implementing a variation; interval gaps are hypotheses, not expected build-time savings.
