# Measured delivery audit

The implemented hill climb is published with measured wins, rejected experiments and correctness gates. Source `3fdc90645289254397e51eccf37a21ba9bb1233e` is the tested implementation; subsequent commits publish evidence only.

| Requested outcome | Inspected evidence | Result |
| --- | --- | --- |
| Zig implementation for Rust and Zig, stable 0.17.0 | Current `zig version` is 0.17.0; [CI](../benchmarks/selected-decoder-ci-validation.json) invokes unit tests and real Rust/Zig integration on Linux/macOS | Passed within documented compiler eligibility |
| Adapt kache ideas and publish a public repository | Public `justrach/nanocompile`; [README](../README.md) documents shared CAS blobs, copy-on-write restoration and single-flight compilation | Published |
| Improve and measure on actual Harness against kache | [Nine-round comparison](selected-decoder-nine-samples.md), unchanged tracked sources and all own-cold artifact checks | Warm medians 2.049 s Nano / 2.082 s kache; small local lead; kache still leads cold |
| Hill climb without sacrificing correctness | [Selected-resource experiment](selected-decoder-experiment.md): independent cold paired batches, preserved 193 artifacts, warm paired control; current source hashes match all eight [adoption checks](../benchmarks/selected-decoder-adoption-checks.json) | Adopted cold improvements of 5.22% and 9.71% over predecessor; warm controlled medians essentially equal |
| Test cache persistence in actual R2 on hosted machines | [Harness R2](../benchmarks/harness.md), run 38010357689; [Turbo R2](../benchmarks/turborepo.md), run 38010359904 | Linux/macOS passed; restored hashes and task execution counts verified |
| Benchmark Xcode and compare kache | [Real Harness five-pipeline comparison](../benchmarks/xcode-managed-harness.json), [hosted Mac comparison](../benchmarks/xcode-managed-github-macos.json), [method and limits](../benchmarks/xcode.md) | All builds exit successfully and warm objects match own cold; managed command uses Apple native CAS |
| Turborepo cache with runnable example | [Two-package example](../examples/turborepo/README.md), signed JSON/HTML tasks, source/dependency/env invalidation and corruption repair; fresh actual R2 reports | Passed on Linux/macOS |
| Improve presentation with original imagegen art | [Banner](images/readme-cache-banner.png), [generation provenance](artwork.md), public README | Delivered |

The measurements support the implemented improvements, not a universal advantage over kache. Rust producers require explicit experimental policy, unsupported invocations pass through, mutable inputs remain content-hashed, and selection guards remain live. R2 transports explicit snapshots; path/environment/host keys limit cross-machine reuse. Clang CAS is local, and Xcode uses Apple's cache. The Turbo server is a loopback development adapter. These limits remain part of the shipped product and are described alongside the results.
