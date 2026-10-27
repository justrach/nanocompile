# Bounded task and worktree cache hill-climb

This experiment extends the earlier small Rust-restore study to declared
asset-generation tasks and Next.js compiler-cache archive creation. It is a
local experiment, not a comparison against a newly published binary or a
whole-application build-speed claim. Both native variants use ReleaseSafe and
the same working-tree code except for the candidate under measurement; existing
uncommitted work is held constant. The baseline executable is built before
editing and never overwritten.

## Declared-task workloads

`benchmarks/experiments/task_hill_check.py` runs real isolated Python commands
which consume every declared project input, using the focused-contract example's
explicit Python startup resources. The workloads are:

- 256 small assets of 4 KiB each, combined into one output;
- eight 1 MiB assets, combined into one output;
- an ordered graph of 16 dependent asset-generation tasks.

Every invocation starts with its declared outputs deleted. Cold population and
two warmups are excluded. Timed hits must restore the same SHA-256 outputs as
uncached execution and report no child execution. Same-size edits with restored
mtime must miss, edited inputs must subsequently hit, and reverting the source
must restore the original bytes. Reports contain timings and aggregate counts,
not temporary paths, command output or environment values.

Initial measurements use four batches of eight adjacent baseline/candidate
pairs, alternating AB/BA order within and between batches. Confirmation uses
three batches on freshly created fixtures and caches. Reporting includes native
phase timings and subprocess wall time; separate unreported invocations measure
wall time without report-file generation. Output deletion, direct reference
execution and byte verification are outside the subprocess timer. These are
warm-filesystem local cache-hit measurements, not complete session timings or
cold-disk guarantees.

### Rejected: invocation-local host identity reuse

Reusing native host discovery across the ordered graph did not establish a
repeatable benefit. The initial graph's reported median was 19.367 ms baseline
versus 19.392 ms candidate, with mixed per-batch directions. A fresh confirmation
favored the candidate, but the initial large-file task regressed and the separate
unreported small-asset confirmation also regressed. The changes were removed;
there is no retained host-key or host-partition change.

### Retained: bounded parallel declared-input hashing

For contracts with at least eight declared inputs, `src/task.zig` now uses
at most four file workers with private allocators. Tiny contracts stay serial.
Every file still receives its complete content hash and before/after state
check, before and after child execution. Results are assembled in declaration
order; all workers join and errors propagate before key construction or child
execution. No persistent input memo, weaker key, skipped byte validation or
parallel task scheduling is introduced.

| Workload / study | Baseline input hashing | Candidate input hashing | Baseline process wall | Candidate process wall |
| --- | ---: | ---: | ---: | ---: |
| many-small / initial | 4.687 ms | 1.755 ms | 15.762 ms | 12.957 ms |
| large-files / initial | 4.998 ms | 1.441 ms | 19.660 ms | 15.921 ms |
| many-small / confirmation | 4.975 ms | 1.771 ms | 16.748 ms | 13.394 ms |
| large-files / confirmation | 5.287 ms | 1.523 ms | 20.848 ms | 17.148 ms |

Input hashing improved in all seven batch medians for both workloads.
Reported subprocess wall medians fell roughly 18–20%; separate unreported
wall medians fell 19–29% across these two workloads and both studies. This is
a task-hit fixture result, not evidence of the same gain on whole builds.

The eight-tiny-asset control was effectively flat: reported wall medians were
4.485 versus 4.492 ms initially and 4.623 versus 4.614 ms on confirmation.
The 16-task graph remains on the serial input path; its mixed per-batch wall
changes do not establish a graph/scheduling speedup. Concurrent independent
CLI workloads, other operating systems and very large individual files were
not performance-tested.

## Retained: larger uncompressed archive copy buffer

`tools/nextjs_cache.py` now gives the standard-library tar writer a 1 MiB
copy buffer instead of its default 16 KiB. The archive format, member ordering,
normalization, link checks, limits, restore validation and locking are unchanged.
The extra copy memory is bounded; no compression or persistent cache shortcut
was added.

`benchmarks/experiments/archive_hill_check.py` tests a private real SWC/Webpack
snapshot (nine files, 66,673,475 payload bytes) and a synthetic 1,024-small-file
snapshot (1 MiB payload). Nine adjacent AB/BA pairs per workload are followed
by nine pairs using fresh temporary fixture/output directories. The real cache
is copied, never mutated. Only archive creation is timed, not fixture copying,
archive comparisons, restoration, CAS operations, framework builds or hashing
the restored files. Fresh confirmation does not mean cold filesystem caches.

| Workload / study | Baseline archive wall | Candidate archive wall |
| --- | ---: | ---: | ---: |
| real_multi_mb / initial | 36.236 ms | 11.235 ms |
| many_small / initial | 82.375 ms | 83.112 ms |
| real_multi_mb / fresh_confirmation | 37.721 ms | 11.673 ms |
| many_small / fresh_confirmation | 83.310 ms | 80.613 ms |

All 18 real-cache pairs favored the candidate. Each paired archive was
byte-for-byte identical, and every restored file matched its source SHA-256.
The many-small archive control is essentially unchanged and does not justify
a speedup claim. The retained gain is archive creation, not faster Next.js or
OpenNext compilation, restoration, package installation or deployment.

## Evidence and reproduction

[Raw measurements](../benchmarks/task-hill-climb.json) include every paired
native/wall/CPU timing, fresh confirmation, binary hashes, controls and the
rejected host candidate. They contain no private cache filenames, temporary
paths, logs or environment values. The original compiler-cache archives stay
private under `.tmp`; no transformed application source is published.

Capture the baseline before applying the candidate, in the same checkout and
environment. Do not overwrite it when rebuilding the candidate. Native commands:

```sh
zig build -Doptimize=ReleaseSafe --prefix .tmp/task-hill/baseline
# Apply the candidate, then:
zig build -Doptimize=ReleaseSafe --prefix .tmp/task-hill/hash-candidate
python3 benchmarks/experiments/task_hill_check.py \
  .tmp/task-hill/baseline/bin/nanocompile \
  .tmp/task-hill/hash-candidate/bin/nanocompile \
  --output .tmp/task-hill/native-study.json
```

For archive timing, first save an immutable copy of the old helper as
`.tmp/task-hill/archive-baseline.py`. Then run serially, not alongside other
performance experiments:

```sh
python3 benchmarks/experiments/archive_hill_check.py \
  .tmp/task-hill/archive-baseline.py tools/nextjs_cache.py \
  --cache-dir /path/to/private/.next/cache \
  --output .tmp/task-hill/archive-study.json
```

## Correctness verification

The retained candidate passed native ReleaseSafe build/unit tests and Zig
format checks, 19 declared-task contract/report tests, five focused-input
contract tests, 12 relocatable-task tests, the cache-savings integration's six
real builds/five matched warm-compiler pairs, 25 Next.js cache tests and three
native worktree CLI tests. Task checks include invalidation, failed contracts,
report controls and isolation; archive measurements independently require
byte-identical archives and all-file restore hashes. Neither optimization
relaxes cache keys or skips source/blob content validation.

These changes and measurements are source-level development work. They are not
included in the already-published `v0.1.0` release; publishing them on `main`
does not update the downloadable release binaries.
