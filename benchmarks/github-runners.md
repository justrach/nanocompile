# GitHub-hosted runtime validation

Both platforms passed the real compiler integration suite. These are small
synthetic workloads measured on actual GitHub-hosted runners, with nine samples
per mode, rotating measurement order, compiler outputs removed, byte equality
checked, and all measured wrapper invocations required to record cache hits.

| Runner | Rust direct median | Rust cache median | Zig direct median | Zig cache median |
| --- | ---: | ---: | ---: | ---: |
| Ubuntu 24.04, x86_64 | 412.49 ms | 3.32 ms | 170.39 ms | 6.04 ms |
| macOS 15, arm64 | 533.04 ms | 7.54 ms | 134.38 ms | 6.31 ms |

Linux raw samples: [github-linux.json](github-linux.json),
[successful job](https://github.com/justrach/nanocompile/actions/runs/37902691257/job/113728693827).
macOS raw samples: [github-macos.json](github-macos.json),
[successful job](https://github.com/justrach/nanocompile/actions/runs/37901538772/job/113725006899).
The macOS measurement preceded the Linux atomic-write correction. Each JSON
records its executable checksum, compiler versions and timestamp. Both used
Zig 0.17.0 and Rust 1.97.1. They do not use identical hardware, so platform
timings are not a controlled hardware comparison.

An initial Linux runtime test caught an incorrect atomic-file option:
`File.Atomic.replace` requires `CreateFileAtomicOptions.replace = true`.
macOS's fallback to named temporary files hid the mistake; Linux used an
unnamed file, and the attempted rename failed. The corrected Linux job passed
the integration suite, including cache persistence, restored artifacts, input
invalidation, corruption repair, concurrency and GC. Cross-compilation alone
had not exposed this bug.

These fixture results do not predict whole-Cargo-project performance. See the
[Harness clean-build results](harness.md) for a more realistic coverage baseline.
