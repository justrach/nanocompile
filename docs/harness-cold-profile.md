# Current Harness cold-build profile

The current production baseline (ddfe785, runtime 65501a4) was instrumented in an isolated checkout. The workload is the same actual-source Harness snapshot used for the source-edit benchmarks: release `harness-adapters` library, Rust 1.97.1, four jobs, opt-in macro/executable producers and native Clang adapter. The human checkout is untouched.

The diagnostic cold build took 31.937538 s and its clean warm restore 2.255564 s. Both produce identical hashes for all 193 artifacts; cold records 167 Rust/24 native misses and warm records 167 Rust/24 native hits. The diagnostic environment and instrumentation affect identities and timing: these are not comparison samples.

| Phase | Aggregate span over concurrent jobs |
| --- | ---: |
| Before compilation | 9.893 s |
| Compiler execution | 67.628 s |
| After compilation | 6.859 s |
| Post-compile input validation | 0.531 s |
| Dependency graph collection | 4.258 s |
| Entry/blob storage | 0.471 s |
| Graph sysroot/target-libdir queries | 2.394 s (169 queries) |
| Graph root decoding | 0.613 s |
| Graph dependency discovery | 1.216 s |

These spans overlap across Cargo jobs, and graph subphases are nested. They cannot be added together or treated as wall-clock savings. The first four jobs each spend 0.874–0.879 s before compilation, sharing the initial installed-toolchain fingerprint barrier. The tail `harness-adapters` compiler itself takes 9.021 s; its graph collection takes 0.128 s. A compiler cache still has to perform the real compilation when its cache is empty.

The first optimization experiment, [parallel installed-file hashing](toolchain-hash-experiment.md), did not produce a consistent whole-build gain and was rejected. The [installation-location candidate](rust-installation-locations.md) was also withdrawn: a later coverage audit showed it never activated under Cargo's loader environment. Lower measured times without verified feature coverage were insufficient. The final repeated kache comparison and concurrency experiment are recorded in [cold results](../benchmarks/harness-cold.md).

[All 503 phase records and totals](../benchmarks/harness-current-cold-phases.json), [build and artifact verification](../benchmarks/harness-current-cold-profile-builds.json), [reproducible instrumentation patch](../benchmarks/experiments/current-cold-profile.patch). Apply the patch to ddfe785 and run `benchmarks/experiments/cargo_timing_capture.py` with `--miss-profile`, `--native-clang` and a fixed native wrapper. Instrumentation is not enabled in the installed production binary.
