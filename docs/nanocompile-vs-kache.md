# nanocompile vs kache

Head-to-head as competing **build caches**, not as a single `RUSTC_WRAPPER`
genome. Occupancy of the size × edit MAP-Elites grid is unchanged. Bakeoff
rows are tagged `cache_tool=nanocompile|kache` and stay held-out.

Harness: `bench/compare_caches.py`. Isolated stores, apply/revert per run,
empty vs warm tagged, correctness gate is `cargo test` + LLVM rustc.
Raw rows: `bench/archive/cache-bakeoff.json`.

Best **ok** config of each tool. Winner is ≥3% faster. After the Linux
producer / logical-restore hill-climb: **nanocompile 35, kache 23, stall 5,
no-data 3** (66 cells).

## Feature overlap

| nanocompile function | What it does | kache equivalent |
| --- | --- | --- |
| rustc wrapper cache | `RUSTC_WRAPPER=nanocompile` stores eligible `lib`/`rlib`/`rmeta` under a BLAKE3 CAS. As-shipped forces `CARGO_INCREMENTAL=0`. Best config: `NANOCOMPILE_ALLOW_INCREMENTAL=1` keeps rustc incremental on misses and still caches workspace rlibs so emptied-target can restore them. `NANOCOMPILE_CACHE_DEPS_ONLY=1` is the opt-in that bypasses workspace rlibs. | `RUSTC_WRAPPER=kache`. Caches rustc and clippy-driver. Adaptive incremental stays on by default (`KACHE_ADAPTIVE_INCREMENTAL`). |
| Task graph / noop cache | `nanocompile task SPEC.json` and `nanocompile rust-loop`: explicit declared-file graph. `loop=graph` noop elites sit near 1–3 ms. | **No equivalent.** kache does not wrap cargo or skip a declared graph. |
| Artifact store + restore | Content-addressed `entries/` + `blobs/`. Restore: APFS `clonefile` / Linux `FICLONE`, then exclusive hardlink for immutable `.rlib`/`.rmeta`/`.so`/`.dylib`, then copy. Output and input paths under `CARGO_TARGET_DIR` are stored as `$NANO_TARGET` so a sibling or emptied target can restore. Misses unlink read-only hardlinks before rustc runs. | CAS blobs + SQLite index. Restore: CoW clone, then exclusive hardlink for immutable `.rlib`/`.rmeta` (and Linux proc-macro / build-script binaries), then copy. |
| Cross-worktree reuse | Keys are `nanocompile-v9` with `$NANO_TARGET` / `$NANO_OUT` rewriting so sibling `CARGO_TARGET_DIR`s match. Stored dep/output paths use the same tokens. Registry/git source paths are shared via `CARGO_HOME`. | Path-independent keys plus daemon prefetch of registry/git units from the last target built by the same rustc. Advertised sibling-worktree hit. |
| Build-script caching | Opt-in whole-script cache via `NANOCOMPILE_BUILD_SCRIPTS_FILE` (explicit input contract). Off by default. Best config caches the **compile** of `build_script_build` as a host binary; it does not skip the **run**. | Automatic build-script **run** cache on Linux/macOS (`KACHE_BUILD_SCRIPT_CACHE`, default on). Optional hermetic `OUT_DIR` (`KACHE_BUILD_SCRIPT_HERMETIC`). |
| C/C++ / Zig compile cache | `nanocompile cc`/`c++` portable object cache; `nanocompile clang` / `xcodebuild` native CAS on macOS; `nanocompile zig` for pure Zig emit. | `kache cc` / `CC=kache` / `kache init --shims`. Same local store as rustc. No Zig compiler cache. |
| Remote / shared cache | Explicit R2 snapshot transport (`tools/r2_cache.py`) and Turborepo `artifact put\|get\|head`. Not a per-invocation remote. | Daemon + S3/GCS/shared-filesystem/OCI remotes, prefetch, planner. Disabled here with `KACHE_LOCAL_ONLY=1` `KACHE_SCHEDULER=0`. |
| Cache stats / explain | `nanocompile stats` (hits, restore method, `restore_ns`), `NANOCOMPILE_TRACE=1`, task reports. | `kache stats --json`, `kache explain`, `kache monitor`, `kache list`. |
| Eviction | `nanocompile gc [MAX_BYTES]` (default 10 GiB logical blobs). Access-time order. | `kache clean`; daemon scheduled GC; store size limit. |
| Disk usage | `stats` logical blob bytes + `target/` from the harness. Hardlink restore does not duplicate `.rlib`/`.rmeta`/`.so` bytes. | `kache stats` `disk.store_bytes` and `cloned_into_targets_bytes`. |

