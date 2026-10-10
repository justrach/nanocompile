# Where the default Harness runtime spends time

The [isolated diagnostic session](../benchmarks/harness-default-phase-session.json) completes one cold pair and one warm round on the unchanged real Harness adapters snapshot, eight jobs, Rust 1.97.1 and kache 1.0.0. All warm Rust, macro, compiled-script, launcher and native artifact checks pass against each tool's own cold outputs. Nano records 167 Rust misses cold and 167 hits warm, plus the corresponding ring execution miss/hit. No R2 is used. This is the adapters library workload, not the full GUI.

The [phase records](../benchmarks/harness-default-phase-profile.json) identify a concrete first-wave cost: identity and key preparation takes 0.350s for `unicode_ident`, 0.346s for `pin_project_lite`, 0.345s for `stable_deref_trait`, 0.343s for `cfg_if` and 0.342s for `smallvec`. Across all 136 completed ordinary cold calls, the median is 1.419ms. These initial intervals overlap and include waiting inside toolchain fingerprinting; their sum is not potential wall-time savings. They explain most of the approximately 0.4s small-crate gaps in the separate [live capture](../benchmarks/harness-live-pipelining-trace.json), without proving an optimization gain.

| Ordinary cold phase | Median | Maximum |
| --- | ---: | ---: |
| Identity and key preparation | 1.419ms | 349.981ms |
| Key/output locks and declaration validation | 0.243ms | 4.648ms |
| Lookup | 0.022ms | 0.329ms |
| Input snapshot and command preparation | 0.528ms | 24.490ms |
| Compiler invocation and stream forwarding | 131.246ms | 6.358s |
| Successful event, validation and storage | 8.214ms | 239.628ms |

The longest compiler interval is `harness_adapters` at 6.358s; `tokio` is 3.666s and `rustls` 2.936s. Those durations also overlap and do not identify the critical path by themselves. Warm ordinary calls have 1.440ms median identity/key preparation and 5.047ms median verified restore/replay. Producer, native, script execution, failed and bypass calls are excluded from these phase records; the full capture remains necessary for whole-build analysis.

Instrumentation lives only in the retained [patch](../benchmarks/experiments/default-phase-profile.patch), against the [recorded base and binary](../benchmarks/experiments/default-phase-provenance.json). It records monotonic boundaries and writes one private JSON record per completed ordinary call. Diagnostic writes and timing calls add overhead; this session's whole-build times are excluded from production speed claims. Apply the patch in a disposable copy of the recorded base, build with stable Zig 0.17.0, then run `tests/project_comparison.py` with the same options as the recorded session. Summarize `<NANOCOMPILE_DIR>/default-phase` using [default_phase_summary.py](../benchmarks/experiments/default_phase_summary.py).

## Instructions for the next variation

1. Instrument the first fingerprint internally to distinguish compiler queries, resource discovery, full-byte hashing, memo writes and lock waits. Preserve the selected executable, complete resource membership, symlink resolution, content checks and post-hash stamps. Do not treat the entire identity interval as hashing.
2. Evaluate resource scheduling or worker-count changes against the current four-worker implementation. Compare the exact full content identity and decoder identity, then test mutations and unavailable resources. Avoid moving prewarming outside the cold timer or retaining fingerprints when claiming empty compiler caches.
3. Compare each promising candidate to the frozen production default at one wrapper path, with identical arguments/environment and alternating empty-cache builds. Repeat cold and warm comparisons against kache separately. Require own-cold artifact equality, actual edit/revert results, expected hit counts and both-platform integration checks.
4. Split validation/graph/storage timings before attempting to reduce the separate cold save outliers. Full mutable inputs and output validation must remain mandatory. Record rejected variations and retain every timing sample; promote only repeatable whole-build gains.

The current production runtime's [repeated cold/warm results and verified edits](default-pipelining.md) remain the performance evidence. This profile establishes the next measured target, not a new speedup.
