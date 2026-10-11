# Matched warm Harness profile

The [nine-build capture](../benchmarks/harness-warm-gap-matched-profile.json) completes the requested matched Nano/kache warm diagnostic. It contains a direct reference, empty-cache primes for both caches, and three alternating warm pairs on the full Harness CLI with the same eight-worker Nano runtime and pinned kache 1.0.0. Production still uses four input workers.

| Warm pair | Nano, traced | kache, traced |
| --- | ---: | ---: |
| 1 | 9.341 s | 7.193 s |
| 2 | 7.846 s | 6.612 s |
| 3 | 7.696 s | 6.947 s |

These observations locate work; they are not untraced speed measurements. Nano records 1,099 compiler hits, three misses and 31 script hits in each warm build. Kache records 1,237 local hits. Expected failed compiler feature probes remain in the logs. Both implementations reproduce their own cold artifacts and permission modes and pass CLI checks.

Every build has 1,237 Cargo units. All nine complete consoles and capture manifests verify; Nano captures 1,145 compiler/probe requests per build, kache 1,226 cold and 1,103 warm. All 883 frozen snapshot files verify. The final kache output set has 1,214 verified permission modes; Nano additionally collects its script launchers. The public report retains capture-manifest and artifact-map digests. Every individual artifact hash/mode and all raw streams remain in the private report and capture directories.

The largest `objc2_app_kit` output-validation wait in each Nano warm build is **102.136, 120.028 and 121.316 ms**. This is the remaining wait after overlapping output checks with input validation. Current code checks large output blobs on one worker. The final Harness request still spends time validating its large input graph; these are separate costs, and overlapping request durations cannot be summed into predicted project savings.

The [parallel-output experiment](parallel-output-hash.md) therefore targets large output blobs while preserving complete reads and digests. It is separate from the earlier source-first experiment, which did not establish a warm improvement. Require actual cache-restore comparisons, edited/corrupt output checks and repeated full Harness baseline/kache trials before changing defaults.

The quiet-host preflight was deliberately ended before any full build so that diagnostic work could proceed. During the capture, the observer records 578 snapshots and no recognized external build tools, but other-process CPU observations have a median of 323.4% and maximum of 1017.8%. This is not an idle-host qualification; sampling and process-name detection also have limits. No samples were discarded.

Raw evidence is in `/tmp/nano-warm-gap-matched-profile-20261011` and its adjacent JSON report. Frozen controls, source helpers, observer records, retained preflight history and verification are in `/tmp/nano-warm-gap-matched-profile-preparation-20261011`; full analysis and timeline are in `/tmp/nano-warm-gap-matched-profile-analysis-20261011`. The analyzer used for this frozen capture predates the explicit `warm_caches_only` provenance field, but the raw report and method record the schedule.