## Incremental fairness

| Config | nanocompile | kache |
| --- | --- | --- |
| As-shipped | `RUSTC_WRAPPER=nanocompile` `CARGO_INCREMENTAL=0`. Workspace and registry crates are both eligible. `nanocompile rust-loop run --wrapper` still forces incremental off unless `NANOCOMPILE_ALLOW_INCREMENTAL=1`. Producer flags stay off. | Incremental on. Adaptive incremental isolates rapidly changing units. Local-only, no scheduler in this bakeoff. |
| Best allowed | Incremental on. Cache workspace and registry/git units. `NANOCOMPILE_PROC_MACROS=reported`, `NANOCOMPILE_PROC_MACRO_PRODUCERS=1`, `NANOCOMPILE_EXECUTABLE_PRODUCERS=1`. Linux/debug proc-macro `.so` and host binaries use the ordinary dep-info store; Darwin `debuginfo=0` still uses the linker observer. Path-normalized keys + logical `$NANO_TARGET` restore + hardlink. `-C incremental`, `-C link-arg`/`linker`, and nightly `-Z` flags are tracked. | Incremental on (same as shipped). Caches proc-macro dylibs, build-script **runs**, and (on Linux) executables. Warm store for emptied-target and sibling worktrees. |

Do not stack wrappers. sccache is out of this bakeoff.

## What changed in nanocompile

1. **Path-normalized keys (`nanocompile-v9`)** — `CARGO_TARGET_DIR` and `OUT_DIR` become `$NANO_TARGET` / `$NANO_OUT` in argv, cwd, and env. `NANOCOMPILE_*` and terminal variables are omitted so isolated stores and sibling worktrees can share hits.
2. **Logical restore** — stored dependency and output paths use those same tokens. Restore expands them against the current `CARGO_TARGET_DIR`, so emptied-target and sibling worktrees hit the same entry. Realpath aliases of the target dir are rewritten too.
3. **Hardlink restore** — after clonefile/FICLONE fails, immutable `.rlib`/`.rmeta`/`.so`/`.dylib` get an exclusive hardlink to the blob. The blob is then marked read-only. Misses unlink those outputs before rustc runs so a later compile can replace them.
4. **Incremental coexistence** — `-C incremental` is tracked. Incremental on a miss still uses rustc incremental. Workspace rlibs stay cacheable so emptied-target can restore them. `NANOCOMPILE_CACHE_DEPS_ONLY=1` is the explicit bypass for workspace rlibs.
5. **Linux / debug producers** — `NANOCOMPILE_PROC_MACRO_PRODUCERS=1` caches host `lib*.so` through rustc dep-info (not the Darwin observer). `NANOCOMPILE_EXECUTABLE_PRODUCERS=1` caches host binaries the same way. Workspace macros/bins are not bypassed when those flags are set.
6. **Store without a complete rustc metadata graph** — incremental `cargo check` writes rmeta under `build/*/out` and can omit `-L dependency`. `UnresolvedRustDependency` no longer drops the unit; dep-info + externs are enough to store.
7. **Build/test eligibility** — nightly cargo's `-Z embed-metadata=no` and `-C link-arg`/`linker` no longer force a bypass, so `cargo build`/`test` can populate the store.

## Why kache still wins some cells

Logical restore plus producers flipped emptied-target / worktree / `cargo clean` on rust-loop, hashbrown, serde_derive, and nalgebra. Remaining kache cells are coverage, not keying:

