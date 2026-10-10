# Selected-resource decoder: complete Harness comparison

The installed version has warm medians **2.048817 s Nano, 2.082112 s kache
and 24.026856 s direct Cargo**. Nano is faster in all nine corresponding
rounds, with a small local lead. Every sample is retained.

| Mode | Median | Mean | Range | Sample standard deviation |
| --- | ---: | ---: | ---: | ---: |
| Direct | 24.026856 s | 24.355959 s | 23.896504–26.192331 s | 0.723940 s |
| Nano | 2.048817 s | 2.042781 s | 2.011622–2.074185 s | 0.023061 s |
| kache | 2.082112 s | 2.107690 s | 2.054924–2.214686 s | 0.054700 s |

Same-round Nano-minus-kache differences have median −44.900 ms, mean
−64.909 ms and descriptive standard error 19.686 ms. These rotating rounds
share one machine/session and are not independent host trials. They support
a local warm lead, not a general cross-machine advantage or attributing the
entire gap to selected-resource scope. The [controlled comparisons](selected-decoder-experiment.md)
establish the cold gain separately; their warm medians are essentially equal.
The earlier sessions, including one favoring kache, remain published.

Cold is **29.059060 s Nano versus 28.082190 s kache**. Kache still leads
cold by 0.976870 s in these single samples. Direct prime takes 25.949447 s.
All 27 warm builds match their own cold Rust libraries, macro dylibs,
build-script executables, native objects and archives. Tracked Rust sources,
manifests and lockfile are unchanged. Each Nano warm build has 167 Rust
hits, 24 native hits, eight bypasses and three failed probes. Each kache
warm build has 187 local hits and three passthroughs. Scanner debug output
and kache remapping prevent claiming cross-mode artifact byte equality.

Measured source revision: `3fdc90645289254397e51eccf37a21ba9bb1233e`.
Installed executable SHA-256:
`ce7204f1e4bd5968d5e40d7dd3c9496c2a4b77b4344f718718108911b4e57a3c`.
Host: Apple M3 Ultra, 28 logical CPUs, 256 GiB RAM, arm64 macOS 27.
Builds use Rust 1.97.1, four Cargo jobs, a 40 GiB sampled process-tree RSS
cap, locked offline release library mode and clean fixed target paths.
The runner starts/cleans up a private kache daemon and rotates three-way
order each round. Nano explicitly uses native Clang CAS, reported macro
inputs and experimental Apple macro/executable producers. Default-policy
results remain separate; this is not a benchmark of every Rust project.

```sh
env RUSTUP_TOOLCHAIN=1.97.1 python3 tests/project_comparison.py \
  zig-out/bin/nanocompile /Users/rachpradhan/harness \
  --kache /tmp/nanocompile-kache-bin/kache \
  --state /tmp/nanocompile-selected-decoder-nine-way \
  --runs 9 --jobs 4 --proc-macros reported \
  --proc-macro-producers --executable-producers --native-clang \
  --output benchmarks/harness-selected-decoder-nine-samples.json
```

[Raw comparison](../benchmarks/harness-selected-decoder-nine-samples.json),
[all-sample analysis](../benchmarks/harness-selected-decoder-nine-analysis.json)
and [summary script](../benchmarks/experiments/three_way_summary.py) retain
provenance. The adopted source passes [Linux/macOS CI](https://github.com/justrach/nanocompile/actions/runs/38010109674),
including active selector changes between Rust 1.97.1 and 1.98.1.
[Hosted CI evidence](../benchmarks/selected-decoder-ci-validation.json)
contains both scope artifacts and job results.

A follow-up probe attempts to combine the existing live sysroot/target-libdir
query and `-Zls=root` decoding in one compiler invocation. Rust 1.97.1 instead
treats the binary metadata artifact as source and fails with invalid UTF-8;
both commands work separately. That approach is rejected, and production
retains the separate live commands. [Probe evidence](../benchmarks/root-print-combination-probe.json)
records the compiler version, artifact digest, exact arguments and results.

Fresh R2 validation for this source passes on hosted Ubuntu: [Harness run](https://github.com/justrach/nanocompile/actions/runs/38010357689) and [Turborepo run](https://github.com/justrach/nanocompile/actions/runs/38010359904). [Harness raw results](../benchmarks/harness-selected-decoder-r2-linux.json) and [Turbo raw results](../benchmarks/turbo-selected-decoder-r2-linux.json) are retained. Both macOS jobs are still queued as of publication; their results are pending. The hosted Harness workload is pinned to `20c4019201e4b1eee5e04cfbb8dc7bda941b11b9`, separate from the local comparison above.
