# Measured optimization trail

For a real Cargo workload, start with the [Harness comparison against kache](kache-harness.md): direct 22.77 s, nanocompile 22.95 s, kache with its daemon 2.01 s. The individual compiler fixtures below measure warm-hit latency and do not predict project-level performance.

The final run used the actual `nanocompile 0.1.0` release binary built with stable Zig 0.17.0 on macOS/arm64. Its SHA-256, timestamp, every sample, compiler versions, and kache counters are recorded in [results.json](results.json). The measured binary's checksum was checked against `zig-out/bin/nanocompile` after the run.

## Final comparison

25 measured runs per case, rotating measurement order. Timing includes process startup and artifact restoration, with the primary output removed before each run.

| Workload | Direct compiler median | nanocompile hit median | Comparison |
| --- | ---: | ---: | --- |
| Rust: 1,200 exported arithmetic functions, optimized rlib | 326.46 ms | 6.72 ms | 48.56× direct compilation |
| Zig: small executable, native compiler cache already warm | 120.25 ms | 11.58 ms | 10.39× direct invocation |
| Same Rust fixture through kache 1.0.0 | kache hit: 10.15 ms | 6.72 ms | 33.8% less time, 1.51× throughput for serial requests |

All 25 nanocompile measurements per language were recorded hits. Kache's store contained one entry, and its counters recorded 25 local hits and one miss. Both caches were standalone during timed compiles. Kache's stats command briefly started a daemon afterward; the script stopped it. This is not a comparison against a prestarted kache daemon.

Outputs are validated, not just timed. Nanocompile's Rust outputs match the direct compiler bytes. Zig native executable bytes can change between fresh links, so restores are compared to the cached cold artifact and the direct executables are executed. Kache can remap embedded paths: its restored bytes must match its own cold artifact, and a separately linked consumer checks representative function results.

The first nanocompile miss took 925.33 ms for Rust and 310.26 ms for Zig, including the initial full toolchain fingerprint. Kache's Rust miss took 376.97 ms. This first-use cost is a real regression; subsequent crates share the verified toolchain identity. The benefit depends on enough repeated eligible work to amortize it.

These are synthetic latency fixtures. They do not establish a whole-project, cold-build, daemon, large-dependency-directory, or cross-machine advantage. The Rust fixture has no extern search directory; the wrapper's conservative transitive-library hashing costs more on large Cargo dependency graphs.

## Changes guided by measurements

| Experiment | Rust hit median | Zig hit median | Decision |
| --- | ---: | ---: | --- |
| Version query on every invocation | 30.67 ms | 34.83 ms | Compiler startup dominated the hit path |
| Memoized content identity, verifying all installed resources | 14.14 ms | 66.72 ms | Helped Rust; rejected the Zig resource scope |
| Check only eligible Zig compiler/std/runtime resources | 14.21 ms | 7.54 ms | Removed 19,000 unrelated C/C++ header checks |
| Exclude Rust source/debugger resources unused by eligible compilation, then finish integrity/host/output locking checks | 6.72 ms | 11.58 ms | Final validated implementation |

The first three exploratory runs are retained in [baseline.json](baseline.json), [toolchain-memo.json](toolchain-memo.json), and [zig-resource-scope.json](zig-resource-scope.json). They used smaller sample counts, an earlier measurement order, and earlier implementations. They explain the decisions but are not controlled A/B results or independently reproducible historical binaries. The final comparison uses one script, validated cache hits, a binary checksum, and rotated order.

Toolchain memo keys were also narrowed to actual selection variables, while compilation keys still include the full environment. An integration assertion verifies that two Cargo crates share one new toolchain memo rather than hashing the installation again for each package's environment values. Warm toolchain validation uses shared locks, so different compilation requests can validate concurrently.

## Reproduce

```sh
zig build -Doptimize=ReleaseFast
zig build test
zig build integration -Doptimize=ReleaseFast
python3 tests/benchmark.py zig-out/bin/nanocompile --runs 25 \
  --kache /path/to/kache --output benchmarks/results.json
```

The kache comparator used the official aarch64 macOS v1.0.0 release archive. Its published SHA-256 matched `6d1be0079d0689a85fa04b7fed7eaa94f7e08259cafb8bd361a5c25c4c98c4a3`. The benchmark isolates its cache, configuration, host configuration, and daemon socket in a temporary directory. It never runs `kache init` or edits Cargo's global configuration.
