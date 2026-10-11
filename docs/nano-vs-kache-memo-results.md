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
| Final cold/warm study at that point, cold median | **174.055 s** | 186.655 s | 3/3 |
| Final cold/warm study at that point, warm median (calmer host) | 6.162 s | **5.955 s** | 1/3 |
| + text build-script shims, warm (6 pairs) | **6.228 s** | 6.593 s | **5/6** |
| + text build-script shims, cold prime (1 build each) | 174.984 s | 187.569 s | — |

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

Build-script runs remained the one category where kache was faster. On a calmer host the final cold/warm study showed why. Nano's warm build-script slot time was 9.53 s against kache's 5.24 s, and the profiler placed the excess on the first wave of scripts (0.28–0.32 s each against 0.02–0.18 s). macOS assesses every newly created executable on its first exec, and Cargo copies each shim to a new inode. The [text shims](declared-build-scripts.md#text-shims) make the kernel run the already-validated Nano binary instead, which cut build-script slot time to 6.48 s (kache 5.65 s). The next warm study won 5 of 6 pairs.

## Source edits

[`tests/harness_full_source_edits.py`](harness-full-source-edits.md) builds the same workload four times:

1. an initial cold build
2. an edit to the CLI description in `apps/harness/src/main.rs` (leaf)
3. an additional edit to the shared `version_triple` parser in `crates/proto/src/lib.rs` (shared)
4. a revert of both edits

Each edit is built with retained caches, then rebuilt with an empty cache at identical paths as a correctness reference. Five complete samples (90 builds) pass every artifact, mode, CLI and linked-parser check. All logs are rehashed.

| Scenario | Nano (5 samples) | kache (5 samples) | Nano median | kache median | Nano wins |
| --- | --- | --- | ---: | ---: | ---: |
| initial cold | 172.7, 172.1, 170.4, 169.9, 180.7 | 186.8, 186.1, 183.0, 182.9, 192.3 | **172.1 s** | 186.1 s | 5/5 |
| leaf edit | 76.9, 75.2, 75.3, 75.5, 88.4 | 82.0, 80.8, 80.2, 80.2, 82.0 | **75.5 s** | 80.8 s | 4/5 |
| shared edit | 120.4, 119.1, 119.8, 118.7, 118.9 | 117.3, 115.8, 117.0, 115.4, 117.8 | 119.1 s | **117.0 s** | 0/5 |
| revert | 6.6, 6.2, 6.4, 5.9, 6.3 | 13.4, 13.5, 13.5, 13.1, 13.7 | **6.3 s** | 13.5 s | 5/5 |

- **Initial cold and revert:** Nano is about 7% faster on cold builds and twice as fast on the revert, where its bounded manifest history serves 10 variant hits.
- **Leaf edit:** kache spends 1.5–5.8 s restoring workspace crates that did not change after a workspace edit, matching its documented dependency re-discovery. Nano restores them in under 0.1 s.
- **Position effect:** in sample 5 the rotation was shifted. Nano built the leaf edit first and lost it, with its final link 13 s slower than in any other position. Whichever implementation builds first after the large reference-cache cleanup pays a host-level penalty, so per-scenario comparisons need more than one rotation.

### The shared edit is still a loss

In all five samples, kache's shared-edit lead comes from one critical-path unit. Medians of the critical-path compiles:

| Unit | direct | kache | Nano |
| --- | ---: | ---: | ---: |
| `harness-proto` | 3.39 s | 2.75 s | 2.65 s |
| `harness-adapters` | 14.45 s | 12.22 s | 11.79 s |
| `harness-engine` | 18.24 s | 18.12 s | 17.98 s |
| `harness-ui` | 24.59 s | 25.94 s | **29.25 s** |
| final binary | 65.62 s | 67.64 s | 67.45 s |

What was ruled out ([details](../benchmarks/harness-shared-edit-diagnostic.json)):

- **Nano bookkeeping:** probing, storing and graph collection add about 0.3 s to the `harness-ui` miss.
- **Restored files and their page cache:** recompiling `harness-ui` takes 25.0–25.9 s whether its inputs are Nano-restored clones, byte copies or pre-read.
- **kache's daemon:** stopping it during Nano builds did not change the result.
- **Jobserver inheritance and thread priority:** rustc launched through Nano joins Cargo's jobserver and runs at the same priority.
- **Build position:** shifting the rotation narrowed the gap to 1.1 s but did not remove it.

The slow rustc is compute-bound: samples show ordinary type checking and LLVM work. It does the same user CPU in more wall time, which suggests it gets fewer codegen threads or less CPU. Outside the study, a cloned reproduction with Nano as the direct wrapper shows `harness-ui` at 25.6 s on the first shared edit, and 28.8 s or more on later distinct edits. The cause is not yet identified, and Nano does not yet beat kache on this scenario.

Records: [sample 1](../benchmarks/harness-source-edits-memo-kache.json), [2](../benchmarks/harness-source-edits-memo-kache-2.json), [3](../benchmarks/harness-source-edits-memo-kache-3.json), [4](../benchmarks/harness-source-edits-memo-kache-4.json), [5](../benchmarks/harness-source-edits-memo-kache-5.json).
