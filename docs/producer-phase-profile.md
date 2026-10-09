# Producer hit phase profile

The [private phase capture](../benchmarks/producer-phase-profile.json) measures
one cold and two warm Harness Cargo builds with the accepted live-driver-plan
implementation, using a timing patch and the existing Python capture wrapper.
All 62 warm producer invocations are hits. Source files and manifests still
match the preceding accepted benchmark. This is diagnostic evidence, not a
project performance comparison; concurrent timings overlap and include timer
output/capture overhead.

| Producer hit stage | Median |
| --- | ---: |
| Prepare/cache maintenance lock | 0.036 ms |
| Live native selection | 29.224 ms |
| Rust compilation key | 1.223 ms |
| Full observer executable digest | 1.113 ms |
| Producer key/output locks | 0.094 ms |
| Dependency/blob validation and restoration | 10.770 ms |

The executable is about 1.6 MiB. Its full digest remains unchanged in production:
the measured cost does not justify adding a metadata shortcut for it. Every
producer dependency graph already meets the parallel hashing threshold of
32 unique files and 8 MiB. The median largest-file position is 97.1% of the
original queue, usually a Rust runtime archive near the end of executable
producer records. This motivates testing a large-file-first queue, with the
same four-worker limit and complete content verification.

The [queue experiment](../benchmarks/harness-hill.md#largest-file-first-restore-queue-rejected)
was subsequently rejected after 27 controlled pairs showed no reliable gain.
Its patch and raw samples are retained; production keeps the accepted queue.

The profiler is kept only as two experiment patches:

- [Producer timing patch](../benchmarks/experiments/producer-phase-profile.patch)
- [Capture environment patch](../benchmarks/experiments/producer-profile-capture.patch)

They were applied to a private copy of revision `886f2d8`, compiled with stable
Zig 0.17.0, and then removed from the production source and executable. The
capture patch sets a diagnostic environment variable which the actual compiler
also receives. Compilation keys include that environment. Compiler environments
and argument lists are omitted from the public phase report. Recorded patch,
script and executable checksums identify the measured instrumentation.

To reproduce, use a disposable checkout at that revision, apply both patches,
build ReleaseFast, then run:

```sh
RUSTUP_TOOLCHAIN=1.97.1 python3 tests/rust_diagnostic.py \
  /absolute/path/to/instrumented/nanocompile /absolute/path/to/harness \
  --state /tmp/nano-profile-new --proc-macros reported \
  --proc-macro-producers --executable-producers --warm-runs 2
```

Read the `nanocompile: profile producer STAGE N ns` lines in the private capture.
The timings are not interchangeable with the uninstrumented paired or kache
comparisons. Do not use this diagnostic executable for published performance
comparisons.

The follow-up [restore phase profile](restore-phase-profile.md) separates the
restore stage into input hashing, dependency guards, output verification and
materialization, with ordinary and producer hits reported independently.
