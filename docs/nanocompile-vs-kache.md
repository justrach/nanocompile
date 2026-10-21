# nanocompile vs kache

Head-to-head as competing **build caches**, not as a single `RUSTC_WRAPPER`
genome. Occupancy of the size × edit MAP-Elites grid is unchanged. Bakeoff
rows are tagged `cache_tool=nanocompile|kache` and stay held-out.

Harness: `bench/compare_caches.py`. Isolated stores, apply/revert per run,
empty vs warm tagged, correctness gate is `cargo test` + LLVM rustc.
Raw rows: `bench/archive/cache-bakeoff.json`.

## Feature overlap

| nanocompile function | What it does | kache equivalent |
| --- | --- | --- |
| rustc wrapper cache | `RUSTC_WRAPPER=nanocompile` stores eligible `lib`/`rlib`/`rmeta` under a BLAKE3 CAS. As-shipped forces `CARGO_INCREMENTAL=0`. Best config: `NANOCOMPILE_ALLOW_INCREMENTAL=1` caches only `$CARGO_HOME/registry` and `$CARGO_HOME/git` crates. | `RUSTC_WRAPPER=kache`. Caches rustc and clippy-driver. Adaptive incremental stays on by default (`KACHE_ADAPTIVE_INCREMENTAL`). |
| Task graph / noop cache | `nanocompile task SPEC.json` and `nanocompile rust-loop`: explicit declared-file graph. `loop=graph` noop elites sit near 1–3 ms. | **No equivalent.** kache does not wrap cargo or skip a declared graph. |
| Artifact store + restore | Content-addressed `entries/` + `blobs/`. Restore: APFS `clonefile` / Linux `FICLONE`, then exclusive hardlink for immutable `.rlib`/`.rmeta`, then copy. Misses unlink read-only hardlinks before rustc runs. | CAS blobs + SQLite index. Restore: CoW clone, then exclusive hardlink for immutable `.rlib`/`.rmeta` (and Linux proc-macro / build-script binaries), then copy. |
| Cross-worktree reuse | Keys are `nanocompile-v9` with `$NANO_TARGET` / `$NANO_OUT` rewriting so sibling `CARGO_TARGET_DIR`s match. Registry/git source paths are shared via `CARGO_HOME`. Workspace sources stay path-absolute on restore. | Path-independent keys plus daemon prefetch of registry/git units from the last target built by the same rustc. Advertised sibling-worktree hit. |
| Build-script caching | Opt-in whole-script cache via `NANOCOMPILE_BUILD_SCRIPTS_FILE` (explicit input contract). Off by default. | Automatic build-script **run** cache on Linux/macOS (`KACHE_BUILD_SCRIPT_CACHE`, default on). Optional hermetic `OUT_DIR` (`KACHE_BUILD_SCRIPT_HERMETIC`). |
| C/C++ / Zig compile cache | `nanocompile cc`/`c++` portable object cache; `nanocompile clang` / `xcodebuild` native CAS on macOS; `nanocompile zig` for pure Zig emit. | `kache cc` / `CC=kache` / `kache init --shims`. Same local store as rustc. No Zig compiler cache. |
| Remote / shared cache | Explicit R2 snapshot transport (`tools/r2_cache.py`) and Turborepo `artifact put\|get\|head`. Not a per-invocation remote. | Daemon + S3/GCS/shared-filesystem/OCI remotes, prefetch, planner. Disabled here with `KACHE_LOCAL_ONLY=1` `KACHE_SCHEDULER=0`. |
| Cache stats / explain | `nanocompile stats` (hits, restore method, `restore_ns`), `NANOCOMPILE_TRACE=1`, task reports. | `kache stats --json`, `kache explain`, `kache monitor`, `kache list`. |
| Eviction | `nanocompile gc [MAX_BYTES]` (default 10 GiB logical blobs). Access-time order. | `kache clean`; daemon scheduled GC; store size limit. |
| Disk usage | `stats` logical blob bytes + `target/` from the harness. Hardlink restore does not duplicate `.rlib`/`.rmeta` bytes. | `kache stats` `disk.store_bytes` and `cloned_into_targets_bytes`. |

## Incremental fairness

| Config | nanocompile | kache |
| --- | --- | --- |
| As-shipped | `RUSTC_WRAPPER=nanocompile` `CARGO_INCREMENTAL=0`. Workspace and registry crates are both eligible. `nanocompile rust-loop run --wrapper` still forces incremental off unless `NANOCOMPILE_ALLOW_INCREMENTAL=1`. | Incremental on. Adaptive incremental isolates rapidly changing units. Local-only, no scheduler in this bakeoff. |
| Best allowed | Incremental on. Cache registry/git only; workspace crates pass through to rustc incremental. `NANOCOMPILE_PROC_MACROS=reported`. Path-normalized keys + hardlink restore. `-C incremental`, `-C link-arg`/`linker`, and nightly `-Z` flags are tracked so `cargo build`/`test` stay eligible. | Incremental on (same as shipped). Caches proc-macro dylibs, build-script runs, and (on Linux) executables. Warm store for emptied-target and sibling worktrees. |

