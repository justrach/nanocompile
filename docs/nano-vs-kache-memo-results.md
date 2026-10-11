# Nano versus kache after the memo hill-climb

Workload: the full Harness CLI release binary (1,237 Cargo units, 138 build-script runs) at the frozen dirty snapshot of commit `32b41cb0`, with Rust 1.97.1, eight jobs, pinned kache 1.0.0 (build-script caching on, private daemon) and the recorded native contract. Every build starts from an empty Cargo target. Each implementation's outputs are checked against its own cold reference, including permission modes, macro dylibs, build-script executables, native archives, the final executable and `--help`.

All runs shared one busy machine: unrelated processes kept the load average around 14–25. Treat every row as a single-machine observation, not independent confirmation.

## Results

| Study | Nano | kache | Nano pair wins |
| --- | ---: | ---: | ---: |
| Before (frozen eight-worker study), warm median | 7.772 s | 6.529 s | 0/3 |
| Before, cold median | 189.748 s | 186.549 s | 1/3 |
| Digest memo only, warm median | 7.506 s | 6.512 s | 0/3 |
| Digest memo only, cold median | 189.579 s | 202.502 s | 3/3 |
| + selection memo + declared build scripts, warm median | 6.445 s | 6.462 s | 2/3 |
| + selection memo + declared build scripts, cold median | 188.955 s | 190.351 s | 2/3 |
| + compact installed-tree memo, warm (6 pairs) | **6.350 s** | 6.676 s | **5/6** |
| + compact installed-tree memo, cold prime (1 build each) | 179.085 s | 190.906 s | — |

In the six-pair warm study, the paired kache-minus-Nano saving is 0.308 s on average, with a standard error of 0.132 s. Every warm build restores all 138 build-script runs. Nano records 1,095 compiler hits, three misses and five bypasses. kache records 1,237 local hits.

Source-edit results are in [the source-edit section](#source-edits).

Records:

- [digest memo study](../benchmarks/harness-digest-memo-kache-paired.json)
- [declared build-script study](../benchmarks/harness-declared-scripts-kache-paired.json)
- [warm-focused tree-memo study](../benchmarks/harness-treememo-warm-kache-paired.json)
- [paired statistics and verification](../benchmarks/harness-memo-kache-verification.json)

Every build log was rehashed with `tools/build_trace.py verify-logs`.

## What changed and why

Each step was chosen with [the profiler](rust-profiler.md):

1. The profiler showed that warm builds are throughput-bound: most of the critical path is waiting for job slots. Nano used 52.1 s of slot time against kache's 42.4 s. The diff attributed the gap to build-script runs, library hits, the final link and build-script compiles.
2. The [digest memo](digest-memo.md) stops re-hashing unchanged inputs and cached outputs on every hit. Rust-request CPU fell from 25 s to 13 s per warm build, and the final link request from 342 ms to 113 ms.
3. The [selection memo](digest-memo.md#selection-memo-srcnative_identityzig) removes four process spawns from each linking request (23 ms to 0.7 ms each).
4. [Declared build-script caching](declared-build-scripts.md) covers the 107 scripts outside the explicit contract, which previously ran live on every warm build.
5. A traced profile then showed the 31 contracted scripts queuing on an exclusive lock around a 3.8 MB JSON SDK-tree memo (112 ms per hit). The compact, lock-free [installed-tree memo](digest-memo.md#installed-tree-memo-srcidentityzig) removes that.

After step 5, Nano's warm slot time by category (medians of six builds) is:

| Category | Nano | kache |
| --- | ---: | ---: |
| libraries | 30.90 s | 31.73 s |
| build-script compiles | 3.54 s | 5.03 s |
| build-script runs | 8.91 s | 6.33 s |
| final binary | 0.07 s | 0.06 s |

Build-script runs remain the one category where kache is faster. Contracted scripts still re-validate about 16,000 SDK stamps per hit, and the remaining declared scripts pay about 13 ms more than kache. These are the next targets.

## Source edits

[`tests/harness_full_source_edits.py`](harness-full-source-edits.md) builds the same workload four times:

1. an initial cold build
2. an edit to the CLI description in `apps/harness/src/main.rs` (leaf)
3. an additional edit to the shared `version_triple` parser in `crates/proto/src/lib.rs` (shared)
4. a revert of both edits

Each edit is built with retained caches, then rebuilt with an empty cache at identical paths as a correctness reference. All 18 builds pass artifact, mode, CLI and linked-parser checks. Each scenario is a single sample.

| Scenario (sample 1) | direct | Nano | kache |
| --- | ---: | ---: | ---: |
| initial cold | 171.771 s | **172.725 s** | 186.753 s |
| leaf edit | 172.205 s | **76.888 s** | 82.014 s |
| shared edit | 173.184 s | 120.355 s | **117.344 s** |
| revert | 178.654 s | **6.607 s** | 13.357 s |

- **Leaf edit:** after a workspace change, kache spends 1.5–5.8 s restoring workspace crates that did not change (`harness-ui`, `harness-adapters`, `gpui`). This matches kache's documented dependency re-discovery after workspace edits. Nano restores them in under 0.1 s.
- **Revert:** Nano serves 10 variant hits from its bounded manifest history.
- **Shared edit:** the profiler attributes kache's 3.0 s lead entirely to one critical-path unit. `harness-ui` compiled in 30.24 s under Nano, against 25.1–25.7 s in every other build, including Nano's own cold and empty-cache builds. This looks like contention in one sample; a second sample is running.

[Record](../benchmarks/harness-source-edits-memo-kache.json); all 18 logs rehashed.
