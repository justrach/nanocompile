# Xcode comparison

Xcode is a build system, so compiler-family coverage matters. Kache 1.0.0 can
wrap Apple Clang but does not accept Swift compiler invocations. Nanocompile's
current cache core supports Rust/Zig; it passes Xcode Clang through. Swift uses
Xcode's native driver in this comparison. Neither external cache is credited
with Swift caching.

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

## Harness iOS benchmark

The same script supports the real Harness iOS project, including its Swift and
C package dependency graph. It copies the project sources to a dedicated
snapshot, resolves packages before timing, builds a generic iOS Simulator app
with signing disabled, and validates its app executable and compiled objects.
The native Swift integrated driver remains enabled. Three warm samples per
pipeline are the intended measurement; completed results will be added here.

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

The next implementation work should follow the actual refusal flags and native
cache results. Supporting Swift requires a Swift-specific dependency and output
model, or an explicit integration with Xcode's native CAS. Treating a complete
app bundle as an opaque cache entry would hide dependency errors.
