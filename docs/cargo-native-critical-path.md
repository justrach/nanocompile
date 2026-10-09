# Native compilation on the warm Cargo path

The [accepted Cargo timing capture](../benchmarks/cargo-timing-accepted.json)
identifies a larger target than the recent reader and worker experiments:
`ring`'s build-script execution remains expensive even when the build-script
executable itself restores successfully. In three clean warm builds it takes
**1.88 seconds each time**, out of 2.6767–2.7263 seconds observed for the build.
Its Rust dependencies are released near the end of the build. The local
`ring` 0.17.14 source uses `cc::Build` to compile its native library. The report
records its source checksum.

| Warm run | Observed build | Ring execution start | Ring execution duration | Ring ends | Final Harness unit ends |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 2.7263 s | 0.62 s | 1.88 s | 2.50 s | 2.70 s |
| 2 | 2.6767 s | 0.59 s | 1.88 s | 2.47 s | 2.64 s |
| 3 | 2.7019 s | 0.60 s | 1.88 s | 2.48 s | 2.65 s |

Cargo's unit intervals are rounded to hundredths of a second. They are wall
clock measurements, not CPU samples or a complete dependency DAG. The reported
`unblocked_units` connect ring's execution to its Rust compilation and rustls's
build-script execution. This establishes a late dependency bottleneck; it does
not predict the savings of removing any particular native compiler task.
Other build-script work and Cargo scheduling remain part of these intervals.

The accepted Nano executable is used directly as `RUSTC_WRAPPER`, with stable
Cargo `--timings`. No extra Python compiler wrapper is inserted. This is a
profile capture, not a new A/B speedup comparison. Each of the three warm builds
has 167 hits, nine bypasses and three failed probes; all 167 collected artifacts
match the prime. The timing-enabled command has one more bypass than the earlier
paired command. The capture records that observation rather than forcing the
older bypass count. All tracked Rust/manifest/lock contents remain unchanged in
the existing dirty Harness checkout. Rust is pinned to 1.97.1; four Cargo jobs
and a 40 GiB parent/Cargo/compiler process-tree cap are used. The prime takes
39.898 s. R2 transfer is excluded.

The locally installed `cc` 1.2.67 automatically selects `RUSTC_WRAPPER` as a native
compiler wrapper only for known names: sccache, cachepot, buildcache and kache.
Nanocompile is absent. Its documented `CC`/`CC_KNOWN_WRAPPER_CUSTOM` mechanism
can select a custom adapter explicitly. The source checksum is recorded. This
selection policy is evidence about cc's integration; it does not prove that
any particular kache benchmark served native cache hits.

## Local Apple Clang feasibility checks

The [Clang CAS fixture probe](../benchmarks/clang-cas-probe.json) uses the installed
Apple Clang 21.0.0 and its own dependency scanner and compilation cache:

```text
-fdepscan=inline -Xclang -fcas-path -Xclang <private CAS>
-Xclang -fcache-compile-job -Rcompile-job-cache
```

Both C with SDK/local headers and preprocessed assembly produce a reported cold
miss followed by a reported warm hit, with exact object bytes matching direct
compilation. A same-size header change with preserved mtime produces a miss
and an object matching a fresh direct compile. Deliberately failing source
returns compiler failure without an object. These are narrow local fixture
checks, not a production adapter, exhaustive native invalidation validation,
Cargo speedup, R2 cache or cross-platform support claim. Normal production code
and the installed Nano executable remain unchanged.

This motivates a controlled opt-in native compiler adapter for Cargo. The
build scripts must still execute every time; caching arbitrary build-script
side effects would invalidate this model. The native compiler should handle
its own dependency discovery and cache replay, as Xcode already does for the
existing managed Xcode cache. The next experiment can compare passthrough and
CAS compiler adapters at one stable `CC` path, with identical environment,
Rust wrapper and target/cache paths, so changing native dispatch does not
invalidate the Rust entries being measured.

Reproduce the profile using the accepted binary and a fresh state directory:

```sh
python3 benchmarks/experiments/cargo_timing_capture.py \
  /absolute/path/to/accepted/nanocompile /absolute/path/to/harness \
  --state /tmp/cargo-timing-accepted-new --warm-runs 3 \
  --output /tmp/cargo-timing-accepted-new.json
python3 benchmarks/experiments/cargo_timing_extract.py \
  /tmp/cargo-timing-accepted-new.json /tmp/cargo-timing-accepted-new
python3 benchmarks/experiments/clang_cas_probe.py \
  --output /tmp/clang-cas-probe-new.json
```

The extractor verifies each captured HTML checksum and reads embedded JSON
without running its JavaScript. The public JSON retains all unit intervals,
concurrency observations, binary/helper checksums, artifact hashes and tracked
source hashes. Private logs/HTML remain in the state directory; compiler
argument lists and environment values are excluded from public reports.
