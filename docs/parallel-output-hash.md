# Bounded parallel hashing of large cached outputs

This default-off experiment reduces one actual Harness `objc2-app-kit` cache restore from **159.043 ms to 82.252 ms median**, winning all 15 alternating pairs. On the [full Harness warm build](../benchmarks/harness-parallel-output-full-warm.json), the same executable at mode 2 has a **7.230 s median against 8.481 s** at mode 0, winning 7 of 9 alternating pairs. Both hosts were contended, so these results are promising but not confirmed. No kache comparison or production change has been made. [Every request sample and verification](../benchmarks/parallel-output-hash-request.json) and the [initial digest experiments](../benchmarks/parallel-output-hash-initial.json) are retained.

The [patch](../benchmarks/experiments/parallel-output-hash.patch) changes only output-blob validation. `NANOCOMPILE_BLOB_HASH_MODE=0` uses the existing streaming reader. Mode `1` reads a bounded owned buffer and hashes it serially. Mode `2` uses the same buffer and Zig 0.17.0's `Blake3.hashParallel`, with at most three additional worker threads. This separate buffered control helps distinguish allocation/read costs from parallel hashing. Only 32–256 MiB regular files use the new path; other sizes retain streaming. Default execution remains streaming.

The owned snapshot requires exact length and unchanged file state before hashing. Every byte is hashed with the same BLAKE3 format; input checks, keys, entry schema and materialization order remain unchanged. All output checks still finish before restoration writes. Larger buffers and extra threads may increase memory pressure or compete with Cargo jobs, so isolated throughput does not establish a project gain.

| Actual blob size | Streaming median | Buffered serial median | Bounded parallel median |
| --- | ---: | ---: | ---: |
| 135,604,864 bytes | 79.528 ms | 80.289 ms | 36.934 ms |
| 128,842,328 bytes | 73.162 ms | 76.128 ms | 33.288 ms |
| 117,455,539 bytes | 66.512 ms | 69.830 ms | 32.313 ms |

Each file has nine samples per mode, rotating order after excluded primes. Internal time includes opening, reading, hashing, worker startup/cleanup and result allocation; process elapsed times are also retained. All digests agree with the independently pinned official BLAKE3 C probe used in the earlier investigation. The C implementation is only a correctness oracle here, not a new runtime dependency.

Build/unit tests, real Rust/Zig integration and the executable fixture pass. Fifteen input sizes cover empty and chunk boundaries, 32 MiB threshold boundaries, non-power-of-two tails, the 256 MiB cap and streaming fallback above it. The new cache test verifies an odd-length 32 MiB output with single-input and 32-input manifests, including preserved-mtime blob corruption, untouched destinations on refusal and successful repair. Independent verification checks 95 source files, five validation logs, 153 probe executions and 306 streams. Fourteen aggregate observations cover the standalone comparisons with no recognized external build tools; this is not proof of an idle machine.

The first timing attempt stopped because its discovery code searched only the top level of the sharded CAS. No file timing comparison completed in that attempt. The corrected recursive discovery retains the failed report and all preceding successful correctness checks unchanged.

Reproduce the runtime source from `d88cdca` by applying `full-graph-eight-workers.patch`, then `parallel-output-hash.patch`. This reproduces every runtime/build source; the report identifies two unrelated helper differences in the private snapshot. The [probe](../benchmarks/experiments/parallel_output_hash_probe.zig) takes mode `0`, `1` or `2` followed by a file path:

```sh
zig build-exe -O ReleaseFast -lc --dep cache \
  -Mroot=benchmarks/experiments/parallel_output_hash_probe.zig \
  -O ReleaseFast -Mcache=src/cache.zig -femit-bin=/tmp/output-hash-probe
/tmp/output-hash-probe 2 /absolute/path/to/blob
```

## Actual compiler request

The replay uses the real `objc2-app-kit` 0.3.2 request captured from the matched full Harness build, with a cloned package, Rust 1.97.1 and fixed prebuilt dependencies. Both modes use runtime `6fb7d4d2e661d2f5f07dadb7838d63e6ffe8703bb7df2ccd8077b6dc14c7c5ea`. Their environment-specific keys are primed separately. Each timed request starts with an empty output directory; compiler caches and OS filesystem caches are warm. Trace and phase profiling remain enabled throughout.