- **Build-script runs** stay opt-in contracts here; kache caches the run by default. That is the axum / ripgrep / bhumi emptied-target and `cargo clean` gap (nano ~0.7–1.5 s vs kache ~0.2–0.4 s) even at 97–99% rustc hit.
- **Test harnesses / extra bins** — rust-loop and hashbrown `cargo test` emptied-target still lose (193 vs 61 ms; 4.7 vs 2.7 s). kache restores the harness; nanocompile's executable producer does not cover every test bin layout.
- **Input prediction** — kache can skip the dep-info pre-pass; nanocompile rehashes every dependency on restore.
- **Empty-store cold on tiny crates** — a fresh `NANOCOMPILE_DIR` still fingerprints the toolchain on first use. rust-loop check empty_cold is 146 vs 72 ms. Larger crates now match or beat kache on empty_cold (axum, nalgebra, ripgrep, bhumi, hashbrown check stall).
- **Daemon prefetch** is off in this bakeoff (`KACHE_SCHEDULER=0`).
- **ruff** rows in the archive are from the pre-climb pass (0% nano hit on emptied-target). Not re-raced after logical restore.

Those remaining cells are stalled for this hill-climb without a default build-script **run** cache and broader test-bin coverage.

## Per-scenario win/loss

Best **ok** config of each tool. Times are median ms.

| Sample | Loop | Scenario | Winner | nanocompile | kache | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| rust-loop | check | empty_cold | kache | 146 shipped | 72 noinc | first-store identity |
| rust-loop | check | warm_emptied_target | nanocompile | 32.7 best | 43.7 noinc | 100% hit |
| rust-loop | check | noop | kache | 11.1 shipped | 10.7 noinc | cargo noop |
| rust-loop | check | body | nanocompile | 13.3 best | 25.7 noinc | |
| rust-loop | check | sig_dep | nanocompile | 12.0 best | 25.6 noinc | |
| rust-loop | check | worktree | nanocompile | 31.8 best | 46.6 noinc | logical restore |
| rust-loop | check | cargo_clean | nanocompile | 32.7 best | 44.7 shipped | |
| rust-loop | build | empty_cold | kache | 160 best | 77.6 shipped | |
| rust-loop | build | warm_emptied_target | nanocompile | 33.6 best | 44.5 shipped | |
| rust-loop | build | noop | stall | 11.1 best | 11.0 shipped | |
| rust-loop | build | body | nanocompile | 13.8 best | 29.0 noinc | |
| rust-loop | build | sig_dep | nanocompile | 13.2 shipped | 28.0 noinc | |
| rust-loop | build | worktree | nanocompile | 32.9 shipped | 44.2 shipped | |
| rust-loop | build | cargo_clean | nanocompile | 33.5 best | 45.0 shipped | |
| rust-loop | test | empty_cold | nanocompile | 218 shipped | 396 noinc | kache stores the harness |
| rust-loop | test | warm_emptied_target | kache | 193 shipped | 61.4 noinc | test bin restore |
| rust-loop | test | body | kache | 172 shipped | 45.7 noinc | test bin |
| hashbrown | check | empty_cold | stall | 576 shipped | 569 shipped | |
| hashbrown | check | warm_emptied_target | nanocompile | 40.4 best | 58.1 shipped | 100% hit |
| hashbrown | check | noop | stall | 14.9 best | 14.9 noinc | |
| hashbrown | check | body | nanocompile | 19.9 shipped | 68.1 noinc | |
| hashbrown | check | sig_dep | nanocompile | 18.7 best | 69.4 noinc | |
| hashbrown | check | worktree | nanocompile | 45.8 best | 81.1 noinc | |
| hashbrown | check | cargo_clean | nanocompile | 44.2 best | 58.6 shipped | |
| hashbrown | build | empty_cold | kache | 677 shipped | 643 noinc | |
| hashbrown | build | warm_emptied_target | nanocompile | 43.4 best | 55.8 noinc | |
| hashbrown | build | body | nanocompile | 20.3 shipped | 67.7 noinc | |
| hashbrown | build | worktree | nanocompile | 41.1 shipped | 82.3 noinc | |
| hashbrown | test | empty_cold | stall | 6389 shipped | 6554 noinc | |
| hashbrown | test | warm_emptied_target | kache | 4691 shipped | 2732 noinc | test bins |
| hashbrown | test | body | kache | 3183 best | 2752 noinc | test bins |
| serde_derive | check | empty_cold | kache | 4949 best | 2144 noinc | pre-climb empty_cold row |
| serde_derive | check | warm_emptied_target | nanocompile | 63.1 best | 87.3 noinc | producers + logical restore |
| serde_derive | check | body | nanocompile | 21.3 best | 205 noinc | 10× |
| serde_derive | check | worktree | nanocompile | 67.0 best | 165 noinc | |
| serde_derive | check | cargo_clean | nanocompile | 62.9 best | 84.1 shipped | |
| axum | check | empty_cold | nanocompile | 7332 shipped | 7805 noinc | |
| axum | check | warm_emptied_target | kache | 731 best | 350 noinc | build-script run |
| axum | check | body | kache | 215 best | 123 noinc | |
| axum | check | worktree | nanocompile | 675 best | 1696 noinc | |
| axum | check | cargo_clean | kache | 701 best | 337 shipped | build-script run |
| nalgebra | check | empty_cold | nanocompile | 5722 shipped | 6927 shipped | |
| nalgebra | check | warm_emptied_target | nanocompile | 145 best | 164 shipped | |
| nalgebra | check | body | nanocompile | 85.3 best | 306 noinc | 3.6× |
| nalgebra | check | worktree | nanocompile | 155 best | 517 shipped | |
| nalgebra | check | cargo_clean | nanocompile | 147 best | 161 noinc | |
| ripgrep | check | empty_cold | nanocompile | 3255 shipped | 3475 shipped | |
| ripgrep | check | warm_emptied_target | kache | 932 best | 184 shipped | build-script run |
| ripgrep | check | body | kache | 166 best | 132 noinc | |
| ripgrep | check | worktree | nanocompile | 943 best | 984 shipped | |
| ripgrep | check | cargo_clean | kache | 918 best | 189 shipped | |
| bhumi | check | empty_cold | nanocompile | 11250 shipped | 12881 noinc | Rach repo |
| bhumi | check | warm_emptied_target | kache | 1527 best | 421 shipped | build-script run |
| bhumi | check | body | kache | 622 best | 189 noinc | |
| bhumi | check | worktree | kache | 1528 best | 653 noinc | |
| bhumi | check | cargo_clean | kache | 1541 best | 434 noinc | |
| ruff | check | warm_emptied_target | kache | 49704 shipped | 19604 shipped | pre-climb; 0% vs 50% hit |
| ruff | check | body | kache | 20790 best | 1150 noinc | pre-climb |
| emergentDB | check | * | no-data | — | — | both tools `ok=false` |

