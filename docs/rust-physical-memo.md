# Verified physical Rust installation identity

The cold Harness trace showed roughly one second of additional elapsed time across early Nano requests. The previous runtime creates 147 selection memos in a cold build because Cargo runs crates in different working directories and changes `DYLD_FALLBACK_LIBRARY_PATH`. Every memo queries and enumerates the same physical Rust installation. A direct stock compiler has already been selected; rustup ancestor overrides do not select it again.

The accepted optimization shares that installation identity only for the exact observed macOS arm64 Rust 1.97.1 compiler and driver bytes. It checks installed file content identities, verifies the direct canonical compiler path and the Mach-O startup load paths, and then omits ancestor rustup selector paths and the proven irrelevant fallback library path from this selection memo. Other selection variables stay keyed. The full compilation key still includes every environment value and argument. Each memo hit checks every installed-resource stamp; source dependencies and output blobs retain full content validation. No source metadata shortcut is introduced.

The same verified identity retains the compiler-reported default sysroot and target-libdir for eligible graph collection, avoiding repeated location queries. Explicit target/sysroot changes, native proxies, unrecognized versions and other loader policies retain the original live-query path. The byte pins are an eligibility gate, not a substitute for the complete installation resource identity. Recognized compiler updates invalidate through content/stamp checks, and unrecognized bytes fall back to normal selection. Rustup proxy invocations and raw Zig keep their existing selection logic.

| Session | Production baseline median | Candidate median | Candidate pair wins |
| --- | ---: | ---: | ---: |
| Three initial cold pairs | 18.658979s | 17.201776s | 3/3 |
| Three confirmation cold pairs | 19.094965s | 17.270596s | 3/3 |

That is a 7.8% median reduction in the first batch and 9.6% in confirmation. Compare within each row. All builds have 167 Rust and 24 native misses, zero hits and **193 artifacts identical to the first baseline output**. The candidate produces one full toolchain memo per build versus 147 for baseline. Both runs use the same stable Rust wrapper path and fixed production Clang wrapper, alternating order, empty Nano compiler caches and a deleted Cargo target every build. They disable Nano trace logging. Dependency fetching and OS filesystem cache flushing are excluded. No R2 is involved.

The real Harness adapters dirty-source snapshot is at commit `32b41cb0bff55e3c9cbfab3012acec2b179ad199`, Rust 1.97.1, stable Zig 0.17.0 and eight jobs. This is the release adapters library workload, not the complete Harness GUI build. Sources, manifests and lockfile remain unchanged. Sampling includes the runner's process tree and enforces a 40 GiB limit.

## Equal-settings kache comparison

Three alternating cold pairs and three rotating warm rounds compare the candidate with normal kache 1.0.0 (build-script execution caching enabled). Each tool must match its own cold Rust/producer/native bytes; kache's remapping prevents requiring cross-tool byte equality.

| Workload | Nano candidate median | Kache median | Nano pair wins |
| --- | ---: | ---: | ---: |
| Cold | 17.160262s | 17.059254s | 1/3 |
| Warm | 1.763895s | 1.305709s | 0/3 |

This **does not establish a kache win**. The cold difference is small and variable; the warm gap remains. Both caches are emptied and the private kache daemon restarted before every cold pair, outside timing. Every warm Nano build records 167 Rust and 24 native hits; kache records 187 local hits. Outputs match each implementation's own cold outputs and sources remain unchanged. These ordinary comparisons have no whole-build trace frontend.

The narrower production improvement is accepted; the overall goal of beating kache remains open. The [build-script ablation](kache-build-script-ablation.md) shows another source of work, but also shows that removing a long overlapping interval does not guarantee a corresponding whole-build gain.

## Reproduction and correctness evidence

- [Exact measured candidate patch against runtime 7e5d269](../benchmarks/experiments/rust-physical-memo.patch)
- [Alternating untraced A/B runner](../benchmarks/experiments/rust_physical_cold_pair.py)
- [First batch samples, hashes and source provenance](../benchmarks/harness-rust-physical-cold-first.json)
- [Confirmation samples, hashes and source provenance](../benchmarks/harness-rust-physical-cold-confirm.json)
- [Kache comparison including every artifact hash](../benchmarks/harness-rust-physical-kache.json)
- [Guard and source-edit fixture](../benchmarks/experiments/rust_physical_memo_check.py)
- [Guard results](../benchmarks/rust-physical-memo-check.json)
- [Loader/proxy/version fixture](../benchmarks/experiments/rust_physical_locations_check.py) and [results](../benchmarks/rust-physical-locations-check.json)

The guard fixture verifies sharing across two working directories, a new rustup override file and two fallback paths; native proxy and alternate loader refusal; exact direct-rustc output equality within each working directory; and same-size, preserved-mtime source edits/reverts with correct changed/restored outputs. Rust can legitimately embed working-directory information, so outputs across different working directories are not assumed identical. Unit tests and the real Rust/Zig integration suite pass for the candidate and production source. The production binary can differ from the isolated candidate binary because the Zig build roots differ; the measured stock case follows the same implementation. Production additionally requires the physical byte pin both when recording and reading location reuse and updates an adoption comment; this retains live graph queries for unrecognized compilers. Binary hashes are recorded separately.

## Actual Harness source edits

The [18-build source-edit sequence](../benchmarks/harness-rust-physical-source-edits.json) changes exported functions in the actual adapters leaf and proto shared dependency, then reverts them. Every history-cache result matches a fresh empty-cache build at the same paths, including Rust libraries, macro dylibs, executable producers and native objects/archives. Linked probes return 300 initially, 301 after the leaf edit, 312 after the shared edit and 300 after revert. Original source hashes remain unchanged; only a disposable snapshot is edited.

| Single observation | Nano | Kache |
| --- | ---: | ---: |
| Leaf edit | 8.479171s | 8.328533s |
| Shared edit | 9.615084s | 10.022096s |
| Revert | 1.730753s | 1.944427s |

These are **single samples**, not repeatable superiority evidence. Nano has one and two Rust misses for the respective edits; the revert restores all 167 Rust results plus 24 native results. The source runner now uses deterministic per-state unique function names because the existing dirty benchmark snapshot already contained probes from an earlier run. This avoids declaration collisions without modifying the original snapshot.

This sequence uses production build `b26f6e2f…` before the final conservative guard for unrecognized compiler location memos; the final `dca2d069…` build follows the same byte-pinned stock case. [Final production guards](../benchmarks/rust-physical-production-check.json), [loader/version checks](../benchmarks/rust-physical-production-locations-check.json), and [raw Zig preserved-mtime verification](../benchmarks/zig-physical-memo-preserved-mtime.json) record the final binary separately. Linux/macOS CI runs the new guard fixture where its byte-pinned architecture/compiler is available, and ordinary compiler tests cover fallback configurations.
