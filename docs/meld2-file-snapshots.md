# Meld2: file snapshots and verified seed reuse

This local hill climb follows the [archive-overlap experiment](meld2-performance.md).
It profiles the actual React/Vite + Next/OpenNext pipeline, measures byte churn,
and changes the compiler-hint representation and refresh policy. **Every app
build still executes.** No typecheck, bundling step or compatibility validation
was removed. This is a source implementation, not a new downloadable release.

## What the profile showed

Three actual builds took about 11.1–11.3 seconds inside the application command.
A diagnostic Next child envelope was about 5.4 seconds, including a roughly
1.8-second TypeScript trace span. OpenNext packaging after Next completed took
about 3.7 seconds. These are overlapping diagnostic envelopes, not additive CPU
attribution. The application remains much more expensive than wrapper overhead;
this change does not claim to speed up Next's typechecking or OpenNext bundling.

Across those builds, roughly **99.5% of compiler-cache payload bytes were
unchanged**. Each build added six files and changed two, around 1.47 MB, while
295–298 MB of completed hints were being repackaged. That motivated two changes:

1. Native **file-granular snapshots**: one sealed entry references each regular
   file's CAS blob directly. Unchanged files are shared across completed seeds.
2. **Keep a verified compatible seed**: after a successful build, recheck the
   complete source/tool/environment/HEAD/engine contract and concurrently verify
   the existing exact-key seed by content. If both pass, retain it instead of
   rewriting it solely because compiler bookkeeping changed. Misses, corruption
   and eviction refresh it; `--refresh-snapshot` explicitly forces replacement.

The native [file-artifact contract](artifact-files.md) documents inventory bounds,
logical names, metadata and absent private staging. Every get/head freshly
hashes referenced blobs. There is no persistent stat-only fast path. Restore
also validates supported roots and Turbopack CURRENT before publishing hints;
existing mutable local caches are never merged or overwritten.

## Retention on three actual builds

Each completed build's exact compiler files were stored in three independent
native stores. The large-budget baseline used 1 TiB; both bounded variants used
**384 MiB (402,653,184 bytes)**. All archive roundtrips and restored file hashes
matched their originals.

| Completed snapshot | Archives, large budget | Archives, 384 MiB | Files, 384 MiB |
| --- | ---: | ---: | ---: |
| 1 | 299,919,799 | 299,919,799 | 299,836,608 |
| 2 | 601,293,678 | 301,373,879 | 301,320,500 |
| 3 | 904,121,637 | 302,827,959 | 302,805,921 |
| Retained snapshots | 3 | 1 | 3 |

Values are logical bytes in managed entries plus blobs. Keeping the same three
seeds required **66.5% less logical storage** with file references. Under the
same budget this means three useful seeds rather than one, not substantially
less space for one complete seed. Single snapshot files and app bundles did not
shrink. This is not a measurement of unique physical allocation or remote
bandwidth; no incremental remote-transfer protocol was implemented.

Only generated compiler directories were moved aside under the worktree lock
for a real restore. The file seed restored, a complete application build passed,
the worker was packaged and frontend bytes matched. The adapter then retained
the valid seed. Sources, dependencies and ignored environment files were not
removed or copied to another worktree.

## Performance and its trade-off

Four actual packaging builds ran in AB then BA order, after warming both stores
in the exact comparison environment. The baseline is the saved task-start
archive-overlap adapter; the candidate combines file snapshots and retained-seed
reuse. Both used the same native CLI. Frontend bytes matched and every build
packaged its worker successfully.

| Wrapper overhead, excluding measured child build | Baseline | Candidate |
| --- | ---: | ---: |
| Median, two builds each | 595.4 ms | 556.3 ms |

That is **39.1 ms / 6.6% less wrapper overhead**, with both adjacent comparisons
favoring the candidate. It is not a statistically established whole-build gain,
nor a storage-format-only speedup. The child still took about 11 seconds.
An initial comparison that encountered a fresh candidate seed was excluded;
both stores were explicitly warmed before the reported pairs.

A separate fixed-snapshot comparison measured representation costs without an
app build. Six warm pairs alternated order and used fresh restore directories;
all file-content equality checks were outside the clock. Publication includes
inventory/archive creation and native put; restore includes native full blob
validation and helper validation/publication.

| Warm median phase | Archive | Files |
| --- | ---: | ---: |
| Force-publish identical snapshot | 93.2 ms | 376.1 ms |
| Restore into a fresh project | 181.6 ms | 158.4 ms |

**The trade-off matters:** file publication was about 4.0 times slower here;
restore was about 12.8% faster (23.2 ms). One cold publication observation was
88.4 ms versus 385.6 ms, not enough for a cold-throughput claim. The new format
is a retention/deduplication improvement, not a universally faster write path.
Keeping an already verified seed avoids that refresh cost on unchanged inputs.
Forced refresh and frequently changing keys can favor archives for latency.
Neither source nor cached-blob validation was weakened to improve these numbers.

## Installed behavior and verification

Meld2's adapter defaults to `--snapshot-format auto`. With the newly installed
local **ReleaseSafe** CLI and matching helpers it selects files; an older CLI
with budget support falls back to archives. Use `--snapshot-format archive` to
choose archives explicitly or `files` to require the new API. Existing generic
Next/worktree helpers still use their archive backend.

The actual `bun run build:cached --local-fixture-env` package command passed
with default CLI selection and reported `storage:"files"`, `snapshot:"refreshed"`
and `stored:true`. It packaged the worker and preserved frontend bytes. Repeated
same-key builds and a restored-seed build separately reported
`snapshot:"retained"`; the real application command still ran each time.
`stored:true` in a retained summary means a useful verified seed exists, not
that a new snapshot was written during that invocation.

Verification included:

- ReleaseSafe native build and Zig unit tests in the isolated source export.
- Six native file-artifact integration tests covering invalid names, bounds,
  corruption/seal failures, copy isolation, concurrent operations and GC sharing.
- Fourteen existing budget tests and 28 Next helper tests.
- Existing real Rust/Zig restore, invalidation, corruption and isolation tests.
- Twenty-two bounded adapter control-flow cases across archive and file paths,
  including changed inputs/engine, eviction, cache errors, unavailable threads,
  failed children, disabled snapshots and forced refresh.
- Matched real builds, full-file/empty-directory restores and the actual package
  script with its default installed CLI. No live-service/browser acceptance or
  Linux/Windows runtime coverage is claimed.

[Aggregate evidence](../benchmarks/meld2-file-snapshots.json) contains the counts,
phase pairs, actual build intervals and retention results. Raw logs, source
filenames, inventories, compatibility keys, environment values and payload
fingerprints remain private. Generated comparison payload stores were removed
after success; the useful default store and installed CLI remain. No app source,
Next configuration, dependency lockfile, deployment or Git publication changed.
Never deploy fixture-built outputs: rebuild with actual deployment configuration.