Do not stack wrappers. sccache is out of this bakeoff.

## What changed in nanocompile

1. **Path-normalized keys (`nanocompile-v9`)** — `CARGO_TARGET_DIR` and `OUT_DIR` become `$NANO_TARGET` / `$NANO_OUT` in argv, cwd, and env. `NANOCOMPILE_*` and terminal variables are omitted so isolated stores and sibling worktrees can share registry/git hits.
2. **Hardlink restore** — after clonefile/FICLONE fails, immutable `.rlib`/`.rmeta` get an exclusive hardlink to the blob. The blob is then marked read-only. Misses unlink those outputs before rustc runs so a later compile can replace them.
3. **Incremental coexistence** — `-C incremental` is tracked. When incremental is on (or `NANOCOMPILE_CACHE_DEPS_ONLY=1`), workspace crates bypass the wrapper and rustc incremental owns the edit loop.
4. **Build/test eligibility** — nightly cargo's `-Z embed-metadata=no` and `-C link-arg`/`linker` no longer force a bypass, so `cargo build`/`test` can populate the store.

## Why kache still wins some cells

Worktree wall time now tracks emptied-target wall time for nanocompile (path keys work). The remaining emptied-target / worktree / `cargo clean` gap is coverage, not keying:

- **Proc-macro dylibs** stay ineligible on Linux (producer mode is macOS-only). serde_derive / axum / bhumi warm restores sit at 30–40% hit vs kache's ~100%.
- **Build-script runs** are opt-in contracts here; kache caches them by default.
- **Executables / test harnesses** stay ineligible; kache caches them on Linux. That is the hashbrown `cargo test` emptied-target gap (5.8 s vs 2.7 s).
- **Input prediction** — kache can skip the dep-info pre-pass; nanocompile rehashes every dependency on restore (hashbrown restore 8–22 ms).
- **Empty-store cold** — a fresh `NANOCOMPILE_DIR` still fingerprints the toolchain on first use (~3 s). kache's first rustc is cheaper.
- **Daemon prefetch** is off in this bakeoff (`KACHE_SCHEDULER=0`) but kache still restores a complete unit set.

Those cells are stalled for this hill-climb: further tries without those features stay well beyond 3%.

## Per-scenario win/loss

Best **ok** config of each tool. Winner is ≥3% faster. Times are median ms.

