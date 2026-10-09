# Native Clang invocation phases

The accepted Cargo timing profile pointed to ring's native build script.
An isolated diagnostic build now separates eligible Clang invocations into
five wall-time phases, using Zig's monotonic awake clock. The Rust wrapper
remains the accepted executable. The diagnostic patch changes only
`src/clang.zig`; it does not remove queries, validation, hashing or CAS work.

Three clean warm builds take **2.036754, 2.050737, and 2.013023 seconds**.
All four builds, including the prime, have 193 identical artifacts. Each
warm build has 167 Rust and 24 native hits. Tracked Rust sources, manifests
and lockfile remain unchanged. The native regression suite also passes,
including preserved-mtime and already-dirty mmap header invalidation.

Cargo retains compiler diagnostics in ring's build-script `output` file.
The final warm build supplies **24 hit records**:

| Phase | Sum across 24 invocations | Median invocation |
| --- | ---: | ---: |
| Live compiler/SDK selection | 199.610 ms | 8.335 ms |
| Native executable, cache preparation, maintenance lock, installed identity | 2.429 ms | 0.101 ms |
| Capability memo validation | 0.462 ms | 0.018 ms |
| CAS directory, permissions, arguments and run event | 1.963 ms | 0.081 ms |
| Clang process spawn, scan, replay and captured output | 742.895 ms | 26.716 ms |
| Total inside adapter through compiler completion | 947.359 ms | 35.285 ms |

These are aggregate per-invocation elapsed durations, which may overlap;
they are not additive critical-path savings. Adapter startup, subsequent
diagnostic forwarding/event writes, noneligible probes, archiving and other
build-script work are outside these totals. The first two warm output files
were replaced by subsequent clean builds, so only the final build is claimed
as a per-invocation sample. Cargo instrumentation and diagnostic output make
this a cost attribution exercise rather than an A/B speedup result.

The small identity/capability/setup cost suggests investigating Clang
execution before optimizing this bookkeeping. A driver-only `-###` probe
of a captured native command reports separate cc1 execution by default;
adding `-fintegrated-cc1` reports `(in-process)`. Both driver queries return
zero. This establishes a change in execution mode, not a performance gain.
An isolated candidate adds this driver flag before caller arguments, so
caller policy can still override it. Live Clang/SDK selection and all
mutable input validation remain in place.

The local compiler is Apple Clang 21.0.0 (`clang-2100.3.34.2`) on arm64 macOS
27. The diagnostic binary SHA-256 is
`45116c708c497081faf41039b852c9e5be5e39455404a60141652ea64e00228a`,
built with stable Zig 0.17.0 from `354a3de` plus the recorded patch. All
Cargo captures use Rust 1.97.1, four jobs, an isolated target/cache,
offline locked release library mode, and a 40 GiB sampled RSS cap.

Artifacts and reproduction sources:

- [Diagnostic patch](../benchmarks/experiments/clang-phase-profile.patch)
- [Capture runner](../benchmarks/experiments/cargo_timing_capture.py)
- [Phase extractor](../benchmarks/experiments/clang_phase_summary.py)
- [Build evidence, source and artifact digests](../benchmarks/harness-clang-phase-profile-builds.json)
- [All native invocation records](../benchmarks/harness-clang-phase-profile.json)
- [Diagnostic native regression checks](../benchmarks/clang-phase-profile-regression.json)
- [Driver execution-mode probe](../benchmarks/clang-phase-driver-execution.json)

Use the diagnostic binary only as `--clang-wrapper` with `--native-clang`
in the capture runner. A separate [paired benchmark and confirmation](clang-integrated-cc1-experiment.md)
subsequently justify adopting integrated cc1 execution; phase instrumentation
remains isolated and is not part of production.
