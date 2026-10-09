# Cold Rust miss phases

The complete diagnostic capture identifies dependency-graph discovery as
the largest measured post-compilation cost. Across **167 successful cold
misses**, graph work totals **56.536667 seconds** of per-job elapsed time;
artifact storage totals **1.064325 seconds**. These durations overlap across
four Cargo jobs. They are not additive end-to-end time or promised savings.

| Phase | Aggregate elapsed time across jobs |
| --- | ---: |
| Planning, identity, locks and pre-compilation snapshots | 14.707543 s |
| Compiler process | 73.133228 s |
| All post-compilation work | 60.951747 s |
| Input validation inside save | 1.224431 s |
| Dependency-graph discovery inside save | 56.536667 s |
| Artifact storage inside save | 1.064325 s |

The last three rows are subsets of post-compilation work. Producer
post-compilation work also includes output materialization, diagnostics,
link-input collection and tool/observer revalidation before save. The job
population is **136 ordinary compilations, 21 executable producers, and
10 macro producers**. Ordinary graph discovery accounts for 49.544137 s;
executable producers for 2.043900 s; macro producers for 4.948630 s.

The final `harness_adapters` job is especially useful: it spends **9.107874 s
in rustc**, followed by **1.826996 s post-compilation**, of which **1.771901 s
is graph discovery** and **0.026763 s is storage**. Cargo records that final
unit at 36.86–47.83 s, duration 10.97 s. Its timestamps are rounded to
hundredths, while the adapter uses a monotonic nanosecond clock. Reqwest
also records 1.776344 s in graph discovery after 3.645974 s compilation.
This supports profiling graph classification/query reuse next, while
preserving live selection, full mutable-input hashing and all competing
library/directory guards. No production optimization is adopted here.

The diagnostic prime takes **47.864502 s**; warm restores take **2.207531,
2.203211, and 2.159000 s**. Instrumentation, a distinct executable/observer,
an explicit environment switch, a new state directory and Cargo `--timings`
make these diagnostic samples. They do not replace the uninstrumented
38.066364 s Nano versus 27.462381 s kache cold comparison or establish an
additional throughput regression/improvement.

All four builds match **193 exact artifact hashes**, including native
objects/archives and Rust/producer outputs. All tracked Rust sources,
manifests and lockfile remain unchanged. Every warm build has 167 Rust hits,
24 native hits, three failed probes and nine bypasses. Native Clang stays
the accepted installed binary; only the Rust wrapper is diagnostic.

The patch is applied to an archive of `232f016`, whose production core is
the accepted integrated-cc1 version. Stable Zig **0.17.0** builds the
diagnostic executable with SHA-256
`46d426ca147787e1511b9e340dd373428f80344396ccb981420069d50c24b957`.
Unit tests pass, and real Rust/Zig integration passes with profiling disabled
and enabled, including stderr replay equivalence. Timing records are
written to separate atomic files under the experimental cache namespace
`cold-profile`, only with `NANOCOMPILE_MISS_PROFILE=1`. This avoids relying
on compiler stderr that build scripts can consume. An earlier stderr-only
collector observed 165/167 records; the reported complete capture joins
**all 167 miss and 167 save records** by exact cache key.

Reproduce using the isolated patch and a new state directory:

```sh
python3 benchmarks/experiments/cargo_timing_capture.py \
  /tmp/nanocompile-cold-phase-source/zig-out/bin/nanocompile \
  /Users/rachpradhan/harness --native-clang \
  --clang-wrapper zig-out/bin/nanocompile --miss-profile \
  --state /tmp/nanocompile-cold-phase-complete \
  --output benchmarks/harness-cold-phase-builds.json --warm-runs 3
python3 benchmarks/experiments/cold_phase_summary.py \
  /tmp/nanocompile-cold-phase-complete/cache/cold-profile \
  --builds benchmarks/harness-cold-phase-builds.json \
  --patch benchmarks/experiments/cold-phase-profile.patch \
  --output benchmarks/harness-cold-phase-profile.json
```

[Diagnostic patch](../benchmarks/experiments/cold-phase-profile.patch),
[build/source/artifact evidence](../benchmarks/harness-cold-phase-builds.json),
[all phase records and individual file digests](../benchmarks/harness-cold-phase-profile.json),
[Cargo unit data](../benchmarks/harness-cold-phase-cargo-units.json), and
[build/check provenance](../benchmarks/cold-phase-profile-check.json)
retain the complete result. Builds use Rust 1.97.1, four jobs, a 40 GiB
sampled process-tree RSS cap, locked offline release library mode, and
reported macro/executable producer policies on the dirty Harness checkout.