| Fifteen warm pairs | Streaming | Bounded parallel |
| --- | ---: | ---: |
| Complete request median | 159.043 ms | 82.252 ms |
| Input-validation median | 32.831 ms | 33.410 ms |
| Output-validation remaining-wait median | 117.591 ms | 41.496 ms |

Mean paired savings are 77.534 ms, with a 0.831 ms standard error. The remaining-wait phase follows overlapping input/output validation; these phase values must not be added to estimate full-build savings. The request restores a 128,810,432-byte `.rlib`, a 117,430,175-byte `.rmeta` and dep-info. It is one feature configuration of this package, not every request with the same crate name.

All 42 compiler executions have matching direct-reference artifact hashes, sizes and permission modes. Saved compiler streams are byte-equal after removing Nano trace lines. An exported constant is added while preserving the source timestamp; direct compilation and both modes produce changed artifacts, and three linked consumers print `42`. Reverting gives hits. Flipping the last byte of the large cached archive while preserving its timestamp forces recompilation, repairs the blob and permits a subsequent hit. Cold/edit observations are single correctness checks, not repeated performance claims.

Independent verification checks 96 saved streams, 95 candidate source files, 310 original/cloned package files, 9,149 prebuilt inputs, recorded per-execution artifact maps, the final physical artifacts and repaired CAS blob. Earlier physical outputs were replaced by subsequent executions; only their recorded maps and streams remain. The raw report's phase array is empty because its collector expected per-request JSON files that this replay did not produce. A separate hash-linked analysis parses the preserved stderr directly and derives the request identity from the frozen runner; the original report remains unchanged.

The observer records 158 snapshots, including 96 with recognized external build activity. All samples are retained; short requests can have no snapshot inside their interval. These timings establish a promising mechanism under the observed conditions, not an uncontended result or a project-level advantage.

Private candidate files remain in `/tmp/nano-parallel-output-hash-candidate-20261011`; replay outputs and complete streams are in `/tmp/nano-parallel-output-objc2-replay-20261011`, with controls, verifier, phase analysis and aggregate observations in `/tmp/nano-parallel-output-objc2-replay-preparation-20261011`.

## Full Harness warm builds

The comparison uses one runtime (`6fb7d4d2…c5ea`) at `NANOCOMPILE_BLOB_HASH_MODE` 0 and 2 on the frozen Harness CLI workload (commit `32b41cb0`, dirty snapshot, Rust 1.97.1, eight jobs, recorded native contract). Each mode gets its own untraced prime, followed by nine alternating untraced warm pairs. Cargo target is removed before every build.

| Nine warm pairs | Streaming (mode 0) | Bounded parallel (mode 2) |
| --- | ---: | ---: |
| Median | 8.481 s | 7.230 s |
| Range | 6.923–10.371 s | 7.013–9.195 s |

Paired savings are 2.151, 0.514, 1.154, 1.321, 0.241, −0.018, −0.304, 0.889 and 3.159 s: mean 1.012 s, median 0.889 s, standard error 0.367 s. Most of the median difference comes from slow baseline outliers; the candidate is more consistent. A saving larger than the isolated request's 77 ms is plausible because the cache holds ten blobs in the 32–256 MiB range, but this run does not attribute the saving to specific requests.

Every warm build records 1,099 compiler hits, three misses and 31 build-script hits. All 20 builds pass cross-mode artifact byte checks against the first prime, their own permission modes, and CLI help checks. Independent verification rehashes all 20 consoles, 883 snapshot sources and 1,244 final artifacts with their modes. Sampled process-tree RSS stays below 410 MiB in warm builds and 5.5 GiB in primes.

The host was busy: the observer records recognized external build activity in 341 of 521 samples, including every warm interval, and a 598% median other-process CPU. Baseline outliers may reflect this contention. No samples were removed.

Private state is in `/tmp/nano-parallel-output-full-warm-20261011`; the frozen runner, controls, observer records and verification are in `/tmp/nano-parallel-output-full-warm-preparation-20261011`.

Next, independently confirm the full-build result on a quieter host using a fresh state directory. If it holds, compare the candidate with frozen Nano and kache in alternating cold, warm and source-edit trials. Keep the default unchanged until both checks pass.
