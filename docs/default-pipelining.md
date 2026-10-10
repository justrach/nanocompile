# Default Rust compiler pipelining

Regular cacheable Rust library compilations now forward compiler output immediately while retaining byte-exact streams for verified cache replay. Metadata-first dependency guards tolerate only a proven unused, same-stem regular archive appearing later. Full metadata content and other candidate guards remain mandatory. Producer compilations retain their existing private-output publication behavior; raw Zig compilation is unchanged.

The membership optimization applies only when matching regular metadata existed in both snapshots and its conventional filename can be represented safely. Symlink metadata and unsupported names keep the original full directory guard rather than making an otherwise cacheable static invocation fail storage. Tests exercise real Rust 1.97.1 and 1.98.1, symlink metadata, archive presence changes, competing candidates, full metadata mutations, explicit archive inputs and final linking. A deterministic proxy publishes an unused archive after real rustc runs but before Nano receives compiler completion.

Set `NANOCOMPILE_STREAM_COMPILER=0` or `NANOCOMPILE_PIPELINED_COMPANIONS=0` to disable a component for diagnosis. These environment values remain cache-key inputs. Current benchmark runners expose `--no-compiler-stream` and `--no-pipelined-companions`; report fields are the explicit override strings or `null` for the tested binary's defaults. Historical frozen binaries have their historical defaults.

## Repeated default-binary results

[Five alternating cold pairs and three warm rounds](../benchmarks/harness-default-pipelining.json) use the real dirty Harness adapters snapshot, Rust 1.97.1, kache 1.0.0 and eight jobs. No streaming or companion environment overrides are set. The explicit ring execution contract and reported macro/producer options remain the same as earlier comparisons; these separate features still require opt-in. This is `cargo build --release --lib --locked --offline -p harness-adapters`, not the full GUI build.

| Phase | Nano median | kache median | Nano pair wins |
| --- | ---: | ---: | ---: |
| Empty compiler caches, clean target | 15.988398s | 17.239241s | 5/5 |
| Primed compiler caches, clean target | 0.962852s | 1.380159s | 3/3 |

Nano's medians are 7.3% lower cold and 30.2% lower warm in this session. Every cold Nano run has 167 Rust misses and one script miss; every warm run has 167 Rust hits and one script hit. Every repeated rlib, macro dylib, script launcher, original script executable, native object and archive matches its implementation's own cold reference. Tracked sources are unchanged. OS filesystem caches are unflushed; fetching, daemon startup and R2 are excluded. The direct warm-reference median is 14.460527s; compiler-cache cold wins do not imply beating direct compilation without cache bookkeeping.

The frozen default binary SHA-256 is `977ffde7c47c9ad024f0ae8219b3c0395729d7c99bbce919cacfc04e95daf2a0`. [Rust 1.97.1 checks](../benchmarks/default-pipelining-priority.json), [Rust 1.98.1 checks](../benchmarks/default-pipelining-priority-198.json) and [disabled-companion checks](../benchmarks/default-pipelining-disabled.json) preserve the real compiler evidence. Local unit tests, Linux cross-compilation and the full Rust/Zig integration suite pass. [Hosted CI for the default-runtime and live-capture commit](https://github.com/justrach/nanocompile/actions/runs/38064754357) passes on Ubuntu 24.04 and macOS 15, including real Rust 1.97.1/1.98.1 companion probes, stream forwarding, integration, build-script, native, Zig and Turbo checks. The [sanitized-report follow-up](https://github.com/justrach/nanocompile/actions/runs/38064876995) also passes on both platforms.

The [preceding guarded variation](pipelined-companions.md) also has five matched cold A/B wins and a verified real leaf/shared/revert sequence. Those source-edit points are single samples and use a different frozen binary with explicit flags; they are not repeated default-binary edit medians.

## Real source edits with the default binary

[The completed default-binary edit sequence](../benchmarks/harness-default-pipelining-source-edits.json) uses the same frozen `977ffd…` binary without streaming or companion overrides. These are single samples per point, with a separate empty-cache validation build for each tool at every edit/revert. Sources are changed only in a disposable Harness snapshot.

| Point | Nano | kache | Nano Rust hits / misses |
| --- | ---: | ---: | ---: |
| Initial cold | 15.371445s | 17.450059s | 0 / 167 |
| Leaf edit | 7.640419s | 8.144585s | 166 / 1 |
| Shared edit | 9.101730s | 9.623256s | 165 / 2 |
| Revert | 0.944173s | 1.833134s | 167 / 0 |

The linked probe returns 300 → 301 → 312 → 300. Every Nano Rust library, macro dylib and actual compiled script matches direct compilation. Each tool's history-cache outputs also match its fresh same-path outputs, including native objects/archives and Nano's copied script launcher plus original executable. The original project remains unchanged. Expected failed feature probes do not fail Cargo. Source-edit wins in this sequence supplement the repeated cold/warm results; they are not repeated edit medians.

The [current ordinary-compiler phase profile](default-phase-profile.md) attributes the remaining first-wave cold startup gap to identity/key preparation and gives reproducible instructions for the next variation. It is diagnostic evidence, excluded from the untraced performance figures above.

[Actual R2 refresh](default-pipelining-r2.md) verifies accepted default-runtime Harness and real Turborepo restores on hosted Linux/macOS machines. [Save phase attribution](save-phase-profile.md) identifies Rust graph collection as the next larger cold-path target; its decoder variation remains under test.
