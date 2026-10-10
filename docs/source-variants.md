# Bounded compiler source variants

Real source edits exposed a large [revert gap](harness-source-edits.md): Nano recompiled two crates, taking 11.981 s, while kache restored the reverted state in 2.058 s. Ordinary command keys partition compiler identity, full environment, host, arguments and cwd; the single dependency manifest previously replaced the preceding source state.

The compiler path now retains the current sealed manifest plus three previous manifests for each command key. Unchanged primary hits use the same lookup and full validation path. A primary miss probes at most three fixed historical slots. Every candidate must validate its complete file contents, directory/library observations, negative lookups, symlinks, destination paths and output/diagnostic blobs before restoration. A historical hit records `variant_hit` alongside the ordinary `hit` event. This changes reuse across source states, not compiler eligibility or key identity.

History slots use domain-separated 64-character digest keys and ordinary sealed entries. The existing GC reference accounting, maintenance/key/output locks, clear operation and R2 snapshot format apply. There is no separate index or untracked blob reference. History is bounded to three preceding stored manifests, rather than an unlimited set of source versions. Repeated or corrupt states may occupy slots; corruption always undergoes normal validation and can become a miss. Existing single-manifest caches remain readable.

Stores rotate the prior sealed manifest under the caller’s existing command lock, before atomically replacing the primary. Cold misses perform three extra absent-entry probes; ordinary primary hits add no historical probes. Retaining history uses additional metadata and may keep more output blobs alive until GC. This is an edit/revert reuse optimization, not a claim of faster cold compilation.

Unit tests cover five source states, oldest-state eviction, historical output corruption and refused destination changes without writes. Real Rust integration checks preserved-mtime source reverts and linked native directory state reversions, alongside the existing invalidation, corruption, concurrency, GC, isolation and compiler failure checks. A valid historical duplicate may recover a damaged primary; corruption tests therefore invalidate all candidates when requiring a miss.

The source-edit runner excludes unrelated nested `.worktrees`, Git internals, target directories and node_modules from disposable snapshots, while retaining the project’s tracked sources and ordinary nonignored source files. Original tracked source/manifests and lockfile hashes are checked after the run. The snapshot copy no longer replicates tens of gigabytes of unrelated nested checkouts.

## Verified Harness comparison

Runtime source `65501a4` is built with stable Zig 0.17.0. The same disposable real-source edit runner measures the same tracked source/manifests as the earlier report, with Rust 1.97.1, release thin-LTO settings, four jobs and explicit reported-macro/Apple producer/native policies. Exact tool and runner digests, all samples and artifact checks are in the [raw report](../benchmarks/harness-source-variants-verified.json).

| Clean-target scenario | Direct (s) | Nano (s) | kache (s) |
| --- | ---: | ---: | ---: |
| initial | 25.168 | 28.174 | 27.032 |
| leaf-edit | 22.778 | 10.523 | 10.136 |
| shared-edit | 24.201 | 12.516 | 11.556 |
| revert | 24.657 | 2.078 | 2.238 |

The revert records 167 Rust hits, 24 native hits, two historical `variant_hit` observations and zero compile misses. Its previous two Rust recompilations are eliminated. Revert time falls from the earlier 11.981 s to 2.078 s; kache takes 2.238 s in the new session. These before/after timings come from separate sessions and are not a paired statistical experiment. The semantic evidence is the two historical restores and complete matching artifact/behavior checks. The new small lead over kache is one sample.

Kache still leads the initial cold, new leaf edit and new shared edit. Cold Nano is 28.174 s versus 27.032 s kache. Every edited Nano/kache result matches its own same-path empty-cache rlibs, macro dylibs, build-script executables and native object hashes. All 18 builds pass linked probes (300, 301, 312, 300), and both source-unchanged assertions pass. No R2 network transfer is timed.

Each point is a single sample. Cargo targets are deleted before every build; compiler cache history is retained for timed edits, and the extra empty-cache correctness references do not pollute that history. This remains a CI-style clean-target source-edit workload, not a retained-target incremental developer loop. The machine is not locked against unrelated activity, and OS file caches are not flushed. Full reproducibility flags are given in the [earlier source-edit methodology](harness-source-edits.md).

The updated metadata-priority, proc-macro producer and executable producer fixtures also pass locally; [raw correctness reports](../benchmarks/source-variant-checks/) include binary/fixture hashes and loaded behavior. These tests require fresh native/source changes to miss, and explicitly damage every candidate when requiring corruption repair through recompilation.

Full [Linux/macOS CI](https://github.com/justrach/nanocompile/actions/runs/38038907985) passes on `790999c` (runtime unchanged from `65501a4`), including unit/compiler integration, updated metadata/producer fixtures, portable C/C++ checks and Turbo/task checks. Earlier CI attempts surfaced assertions that required misses for now-valid reverts; the final tests require the validated historical hits and retain new-state/corruption rejection checks.
