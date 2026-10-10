# Full Harness application comparison

The broader benchmark builds the actual `harness` executable from the same dirty snapshot used for adapters measurements:

```sh
cargo build --release --locked --offline --bin harness -p harness -j 8
```

This includes GPUI, the renderer, Harness engine, UI and final application linking. The [initial completed builds](../benchmarks/harness-full-app-initial.json) contain 945 Rust libraries and final executable hashes. Each final executable passes an explicit `--help` probe outside build timing, with identical help output across direct, Nano and kache builds. The application GUI is not launched by this probe.

| Initial build | Seconds |
| --- | ---: |
| Direct prime/reference | 176.104585 |
| Nano cold | 176.806028 |
| kache cold | 196.383687 |

Nano is approximately 10.0% lower than kache in this single initial pair. This is not a repeated median or proof of a dependable full-application lead. Nano's cold run records 1,098 Rust misses and one ring execution miss, without hits. Failed compiler feature probes are expected and do not fail Cargo. Final executable bytes differ across implementations; cross-tool byte equality is not asserted. Repeated builds must match each implementation's own initial artifact hashes, including the final executable.

The session remains active, with three alternating cold pairs and three rotating warm rounds requested. Compiler caches are emptied before each cold pair, targets before every build, and the private kache daemon is restarted outside timing. OS filesystem caches remain unflushed; dependency fetching and R2 are excluded. Rust 1.97.1, kache 1.0.0 and the accepted Nano default binary `977ffde7…` are frozen. The explicit reported macro/producer options and existing ring execution contract are used consistently with earlier local comparisons. Reported macro mode assumes otherwise unreported reads are declared, as described in the README; the benchmark does not make arbitrary macros hermetic.

[project_comparison.py](../tests/project_comparison.py) now accepts `--bin` to select a final binary instead of a library, hashes that executable and rejects repeated own-cold mismatches. Optional `--probe-help` explicitly checks its command-line help. All build stdout/stderr logs remain in the private session directory `/tmp/nano-full-harness-comparison-20261011`; timing stops before artifact hashing and execution probes. Full repeated results and any failures must be retained before making broader performance claims.
