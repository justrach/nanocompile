# Harness package benchmark

Measured locally on Apple M3 Ultra, macOS 27 arm64, Rust 1.97.1, Zig 0.17.0,
four Cargo jobs. Workload: `cargo build --release --locked --offline --lib -p
harness-adapters`, including its dependency graph. This is not the full GUI
application. Dependencies were fetched before timing, and the dedicated target
directory was deleted before every build. The working checkout was dirty;
its base revision is recorded in [harness-local.json](harness-local.json).

| Mode | Seconds | Recorded hits |
| --- | ---: | ---: |
| Direct, median of two builds | 23.11 | — |
| Empty wrapper cache | 28.96 | 0 |
| Warm wrapper cache, median of two builds | 23.43 | 2–3 |
| After R2 snapshot restore, build only | 23.05 | 2 |
| R2 download + unpack + rebuild | 24.92 | 2 |

All builds succeeded. All 135 resulting rlibs matched the first wrapped build
by SHA-256, including the direct builds. The snapshot contained 22 files,
1,965,245 unpacked bytes and 574,583 compressed bytes. Upload took 2.89 seconds;
download/unpack took 1.87 seconds. These network timings are one observation,
not a stable R2 latency estimate. Toolchain memos were retained for the remote
restore test; compiler outputs, entries and blobs were removed before restore.

The warm wrapper is slightly slower in this sample. Most compilation units
bypass the conservative proc-macro/native-input gates (167 bypass calls per
warm build), and dependency-directory churn invalidates some eligible entries.
The three `failed` events are unsuccessful compiler invocations used by build
probes; Cargo reports overall success. Raw events alone do not count crates.
Small synthetic hit timings do not establish a whole-project speedup.

The R2 experiment proves preservation/restoration and matching-build reuse on
this machine. It does not establish cross-machine hits. Keys still retain all
environment values, paths and host identity. The current remote transport is
an optional Python/boto3 snapshot utility, separate from the Zig compiler core.

GitHub's manual Harness workflow tests a pinned publicly available revision.
That revision may differ from this local checkout; compare results only with
their recorded commit, platform and toolchain. Artifacts contain timing JSON.
