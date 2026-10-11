# Source-edit observations

One source-edit sequence; single observations, not repeated medians or a proven speedup. Fresh references are correctness checks. Build logs establish console integrity, not per-request attribution. No compiler critical path or cause is inferred from cache counts.

Session: complete

| Case | Phase | Direct (s) | Nano (s) | kache (s) | Nano − kache (s) |
| --- | --- | ---: | ---: | ---: | ---: |
| initial | cold | 173.467 | 179.538 | 190.191 | -10.653 |
| leaf-edit | edit | 176.218 | 80.084 | 82.096 | -2.012 |
| shared-edit | edit | 173.087 | 125.122 | 117.312 | +7.810 |
| revert | edit | 172.655 | 7.802 | 13.448 | -5.646 |

## Instructions for the next variation

1. Preserve this report hash, frozen binaries, source snapshot, toolchain, flags, job count and native contracts. Keep complete logs for both tools and every failure.
2. Reproduce the largest observed Nano loss first in alternating repeated untraced trials. A single gap is a hypothesis; do not claim it is repeatable yet.
   Priority case: shared-edit / edit, observed gap 7.810s.
3. Capture matched complete compiler/Cargo timelines separately from speed trials. Attribute elapsed time to actual requests; distinguish compilation, input validation, publication and postcompile storage. Nested or overlapping spans cannot be summed into projected savings.
4. Change one measured cause. Retain full input validation and fallback behavior. Compare the candidate with frozen Nano and kache, then run an independent confirmation.
5. Require fresh/cached artifact bytes and modes, leaf/shared edits, reverts, expected executable behavior, unchanged original sources, corruption/failure and concurrency gates before adopting it.

All observations, failed checks and console digests are retained in analysis.json. Raw consoles remain private in the supplied state directory.

## Verified session scope

[Full samples and artifact hashes](../benchmarks/harness-full-app-eight-workers-source-edits.json); [generated analysis](../benchmarks/harness-full-app-eight-workers-source-edit-analysis.json). All 18 whole-build consoles and 36 linked-probe streams passed hash verification; both frozen runtimes and all 72 frozen runner/source files matched. Fresh-cache checks reproduced each wrapper’s artifacts, modes and expected CLI/library behavior. Original Harness inputs stayed unchanged and disposable edits were restored.

This tests the complete Harness CLI release binary on macOS ARM64 with Rust 1.97.1 and eight Cargo jobs. Eight input-hash workers are an experimental candidate; production retains four. The dirty Harness snapshot, native contracts and optional producer policies are recorded in the report. Filesystem caches are unflushed, dependency fetches and daemon startup excluded, and R2 is unused. This is not a GUI build or a cross-machine claim.

The shared edit remains 7.810s slower than kache. The single cold observation also remains 6.071s slower than direct Cargo. Profiling must separate actual compilation from input validation and postcompile storage before attributing either gap. Preserve all observed wins and losses and require independent repeated confirmation.
