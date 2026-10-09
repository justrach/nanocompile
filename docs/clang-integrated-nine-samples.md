# Integrated cc1: nine-sample complete comparison

The adopted integrated-cc1 version has warm medians of **2.037682 seconds
Nano, 2.506297 seconds kache, and 24.499832 seconds direct Cargo** in this
local session. Nano is faster than kache in all nine corresponding rounds.
All samples, including slower runs, are retained.

| Mode | Median | Mean | Range | Sample standard deviation |
| --- | ---: | ---: | ---: | ---: |
| Direct | 24.499832 s | 24.530059 s | 23.511668–25.521107 s | 0.632199 s |
| Nano | 2.037682 s | 2.096905 s | 1.992230–2.368820 s | 0.130048 s |
| kache | 2.506297 s | 2.671019 s | 2.136777–3.781673 s | 0.593161 s |

Same-round Nano-minus-kache differences have median **−422.437 ms**, mean
**−574.114 ms**, and descriptive standard error **160.299 ms**. The rotating
rounds share one host/session and are not independent machine trials. Kache
varies substantially; its seventh/eighth samples take 3.565005/3.781673 s,
while Nano's corresponding samples take 2.238851/2.368820 s. The cause of
this variability is not established. This session supports a local warm
latency lead, not a universal advantage or attributing the entire difference
to integrated cc1. The controlled two-binary comparisons establish the
5.14%/5.62% gain separately.

The [previous nine-sample session](../benchmarks/harness-clang-selection-nine-samples.json)
had medians 2.005335 s Nano and 1.962289 s kache. That ordering is retained
as historical evidence. Comparing Nano's absolute times across these
sessions does not measure the source change: target/cache states and
measurement sessions differ.

Cold remains slower for Nano: **38.066364 s Nano versus 27.462381 s kache**.
The direct prime takes 23.552804 s. All 27 warm builds match their own cold
Rust libraries, macro dylibs, build-script executables, native objects and
archives; all tracked Rust/manifest/lockfile hashes remain unchanged.
Every Nano warm build has **167 Rust hits, 24 native hits, eight bypasses,
and three failed compiler probes**. Every kache warm build has **187 local
hits and three passthroughs**. Compiler-owned scanner debug representation
and kache's path remapping prevent asserting cross-mode byte equality.

The measured core revision is `8f6dace1054341dcd215f6502f7adb2e157437c4`;
installed executable SHA-256 is
`f03c9570446371873565886f4e6ba980629547f99284437240c13a2003200be1`.
The host is Apple M3 Ultra, 28 logical CPUs and 256 GiB RAM, on arm64 macOS
27. Builds use Rust 1.97.1, four Cargo jobs, a 40 GiB sampled process-tree
RSS cap, locked offline release library mode, and clean fixed target paths.
The private kache daemon is explicitly started and cleaned up by the runner.
Three-way order rotates each round. Nano explicitly opts into native Clang
CAS, reported macro inputs and macro/executable producer caching.

```sh
env RUSTUP_TOOLCHAIN=1.97.1 python3 tests/project_comparison.py \
  zig-out/bin/nanocompile /Users/rachpradhan/harness \
  --kache /tmp/nanocompile-kache-bin/kache \
  --state /tmp/nanocompile-clang-integrated-nine-way \
  --runs 9 --jobs 4 --proc-macros reported \
  --proc-macro-producers --executable-producers --native-clang \
  --output benchmarks/harness-clang-integrated-nine-samples.json
```

[Full build evidence](../benchmarks/harness-clang-integrated-nine-samples.json),
[summary with every sample and same-round difference](../benchmarks/harness-clang-integrated-nine-analysis.json),
and [reproducible summary script](../benchmarks/experiments/three_way_summary.py)
retain the results. The adopted core also passes
[Linux and macOS CI](https://github.com/justrach/nanocompile/actions/runs/38002956103),
including real compiler, producer, native-selector and Turborepo checks.
