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

The handoff also lists expensive Nano Rust bypasses in `uncached_work`, with the rejecting reason and a separate support-extension instruction. This keeps missing cache coverage visible even when both tools spend similar time compiling a cold request. Such intervals represent potential reuse only with matching inputs; they do not predict faster empty-cache compilation. Failed samples are excluded from this list too.

## Record unrelated compilation activity

Run the read-only host observer alongside a live benchmark on macOS or Linux:

```sh
python3 tools/benchmark_host_activity.py --pid "$benchmark_pid" \
  --output /tmp/new-host-activity.json --interval 1
```

It excludes the benchmark's descendants and records aggregate CPU observations and counts of known build tools outside that process tree. Pass `--owned-pid "$daemon_pid"` for an independently parented daemon belonging to the benchmark. The output contains no unrelated process IDs, executable paths, command arguments or environments. It never stops processes or removes timing samples. The JSON report identifies the tool source and hashes the adjacent JSONL samples.

Each snapshot includes `monotonic_seconds` from Python's `time.monotonic()`. A runner on the same host can record build start/end with that clock to match host observations to individual builds without wall-clock adjustments. A short build can fall between snapshots; an interval with no observations is unknown, not evidence that the host was idle.

Start observation before measured builds, retain all samples, and check the observer's actual coverage window. Attaching it partway through a trial cannot explain earlier outliers. An external compiler observation qualifies the overlapping timings as contended; do not use a contended trial alone for a speed or adoption claim. No observed build tools does not prove an idle host: process-name detection is heuristic, sampling can miss short jobs, other applications can compete for resources, and `ps` CPU percentages have platform-specific semantics. The observer itself adds sampling overhead. A missing initial PID or failed process observation produces an incomplete/error report rather than a clean-host result.

## Retain producer compiler and linker internals

For a diagnostic run, set `NANOCOMPILE_RETAIN_PRODUCER_JOBS=1` and `NANOCOMPILE_TRACE=1` alongside the applicable producer opt-in. Each fresh private job under `NANOCOMPILE_DIR/producer-jobs` keeps the compiler's raw stdout/stderr, compiler argv/status/timestamps, sealed linker invocation, linker dependency report and final staged products. Retained invocation records include an allowlist of the actual linker-child environment (SDK/deployment selection, locale, PATH, loader paths and `ZERO_AR_DATE`) rather than the entire environment. The observer also copies compiler-owned linker inputs while Rust's scratch files still exist. `owned-inputs.json` records lexical/canonical paths and BLAKE3 digests of independent copies with mode `0600`; the enclosing directories are private. Retention does not grant foreign inputs ownership or relax cache validation.

This captures additional evidence for successful and failed producer compilations. Jobs that fail before compiler launch and optional snapshot failures can have partial records; require the relevant records before treating evidence as complete. Diagnostic capture errors do not replace the compiler's exit status. Retention is off by default and adds storage/I/O overhead when enabled, so keep it separate from speed benchmarks. `clear` removes retained jobs; ordinary CAS GC does not manage these diagnostic copies. R2 transports only `entries` and `blobs`, so these private jobs are excluded.

Generated experiment provenance now carries the thin-LTO producer control and script-profile control too. Preserve these fields when handing the evidence to future variations; omitting the LTO control would reproduce a different cache-coverage profile.

## Storage safety and explicit bindgen controls

The comparison and full-Harness source-edit runners now save reports through a temporary file, flush and fsync it, then atomically replace the prior report. A failed save preserves the previous report. If saving a failure record also fails, stderr retains the original error. This protects saved evidence; it does not recover builds that never reached a successful save.

Before starting the session and each clean build, `--min-free-gib` gates available storage. Defaults are 32 GiB for executable/full-Harness workloads and 8 GiB for library comparisons. This is a preflight gate, not a guarantee against disk growth during a build. Complete captures and independent references can consume considerably more space over long sessions. Keep failed sessions distinct from completed evidence.

`--bindgen-tools-file` optionally supplies JSON containing exactly `LIBCLANG_PATH`, `CLANG_PATH`, and `RUSTFMT`, each an existing absolute file. The selection is shared by direct, Nano, and kache builds; its original bytes' SHA-256 and selected paths travel into reports and generated experiment provenance. This is preparation for auditing native build-script inputs, not proof of hermetic execution or a measured optimization. Validate generated bindings against the original configuration before using it for performance claims.

For future full-Harness variations, prioritize the observed warm native build-script intervals (media, tree-sitter and its grammars), then remaining framework-bearing Rust bypasses. Audit each script's actual files, toolchain resources, environment selectors and output paths before granting reuse. Require direct/cold/hit/source-edit/revert checks, failed-tool propagation, and output byte/mode equality against fresh-cache builds. Repeat untraced alternating comparisons against kache with identical shared controls. Reject a candidate if invalidation fails or repeated wall time regresses; overlapping trace intervals are not projected speedups.

## Native-script phase evidence

With `--script-profile`, the analyzer now exports `script_phase_profiles` and `script_profile_coverage` in both `analysis.json` and `experiments.json`, and shows the phases in the filtered HTML table. The next-variation brief lists observed warm phases to inspect while preserving validation. Each row retains its script output-directory identity, individual nanosecond samples, median/range, source-record name and original stderr byte count/SHA-256. Raw stderr is excluded from the generated reports. Analyzer provenance includes the phase-parser source hash.

