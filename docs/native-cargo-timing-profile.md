# Accepted native-CAS Cargo timing profile

Three clean warm Harness builds identify ring's native build script as the
largest remaining Cargo unit. It takes **1.24, 1.22, and 1.23 seconds**;
the corresponding measured builds take **2.095245, 2.045258, and 2.025664
seconds**. This is diagnostic evidence for the next optimization target,
not a speedup or a new kache comparison. Production code is unchanged.

The accepted executable is used directly as both `RUSTC_WRAPPER` and
`CC=".../nanocompile clang"`, with native hit remarks enabled. Its SHA-256 is
`4006ac4f93d81d5bfed50a9ce5bd8d89b567a6ecfba42277335c2977768946ac`.
The measured repository revision is `5b64aae`; its production code is the
accepted Clang-selection-overlap implementation. Harness is the dirty user
checkout at `32b41cb0bff55e3c9cbfab3012acec2b179ad199`, package
`harness-adapters`, Rust 1.97.1. Tracked Rust sources, manifests, and lockfile
are hashed before and after and remain unchanged.

Each build uses four Cargo jobs, an isolated fixed target/cache directory,
offline locked release library mode, disabled incremental compilation,
reported proc-macro inputs, and explicit macro/executable producer caching.
The collector enforces a 40 GiB sampled process-tree RSS limit and an hour
time limit. Cargo's stable `--timings` adds instrumentation; these durations
must not replace the uninstrumented comparison measurements.

| Warm sample | Measured build | ring build-script run | ring starts | ring ends |
| --- | ---: | ---: | ---: | ---: |
| 1 | 2.095245 s | 1.24 s | 0.63 s | ~1.87 s |
| 2 | 2.045258 s | 1.22 s | 0.62 s | ~1.84 s |
| 3 | 2.025664 s | 1.23 s | 0.61 s | ~1.84 s |

Cargo records ring unblocking its Rust library and rustls's build script.
The last finishing units include rustls, rustls-webpki, tokio-rustls,
hyper-rustls, reqwest, and finally harness-adapters. This placement supports
profiling the native work inside ring next. Cargo rounds unit timestamps to
hundredths of a second, so derived end times can overlap the next unit by
one hundredth. Its unblock edges are scheduling observations rather than
a complete dependency graph; this does not prove an exact critical path
or attribute ring's time to any particular system call.

All four builds, including the 38.804807-second prime, have **193 identical
artifact hashes**, including 24 native objects and two archives. Each warm
build records **167 Rust hits, 24 native hits, three failed compiler probes,
and nine bypasses**. Native hits therefore do not imply that ring's whole
build-script execution is free. The next profile should separate native
compiler selection, Clang invocation, and other build-script work while
preserving live SDK selection and mutable-input hashing.

Reproduce from a new state directory:

```sh
python3 benchmarks/experiments/cargo_timing_capture.py \
  zig-out/bin/nanocompile /Users/rachpradhan/harness --native-clang \
  --state /tmp/nanocompile-native-cargo-timing-verified \
  --output benchmarks/harness-native-cargo-timing.json --warm-runs 3
python3 benchmarks/experiments/cargo_timing_summary.py \
  /tmp/nanocompile-native-cargo-timing-verified/warm-{1,2,3}-cargo-timing.html \
  --output benchmarks/harness-native-cargo-timing-units.json
```

[Build evidence and artifact/source digests](../benchmarks/harness-native-cargo-timing.json)
and [all 187 Cargo units per warm sample](../benchmarks/harness-native-cargo-timing-units.json)
are retained. The original HTML reports remain in the local state directory;
their SHA-256 values are recorded in both datasets. The extractor parses
embedded JSON without executing the HTML.
