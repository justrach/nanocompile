# Guarded Rust installation locations: withdrawn

The [current cold profile](harness-cold-profile.md) records 169 sysroot/target-libdir subprocesses totaling 2.394 s across concurrent jobs. Those queries resolve default installation paths already learned while fingerprinting the installed compiler.

The experimental change includes both print requests in the initial fingerprint probe and retains the returned paths in sealed toolchain memo schema 6. Existing selector, file and directory stamps are all revalidated before reading that memo. The shortcut applies only when the compiler argument equals its canonical physical installation path, the executable is exactly `sysroot/bin/rustc`, its version is exactly stock Rust 1.97.1 (`8bab26f4f`), and no `LD_`/`DYLD_` environment variables are present. Explicit `--target` and `--sysroot` arguments, proxies, aliases and other Rust versions retain live graph queries. No default paths are guessed.

The complete compiler and metadata-decoder content identities retain their existing construction. Mutable inputs and restored blobs still require full content validation. Schema-5 selection memos are re-fingerprinted once; shared installed-file digests remain reusable under the existing installation-state contract. The first concurrent-fingerprinting candidate was rejected and is [recorded separately](toolchain-hash-experiment.md).

## Coverage audit changed the decision

After the A/B batches, inspecting the last candidate cache found **147 schema-6 selection memos and zero retained locations**. The shortcut did not activate anywhere in this Harness build. Cargo [sets dynamic-library search paths when compiling](https://doc.rust-lang.org/cargo/reference/environment-variables.html#dynamic-library-paths), including `DYLD_FALLBACK_LIBRARY_PATH` on macOS; the candidate explicitly rejects that loader environment. Therefore the apparent A/B improvements below cannot be attributed to eliminated queries. They are retained as an example of why checking output equality and elapsed times alone is insufficient: an optimization's actual coverage must be verified too.

The change was pushed as 46c1a6f and then fully reverted as 8bdc776. Production runtime remains the predecessor implementation. No Harness speedup is claimed for this candidate. The [coverage record](../benchmarks/rust-installation-locations-coverage.json) records this audit. The direct compiler fixture does exercise the shortcut, but direct invocation coverage does not establish Cargo coverage.

## Repeated predecessor comparison (not evidence of an active optimization)

| Pair | Existing Nano | Location reuse | Seconds saved |
| --- | ---: | ---: | ---: |
| Initial 1 | 31.359622 s | 29.343731 s | +2.015891 s |
| Initial 2 | 30.224987 s | 29.181635 s | +1.043353 s |
| Initial 3 | 29.816120 s | 28.755690 s | +1.060431 s |
| Confirmation 1 | 29.992109 s | 29.575957 s | +0.416152 s |
| Confirmation 2 | 29.292510 s | 29.304976 s | -0.012466 s |
| Confirmation 3 | 31.474545 s | 31.096992 s | +0.377553 s |

Initial medians: 30.224987 s baseline and 29.181635 s candidate (~3.5% lower). Independent confirmation medians: 29.992109 s and 29.575957 s (~1.4% lower). The candidate wins 5/6 pairs in these measurements, despite the shortcut being inactive. Confirmation mean paired saving is 0.260413 s with descriptive standard error 0.136894 s. Variation between batches is substantial; the coverage audit prevents interpreting these times as proof of this optimization.

Each build uses an empty compiler cache and clean target, four Cargo jobs, one stable Rust wrapper path/environment, and the fixed predecessor Clang adapter. Every build matches all 193 Rust/producer/native artifacts, records 167 Rust and 24 native misses with zero hits, and leaves tracked sources unchanged. OS filesystem caches remain warm; R2 is excluded. Baseline is ddfe785 and the experimental runtime is 46c1a6f, subsequently reverted by 8bdc776. This A/B experiment alone does not establish a win against kache.

[Initial raw samples](../benchmarks/harness-rust-locations-cold-first.json), [confirmation](../benchmarks/harness-rust-locations-cold-confirm.json), [runner](../benchmarks/experiments/rust_locations_cold_pair.py), [exact patch](../benchmarks/experiments/rust-locations.patch).

The stable Zig 0.17.0 build and unit checks pass. Unit tests exercise explicit targets, sysroot arguments, alternate paths and loader overrides. The [real installation fixture results](../benchmarks/rust-installation-locations-check.json) verifies direct Rust 1.97.1 location retention and byte-identical warm restoration, a native proxy performing both live fingerprint and graph probes, and Rust 1.98.1 fallback. The fixture ran in Linux/macOS CI for the experimental commit and remains available as an isolated experiment.