## Disk

On this host, kache's warm store is larger when it keeps proc-macro dylibs,
build-script runs, and (on Linux) executables. After producers + logical
restore, nanocompile-best stores are in the same range as kache for rustc
artifacts (serde ~16 MiB both; nalgebra ~77–98 vs 77 MiB).

| Sample (check, warm, best/shipped) | nano store | nano target | kache store | kache target |
| --- | ---: | ---: | ---: | ---: |
| rust-loop | 6–22 KiB | 7–42 KiB | 3–8 KiB | 7–42 KiB |
| hashbrown | 1.4–4.1 MiB | 1.4–9.2 MiB | 1.4–3.2 MiB | 1.4–9.2 MiB |
| serde_derive | 16 MiB | 16 MiB | 16–17 MiB | 45–54 MiB |
| axum | 100–107 MiB | 104 MiB | 104 MiB | 133 MiB |
| nalgebra | 77–98 MiB | 77 MiB | 77–84 MiB | 105–178 MiB |
| ripgrep | 67–69 MiB | 81 MiB | 71 MiB | 99–109 MiB |
| bhumi | 272 MiB | 301 MiB | 295–368 MiB | 324–330 MiB |

Restore cost on nanocompile hits is 0.2–8 ms (rehash + hardlink/copy). kache
reports 2–20 ms hit elapsed on large graphs.
