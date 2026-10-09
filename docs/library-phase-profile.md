# Ordinary library hit profile

The [private phase capture](../benchmarks/library-phase-profile.json) measures
one cold and two warm clean Harness Cargo builds at source revision `c348d5b`,
using stable Zig 0.17.0, Rust 1.97.1 and four Cargo jobs. There are 272 ordinary
library warm hits. Tracked sources match the preceding accepted benchmark.

| Stage | Median |
| --- | ---: |
| Argument/context initialization inside main | 0.040 ms |
| Compilation plan | 0.010 ms |
| Cache preparation and maintenance lock | 0.035 ms |
| Compilation key | 1.241 ms |
| Key/output locks and configuration check | 0.120 ms |
| Restore validation and materialization | 4.246 ms |
| Trace/event bookkeeping | 0.043 ms |
| Complete dispatch inside main | 5.740 ms |
| Complete subprocess observation | 9.793 ms |

Dispatch contains the library stages and deferred lock releases; these rows
must not be added together. The median process duration outside the measured
main interval is 3.987 ms. That includes Python launch/observation, runtime
initialization before main, exit and scheduling costs. It is not a measurement
of Nano initialization alone or a prediction of daemon savings.

The [25-run rotating launch controls](../benchmarks/library-launch-controls.json)
record 2.213 ms for `/usr/bin/true`, 3.104 ms for the accepted Nano help command,
and 3.106 ms for the instrumented help command. They use the same private cwd
and local environment, which differs from Cargo's per-crate environments.
Command work, output and executable loading also differ. The controls support
keeping launch costs separate from the measured library work.

The final `harness_adapters` hits spend 47.083 and 49.169 ms restoring, and
their complete process observations take 52.484 and 54.079 ms. A few other
hits show much larger scheduling/locking delays; all observations remain in
the report. The prior, separate [restore phase capture](restore-phase-profile.md)
attributes that adapter's restore to about 22.5 ms of parallel input hashing
and 22.4–25.4 ms of output blob verification, with sub-millisecond guards and
materialization. Do not combine stage values from the separate sessions into
a new invocation total. The evidence motivates testing full-content hashing
performance before changing planning or cache locks.

Reproduce in a disposable checkout at the recorded revision by applying the
[timing patch](../benchmarks/experiments/library-phase-profile.patch) and
[capture patch](../benchmarks/experiments/library-profile-capture.patch), then
building ReleaseFast and running the same `tests/rust_diagnostic.py` command
as in the [producer profile](producer-phase-profile.md). The capture patch
sets `NANOCOMPILE_PROFILE_LIBRARY=1`; the compiler also receives that flag.
Read the `profile library` and `profile front` lines from the private capture.

Compiler arguments and environments are omitted from the public report. Patch,
script and executable checksums identify the measurement. Timings include
instrumentation/capture overhead and concurrent contention. They are diagnostic
evidence, not a project performance comparison. Profiling source and the
instrumented executable were removed from production.

A subsequent [watched digest experiment](watch-hash-experiment.md) tested
cross-invocation hash reuse. It was rejected: unflushed writes through an
already-dirty writable mmap can escape vnode events and metadata checks.
Its low reuse timings do not justify replacing full content verification.

The [first persistent cache-hit worker](restore-worker-experiment.md) keeps
complete content verification and tests actual Harness builds. Its 27-pair
comparison does not establish a dependable gain, so it remains a private
prototype for transport and dispatch experiments.

The subsequent [file-read strategy experiment](digest-read-experiment.md)
tests full-content positional reads with the existing Zig BLAKE3. Large-file
hashing medians improve modestly, but two 27-pair Harness sessions show only
about 0.3% differences in build medians with uncertain paired savings. The
candidate is not adopted; production keeps its accepted reader.
