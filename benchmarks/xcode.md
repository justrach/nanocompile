# Xcode comparison

Xcode is a build system, so compiler-family coverage matters. Kache 1.0.0 can
wrap Apple Clang but does not accept Swift compiler invocations. Nanocompile's
current cache core supports Rust/Zig; it passes Xcode Clang through. Swift uses
Xcode's native driver in this comparison. Neither external cache is credited
with Swift caching.

## Harness iOS app: complete clean-build comparison

The real app comparison ran on the same M3 Ultra / Xcode 27.1 machine, four
jobs, Release, generic iOS Simulator destination, signing disabled. Packages
were resolved before timing: Loro 1.13.3, swift-markdown 0.8.0 and cmark-gfm
0.8.0. Three warm samples per pipeline, rotated order, dedicated Build outputs
deleted each time; the Swift integrated driver retained its normal behavior.

| Pipeline | Warm clean-build median | External cache hits |
| --- | ---: | ---: |
| Xcode native tools, compilation caching disabled | 46.77 s | reference |
| nanocompile Clang launcher | 48.43 s | 0 |
| kache 1.0.0 Clang launcher | 48.75 s | 0 |
| Xcode native compilation cache enabled | **4.17 s** | 122 native job hits |

The native Xcode cache is **11.2× faster than the direct build** here. Both
external tools record 73 passthrough/bypass calls per rebuild: 70 C compiles
and three discovery probes. Swift remains handled by Xcode. Kache refuses
Xcode's response files, module-session options and serialized diagnostics;
its generic Apple Clang support does not cover this command-line profile.

All 16 builds succeeded. Every warm build's 440 objects/archives matches its
pipeline's cold artifacts by SHA-256. Every built app has a valid Mach-O
executable and all 16 app executables have the same SHA-256. The three native
warm samples were 4.347, 4.171 and 4.173 seconds and each logged 122 native job
cache hits. Sampled process-tree RSS peaked at 5.04 GiB, below the 40 GiB guard.
The native-cache cold build took 52.51 s, versus 52.25 s for the direct prime;
these are single samples, not evidence of a cold-build advantage.

The source snapshot came from the user's dirty local Harness checkout. Its
source-file hashes and every timing/output hash are recorded in
[xcode-harness.json](xcode-harness.json). A checksum-verified Loro archive was
seeded into a private SwiftPM cache to avoid a stalled Xcode downloader;
dependency manifests and sources were unchanged. Download/resolution time was
excluded from all measurements. This does not benchmark the Rust desktop app.

## Completed Clang baseline

Real `xcodebuild` on Apple M3 Ultra, macOS 27, Xcode 27.1 (27A9269), four build
jobs, Release, unsigned macOS executable. The generated project has 32 C units
with 64 arithmetic functions each plus a checked main: 33 object files total.
Every build deletes its dedicated DerivedData/Build directory. Module/SDK caches
are preserved equally. Three warm samples per mode, rotated order.

| Pipeline | Warm clean-build median | Cache coverage |
| --- | ---: | --- |
| Xcode native tools, compilation caching disabled | 1.181 s | reference |
| nanocompile Clang launcher | 1.398 s | 35 bypass calls, zero hits |
| kache 1.0.0 Clang launcher, isolated daemon | 1.475 s | 35 passthrough calls, zero hits |
| Xcode native compilation cache enabled | 1.186 s | 33 object cache hits per warm build |

Each external pipeline includes a Python instrumentation launcher; the direct
and Apple-cache modes use native tools without it. That launcher overhead is
part of these timings. Do not interpret the small timing differences as compiler
cache advantages. Xcode startup and scheduling dominate this tiny workload;
Apple's recorded object hits do not produce a whole-build speedup here.

All warm object hashes match their pipeline's cold objects, and every linked
executable ran successfully and printed `fixture-ok`. Kache's cache events
report the exact refusal: response-file expansion, `-fmessage-length=0`,
`-fmacro-backtrace-limit=0`, and `--serialize-diagnostics` are unsupported in the
measured 1.0.0 binary. Two compiler-discovery probes account for the extra calls.
A generic claim of Apple Clang support does not establish support for Xcode's
full emitted command line.

Raw samples, per-file hashes, refused flags, tool versions, executable checksums
and native cache diagnostics are in [xcode-clang.json](xcode-clang.json).

## GitHub Mac runner result

The same Clang fixture also passed on a hosted macOS 26.6.2 arm64 runner with
Xcode 26.6 (17F113), three warm samples per mode. Direct median was 3.098 s,
nanocompile 3.326 s, kache 3.114 s, and Xcode-native cache 2.440 s. Both external
tools again recorded zero hits; Apple's warmed builds logged object cache hits.
All 16 builds ran the checked executable successfully and restored object hashes
matched the cold references. This is the small C fixture, not the Harness app;
do not compare these timings directly with the M3 Ultra app workload.

[Raw hosted-runner data](xcode-github-macos.json) and the
[successful workflow run](https://github.com/justrach/nanocompile/actions/runs/37913233628)
record the tool versions, every sample and artifact hashes.

## Harness iOS benchmark

The same script supports the real Harness iOS project, including its Swift and
C package dependency graph. It copies the project sources to a dedicated
snapshot, resolves packages before timing, builds a generic iOS Simulator app
with signing disabled, and validates its app executable and compiled objects.
The native Swift integrated driver remains enabled. The completed local measurements are recorded above; the script remains
available for other Xcode projects.

This is a build benchmark, not a simulator UI test. No app is installed,
launched, signed or uploaded to TestFlight. R2 transport is excluded from timed
builds so the result measures local compilation/cache coverage.

## Reproduce

```sh
zig build -Doptimize=ReleaseFast
python3 tests/xcode_fixture.py /tmp/xcode-fixture-new
python3 tests/xcode_comparison.py /tmp/xcode-fixture-new/ClangFixture.xcodeproj \
  --scheme ClangFixture --destination platform=macOS \
  --nanocompile zig-out/bin/nanocompile --kache /path/to/kache \
  --state /tmp/xcode-comparison-new --output bench-results/xcode.json \
  --runs 3 --native-cache --verify-executable Release/ClangFixture

python3 tests/xcode_comparison.py /path/to/harness/apps/ios/Harness.xcodeproj \
  --scheme Harness --nanocompile zig-out/bin/nanocompile --kache /path/to/kache \
  --state /tmp/harness-xcode-new --output bench-results/xcode-harness.json \
  --runs 3 --native-cache --verify-app Release-iphonesimulator/Harness.app
```

`--developer-dir` selects an Xcode installation for just this process; it does
not change the global `xcode-select` setting. `--packages` and `--package-cache`
can reuse a dedicated resolved package cache. `--wrap-swift` is a separate
diagnostic variant which disables the integrated Swift driver; it is not used
for these default-driver results. The manual `Xcode build comparison` GitHub
workflow runs the Clang fixture on a real Mac runner and uploads its logs/data.

The measured improvement target is an explicit integration with Xcode's native
compilation cache, whose Swift/C dependency and replay machinery already works
for this app. This native-cache result is not a speedup supplied by nanocompile.
Clang compatibility work should also follow the recorded refusal flags. Supporting Swift requires a Swift-specific dependency and output
model, or an explicit integration with Xcode's native CAS. Treating a complete
app bundle as an opaque cache entry would hide dependency errors.
