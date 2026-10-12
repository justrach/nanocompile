# Rust workload coverage against kache

The [memo hill-climb](nano-vs-kache-memo-results.md) measured one workload: the full Harness CLI release build. Broadening the comparison to every Harness workspace package, the dev profile and a second, unrelated workspace (754 packages, fat LTO in release; called "workspace B" below) exposed build shapes Nano did not cache. Each one ran live on every warm build. These changes fixed them, in the order the profiler found them:

| Shape | Seen in | Before | Change |
| --- | --- | --- | --- |
| `-C split-debuginfo=unpacked` (Cargo's macOS dev profile) | every dev build | 694 crates bypassed; Harness CLI dev warm 137.6 s against kache's 6.1 s | Without debug info rustc writes no split-debug objects, so those requests cache normally. Libraries store their `<crate><hash>.*.rcgu.o` objects as extra outputs and restore them in place. |
| Contracted build script outside its recorded environment | dev builds (`DEBUG`, `OPT_LEVEL` differ) | `libsqlite3-sys` ran live for 13 s on the critical path | Falls back to declared caching, like an unlisted package. |
| Build script bundling its own static archive, plus a `#[link]` attribute | `psm`, `objc-sys`, `objc2-exception-helper` | 3 misses in every warm build | A static entry in the crate metadata is accepted when the command line names it with `-l static=NAME`. |
| rlib+staticlib with debug info | `tree-sitter-highlight` in dev | live, 0.9 s on the critical path | The debug-free restriction on the companion pair is lifted. |
| Debug binary with unpacked split debug info | final binaries in dev | live link, 2.6 s | Compiled in place in its real output directory, where a direct build puts it, so its debug map names the same objects. The link observer owns only that compile's objects and rustc's scratch directories. |
| Build script with a custom path (`build = "builder/main.rs"`) | `aws-lc-sys` | ran live for 14 s, and its non-reproducible archive invalidated every crate above it | Any `build_script_<stem>` crate is shimmed. |
| Build-script outputs in nested directories | `aws-lc-sys` (generated include tree) | uncacheable | Files are recorded by relative path. An empty directory still makes a run uncacheable. |
| Fat LTO executable | workspace B release | 181 s link on every warm build | Cached under the LTO producer opt-in. LTO executables now compile in place, which also makes thin-LTO output byte-identical to direct builds. |
| rlib+dylib(+staticlib) library, including Cargo's `-C prefer-dynamic` | `html2md` | live, 2.4 s on the critical path | An in-place producer for the dylib link. |
| Native search directories of upstream build scripts | every crate downstream of a `cc`-based `-sys` crate | a workspace B crate rehashed 422 C objects from `aws-lc-sys`'s `OUT_DIR` on every hit | When no static library is named with `-l static=` and the pinned compiler's metadata is readable, the snapshot is replaced by a store-time check that the crate's own native library list has no static entry (a static `#[link]` expanded from another crate's macro makes it uncacheable). |
| Hits contending in Cargo's `deps` directory | every warm build | eight concurrent 40-dependency hits used 4× the system time of the same hits run in turn | Restores clone straight into place instead of a temporary name, two unlinks and a rename, and record the digest memo from the open file. System time for that batch: 191 ms to 144 ms. Split-debug objects skip the memo record; parallel digest workers keep one arena each. |

Every change has a test against real rustc that compares outputs with a direct build: `tests/split_debug_cache.py`, `tests/rust_dylib_cache.py`, `tests/staticlib_companions.py`, `tests/native_metadata_cache.py`, `tests/build_script_declared.py` and `tests/executable_cache.py --thin-lto`.

## Findings about the measurements themselves

- **kache does not restore split-debug objects.** In every warm dev build of the Harness CLI, kache's output lacked 2,343 `.rcgu.o` files that its own cold build produced. Most are library objects that nothing reads (a binary's debug map refers to library code through `rlib` members), but they include the final `harness` binary's own objects, which its debug map names, so a debugger finds no debug info for the main crate. The comparison runner's `--record-kache-mismatches` records the mismatch instead of stopping. Nano's warm dev builds match its cold builds file for file.
- **Concurrent restores make an isolated benchmark misleading.** Restoring a hit's files with four workers made an isolated debug hit 21% faster but a full warm dev build 0.4 s slower, because every job slot already runs a hit. It was reverted.
- **Some native archives are not reproducible.** In workspace B, `ar`/`ranlib` archives built by `cc`-based build scripts differ between two direct builds (symbol-table timestamp and padding bytes), so a cold-to-cold artifact check cannot pass for any tool. Warm builds restore the cold build's archives exactly. The workspace B cold comparison therefore uses a cold-only study without the native-archive check.

