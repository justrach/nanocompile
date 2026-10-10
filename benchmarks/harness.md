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

## GitHub Linux runner

The [Linux benchmark job](https://github.com/justrach/nanocompile/actions/runs/37902722700/job/113728798023)
completed successfully on Ubuntu 24.04 x86_64, using four jobs, Rust 1.97.1 and
a clean checkout at `20c4019201e4b1eee5e04cfbb8dc7bda941b11b9`.
Raw measurements and artifact hashes: [harness-linux.json](harness-linux.json).

| Mode | Seconds | Recorded hits |
| --- | ---: | ---: |
| Direct, median of two builds | 53.17 | — |
| Empty wrapper cache | 54.54 | 0 |
| Warm wrapper cache, median of two builds | 53.39 | 2–3 |
| After R2 restore, build only | 52.54 | 2 |
| R2 download + unpack + rebuild | 53.03 | 2 |

All 131 resulting Rust libraries matched by SHA-256 across every build mode.
The cold snapshot contained only seven files (9,831 unpacked bytes; 4,559
compressed bytes): most successful invocations were bypassed or could not be
stored safely. There were 162 bypass calls per warm build. Upload took 1.97
seconds and download/unpack took 0.49 seconds. Small differences between these
whole-build timings are not convincing evidence of a speedup; this sample has
only two direct and two warm builds. The Linux and local macOS workloads use
different revisions and machines and must not be treated as a controlled
cross-platform comparison.

## Selected-resource revision: fresh R2 validation

[Hosted Harness R2 validation](https://github.com/justrach/nanocompile/actions/runs/38010357689) passes on Ubuntu 24.04 and macOS 15 for Nano source `3fdc90645289254397e51eccf37a21ba9bb1233e`. The workload is clean public Harness revision `20c4019201e4b1eee5e04cfbb8dc7bda941b11b9`, using Rust 1.97.1, four jobs and the default producer policy. This differs from the local opt-in full-workload comparison.

| Runner | Direct median (2) | Warm median (2) | R2-restored build | Restored hits | Pull + unpack |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ubuntu 24.04 | 51.992 s | 36.687 s | 36.545 s | 98 | 3.583 s |
| macOS 15 | 59.019 s | 45.061 s | 40.792 s | 101 | 4.030 s |

All 131 Linux and 135 Mac library hashes match each runner’s cold build across direct, warm and R2-restored builds. Uploaded/downloaded snapshot digests match. These small hosted samples demonstrate preservation and matching-build reuse; they do not establish cross-machine cache hits or a controlled comparison with kache. [Linux raw evidence](harness-selected-decoder-r2-linux.json) and [Mac raw evidence](harness-selected-decoder-r2-macos.json) retain every sample and transfer measurement.
