# Hosted validation and portable coverage

[Linux/macOS CI](https://github.com/justrach/nanocompile/actions/runs/38037270121) passes on source `278d9b4`, built with stable Zig 0.17.0. GCC 13 and Clang 18 on Ubuntu, and Apple Clang 17 on macOS pass real object/depfile equality, header and include invalidation, linked behavior, corruption repair and GC checks. The first run caught a C++ benchmark probe linkage error under GCC; `278d9b4` fixes the fixture by using an explicit C-linkage declaration in a C++ probe. Runtime source is unchanged from `6105aed`.

| Hosted fixture, warm median | Direct / Turbo | Nano |
| --- | ---: | ---: |
| Ubuntu C++ recompilation / restoration | 3.612 s | 0.0453 s |
| macOS C++ recompilation / restoration | 0.4106 s | 0.0657 s |
| Ubuntu two-package Turbo / declared-task restore | 45.07 ms | 2.40 ms |
| macOS two-package Turbo / declared-task restore | 111.38 ms | 7.26 ms |

C++ is a synthetic 512-template translation unit with five warm samples and exact object/linked checks. Task results use nine alternating warm pairs, identical Node scripts and outputs, local-only Turbo/no daemon, and zero Node execution on both caches. These measure the named fixtures; they do not establish a general cold-build or monorepo scheduler advantage. [All raw fixture samples](../benchmarks/hosted-three-directions/).

The separate [portable Harness comparison](https://github.com/justrach/nanocompile/actions/runs/38037043172) uses the pinned clean public Harness revision `20c4019201e4b1eee5e04cfbb8dc7bda941b11b9`, four jobs, Rust 1.97.1, reported macro dependencies and default producer policy. It differs from the dirty local source-edit workload and explicit Apple producer policies. Outputs are compared to each mode’s own cold artifacts; every warm result passes Rust, macro, build-script executable and native artifact checks.

On Ubuntu, warm medians are 52.715 s direct, 8.064 s Nano and 1.224 s kache. Nano reports 133 Rust hits and **30 portable native bypasses, zero native hits** each warm round. The limited portable adapter therefore does not improve native coverage for this Harness profile. Kache reports 181 local hits. One cold sample gives 55.223 s Nano versus 55.828 s kache; this small single observation is insufficient for a cold-win claim. [Raw Ubuntu project report](../benchmarks/hosted-three-directions/ubuntu-24.04-harness-kache.json).

On hosted macOS 26, warm medians are 68.276 s direct, 9.398 s Nano and 3.596 s kache. Nano records 136 Rust hits and **24 portable native bypasses, zero native hits** each warm round; kache records 187 local hits. The single cold samples are 90.611 s Nano and 91.413 s kache. The three warm samples fluctuate substantially, and the small cold lead is not repeated evidence. Both hosted jobs finish successfully with all artifact checks and source-unchanged assertions passing. [Raw macOS project report](../benchmarks/hosted-three-directions/macos-26-harness-kache.json).

The practical next coverage task is to inventory those actual bypass commands and add only flag/job forms whose complete inputs can be validated. Passing fixture compiler checks does not imply coverage for all native build-script commands.
