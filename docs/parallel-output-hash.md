# Bounded parallel hashing of large cached outputs

This default-off experiment roughly halves standalone digest time for three real Harness cache blobs while preserving their digests. It has **not** demonstrated faster cache restores or full builds. Production is unchanged. [Every sample and verification](../benchmarks/parallel-output-hash-initial.json) is retained.

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

Private source, exact binaries, controls and verification are in `/tmp/nano-parallel-output-hash-candidate-20261011`. Next compare actual large-output cache requests using one binary at modes zero/two, priming each environment-specific key independently. Verify fresh references, preserved-mtime edits, output bytes/modes, diagnostics and reverts. Then run repeated untraced full Harness comparisons against frozen Nano and kache, with memory and host activity recorded, followed by independent confirmation. Do not promote this candidate on standalone digest timing.