| Sample | Loop | Scenario | Winner | nanocompile | kache | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| rust-loop | check | empty_cold | kache | 81.4 best | 73.4 noinc | first-store identity vs incremental |
| rust-loop | check | warm_emptied_target | kache | 72.5 shipped | 43.5 shipped | 83% vs 100% hit |
| rust-loop | check | noop | stall | 11.1 best | 10.9 noinc | cargo noop |
| rust-loop | check | body | nanocompile | 24.8 shipped | 25.9 noinc | |
| rust-loop | check | sig_dep | kache | 25.3 shipped | 24.3 noinc | within a few ms |
| rust-loop | check | worktree | kache | 70.6 shipped | 44.0 noinc | keys hit; restore/coverage |
| rust-loop | check | cargo_clean | kache | 71.9 shipped | 43.8 noinc | |
| rust-loop | build | empty_cold | kache | 85.4 best | 70.9 noinc | |
| rust-loop | build | warm_emptied_target | kache | 73.8 shipped | 43.6 noinc | |
| rust-loop | build | body | nanocompile | 34.2 best | 40.6 noinc | incremental workspace |
| rust-loop | test | empty_cold | nanocompile | 238.6 best | 367.3 shipped | kache caches the harness |
| rust-loop | test | warm_emptied_target | kache | 226.9 shipped | 58.6 shipped | executable restore |
| rust-loop | test | body | nanocompile | 171.5 shipped | 185.5 noinc | |
| hashbrown | check | empty_cold | kache | 3340 best | 570 noinc | toolchain fingerprint |
| hashbrown | check | warm_emptied_target | kache | 130.1 shipped | 59.1 noinc | 83% vs 100% |
| hashbrown | check | noop | stall | 15.6 shipped | 15.7 noinc | |
| hashbrown | check | body | nanocompile | 58.0 shipped | 68.6 noinc | |
| hashbrown | check | sig_dep | stall | 65.7 shipped | 66.5 noinc | |
| hashbrown | check | worktree | kache | 133.6 shipped | 81.4 noinc | |
| hashbrown | check | cargo_clean | kache | 149.2 shipped | 60.0 shipped | |
| hashbrown | build | empty_cold | kache | 3294 shipped | 621 shipped | |
| hashbrown | build | warm_emptied_target | kache | 144.9 shipped | 56.6 shipped | |
| hashbrown | build | body | nanocompile | 137.0 best | 382.7 noinc | incremental workspace |
| hashbrown | test | empty_cold | kache | 9153 shipped | 6328 shipped | |
| hashbrown | test | warm_emptied_target | kache | 5783 shipped | 2689 noinc | test bins |
| hashbrown | test | body | kache | 4807 best | 3834 noinc | test bins |
| serde_derive | check | empty_cold | kache | 4949 best | 2144 noinc | |
| serde_derive | check | warm_emptied_target | kache | 1712 shipped | 91.1 noinc | proc-macro dylib |
| serde_derive | check | noop | kache | 19.9 best | 17.4 shipped | |
| serde_derive | check | body | nanocompile | 288.5 best | 887.0 noinc | incremental wins the edit |
| serde_derive | check | sig_dep | kache | 283.2 best | 214.3 noinc | |
| serde_derive | check | worktree | kache | 1888 shipped | 162 shipped | proc-macro |
| serde_derive | check | cargo_clean | kache | 1678 shipped | 91.2 noinc | |
| axum | check | empty_cold | kache | 10256 shipped | 7944 noinc | |
| axum | check | warm_emptied_target | kache | 6995 shipped | 346 noinc | 39% vs 100% |
| axum | check | body | kache | 125.9 best | 116.0 shipped | close |
| axum | check | worktree | kache | 7513 shipped | 1816 shipped | |
| axum | check | cargo_clean | kache | 7044 shipped | 341 noinc | |
| nalgebra | check | empty_cold | kache | 8839 shipped | 6354 noinc | |
| nalgebra | check | warm_emptied_target | kache | 6023 shipped | 157 shipped | |
| nalgebra | check | body | nanocompile | 791.7 best | 3201 noinc | 4× |
| nalgebra | check | worktree | kache | 5809 shipped | 512 shipped | |
| ripgrep | check | empty_cold | kache | 6650 best | 3396 noinc | |
| ripgrep | check | warm_emptied_target | kache | 2980 best | 183 noinc | |
| ripgrep | check | body | nanocompile | 164.5 best | 579.0 noinc | 3.5× |
| ripgrep | check | worktree | kache | 3762 best | 1086 noinc | |
| bhumi | check | empty_cold | kache | 14559 shipped | 11584 noinc | Rach repo |
| bhumi | check | warm_emptied_target | kache | 11671 shipped | 422 noinc | |
| bhumi | check | body | nanocompile | 288.8 best | 455.6 noinc | |
| bhumi | check | worktree | kache | 11473 shipped | 3874 noinc | |
| bhumi | check | cargo_clean | kache | 11629 shipped | 400 noinc | |
| ruff | check | warm_emptied_target | kache | 49704 shipped | 19604 shipped | 0% vs 50% hit; 403-crate workspace |
| ruff | check | body | kache | 20790 best | 1150 noinc | kache restores the proc-macro/dep closure |
| emergentDB | check | * | no-data | — | — | both tools `ok=false` (project does not check clean here) |

Body/sig on mid and large crates is where incremental coexistence pays: nanocompile's best config leaves the workspace crate to rustc and only caches deps. Emptied-target, worktree, and `cargo clean` stay with kache until proc-macro / build-script / executable coverage matches.

## Disk

On this host, kache's warm store is larger because it keeps proc-macro dylibs, build-script runs, and (on Linux) executables. nanocompile's store is the rlib/rmeta CAS only.

| Sample (check, warm) | nano store | nano target | kache store | kache target |
| --- | ---: | ---: | ---: | ---: |
| rust-loop | 8–25 KiB | 7–42 KiB | 3–8 KiB | 7–42 KiB |
| hashbrown | 1.4–4.1 MiB | 1.4–9.2 MiB | 1.4–3.2 MiB | 1.4–9.2 MiB |
| serde_derive | 0.36 MiB | 16–26 MiB | 16–17 MiB | 45–54 MiB |
| axum | 14–24 MiB | 105–165 MiB | 105 MiB | 133 MiB |
| nalgebra | 9.3 MiB | 78–153 MiB | 78–84 MiB | 106–179 MiB |
| ripgrep | 15–23 MiB | 71–104 MiB | 71 MiB | 100–110 MiB |
| bhumi | 13–16 MiB | 298–304 MiB | 298–371 MiB | 327–333 MiB |
| ruff | 99–101 MiB | 721–1225 MiB | 727 MiB | 750–767 MiB |

Restore cost on nanocompile hits is 0.3–22 ms (rehash + hardlink/copy). kache reports 2–8 ms hit elapsed; wall time is still lower because it restores more units and skips the pre-pass.
