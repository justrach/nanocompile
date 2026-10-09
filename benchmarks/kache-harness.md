# Direct comparison with kache on Harness

This initial workload comparison showed **kache helped substantially; nanocompile
did not**. The [subsequent hill climb](harness-hill.md) records coverage improvements and the remaining performance gap. This replaces any inference from the tiny fixture about
which tool performs better on a Cargo project.

Measured on Apple M3 Ultra, macOS 27 arm64, Rust 1.97.1, four Cargo jobs.
Workload: `cargo build --release --locked --offline --lib -p harness-adapters`
and its dependency graph. Three warm samples per implementation, rotating
measurement order. Each build deleted the dedicated target directory first;
these are clean rebuilds, not Cargo no-ops. Dependencies were fetched before
timing, and a direct build primed OS/native caches before populating either
wrapper cache.

| Implementation | Warm clean-build median | Recorded cache hits per build |
| --- | ---: | ---: |
| Direct Cargo/rustc | 22.77 s | — |
| nanocompile 0.1.0 | 22.95 s | 2–3 |
| kache 1.0.0, isolated daemon active | 2.01 s | 187 |

Kache was **11.3× faster than direct compilation** and **11.4× faster than
nanocompile** on this workload. Nanocompile had 167 bypass calls per warm build.
Event counts include compilation/build-script activity and are not crate counts.
The empty-cache builds took 25.37 seconds for nanocompile and 26.84 seconds for
kache; the priming direct build took 25.03 seconds. Those are one cold sample
each and exclude dependency downloads and daemon startup.

All builds succeeded and produced 135 Rust libraries. Each wrapper's warm
libraries matched its own cold outputs by SHA-256. Nanocompile's outputs also
matched direct compilation. Kache remaps embedded paths, so its bytes are
compared with its own cold build rather than requiring equality with direct
rustc. This validates restoration; it is not an exhaustive application test.

Kache used its ordinary daemon path, started as a private foreground subprocess
with isolated cache/config/socket paths and stopped afterward. No system
service was installed. Both tools used local caches; this comparison does not
include R2 transfer time. Kache's release archive checksum and executable
checksum were verified, and v1.0.0 was the latest published release when run.

The source checkout was dirty and its base revision is recorded in
[harness-kache-comparison.json](harness-kache-comparison.json), alongside all
timings, per-build hashes, cache events, kache stats, versions and executable
checksums. This package benchmark covers a real dependency graph; it does not
measure the complete Harness GUI application.

## Reproduce

```sh
zig build -Doptimize=ReleaseFast
python3 tests/project_comparison.py zig-out/bin/nanocompile /path/to/harness \
  --kache /path/to/kache --state /tmp/nano-comparison-new \
  --runs 3 --jobs 4 --output bench-results/comparison.json
```

The state directory must not already exist. `--standalone` runs kache without
its daemon; record that choice when comparing results. No global Cargo or
kache configuration is modified.

The earlier synthetic fixture compared individual compiler calls with kache
in standalone mode. Its lower nanocompile hit latency cannot be extrapolated
to this project comparison. Broad dependency/proc-macro/build-script coverage
dominates the result here; reducing wrapper latency alone will not close this
gap. The next work should focus on that coverage before claiming a practical
advantage from the Zig implementation.
