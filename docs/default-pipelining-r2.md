# Actual R2 refresh for the accepted runtime

[Harness workflow 38066612387](https://github.com/justrach/nanocompile/actions/runs/38066612387) and [Turborepo workflow 38066614621](https://github.com/justrach/nanocompile/actions/runs/38066614621) pass on their Linux and macOS runners. Both build accepted source `83673363fd8b4eb6c4d28b52bb2ac1574d7bf343`, including default Rust stream forwarding and guarded companions. The later scheduling reports do not change production code. This refresh uses actual Cloudflare R2 with repository secrets; credentials are absent from public reports.

Harness uses the workflow's pinned snapshot `20c4019201e4b1eee5e04cfbb8dc7bda941b11b9`, four jobs and the default tracked macro policy. It differs from the local dirty eight-job snapshot and its explicit producer/ring contract. These cloud timings cannot be compared directly with the local kache sessions.

| Runner | Build after R2 snapshot restore | Rust hits | Artifact check |
| --- | ---: | ---: | --- |
| [Ubuntu 24.04](../benchmarks/harness-default-pipelining-r2-ubuntu-24.04.json) | 29.859950s | 98 | All 135 collected rlibs match initial wrapped build |
| [macOS 15](../benchmarks/harness-default-pipelining-r2-macos-15.json) | 32.944695s | 101 | All 135 collected rlibs match initial wrapped build |

Each R2-restored build retains 20 Rust misses and expected bypass/feature-probe activity, and Cargo exits successfully. Uploaded and downloaded archive hashes match. Transport timing is recorded separately. This is snapshot upload/download followed by local cache restoration, not automatic remote lookup on every compiler invocation or a claim of complete build-cache coverage.

The two-package real Turborepo example also restores both tasks through Nano's remote endpoint after recovering the backend cache from R2. No tasks execute, both report remote hits and artifact hashes match cold output on [Ubuntu 24.04](../benchmarks/turbo-default-pipelining-r2-ubuntu-24.04.json) and [macOS 26](../benchmarks/turbo-default-pipelining-r2-macos-26.json). Dependency edits, site edits, environment changes and corruption checks are retained in the reports. Each timing is a single demonstration sample on a small example, not a repeated performance comparison against Turborepo.
