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

The initial session stopped on the second kache cold build: own-cold native, Rust library and final executable byte checks failed. The [complete failed session](../benchmarks/harness-full-app-validation-failure.json) is retained; no repeated full-application performance result is established. Compiler caches are emptied before each cold pair, targets before every build, and the private kache daemon is restarted outside timing. OS filesystem caches remain unflushed; dependency fetching and R2 are excluded. Rust 1.97.1, kache 1.0.0 and the accepted Nano default binary `977ffde7…` are frozen. The explicit reported macro/producer options and existing ring execution contract are used consistently with earlier local comparisons. Reported macro mode assumes otherwise unreported reads are declared, as described in the README; the benchmark does not make arbitrary macros hermetic.

[project_comparison.py](../tests/project_comparison.py) now accepts `--bin` to select a final binary instead of a library, hashes that executable and rejects repeated own-cold mismatches. Optional `--probe-help` explicitly checks its command-line help. All build stdout/stderr logs remain in the private session directory `/tmp/nano-full-harness-comparison-20261011`; timing stops before artifact hashing and execution probes. Full repeated results and any failures must be retained before making broader performance claims.

## Reproducibility repair and new session

Only two native artifacts differ between the initial and second kache cold builds: mimalloc's `static.o` and `libmimalloc.a`. The corresponding `liblibmimalloc_sys` and final executable also differ. Other collected native files, Rust libraries, macro dylibs and compiled scripts match. The mimalloc v2 source embeds `__DATE__` and `__TIME__` in its build-information message. The installed Clang expands both deterministically when `SOURCE_DATE_EPOCH` is set; this is an explicit environment control, not a compiler flag or source-code patch.

[Two isolated empty-target mimalloc builds](../benchmarks/mimalloc-source-date-epoch.json), separated in wall time, produce byte-identical native objects, archives and Rust libraries with epoch `1791423832`. This value is the Harness snapshot commit's Unix timestamp. The [reproduction check](../benchmarks/experiments/mimalloc_epoch_check.py) uses the actual v2 native dependency. It establishes this control for the identified component, not full-app reproducibility by itself.

A new three-cold-pair/three-warm-round session uses the same full application and accepted wrappers with `--source-date-epoch 1791423832` applied identically to direct, Nano and kache builds. The runner reports the actual environment value. This freezes embedded build-time metadata; timings from this controlled session must remain separate from the unpinned failed session. Full byte validation remains mandatory. Logs and ongoing results are private under `/tmp/nano-full-harness-epoch-comparison-20261011` and `/tmp/nano-full-harness-epoch-comparison-20261011.json` until results are verified.

## Preserve artifact bytes for future diagnosis

Future comparison sessions can add `--retain-artifacts`. After the first completed build of each implementation, the runner makes independent private copies of the collected libraries, macro dylibs, compiled scripts/launchers, native objects/archives and final executable. It verifies every copied hash before publishing `reference-artifacts/<implementation>/manifest.json`. Copying and verification occur after build timing. This is optional because full-application reference copies can consume substantial disk space.

The [snapshot helper](../tests/reference_artifacts.py) and [checks](../tests/reference_artifacts_check.py) verify that reference bytes survive source mutation/deletion, reject corruption and reject escaping paths. It uses copies rather than hard links, so later writes to target files cannot alter saved evidence. These are integrity checks on local evidence, not authentication against a writer who can rewrite the manifest too. Reference bytes stay private; public benchmark reports contain hashes and relative manifest locations.

The currently running fixed-epoch session was started before this option was added and does not retain these reference copies. Its measured runner is preserved at commit `b4603a5cbcd2edbbbebe8e6032a09760ea093106`; the recorded script checksum identifies that version. The session continues unchanged.
