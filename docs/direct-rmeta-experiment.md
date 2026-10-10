# Direct Rust dependency metadata decoding

The current graph profile spends about 2.45 aggregate seconds querying own-artifact roots through separate rustc processes. This experiment decodes the root and ordered dependency list of ordinary `.rmeta` files directly in Zig. It preserves the live sysroot/target-libdir query, selected resource checks, full mutable content hashing, directory/library guards and existing entry keys. The integration calls rustc as before whenever the direct decoder refuses a record.

The decoder accepts only the exact Rust 1.97.1 metadata version, ordinary built-in targets and known symbol encodings. It refuses custom JSON targets, producer proc-macro metadata/stubs, unknown predefined symbol indices, unknown versions and malformed/truncated data. Rust 1.98.1 uses the original query path. This is an optimization of an explicitly pinned private compiler format, not a general stable Rust metadata API.

## Correctness and provenance

The layout comes from pinned upstream [CrateRoot and CrateDep definitions](https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/compiler/rustc_metadata/src/rmeta/mod.rs) and its decoder. [Format provenance](../benchmarks/rmeta-direct-format-provenance.json) records source URLs and symbol-source hashes.

On 135 actual Harness metadata files, 129 decoded roots and ordered dependency lists exactly match rustc; six files fall back. Separate real-compiler fixtures cover crate extra filenames, a no-std leaf, transitive dependencies and a consumer of a proc macro. Producer proc-macro metadata and actual Rust 1.98.1 records refuse. Mutation checks exercise truncated files, unknown versions, bad headers, invalid root offsets and missing end markers. See the [corpus oracle](../benchmarks/rmeta-direct-oracle-check.json) and [focused fixtures](../benchmarks/rmeta-direct-fixture-check.json).

Stable Zig 0.17.0 unit and real compiler integration pass, as do native identity, native metadata, static native, producer, executable and compiler-selection fixtures. [Candidate checks](../benchmarks/rmeta-direct-candidate-checks.json) record commands and source/binary hashes. The measured baseline executable is `ce7204f1e4bd5968d5e40d7dd3c9496c2a4b77b4344f718718108911b4e57a3c`; candidate is `5ed66df486b821e3e5ff90eaa42b14996eae9afd2fe3468314aa5469783ecd93`.

## Complete Harness builds

Each cold build removes both target and entire cache. Alternating baseline/candidate pairs use the same wrapper path, environment and fixed native adapter on the same dirty Harness checkout `32b41cb0bff55e3c9cbfab3012acec2b179ad199`. Cargo uses four jobs and the 40 GiB process-tree RSS cap. All twelve controlled cold builds record 167 Rust misses, 24 native misses, no hits and 193 byte-identical artifacts. Tracked Rust sources, manifests and lockfile remain unchanged.

| Batch | Baseline median | Candidate median | Reduction | Candidate pair wins |
| --- | ---: | ---: | ---: | ---: |
| First, 3 pairs | 28.253485 s | 27.252123 s | 3.54% | 3/3 |
| Independent confirmation, 3 pairs | 29.059118 s | 27.593439 s | 5.04% | 3/3 |

All six cold pairs favor the candidate. Mean paired savings are 1.285 s and 1.338 s; descriptive standard errors are 0.755 s and 0.222 s respectively. These small local batches establish a promising workload-specific cold result, not a universal speed guarantee. [First raw batch](../benchmarks/harness-rmeta-direct-cold-first.json), [confirmation raw batch](../benchmarks/harness-rmeta-direct-cold-confirm.json).

The first 27-pair warm batch is mixed: baseline median 2.054554 s, candidate 2.084473 s (candidate 1.46% slower), with 14/27 candidate pair wins. Mean paired saving is −0.004289 s with descriptive standard error 0.021742 s. This does not establish a repeatable warm improvement or regression. Both prime builds are retained too: 30.689803 s baseline and 31.685755 s candidate, so the candidate does not win every observed miss build. All 54 warm builds record 167 Rust and 24 native hits and match 193 artifacts. [Warm samples including primes](../benchmarks/harness-rmeta-direct-warm-paired.json).

The independent 27-pair warm confirmation records 2.077103 s baseline and 2.026316 s candidate medians (candidate 2.45% lower), with 17/27 candidate wins. Mean paired saving is 0.031964 s and descriptive standard error 0.016945 s. All 54 confirmation warm builds again restore 167 Rust and 24 native hits with 193 matching artifacts. Confirmation primes are 31.387251 s baseline and 29.162374 s candidate. [Full warm confirmation](../benchmarks/harness-rmeta-direct-warm-confirm.json).

The opposite median directions across the warm batches do not support a robust warm speed claim. They show no repeatable warm regression. The candidate is adopted for its consistent controlled cold benefit, with the exact-version refusal policy and original rustc fallback preserved. Production source is copied byte-for-byte from the measured candidate; the rebuilt installed executable passes unit and real Rust/Zig integration again ([installed provenance](../benchmarks/rmeta-direct-installed-provenance.json)). The CI workflow adds the focused real-compiler metadata oracle on Linux and macOS. This experiment compares two Nano implementations, not kache. The corpus decoder microbenchmark batches all inputs into one process and must not be reported as a whole-project speedup.

## Reproduction

The [candidate patch](../benchmarks/experiments/rmeta-direct.patch), [standalone decoder](../benchmarks/experiments/rmeta_direct.zig), [corpus checker](../benchmarks/experiments/rmeta_direct_check.py), [real compiler fixture](../benchmarks/experiments/rmeta_direct_fixture_check.py), [cold pair runner](../benchmarks/experiments/rmeta_direct_cold_pair.py) and [warm pair runner](../benchmarks/experiments/rmeta_direct_warm_pair.py) retain the experiment independently of its adoption decision. The broader [performance roadmap](performance-roadmap.md) covers cache coverage, edit builds, transport and Zig workloads.

To apply the retained zero-context patch, start from production baseline `2bad601` in a disposable checkout and run `git apply --unidiff-zero benchmarks/experiments/rmeta-direct.patch` with the patch supplied from this revision. Avoid applying it to the already-updated source.

The adopted source passes [hosted Linux/macOS CI](https://github.com/justrach/nanocompile/actions/runs/38017220898). A [fresh nine-round installed comparison](direct-rmeta-nine-samples.md) measures current Nano, direct Cargo and kache separately from the predecessor experiment.
