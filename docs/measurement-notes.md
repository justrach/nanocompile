# Measurement notes

These notes were previously the opening of the README. Each link records its raw samples and limits.

Measured performance and its limits are published with raw samples: [Rust versus kache](../benchmarks/harness-hill.md), [Xcode](../benchmarks/xcode.md), and [Turborepo with R2 restores](../benchmarks/turborepo.md).

The [real Wootin raw Zig benchmark](../benchmarks/zig-wootin.md) covers cold compilation, restores and source edits, with a measured 9–11% reduction in restore latency and a preserved-timestamp correctness fix.

The [verified physical Rust identity optimization](rust-physical-memo.md) reduces cold Harness adapters build time by 7.8–9.6% across six alternating production A/B pairs. The earlier default configuration comparison favors kache. The [opt-in execution cache](build-script-cache.md) now has repeated warm Harness leads; cold results remain variable. The [accepted production comparison and streaming experiment](harness-streaming-experiment.md) records all samples: 24.8% lower warm median, but a 1.1% higher cold median in the latest session.

The [latest cold Harness trial](../benchmarks/harness-cold.md) cuts Nano build time by 38% using eight Cargo jobs on the test Mac, while kache still wins at equal concurrency. Both attempted cache-core optimizations were rejected after timing and coverage checks.

The [producer profile](producer-phase-profile.md), [restore breakdown](restore-phase-profile.md), and [ordinary-hit profile](library-phase-profile.md) record where warm-hit time goes and link optimization experiments, including rejected candidates.

**Try it today:** Cargo library builds, supported direct Zig invocations, and the runnable Turbo example. Rust proc-macro producers run directly by default. Xcode uses Apple's native cache, and R2 currently transports explicit snapshots. See [supported builds](../README.md#current-eligibility) before choosing a workload.

The [default Rust pipelining comparison](default-pipelining.md) wins five cold pairs and three warm rounds against kache on Harness adapters: 7.3% lower cold median and 30.2% lower warm median, with all expected warm hits. The separate execution contract and macro/producer options remain opt-in.

Capture full real-project builds and generate a Perfetto timeline, crate/native comparisons and instructions for future variations with the [build tracing tools](build-tracing.md). Diagnostic logs stay private; speed claims use separate untraced benchmarks.

The [full Harness eight-worker comparison](full-eight-workers-kache-comparison.md) still favors kache on warm builds and does not establish a Nano cold advantage. For new default-off experiments, the [runtime-control comparison runner](runtime-toggle-comparisons.md) records each build's exact switch value and can verify activation in an excluded prime.

Large Rust metadata now uses a separate bounded, state-checked snapshot reader; the actual Harness `objc2_app_kit` replay restores byte-identical artifacts. See [scope and checks](large-rust-metadata.md). [Thin-LTO producer support](thin-lto-producer-investigation.md) has an opt-in stable-staging candidate; default builds still refuse it.

The opt-in [stable-alias full Harness candidate](full-harness-stable-alias.md) restores the thin-LTO application: two warm rounds give **17.690 s Nano versus 6.863 s kache**. Artifact, permission, signature and CLI checks pass; Nano still loses, and no repeated cold win or default promotion is claimed.
