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

The first fixed-epoch session stopped when Nano's completed application had mode `0644`, so the `--help` probe raised `PermissionError`. The older runner raised before saving that Nano row; its exact wall time is unavailable and is not reconstructed. The [failure evidence](../benchmarks/harness-full-app-epoch-probe-failure.json) preserves the direct reference, failed executable hash/mode and unresolved diagnosis. Its runner is preserved at commit `b4603a5cbcd2edbbbebe8e6032a09760ea093106`.

A diagnostic rebuild produced mode `0755` and traced the final application compile as `bypass: UnsupportedProducerConfiguration`. This does not reproduce or explain the earlier failure, and no runtime fix is claimed. The runner now saves probe failures, file modes and console hashes before rejecting the sample. Repeated final executable modes must also match.

A new full-app diagnostic session under `/tmp/nano-full-harness-trace-20261011` retains compiler streams, Cargo timings, reference artifact bytes and cache events. It uses one cold pair and one warm round with the fixed epoch. These traced timings are diagnostic observations, not repeated speed evidence. The session is complete; results and limitations follow below.

## Completed full-application diagnostic capture

[The six-build capture](../benchmarks/harness-full-app-trace.json) completes one cold pair and one clean-target warm round. This is diagnostic tracing with overhead, not repeated performance evidence.

| Implementation | Cold/reference seconds | Warm-cache, clean target seconds |
| --- | ---: | ---: |
| Direct | 174.202 | 173.414 |
| Nano | 177.113 | 88.981 |
| kache | 189.562 | 6.969 |

Every executable passes `--help` with identical help output and mode `0755`. All repeated libraries, macros, scripts, native outputs, final executables and final modes match their implementation's own cold reference. Source hashes remain unchanged. Nano's final bytes also match direct in this session; cross-tool equality with kache is not required. The earlier permission failure does not reproduce and remains unresolved.

All six full-console digests and capture manifests verify. Each build contains 1,237 Cargo timing units. Wrapped compiler records: Nano 1,145 cold and warm, kache 1,226 cold and 1,103 warm. Direct has Cargo logs/timings rather than frontend records. Three independent reference snapshots verify 1,214 direct, 1,215 Nano and 1,214 kache artifact files. Private logs and copied bytes remain under `/tmp/nano-full-harness-trace-20261011`; public data removes raw decisions and record paths, retaining enumerated cache rejection reasons. The exact measured runner snapshot matches the report's script hash.

The full-app warm result is substantially worse for Nano than kache, despite the earlier adapters-only lead. The final Harness request takes 70.388s warm through Nano's `UnsupportedProducerConfiguration` bypass. Its compiler arguments use `-C lto=thin`; current producer guards reject LTO. Kache's matching-name warm service event is a local hit: 109ms elapsed, 44ms key work, 63ms restore, zero compiler runs. Its hit `compile_time_ms=66681` describes the stored cold compilation, not new warm compiler work.

The next priorities are in [the concrete handoff](full-harness-next-variation.md), [generated observations](full-harness-generated-experiments.md) and [structured instructions](../benchmarks/harness-full-app-experiments.json). Observed gaps overlap and do not predict additive savings. Repeat untraced comparisons before claiming improvements; no production runtime change was made in this diagnostic session.
