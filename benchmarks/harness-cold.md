# Cold Harness builds: faster with more jobs, still behind kache

On this 28-CPU M3 Ultra / 256 GiB Mac, raising Cargo concurrency from four to eight jobs cuts Nano's median cold Harness library build from **29.257204 to 18.106357 seconds**, **38.1% less time**. All three controlled pairs improve and all 193 Rust/producer/native artifacts remain byte-identical. This is a build-configuration improvement using the existing runtime; neither tested cache-core candidate was retained.

Nano still loses to kache at equal concurrency. At eight jobs, three fresh-cache pairs give medians **18.815704 s Nano and 17.158729 s kache**, with kache winning all three. Nano is 9.7% slower by these medians. Five preceding four-job pairs also all favor kache. We have not demonstrated a cold-build cache win.

## Controlled Cargo concurrency change

| Pair | Four jobs | Eight jobs | Seconds saved |
| --- | ---: | ---: | ---: |
| 1 | 30.087610 s | 18.002468 s | 12.085142 s |
| 2 | 28.279856 s | 18.106357 s | 10.173499 s |
| 3 | 29.257204 s | 18.995132 s | 10.262072 s |

Both modes use exactly the same accepted Nano executable (SHA-256 `b2a06e09aaae409bdd4afd8c8f2f2f9d9c7fe5db6f30752c09cf2fcbdbea5595`), one stable wrapper path, fixed native Clang adapter and target path. Entire caches and target are removed before each build. Build order alternates. The only intended configuration difference is `cargo -j4` versus `-j8`; Cargo's derived job environment differs accordingly. Mean paired saving is 10.840238 s with descriptive standard error 0.622977 s. Sampled maximum process-tree RSS rises from ~1.34 GB to ~2.06 GB. These are three pairs on one machine, not a portable optimal job count.

[Every sample, complete artifact hashes and source hashes](harness-cargo-jobs-cold.json), [runner](experiments/cargo_jobs_cold_pair.py).

## Repeated kache comparison

| Session | Nano median | kache median | Nano pair wins |
| --- | ---: | ---: | ---: |
| Four jobs, withdrawn location-query candidate | 29.552423 s | 27.364023 s | 0/5 |
| Eight jobs, accepted existing runtime | 18.815704 s | 17.158729 s | 0/3 |

These are separate sessions and runtime revisions: compare tools within a row. The four-job query shortcut was **inactive**, as verified after timing, and reverted. Its lower predecessor A/B times do not establish an optimization gain. The direct Cargo prime points, 25.839642 s at four jobs and 15.770268 s at eight, are single prime/reference measurements recorded for context; they are not repeated direct medians.

[Five four-job pairs](harness-cold-kache-five.json), [three eight-job pairs](harness-cold-kache-eight-jobs.json). Every repeated output matches its own wrapper's initial cold rlibs, macro dylibs, build-script executables and native objects/archives. Kache remaps paths and Nano's native scanner changes debug representation, so cross-tool byte equality is not asserted. Nano records 167 Rust and 24 native misses with zero hits in every pair; kache records zero local/remote hits. Failed compiler feature probes are expected and do not fail Cargo.

Both compiler caches are cleared before each pair, and the private kache daemon is stopped, its cache deleted, and a new daemon started and checked outside timing. Build order alternates. Cargo target is removed before each build. Rust 1.97.1 and kache 1.0.0 are pinned. The workload is `cargo build --release --lib --locked --offline -p harness-adapters`, the actual dirty-source Harness snapshot used for previous source-edit benchmarks, commit `32b41cb0bff55e3c9cbfab3012acec2b179ad199`. Nano uses the same opt-in reported macro inputs, macro/executable producers and Clang native adapter as those benchmarks; direct and kache keep their usual native compiler. Tracked Rust sources, manifests and lockfile remain unchanged. This is not the complete Harness GUI build.

"Cold" here means empty compiler caches and clean Cargo target. OS filesystem caches are warm/unflushed. Fetching dependencies and daemon startup are excluded, R2 is not used, and no new compilation flags or generated source are introduced.

## What the profile found

The [fresh isolated phase profile](../docs/harness-cold-profile.md) finds ~0.87 s of initial fingerprint waiting, 2.394 s of aggregate repeated sysroot/target-libdir probes and 4.258 s of aggregate graph work. Cargo jobs overlap; aggregate spans cannot be treated as wall savings. The tail `harness-adapters` compiler takes ~9.02 s by itself. Empty caches still have to do this compilation; more concurrent Cargo work shortens the dependency portion.

[Parallel toolchain hashing](../docs/toolchain-hash-experiment.md) lost two of three pairs and was rejected. [Guarded installation locations](../docs/rust-installation-locations.md) appeared faster in A/B timing but a coverage audit found zero active location shortcuts in 147 selection memos. A [native Cargo environment capture](cargo-loader-environment-check.json) confirms the loader variable triggering its gate. It was pushed, audited and reverted. Production core is unchanged; current source is 8bdc776, same runtime as ddfe785. [Linux/macOS CI](https://github.com/justrach/nanocompile/actions/runs/38041834334) passes for the retained runtime.

## Use the measured build configuration

On this machine, use `cargo build --release --lib -p harness-adapters -j8` with your existing Nano wrapper and opt-in policies. This does not edit the human Harness checkout or global Cargo settings. Smaller or memory-constrained machines need their own job-count measurements.

To repeat the cache comparison:

```sh
RUSTUP_TOOLCHAIN=1.97.1 python3 tests/project_comparison.py \
  zig-out/bin/nanocompile /path/to/harness --kache /path/to/kache \
  --state /tmp/harness-cold-new --output /tmp/harness-cold.json \
  --cold-runs 5 --cold-only --jobs 8 --native-clang \
  --proc-macros reported --proc-macro-producers --executable-producers
```

The state directory must be new. `--cold-runs` and `--cold-only` also preserve the runner's ordinary warm comparison when omitted.
