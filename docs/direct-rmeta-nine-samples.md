# Installed direct-metadata build: nine-round comparison

Measured source is `a193bff79044a3d2b3957c5b2c99f0641aa6d776`; installed executable SHA-256 is `0bc634b775e255682d282656375ae53713343ed5524e78a4e15b19df2c166fee`. Stable Zig 0.17.0 builds the cache; the project benchmark pins Rust 1.97.1.

| Implementation | Warm median, 9 samples | Initial cold/prime, 1 sample |
| --- | ---: | ---: |
| Direct Cargo | 23.420443 s | 23.890860 s |
| nanocompile | 2.007020 s | 27.642271 s |
| kache | 2.269442 s | 27.011149 s |

Nano is faster in all nine corresponding warm rounds in this session. Mean same-round lead is 273.196 ms with descriptive standard error 60.893 ms. Every sample, including kache's 2.654564 s sample, is retained. These dependent samples on one local machine are not a general winner test. Kache remains faster in the single cold comparison; direct compilation is faster than both on the first build.

This comparison measures the current installed implementations. It does **not** establish that the new metadata decoder made warm hits faster: the [two independent predecessor comparisons](direct-rmeta-experiment.md) have opposite warm median directions. Their consistent result is a 3.5–5.0% cold median reduction, with six of six controlled cold pair wins.

The workload is the Harness `harness-adapters` release library and its dependency graph, on the same dirty checkout `32b41cb0bff55e3c9cbfab3012acec2b179ad199`. The runner uses four Cargo jobs, a 40 GiB process-tree RSS cap, locked/offline builds and a clean fixed target path before every build. It primes caches, starts and cleans up a private kache daemon and rotates the three-way order. Nano explicitly enables reported macro inputs, experimental Apple macro/executable producers and native Clang CAS. Default-policy results and Xcode results remain separate. This is not a full Harness GUI benchmark.

Each Nano warm build records 167 Rust and 24 native hits. All Rust libraries, macro dylibs, build-script executables and native artifacts match each implementation's own cold output. Tracked Rust files, manifests and lockfile remain unchanged.

```sh
env RUSTUP_TOOLCHAIN=1.97.1 python3 tests/project_comparison.py \
  zig-out/bin/nanocompile /Users/rachpradhan/harness \
  --kache /tmp/nanocompile-kache-bin/kache \
  --state /tmp/nanocompile-direct-rmeta-nine-way \
  --runs 9 --jobs 4 --proc-macros reported \
  --proc-macro-producers --executable-producers --native-clang \
  --output benchmarks/harness-rmeta-direct-nine-samples.json
```

[Raw comparison](../benchmarks/harness-rmeta-direct-nine-samples.json), [all-sample analysis](../benchmarks/harness-rmeta-direct-nine-analysis.json) and the [summary script](../benchmarks/experiments/three_way_summary.py) retain provenance. [Hosted Linux/macOS CI](https://github.com/justrach/nanocompile/actions/runs/38017220898) passes for this source, including the new real-compiler metadata oracle on both hosts. Its [Linux oracle](../benchmarks/rmeta-direct-ci-linux.json) and [macOS oracle](../benchmarks/rmeta-direct-ci-macos.json) each match the no-std/extra-filename, transitive and macro-consumer fixtures and refuse producer/malformed/unknown-version records.
