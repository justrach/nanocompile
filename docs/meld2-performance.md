# Meld2 compiler-hint overhead: overlap without skipping validation

This is a targeted improvement to Meld2's Python workspace adapter, not a faster
Zig compiler, a whole-build result cache, or a new downloadable CLI release.
The application build still runs React/Vite and Next/OpenNext on every invocation.
See [the integration and retention study](meld2-cache.md) for its 384 MiB policy.

## Profile first

A real local fixture build took 13.553 seconds inside the wrapper, including
12.704 seconds running the application's packaging command. The approximately
0.849-second remainder was cache orchestration. Instrumented phase totals were:

| Phase | Calls | Aggregate time |
| --- | ---: | ---: |
| Full compatibility-key construction | 2 | 484 ms |
| Exact native Turbopack identity query | 2 | 89 ms |
| Normalized compiler archive creation | 1 | 215 ms |
| Native artifact put | 1 | 29 ms |
| Retained artifact head check | 1 | 4 ms |

The profile is diagnostic, not an A/B speed claim. Compatibility-key time already
includes source/tool content hashing and runtime identity queries; nested phases
must not be added again. The application's build, not cache orchestration,
remains the dominant cost.

## Retained change

After a successful build, the adapter starts **one archive-writing worker** while
the calling thread performs the same post-build engine and full compatibility-key
checks as before. It waits for both before publishing any native artifact. The
worktree lock remains held throughout, including worker completion on failures;
only the invocation's private temporary archive is written speculatively.

There is no persistent input memo, skipped content hash, weaker key, cached app
output, new snapshot format, or parallel application build. Source/engine changes
still reject publication. Invalid archives, unavailable worker threads and cache
errors remain best-effort cache failures; they do not replace the real child's
exit status. The trade-off is one short-lived worker and overlapping filesystem
reads/writes; constrained or busy hosts may benefit less.

## Isolated phase comparison

The baseline is an immutable copy of the pre-change adapter. Both variants use
the same private quiescent compiler snapshot and workspace environment. Only
post-build revalidation plus archive creation are timed. Copying the fixture,
archive comparisons, extraction and payload hash verification are outside the
clock. Nine adjacent AB/BA pairs are followed by nine pairs in fresh output
directories; this is a warm-filesystem experiment, not a cold-cache guarantee.

| Study | Serial baseline median | Overlapped candidate median | Time reduction |
| --- | ---: | ---: | ---: |
| Initial, nine pairs | 312.609 ms | 264.240 ms | 15.5% |
| Fresh-output confirmation, nine pairs | 298.900 ms | 272.863 ms | 8.7% |

Every paired archive was byte-identical. All 18 candidate archives restored every
file to the source payload hash, and the original fixture stayed unchanged.
Temporary comparison payloads were removed after success. These savings are
**26–48 milliseconds in the measured post-build phase**, not a 9–15% reduction
in the entire application build.

Eight bounded control-flow checks cover successful publication, changed source,
changed native engine, archive exceptions, empty archives, unavailable threads,
failed build exit status and explicitly disabled snapshots. These checks use
controlled fixtures; real archive equality and packaging builds are separate
evidence. Raw logs, environment values, source filenames, compatibility keys,
app-derived archives and artifact fingerprints remain private.

## Real-build confirmation

Four actual React/Vite plus OpenNext builds ran in AB then BA order, with the
mutable local compiler cache preserved for both variants. All succeeded,
retained their snapshots, packaged the worker and produced byte-identical
frontend assets. Median wrapper overhead, excluding the measured child-build
interval, fell from **626.3 ms to 576.8 ms
(7.9%)**. Both adjacent comparisons favored the candidate. This is
functional confirmation on two runs per variant, not a statistically established
whole-build speedup: roughly 11 seconds of application work still dominate.

Final managed entries/blobs were 294,093,296 logical bytes, within 384 MiB.
[Aggregate evidence](../benchmarks/meld2-cache-performance.json) includes all
18 phase pairs, the diagnostic profile totals, four real builds and eight
control-flow checks. Inputs and native payload validation were not relaxed.

The implementation is in Meld2's `tools/nanocompile-build.py`; its local guide
explains the concurrency boundary. The measurements were performed locally;
the source implementation is separate from a downloadable CLI release. No
deployment or change to unrelated nanocompile staged work was performed.
