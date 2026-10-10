# Parallel installed Rust file hashing: not adopted

The [fresh cold profile](harness-cold-profile.md) identifies an initial ~0.87 s fingerprint barrier shared by the first four Cargo jobs. This candidate uses up to four workers for installed Rust file content digests when at least eight regular files total 64 MiB. Workers own their allocators; final fingerprint ordering, installed-file memo locks, stamp revalidation, complete compilation identities and full mutable-input hashing remain intact. Small installations and Zig retain sequential hashing.

The isolated candidate passes stable Zig 0.17.0 build, unit and real Rust/Zig integration checks. It is **not adopted** because the whole-project trial does not show a consistent gain.

| Pair | Sequential baseline | Parallel candidate | Seconds saved |
| --- | ---: | ---: | ---: |
| 1 | 32.000924 s | 32.144746 s | -0.143822 s |
| 2 | 29.480077 s | 28.624142 s | +0.855934 s |
| 3 | 30.305694 s | 31.290833 s | -0.985139 s |

Candidate wins 1/3 pairs. Baseline median is 30.305694 s and candidate median 31.290833 s. Mean paired saving is −0.091009 s, with descriptive standard error 0.532128 s. These three samples do not support claiming that hashing concurrently speeds up Harness.

All six empty-cache builds match all 193 Rust/producer/native artifacts, record 167 Rust misses and 24 native misses with zero hits, and preserve tracked sources. The native Clang wrapper is held fixed while Rust wrappers occupy one stable path. This is clean Cargo-target/empty compiler-cache timing with warm OS filesystem caches, four Cargo jobs, and no R2 transport. Baseline source is ddfe785; this trial is against Nano's predecessor, not kache.

[Raw samples](../benchmarks/harness-toolchain-hash-cold-first.json), [runner](../benchmarks/experiments/toolchain_hash_cold_pair.py), [patch](../benchmarks/experiments/toolchain-hash.patch).
