# Restore phase profile

The [private capture](../benchmarks/restore-phase-profile.json) separates cache
restoration into six stages. It uses the accepted source at `f66a43b`, one cold
and two warm clean Harness Cargo builds, Rust 1.97.1, stable Zig 0.17.0, and four
Cargo jobs. All 334 warm invocations hit: 272 ordinary libraries and 62 macro or
executable producers. Tracked sources match the preceding accepted run.

| Stage | Ordinary hit median | Producer hit median |
| --- | ---: | ---: |
| Read, authenticate and parse entry | 0.060 ms | 0.275 ms |
| Parallel input hashing setup and execution | 0.039 ms | 8.688 ms |
| Dependency content/membership/negative/symlink guards | 0.874 ms | 0.472 ms |
| Output blob content verification | 0.983 ms | 0.913 ms |
| Read and verify captured stdout/stderr | 0.048 ms | 0.046 ms |
| Clone/copy outputs, permissions and rename | 0.629 ms | 0.446 ms |

The parallel-input stage includes file enumeration and stat calls even when a
small ordinary graph does not meet the parallel hashing threshold. Those graphs
hash their regular inputs in the dependency-guard stage instead. Stage medians
do not sum to a median invocation time. Concurrent timings overlap and include
instrumentation overhead; these are diagnostic observations, not project
performance comparisons.

Producer input hashing is the largest restore stage. Inspection found that
each hashing job allocated and freed a private arena just to format its digest.
That observation motivates a fixed-buffer digest experiment, preserving all
file reads, hashes, worker limits and validation checks.

The [fixed-buffer experiment](../benchmarks/harness-hill.md#fixed-buffer-worker-digest-rejected)
subsequently showed no reliable gain in either a 25-pair fixture or 27-pair
Harness comparison. It was rejected; production retains its previous worker.

The profiler is retained as an
[experiment patch](../benchmarks/experiments/restore-phase-profile.patch).
To reproduce, apply it and the existing
[capture environment patch](../benchmarks/experiments/producer-profile-capture.patch)
in a disposable checkout at the recorded revision, build ReleaseFast, and run
the `tests/rust_diagnostic.py` command in the
[producer profile instructions](producer-phase-profile.md). The capture patch
sets `NANOCOMPILE_PROFILE_PRODUCER=1`, which this restore profiler also reads.
The actual compiler receives that diagnostic environment variable. Read the
`nanocompile: profile restore STAGE N ns` lines in the private capture.

The public report omits compiler arguments and environments. Patch, capture
script and executable checksums identify the instrumentation. The profiling
patch is absent from production source and executables.