New captures embed these rows. For older private captures, analysis verifies the entire capture manifest before deriving them from copied script stderr. If the private capture is unavailable and no rows were embedded, coverage is marked `unavailable`; that is unknown cost, not zero. Malformed, negative and out-of-range numeric events are ignored. Failed builds remain excluded.

These are logged call durations, not aligned critical-path spans or kache comparisons. A cold script can call material validation more than once. `material.total`, `restore.total` and publication timing include child phases; stages can also overlap source snapshots and other Cargo jobs. Do not add these numbers into expected build savings. Reproduce the suspected cost in the warm trace, then use matched untraced controls, edit/revert correctness gates and repeated whole-build comparisons before adopting a change.

The [all-native full-Harness capture](../benchmarks/harness-full-app-all-native-trace.json) verifies all six complete manifests and logs, 1,237 Cargo units per build, all recorded own-cold artifact/mode checks, CLI probes and stable tracked sources. The analyzer derives 279 cold and 403 warm phase rows across 31 native scripts. [The generated instructions](../benchmarks/harness-all-native-experiments.json) prioritize the late mixed-staticlib bypass and final producer restoration. The single diagnostic warm round is 8.271s Nano / 7.139s kache; it is not repeated speed evidence or a marginal feature-gain estimate.

The first [implementation driven by this trace](staticlib-companion-candidate.md) is an opt-in mixed-staticlib companion path. Its isolated actual dependency replay validates a C API source edit through both Rust and C links; generated experiment provenance now retains `staticlib_companions`. The repeated full-app timing session is published in [the candidate report](staticlib-companion-candidate.md); full-app source-edit verification remains pending.

Compiler phase instrumentation passed [nine serial validation steps](../benchmarks/compiler-phase-validation.json) in a separate frozen snapshot after the mixed-staticlib repeated benchmark. `NANOCOMPILE_COMPILER_PROFILE=1` together with `NANOCOMPILE_TRACE=1` emits `compiler-phase` intervals; `--compiler-profile` enables and records this diagnostic control in the full project comparison runner and requires `--trace-builds`. It is off by default. The ordinary mixed-staticlib fixture, executable fixture, default-off executable behavior and thin-LTO alias/concurrency fixture pass with complete artifact and linked-output checks. The [actual full-Harness diagnostic](../benchmarks/harness-full-app-compiler-profile.json) has now completed.

Ordinary requests record planning, prepare/compiler identity, locks/configuration, restore, input snapshot/staging, compiler execution/stream forwarding and postcompile storage. Producer requests additionally separate Apple selection (including preparation and maintenance locking), compiler identity, observer identity, locks/configuration and restoration. Totals include child intervals. Restore observations cover manifest parsing, input validation, its nested parallel hashing call, output validation/wait, stream validation and materialization. With overlap enabled, output hashes execute during input validation: the output validation/wait interval measures the remaining join wait, not the entire output-hashing duration. Early refusals can yield a total without all child stages.

The analyzer preserves each request/stage's individual samples, median/range, relative source-record name and stderr byte count/SHA-256 in `compiler_phase_profiles`, alongside coverage status. It excludes failed compiler requests and failed builds. Existing captures are verified before backfilling; missing evidence is unavailable, not zero cost. Generated HTML escapes captured names, and the next-variation instructions prioritize observed warm stages while retaining content validation and publication order. Nested stages and overlapping calls must not be added into predicted whole-build savings.

`--nano-only` prepares a direct reference followed by Nano cold/warm captures, preserving the same artifact, mode, CLI and source checks. It requires `--trace-builds`, records the mode in provenance, and emits no paired speed summary or kache statistics. This mode passed a real tiny Rust crate cold/hit comparison before the three-build full-Harness capture. Neither diagnostic establishes a speed improvement.


## Completed full Harness compiler profile

The [three-build diagnostic summary](../benchmarks/harness-full-app-compiler-profile.json) verifies all three whole-build logs and capture manifests: 1,237 Cargo units each, and 1,145 compiler/probe records in each Nano build. Warm artifacts, modes and CLI output match Nano's cold reference; tracked sources remain unchanged. Complete logs, argv and per-request streams remain privately in `/tmp/nano-full-harness-compiler-profile-20261011`. The full phase arrays, filtered HTML, Perfetto timeline and generated instructions are in `/tmp/nano-full-harness-compiler-profile-analysis-20261011`. The public summary retains selected phase samples and their original stream hashes, while the private analysis retains every phase observation.

The late `harness` warm request records input validation at 0.521500s, with nested parallel input hashing at 0.506399s. An [isolated six-execution final-request replay](../benchmarks/harness-producer-compiler-profile.json) independently records three hits with median input validation 0.388921s and nested hashing 0.374440s. These observations identify hashing as a candidate; they do not establish a worker-count or allocation optimization. Output validation runs concurrently, so its near-zero join wait does not mean output hashing is free. The whole diagnostic warm build takes 9.423933s including capture overhead and has no kache execution.

[Instructions for the next variation](harness-compiler-profile-next-variation.md) connect these measurements to single-cause experiments and correctness gates. The earlier repeated untraced comparison remains the performance reference: Nano cold median 183.695712s versus kache 187.511773s (two of three paired wins), warm 7.170868s versus 5.767633s (zero of three wins). More independent comparisons are needed before claiming reliable cold superiority.
