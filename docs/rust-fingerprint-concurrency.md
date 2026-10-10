# Cold fingerprint scheduling experiments

The [default-runtime phase profile](default-phase-profile.md) identifies approximately 0.35s in identity/key preparation for the first wave of small Harness crates. The [base commit, patch hashes and measured binaries](../benchmarks/experiments/fingerprint-scheduling-provenance.json) preserve reproducibility. These experiments preserve the complete installed resource graph and exact compiler/decoder content identities. They use stable Zig 0.17.0, Rust 1.97.1, macOS 27 and the 28-core M3 Ultra host. The installed graph contains 376 stamps, 360 regular files and 1,238,109,116 file bytes. Every cold observation uses a new private compiler cache; OS filesystem caches are unflushed.

## Rejected: largest resources first

The [retained scheduling patch](../benchmarks/experiments/largest-first-identity.patch) sorts work by descending file size but assembles the final fingerprint in its original sorted order. All workers finish and content/stamp checks are unchanged. Unit tests pass and the compiler/decoder identities match the baseline.

[Eleven alternating cold/warm pairs](../benchmarks/rust-largest-first-identity.json) show cold medians 344.027ms for the existing four-worker implementation and 351.043ms for the candidate. The candidate wins only 2/11 cold pairs; median paired saving is negative 7.074ms. This variation is rejected and production retains its original work order. Warm medians are 0.997ms and 0.990ms, too small a difference to justify this cold regression.

## Not promoted: up to eight workers

The [eight-worker patch](../benchmarks/experiments/eight-worker-identity.patch) changes only Rust initial-content concurrency from at most four to at most eight workers, capped by available CPU count. The existing file-count/byte thresholds, per-file locks, independent worker allocators, content hashing, post-hash stamps, original fingerprint order and fallback behavior remain unchanged. Zig stamp validation is unchanged.

[Eleven alternating cold/warm pairs](../benchmarks/rust-eight-worker-identity.json) show cold medians 340.966ms baseline and 263.511ms candidate, approximately 22.7% lower. The candidate wins 11/11 cold pairs; median paired saving is 78.641ms. Warm medians are 0.931ms and 0.916ms. Both complete compiler and selected decoder identities remain byte-identical throughout. These are fingerprint measurements, not whole-build speedups.

The candidate binary SHA-256 is `25be45a4c47333f2debf9d60aa695b1356e9ed07839c61e90726bd48f8d4aa4c`. Local unit and full real Rust/Zig integration checks pass. [Decoder/selector checks](../benchmarks/eight-worker-decoder-scope.json) verify Rust 1.97.1/1.98.1 changes, caller overrides and reuse. [Physical-memo checks](../benchmarks/eight-worker-physical-memo.json) verify loader overrides, compiler proxies and same-size preserved-timestamp source changes against direct compiler artifacts.

Whole-Harness timing must decide promotion separately. A smaller fingerprint interval does not justify claiming the same reduction in total compilation time, nor generalizing these results to machines with fewer cores or different storage.

## First whole-Harness A/B session

[Five alternating cold pairs](../benchmarks/harness-eight-worker-cold-ab.json) use the same wrapper path, environment, target path and source snapshot. Compiler caches are cleared before every build, including both primes. The candidate wins 4/5 pairs, with medians 15.657055s candidate and 15.831952s baseline, approximately 1.1% lower. Mean paired saving is 194ms with 79ms standard error; five pairs alone leave substantial uncertainty. The fourth pair favors baseline by 72ms. The baseline prime is an 18.733s outlier and is retained but excluded from paired medians.

Every cold run has 167 Rust misses and one script miss, with zero hits. All 194 repeated artifact hashes match their respective binary's prime. The sole cross-binary difference is the copied Nano ring launcher; the actual `.nano-real` compiled script and all other collected artifacts are equal. Tracked sources remain unchanged. The separate macro/producer options and ring execution contract are still explicit opt-ins; no stream/companion overrides are set.

The confirmation below decides promotion separately from the isolated fingerprint result.

## Whole-build confirmation and decision

[The independent five-pair confirmation](../benchmarks/harness-eight-worker-cold-confirm.json) gives medians 15.856944s baseline and 15.797920s candidate, approximately 0.4% lower for the candidate, with only 3/5 candidate wins. Mean paired saving is negative 204ms, including a candidate run losing by 1.200s. Every observation is retained; no slow sample is discarded. All 194 artifacts match each binary's own reference, with the same sole copied-launcher cross-binary difference and unchanged source hashes.

Across both batches the candidate wins 7/10 pairs; the median paired saving is 125ms, but the mean is negative 5ms, effectively zero at this scale. Different medians or a better isolated phase do not establish a dependable additional whole-build gain. **Eight workers are not promoted. Production retains four workers.** The frozen experimental binary and source patch remain available for further machine-specific research; its correctness checks passing does not make it the recommended runtime.

The next variation should split the cold validation/graph/storage outliers from the ordinary phase profile and identify an actual critical-path cost. Repeating worker-count changes on the same host is not the next priority. Preserve all content and output checks and require repeated whole-build gains before adoption.

## Experimental binary against kache

[Three cold pairs and three warm rounds](../benchmarks/harness-eight-worker-kache.json) compare the frozen eight-worker candidate to kache 1.0.0 with the same reported macro/producer options, ring execution contract and unchanged native compiler. No streaming or companion overrides are set. Cold medians are Nano 15.691097s and kache 16.985372s, approximately 7.6% lower, with 3/3 Nano wins. Warm medians are Nano 0.942541s and kache 1.146581s, approximately 17.8% lower, with 2/3 Nano wins; the final warm sample favors kache. Every cold Nano build has 167 Rust misses and one script miss; every warm Nano build has 167 Rust hits and one script hit. Repeated artifacts match own-cold references and sources remain unchanged.

This confirms that the experimental runtime still beats kache in these measured cold builds, but does not demonstrate a dependable improvement over the accepted four-worker Nano default. Those comparisons answer different questions. The eight-worker candidate remains unpromoted; the accepted default's separate [repeated results](default-pipelining.md) remain authoritative for production.