## Final comparison

One binary (commit `4e2a93f`) against pinned kache 1.0.0, Rust 1.97.1, eight Cargo jobs, empty target before every build, alternating order. Every warm build matches its own cold build's libraries, modes, macro dylibs, build-script executables, native outputs and final executable (kache's warm dev builds are recorded as missing split-debug objects). All logs rehash.

| Workload | Profile | Cold: Nano / kache (wins) | Warm: Nano / kache median (wins) |
| --- | --- | ---: | ---: |
| Harness CLI | release | 170.2 / 178.9 s (2/2) | 5.80 / 5.91 s (4/4) |
| Harness CLI | dev | 199.4 / 259.6 s (2/2) | 5.08 / 5.76 s (4/4) |
| `harness-ui` library | release | 103.7 / 113.1 s (2/2) | 5.71 / 5.89 s (3/4) |
| `harness-adapters` library | release | 15.2 / 16.8 s (2/2) | 0.80 / 1.18 s (4/4) |
| workspace B | release | 256.8 / 263.2 s (3/3) | 3.23 / 3.49 s (3/4) |
| workspace B | dev | 56.3 / 71.8 s (3/3) | 3.33 / 3.81 s (4/4) |

A complete Harness source-edit sample (initial cold, leaf edit, shared-parser edit, revert, each with an empty-cache reference that matches) favors Nano in every scenario: 170.6 / 181.0 s, 73.1 / 80.4 s, 113.1 / 117.1 s and 6.2 / 15.8 s. Six alternating shared-edit pairs give Nano 4 of 6 (median 111.8 / 113.3 s, mean saving 1.68 ± 0.89 s). The two losses are by 0.1 s and 0.7 s in pairs where kache's dylib assessment did not stall: Nano's six builds took 111.4–112.7 s, kache's 111.7–115.7 s.

Not every pair is a win. `harness-ui` warm lost one pair of four (by 0.12 s), workspace B release warm one of four (by 0.63 s), and the shared edit two of six (by 0.1 s and 0.7 s). All runs are on one busy Mac.

Records: [Harness CLI release](../benchmarks/final-harness-cli-release-kache.json), [Harness CLI dev](../benchmarks/final-harness-cli-dev-kache.json), [`harness-ui`](../benchmarks/final-harness-ui-kache.json), [`harness-adapters`](../benchmarks/final-harness-adapters-kache.json), [source edits](../benchmarks/final-harness-source-edits-kache.json), [shared-edit pairs](../benchmarks/final-harness-shared-edit-pairs.json), [workspace B (summary without paths or crate names)](../benchmarks/workspace-b-kache-comparison.json).

## Re-measurement after the store-path work

Four later changes shortened Nano's work on the critical path of a miss: binary-searched library candidates, parallel BLAKE3 for files of 32 MiB or more, digest reuse within one entry, and reading an rlib's dependency graph directly instead of asking rustc. Together they cut the Harness UI library's store from 229 ms to 144 ms and the final binary's from 382 ms to 265 ms. With that binary, six pairs each:

| Comparison | Nano median | kache median | Nano wins | Losing margins |
| --- | ---: | ---: | ---: | --- |
| `harness-ui` warm | 5.60 s | 5.84 s | 5/6 | 0.07 s |
| workspace B release warm | 3.17 s | 3.64 s | 5/6 | 0.07 s |
| Harness shared-parser edit | 115.7 s | 116.4 s | 3/6 | 0.2, 1.0, 0.1 s |

The shared-edit run coincided with two macOS background services using a full core each (load around 11): both tools' builds were 3–4 s slower than in the earlier runs and varied by ±2 s. Nano had no frontend stall in any build. The shared edit is almost entirely identical rustc work, so pairs in which kache does not stall are decided by that noise.

Records: [`harness-ui`](../benchmarks/remeasure-harness-ui-kache.json), [shared-edit pairs](../benchmarks/remeasure-harness-shared-edit-pairs.json), [workspace B (summary)](../benchmarks/workspace-b-remeasure.json).
