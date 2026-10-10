# Kache build-script execution ablation

The pinned [kache 1.0.0 implementation](https://github.com/kunobi-ninja/kache/blob/7c27329c286e32c17a8dac05cff22442926ff719/src/build_script.rs) installs a native launcher beside each compiled Cargo build script. It caches the **execution**, including OUT_DIR products and captured stdout/stderr, using Cargo's rerun declarations and environment. A script with no declarations depends on its package directory. The default contract follows Cargo's reported inputs; the separate hermetic mode is off by default. Nano currently caches executable compilation and individual Clang work, while build-script execution remains live.

This is distinct from `native_bundle_audit`: that marker checks native archive members embedded in an rlib. It is not the build-script cache mechanism. The private ring event actually says `crate_name=build_script_run`, `package=ring`, `result=local_hit`, 20ms elapsed and 1,335,040 output bytes. Public capture package labels are now retained so these jobs remain identifiable.

The [initial capture](../benchmarks/harness-build-trace.json) and [ablation](../benchmarks/harness-build-script-ablation.json) use the same production Nano and kache binaries, real dirty Harness adapters snapshot, eight jobs, one cold pair and two warm rounds. The ablation changes only `KACHE_BUILD_SCRIPT_CACHE=0`; it retains normal kache Rust/native caching. Both are diagnostic sessions with verbose Cargo logging and per-call output capture. These are separate sessions, not interleaved paired measurements.

| Observation | Default kache | Build-script caching disabled |
| --- | ---: | ---: |
| Warm ring run-custom-build median | 0.05s | 0.64s |
| Warm native frontend requests per build | 0 | 24 |
| Warm build-script execution hit events | 21 | 0 |
| Whole warm build median | 1.2894s | 1.3672s |
| Native artifact bytes equal own cold reference | yes | yes |

Nano ring medians are 1.28s in the default comparison and 1.29s in the ablation comparison. Nano's whole-build warm medians are 1.9414s and 1.9368s. Each session has 187 Cargo units per build, successful clean-target rebuilds, matching own-cold Rust/producer/native artifacts and unchanged source hashes. OS filesystem caches remain warm; R2 and dependency fetching are outside measured work.

Disabling execution caching clearly restores ring's repeated native jobs and increases that job's interval. The much smaller whole-build difference shows that those interval savings cannot simply be counted as whole-build savings. Scheduling, overlap and limited samples prevent a precise causal estimate of end-to-end benefit. Kache remains faster with execution caching disabled, so porting that feature alone is not proven sufficient to close the gap. Investigate both build-script execution reuse and Nano's slower native request path, then require alternating untraced comparisons and real input edits.

Reproduction adds `--kache-no-build-scripts` to the [whole-build capture command](build-tracing.md). The option is explicitly reported in comparison output. Raw logs stay private in `/tmp/nanocompile-build-script-ablation-20261010`; shareable data excludes raw argv, output and environment values.
