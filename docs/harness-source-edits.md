# Real Harness source edits against kache

The new source-edit workload favors kache in all four timed scenarios. Nano avoids most compilation after leaf/shared changes, but does not establish a cold-build advantage. These results are separate from the earlier identical-build warm wins.

| Clean-target scenario | Direct (s) | Nano (s) | kache (s) |
| --- | ---: | ---: | ---: |
| initial | 25.765 | 28.709 | 27.297 |
| leaf-edit | 23.361 | 10.715 | 10.205 |
| shared-edit | 23.094 | 12.308 | 11.858 |
| revert | 24.379 | 11.981 | 2.058 |

Each point is one sample. The initial build has empty compiler caches; later timed builds keep compiler cache history but delete the Cargo target before every build. This measures clean-target rebuilds with source changes, as in CI, rather than a developer loop retaining Cargo outputs. OS file caches are not flushed, dependencies are fetched before timing, and downloads are excluded.

The disposable snapshot includes the local tracked and nonignored untracked Harness sources, at commit `32b41cb0bff55e3c9cbfab3012acec2b179ad199` with dirty work overlaid. The command builds the real `harness-adapters` release library with four jobs, Rust 1.97.1 and the project’s release settings on an Apple M3 Ultra running macOS 27. Nano is built with stable Zig 0.17.0 from runtime source `6105aed`; exact binary and runner SHA-256 values are in the [raw report](../benchmarks/harness-source-edits-verified.json). kache reports version 1.0.0.

The runner adds exported functions in the real leaf (`crates/harness/src/lib.rs`) and shared dependency (`crates/proto/src/lib.rs`). It changes their returned values, then reverts both. A separately linked thin-LTO probe checks results 300, 301, 312 and 300. The original human checkout is never edited; its tracked source/manifests and lockfile hashes remain unchanged.

For every Nano/kache edited build, an additional empty-cache build at identical paths verifies all rlibs, macro dylibs, build-script executables and native object hashes. All six comparisons pass. These references are correctness checks, excluded from the timed-history summary. The initial and six reference builds all complete successfully. Nano’s `failed` events include compiler capability probes; the Cargo build exit codes are zero.

Nano explicitly enables reported macro dependencies, macro/executable producers and its Apple Clang native adapter. Direct and kache use their usual native selection. Inline scanner debug representation and kache path remapping require comparison against each mode’s own fresh artifacts; cross-mode byte identity is not claimed. These are local compiler-cache measurements, without R2 transfers.

The revert is the clearest remaining gap: Nano records 165 Rust hits, two Rust misses and 24 native hits, while kache records 187 local hits. Ordinary Nano keys partition by command, environment, host and compiler identity; the current store writes one dependency manifest to `entries/<key>`. Changing source contents replaces that manifest, so this path does not retain several source-content variants for the same compilation command. The two recompiled crates dominate the revert time. A bounded variant index with complete dependency validation is a concrete next experiment; this report preserves the current loss.

Reproduction uses [the source-edit runner](../tests/harness_source_edits.py):

```sh
RUSTUP_TOOLCHAIN=1.97.1 python3 tests/harness_source_edits.py \
  zig-out/bin/nanocompile /path/to/harness --kache /path/to/kache \
  --state /tmp/nano-harness-edits --runs 1 --jobs 4 --native-clang \
  --proc-macros reported --proc-macro-producers --executable-producers \
  --output benchmarks/harness-source-edits.json
```

Use a fresh state directory. The runner creates its own snapshot and records exact source hashes. Do not confuse this dirty local workload with the pinned public Harness revision used by hosted comparisons.

A separate [hosted pinned-revision comparison](hosted-three-directions.md) gives Nano small single cold leads on Linux/macOS but substantial warm losses with default producer policy and all portable native jobs bypassing. Those differing workload/policy observations do not overturn the local source-edit losses or establish a repeatable cold advantage.

The subsequent [bounded source-variant implementation](source-variants.md) eliminates the revert recompilations and reduces the new session’s revert to 2.078 s Nano versus 2.238 s kache; cold and new edit losses remain. The original report above is preserved.
