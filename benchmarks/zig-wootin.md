# Raw Zig on Wootin

Stable Zig 0.17.0, ReleaseFast, macOS 27, Apple M3 Ultra (28 CPU cores, 256 GiB). The workload is the real headless Base64 component of [Wootin](https://github.com/justrach/witty), snapshot `04ac6717a0b2c69cd138fb6f6dc17ba6a66c2f90`: `Tests/Base64Benchmark/Base64BenchmarkMain.zig` and its `strict_base64` module. This is not the complete Wootin application.

## Validation and scope

[Runner](../tests/zig_project_benchmark.py), [all samples, source hashes, output hashes and binary checksum](wootin-zig-project.json). Three alternating cold pairs, nine alternating restore/native-cache pairs and three independent source-edit cycles. Each cycle primes both tools, changes the root iteration count from 24 to 25, changes shared decoder arithmetic to equivalent shifts/masks, then reverts both files. Normal edit timestamps are updated. All executable results are checked: exact decoded bytes, invalid-input rejection, split boundaries and equal tokens. Nano restores must match their own cached binary bytes; fresh macOS links can differ, so cross-tool byte equality is not asserted. Executable runtime is outside the build timer. Only a disposable snapshot is edited; sources are restored finally.

Cold means empty wrapper and Zig local/global caches. OS filesystem caches remain warm. For the direct native-cache case, Zig caches remain populated but the executable is removed. For Nano restore hits, both Zig caches are removed before each invocation. These are raw `zig build-exe` invocations, not `zig build` whole-artifact cache hits. Dependencies, network access, R2 and compiler installation are outside timing. This does not establish an advantage over Zig's build runner, Rust/kache, or full GUI builds.

## Complete benchmark results

| Case | Direct Zig median | Nano median | Samples per tool |
| --- | ---: | ---: | ---: |
| Cold | 6.8938 s | 6.950685 s | 3 |
| Populated native cache / Nano restore | 5.0786 s | 0.007197 s | 9 |
| Root source edit | 5.0376 s | 5.051132 s | 3 |
| Shared source edit | 5.0452 s | 5.052708 s | 3 |
| Source revert | 5.0795 s | 0.008154 s | 3 |

Nano restores and source reverts save substantial time in this raw-invocation workload. Cold and new source edits are effectively tied, with Nano slightly slower at the medians. No cold-compilation win is claimed.

## Profile and accepted optimization

An [isolated phase profile](wootin-zig-profile.json) identifies 982 installed-resource stamp checks as a warm-path cost: median stats 1.261 ms, memo decoding/integrity 0.695 ms, compilation key preparation 2.604 ms, artifact restore 0.623 ms. These are internal diagnostic timers, not process wall times. The cold compiler takes 6.795 s versus 0.227 s preparing the initial key. The profile does not distinguish LLVM optimization from code generation/linking; it establishes that compiler execution dominates and the cache wrapper cannot eliminate new compilation work.

The accepted change checks all the same installed resources in parallel, using up to four workers only for Zig memo records with at least 512 stamps. Every worker completes and any failed or changed stamp rejects the memo. Rust checks retain their existing sequence. A regression checks changed and missing resources. No resource or content-integrity check is removed.

Two independent batches use the same wrapper path, cache, output, arguments and environment. Both binaries include the source-cache correctness fix below; only stamp parallelism differs. Traces verify that the candidate optimization activated on every measured hit, and every restored artifact matches the prime. Both runs contain timing outliers; all samples are retained.

| Session | Serial median | Parallel median | Parallel wins |
| --- | ---: | ---: | ---: |
| [First, 27 pairs](wootin-zig-stamp-first.json) | 7.911 ms | 7.208 ms | 24/27 |
| [Confirmation, 27 pairs](wootin-zig-stamp-confirm.json) | 7.470 ms | 6.667 ms | 27/27 |

That is approximately 9–11% less restore latency on this machine. It is not a measured cold-compilation improvement or a universal speed guarantee.

## Preserved-timestamp correctness fix

The initial [aborted diagnostic](wootin-zig-stale-diagnostic.json) found a same-size root edit from 24 to 25 still executing 24. Direct Zig and Nano's miss both reused stale native parsing state. Content hashing alone did not prevent the compiler from returning an old result. Its incomplete timings are not the accepted benchmark.

Eligible Nano Zig misses now use a fresh private local compiler cache; the global compiler cache remains available. Private directories are cleaned after compilation. Hits restore artifacts without launching Zig. A Zig-only cache-key domain change invalidates old entries once. This trades local parsing reuse on new edits for correct source results; it does not modify the Zig compiler or Rust cache keys.

The [regression runner](../tests/zig_preserved_mtime.py) edits an imported constant 42→43 with identical size and preserved mtime, checks against a separate fresh direct compilation, checks repeat restores, then verifies reverting returns the original artifact. [Old-binary reproduction](zig-preserved-mtime-baseline.json) observes 42; [integrated runtime result](zig-preserved-mtime-fixed.json) observes 43 and passes restore/revert checks. CI runs this on Linux and macOS.

## Reproduce

Use a disposable checkout of Wootin at the pinned revision and a fresh state directory:

```sh
zig build -Doptimize=ReleaseFast
python3 tests/zig_project_benchmark.py zig-out/bin/nanocompile /path/to/disposable/wootin \
  --state /tmp/new-zig-benchmark --output /tmp/wootin-results.json
python3 tests/zig_preserved_mtime.py zig-out/bin/nanocompile \
  --output /tmp/zig-preserved-mtime.json
```

The exact diagnostic instrumentation is retained in [zig-phase-profile.patch](experiments/zig-phase-profile.patch), against Nano `537a79b87923473a56b66484ef2c345ed789454f`. The stamp A/B runner is [zig_stamp_pair.py](experiments/zig_stamp_pair.py); its baseline uses the correctness fix with the pre-change serial identity implementation. The [accepted source patch](experiments/zig-cache-changes.patch) and [measured binary provenance](experiments/zig-provenance.json) are retained alongside the report.
