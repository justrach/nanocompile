# Rust-loop benchmark

Stable entrypoint: [`bench/rust_loop_bench`](../bench/rust_loop_bench). Other
agents should call this file. JSON schema is `1`; results land in
`bench/results/<sample>/result.json` and `result.md`.

The harness copies the project, isolates `CARGO_TARGET_DIR`, and does not edit
the caller's tree. It times wall-clock cargo/nanocompile invocations itself
(hyperfine is optional and not required).

## Run

```sh
zig build -Doptimize=ReleaseFast

# Smoke the fixture (1 run, check only, plus the broken-edit gate)
python3 bench/rust_loop_bench --self-test --nanocompile zig-out/bin/nanocompile

# Isolate cranelift from nightly-vs-stable (same nightly, test --no-run)
python3 bench/nightly_pair.py examples/rust-loop --name rust-loop --offline

# Any Cargo project
python3 bench/rust_loop_bench path/to/crate \
  --nanocompile zig-out/bin/nanocompile \
  --runs 5 --warmup 1 \
  --name my-sample --offline
```

Flags (keep these names):

| Flag | Meaning |
| --- | --- |
| `PROJECT` | Cargo project root |
| `--nanocompile PATH` | wrapper / `task` binary (default `zig-out/bin/nanocompile`) |
| `--runs N` | timed samples per cell (default 3) |
| `--warmup N` | discarded runs (default 1) |
| `--jobs N` | `cargo -j` |
| `--output DIR` | write `result.json` / `result.md` |
| `--name SAMPLE` | results directory name |
| `--steps LIST` | subset of step ids below |
| `--commands LIST` | `check`, `build`, `test` |
| `--offline` | `cargo --offline` after a successful `cargo fetch` |
| `--skip-install` | do not try to install nightly cranelift / mold |
| `--self-test` | correctness + 1-run check on `examples/rust-loop` |
| `--genome FILE` | evaluate one MAP-Elites genome on every edit type |
| `--map-elites` | seed + mutate elites for this sample's size bucket |
| `--emit-archive FILE` | write `bench/archive/<sample>.json` shard |
| `--mutations N` | stop a cell after N non-improving tries (default 4) |
| `--package NAME` | `cargo -p NAME` for check/build/test and the graph spec |
| `--validate-package NAME` | `cargo test -p NAME` for the broken-edit gate (default: `--package`) |
| `--timeout SEC` | per-invocation timeout (default 3600; was a hard 600) |

Prefer `nanocompile rust-loop` when that subcommand exists; otherwise the
harness uses `tools/rust_loop.py`. Either driver must keep `validate` as the
commit signal.

## What is measured

Phases, in order, per step × command:

| Phase | Setup |
| --- | --- |
| `cold` | empty target dir |
| `noop` | unchanged sources, retained target |
| `edit_body` | insert a no-op into a function body (`// nano-loop-body` or the first `fn`) |
| `edit_sig` | add `_nano_loop_sig: ()` (`// nano-loop-sig` or the first `fn`) |
| `worktree` | sibling checkout + new `CARGO_TARGET_DIR`; compiler cache shared when `warm_store` |

Each cell records sample wall times, median, population stdev, min/max, and
`target/` byte size. Incremental edits are applied, timed, and reverted **per
run**, then an untimed rebuild restores the original tree so extra `--runs` are
independent first rebuilds, not no-ops of an already-edited workspace.

### Step ids

| id | Command under test |
| --- | --- |
| `baseline` | plain `cargo check` / `build` / `test` |
| `nanocompile-wrapper` | `RUSTC_WRAPPER=nanocompile CARGO_INCREMENTAL=0` |
| `fast-check` | `cargo check` only |
| `validate-graph` | declared `fast-check` → `cargo test` via `nanocompile task` |
| `nightly-llvm` | `cargo +nightly` LLVM `build` / `test` (control for cranelift) |
| `cranelift-dev` | `cargo +nightly -Zcodegen-backend` plus `RUSTFLAGS=-Zcodegen-backend=cranelift` (no `CARGO_PROFILE_*` / no `cargo-features` in the user's manifest) |
| `fast-linker` | `-C link-arg=-fuse-ld=mold` or `lld` on build/test |
| `sccache` | `RUSTC_WRAPPER=sccache` |
| `kache` | `RUSTC_WRAPPER=kache` with isolated `KACHE_CACHE_DIR` (local-only, no scheduler) |
| cache bakeoff | `bench/compare_caches.py` races nanocompile vs kache across every overlapping cache function (not only the wrapper gene). See [nanocompile vs kache](nanocompile-vs-kache.md). |
| `crate-shape` | `-C codegen-units=256` |
| `disk-hygiene` | `-C debuginfo=line-tables-only` |

Missing tools skip the cell with a reason. They are not silent zeros.

## Correctness

Before timing, the harness applies a type-error body edit. `cargo check` and
`cargo test` must both fail (`agree_on_broken`). The declared graph must not
write `.nanocompile-loop/validate.ok` (`validate_is_final`). A successful fast
path is never the recorded gate.

## Results layout

```
bench/results/<sample>/result.json
bench/results/<sample>/result.md
```

Other agents may add more sample directories. Do not change `schema` without
bumping it and updating this page.

## MAP-Elites archive

Source of truth: [`bench/map_elites.json`](../bench/map_elites.json)
(schema 1). JSON Schema: [`bench/map_elites.schema.json`](../bench/map_elites.schema.json).
Other agents write [`bench/archive/<sample>.json`](../bench/archive/README.md)
and merge:

```sh
python3 tools/map_elites.py validate bench/archive/my-sample.json
python3 tools/map_elites.py merge --into bench/map_elites.json bench/archive/*.json
python3 tools/map_elites.py render --into docs/rust-iteration-bench.md
./zig-out/bin/nanocompile map-elites validate bench/map_elites.json
```

The grid is **size** (`small` / `mid` / `large`) × **edit** (`cold` / `noop` /
`body` / `sig_dep` / `worktree`). Disk use is recorded per elite, not a third
axis. Crate shape (`proc_macro` / `async_web` / `generic` / `normal`) is
classify metadata only — a third occupancy axis would vacate the stalled
size × edit grid.

A genome is the full loop config (`wrapper`, `dev_backend`, `linker`, `sccache`,
`kache`, `warm_store`, `codegen_units`, `incremental`, `debuginfo`, `fast_check`,
`loop`, `jobs`, `offline`, plus optional `opt_level_deps`, `share_generics`,
`frontend_threads`, `hint_mostly_unused`, `target_tmpfs`). `loop` is `check`,
`graph`, `test`, `build`, `clippy`, or `nextest`. `build` is the cranelift-dev
gene because `cargo check` skips codegen. `clippy` / `nextest` are timed loops
only. `validate` is **not** a gene: it is always `cargo test` with LLVM rustc.
Compiler caches (`wrapper` / `sccache` / `kache`) are mutually exclusive.
Merge replaces a cell only when the new median is ≥3% faster and
`correctness.ok` is true.

Size is by Rust LOC, not crate-count tricks: `small` is LOC < 2000,
`mid` is 2000 ≤ LOC < 50000 and ≤20 crates, else `large`. The three-crate
`examples/rust-loop-medium` fixture is small. `examples/pinned-hashbrown`
(hashbrown 0.15.2, ~23k LOC) is the mid sample this agent controls.
PR #11's ripgrep 15.2.0 + tokio 1.54.0 trees classify as **large**.
PR #13's ruff 0.17.1 tree is also large (~838k LOC); measure it with
`--package ruff`. Incremental edits are applied/reverted per `--runs`
sample so extra runs stay first rebuilds.

Each elite records `fitness_method` and, for cold cells, `cache_state`.
`official_first_rebuild` is this harness. `restore_rebuild_mean_of_medians`
is the PR #11 protocol (restore+rebuild before every timed edit, then mean
of the two project medians). Do not compare raw ms across methods.
`warm_compiler_cache` means sccache/nanocompile/kache stayed populated after
`target/` was emptied, or a sibling worktree reused that store — not a true
empty-cache cold. Head-to-head wrapper compares live in
[`bench/compare_wrappers.py`](../bench/compare_wrappers.py).

`package_scope=touched` (`cargo check -p` the hub crate) cannot occupy
`sig_dep` unless `correctness.dependents_agree_on_broken` is true. Promote
weights **real** samples over rust-loop fixtures.

<!-- MAP_ELITES_GRID_BEGIN -->

## MAP-Elites grid

Canonical archive: [`bench/map_elites.json`](../bench/map_elites.json).
Schema: [`bench/map_elites.schema.json`](../bench/map_elites.schema.json).
Merge shards from `bench/archive/<sample>.json` with `nanocompile map-elites merge` or `python3 tools/map_elites.py merge`.

Axes: size (`small` / `mid` / `large`) × edit (`cold` / `noop` / `body` / `sig_dep` / `worktree`).
Fitness is median loop wall time in ms (lower is better). Disk is recorded, not an axis.
Worktree is a sibling checkout + new target dir + shared compiler cache.

| Size \ Edit | cold | noop | body | sig_dep | worktree |
| --- | ---: | ---: | ---: | ---: | ---: |
| small | 37.1 ms (rust-loop-kache-round, check) | 1.3 ms (rust-loop, graph) | 21.7 ms (rust-loop-wrappers, check) | 22.1 ms (rust-loop-wrappers, check) | 36.9 ms (rust-loop-wrappers, check) |
| mid | 323.8 ms (pinned-hashbrown-kache-round, check) | 3.2 ms (pinned-hashbrown, graph) | 114.0 ms (pinned-hashbrown-kache-round, check) | 113.2 ms (pinned-hashbrown, check) | 336.3 ms (pinned-hashbrown-kache-round, check) |
| large | 2911.7 ms (ripgrep-wrappers, check) | 30.7 ms (ripgrep, check) | 155.7 ms (ripgrep, check) | 761.2 ms (nalgebra-wrappers, check) | 2754.0 ms (ripgrep-wrappers, check) |

### Elites

| Cell | Sample | Fitness ms | Method | Cache | Loop | Wrapper | Backend |
| --- | --- | ---: | --- | --- | --- | --- | --- |
| small|cold | rust-loop-kache-round | 37.1 | first-rebuild | empty | check | no | llvm |
| small|noop | rust-loop | 1.3 | first-rebuild | — | graph | yes | llvm |
| small|body | rust-loop-wrappers | 21.7 | first-rebuild | — | check | no | llvm |
| small|sig_dep | rust-loop-wrappers | 22.1 | first-rebuild | — | check | no | llvm |
| small|worktree | rust-loop-wrappers | 36.9 | first-rebuild | empty | check | no | llvm |
| mid|cold | pinned-hashbrown-kache-round | 323.8 | first-rebuild | empty | check | no | llvm |
| mid|noop | pinned-hashbrown | 3.2 | first-rebuild | — | graph | yes | llvm |
| mid|body | pinned-hashbrown-kache-round | 114.0 | first-rebuild | — | check | no | llvm |
| mid|sig_dep | pinned-hashbrown | 113.2 | first-rebuild | — | check | no | llvm |
| mid|worktree | pinned-hashbrown-kache-round | 336.3 | first-rebuild | empty | check | no | llvm |
| large|cold | ripgrep-wrappers | 2911.7 | first-rebuild | empty | check | no | llvm |
| large|noop | ripgrep | 30.7 | first-rebuild | — | check | no | llvm |
| large|body | ripgrep | 155.7 | first-rebuild | — | check | no | llvm |
| large|sig_dep | nalgebra-wrappers | 761.2 | first-rebuild | — | check | no | llvm |
| large|worktree | ripgrep-wrappers | 2754.0 | first-rebuild | empty | check | no | llvm |

### Generalization

| Trained | Cell | Tested | Fitness ms | vs local elite | Correct |
| --- | --- | --- | ---: | ---: | --- |
| rust-loop | small|cold | rust-loop | 45.1 | -0.2% | yes |
| rust-loop | small|noop | rust-loop | 1.4 | 9.2% | yes |
| rust-loop | small|body | rust-loop | 24.7 | 1.2% | yes |
| rust-loop | small|sig_dep | rust-loop | 24.1 | -2.6% | yes |
| rust-loop-medium | mid|cold | rust-loop | 43.5 | -3.7% | yes |
| rust-loop-medium | mid|noop | rust-loop | 1.3 | -1.4% | yes |
| rust-loop-medium | mid|body | rust-loop | 25.9 | 5.8% | yes |
| rust-loop | small|cold | rust-loop-medium | 108.5 | 24.3% | yes |
| rust-loop | small|noop | rust-loop-medium | 1.4 | 0.5% | yes |
| rust-loop | small|body | rust-loop-medium | 67.4 | 7.1% | yes |
| rust-loop | small|sig_dep | rust-loop-medium | 34.3 | — | yes |
| rust-loop-medium | mid|cold | rust-loop-medium | 85.2 | -2.4% | yes |
| rust-loop-medium | mid|noop | rust-loop-medium | 1.4 | 2.8% | yes |
| rust-loop-medium | mid|body | rust-loop-medium | 63.3 | 0.7% | yes |
| rust-loop | small|cold | midsize | 3908.9 | 181.8% | yes |
| rust-loop | small|noop | midsize | 0.0 | — | no |
| rust-loop | small|body | midsize | 245.9 | 101.7% | yes |
| rust-loop | small|sig_dep | midsize | 1560.9 | 194.6% | yes |
| rust-loop-medium | mid|cold | midsize | 4211.8 | 203.6% | yes |
| rust-loop-medium | mid|noop | midsize | 0.0 | — | no |
| rust-loop-medium | mid|body | midsize | 134.2 | 10.0% | yes |
| rust-loop-medium | mid|sig_dep | midsize | 1659.1 | 213.2% | yes |
| rust-loop | small|cold | pinned-hashbrown-held-out | 418.1 | -5.3% | yes |
| rust-loop | small|noop | pinned-hashbrown-held-out | 3.2 | 0.9% | yes |
| rust-loop | small|body | pinned-hashbrown-held-out | 259.7 | 111.7% | yes |
| rust-loop | small|sig_dep | pinned-hashbrown-held-out | 260.5 | 130.1% | yes |
| midsize | large|cold | pinned-hashbrown-held-out | 536.9 | 21.6% | yes |
| midsize | large|noop | pinned-hashbrown-held-out | 16.3 | 409.5% | yes |
| midsize | large|body | pinned-hashbrown-held-out | 129.7 | 5.7% | yes |
| midsize | large|sig_dep | pinned-hashbrown-held-out | 129.1 | 14.0% | yes |
| pinned-hashbrown | mid|cold | pinned-hashbrown-held-out | 411.5 | -6.8% | yes |
| pinned-hashbrown | mid|noop | pinned-hashbrown-held-out | 3.1 | -1.7% | yes |
| pinned-hashbrown | mid|body | pinned-hashbrown-held-out | 122.8 | 0.1% | yes |
| pinned-hashbrown | mid|sig_dep | pinned-hashbrown-held-out | 128.3 | 13.4% | yes |
| pinned-hashbrown | mid|cold | rust-loop-from-hashbrown | 81.1 | 86.4% | yes |
| pinned-hashbrown | mid|noop | rust-loop-from-hashbrown | 1.5 | 10.2% | yes |
| pinned-hashbrown | mid|body | rust-loop-from-hashbrown | 27.9 | 14.2% | yes |
| pinned-hashbrown | mid|sig_dep | rust-loop-from-hashbrown | 197.3 | 696.8% | yes |
| rust-loop | small|body | bhumi | 426.5 | 135.6% | yes |
| rust-loop | small|body | emergentDB | 905.3 | 270.9% | yes |
| rust-loop | small|body | codegraff2 | 4752.9 | 349.2% | yes |
| rust-loop | small|sig_dep | bhumi | 439.1 | 123.7% | yes |
| rust-loop | small|sig_dep | emergentDB | 877.9 | 308.5% | yes |
| rust-loop | small|sig_dep | codegraff2 | 4880.2 | 379.1% | yes |
| rust-loop-medium | mid|body | bhumi | 218.1 | 20.5% | yes |
| rust-loop-medium | mid|body | emergentDB | 355.2 | 45.6% | yes |
| rust-loop-medium | mid|body | codegraff2 | 1664.1 | 57.3% | yes |
| rust-loop-steps | small|body | bhumi | 210.6 | 16.3% | yes |
| rust-loop-steps | small|body | emergentDB | 330.6 | 35.5% | yes |
| rust-loop-steps | small|body | codegraff2 | 1603.2 | 51.5% | yes |
| rust-loop-steps | small|sig_dep | bhumi | 199.6 | 1.6% | yes |
| rust-loop-steps | small|sig_dep | emergentDB | 316.6 | 47.3% | yes |
| rust-loop-steps | small|sig_dep | codegraff2 | 1828.1 | 79.5% | yes |
| rust-loop | small|noop | bhumi | 72.0 | 2.1% | yes |
| rust-loop | small|noop | emergentDB | 88.3 | 1.6% | yes |
| rust-loop | small|noop | codegraff2 | 206.8 | 7.9% | yes |
| midsize | large|cold | bhumi | 14088.0 | 79.3% | yes |
| midsize | large|cold | emergentDB | 3990.0 | -30.8% | yes |
| midsize | large|noop | bhumi | 180.4 | 155.8% | yes |
| midsize | large|noop | emergentDB | 107.3 | 23.5% | yes |
| midsize | large|body | bhumi | 253.3 | 39.9% | yes |
| midsize | large|body | emergentDB | 318.0 | 30.3% | yes |
| midsize | large|sig_dep | bhumi | 278.4 | 41.8% | yes |
| midsize | large|sig_dep | emergentDB | 406.8 | 89.3% | yes |
| rust-loop-cranelift | small|body | bhumi | 0.0 | — | no |
| rust-loop-cranelift | small|body | emergentDB | 0.0 | — | no |
| midsize | large|cold | codegraff2 | 12485.2 | -0.7% | yes |
| midsize | large|noop | codegraff2 | 192.8 | 0.6% | yes |
| midsize | large|body | codegraff2 | 1646.3 | 55.6% | yes |
| midsize | large|sig_dep | codegraff2 | 1633.2 | 60.3% | yes |
| emergentDB | mid|body | hashbrown-from-rach-repos | 5585.7 | 1414.6% | yes |
| emergentDB | mid|sig_dep | hashbrown-from-rach-repos | 255.0 | 175.2% | yes |
| emergentDB | mid|noop | hashbrown-from-rach-repos | 15.2 | -84.1% | yes |
| bhumi | small|body | hashbrown-from-rach-repos | 276.5 | -25.0% | yes |
| bhumi | small|sig_dep | hashbrown-from-rach-repos | 254.1 | 174.2% | yes |
| bhumi | small|noop | hashbrown-from-rach-repos | 15.5 | -83.7% | yes |
| bhumi | small|cold | hashbrown-from-rach-repos | 403.1 | 10.1% | yes |
| codegraff2 | large|body | hashbrown-from-rach-repos | 274.0 | -25.7% | yes |
| codegraff2 | large|sig_dep | hashbrown-from-rach-repos | 319.0 | 244.3% | yes |
| codegraff2 | large|noop | hashbrown-from-rach-repos | 15.0 | -84.3% | yes |
| codegraff2 | large|cold | hashbrown-from-rach-repos | 404.8 | 10.5% | yes |
| emergentDB | mid|cold | hashbrown-from-rach-repos | 7842.5 | 2041.0% | yes |
| pinned-hashbrown | mid|cold | bhumi-from-hashbrown | 12264.5 | — | yes |
| pinned-hashbrown | mid|noop | bhumi-from-hashbrown | 15.4 | — | yes |
| pinned-hashbrown | mid|body | bhumi-from-hashbrown | 290.1 | — | yes |
| pinned-hashbrown | mid|sig_dep | bhumi-from-hashbrown | 245.8 | — | yes |
| pinned-hashbrown | mid|cold | ripgrep-from-hashbrown | 2919.9 | — | yes |
| pinned-hashbrown | mid|noop | ripgrep-from-hashbrown | 2286.0 | — | yes |
| pinned-hashbrown | mid|body | ripgrep-from-hashbrown | 153.9 | — | yes |
| pinned-hashbrown | mid|sig_dep | ripgrep-from-hashbrown | 134.8 | — | yes |
| midsize | large|cold | large-workspace | 471.5 | 3.8% | yes |
| midsize | large|noop | large-workspace | 169.9 | 12.6% | yes |
| midsize | large|sig_dep | large-workspace | 7052.3 | 5.8% | yes |
| pinned-hashbrown-held-out | mid|cold | large-workspace | 53275.1 | 14.4% | yes |
| rust-loop | small|cold | large-workspace | 53275.1 | 14.4% | yes |
| rust-loop | small|sig_dep | large-workspace | 14769.2 | 121.7% | yes |
| rust-loop-medium | small|cold | large-workspace | 53275.1 | 14.4% | yes |
| rust-loop-medium | small|sig_dep | large-workspace | 14769.2 | 121.7% | yes |
| pinned-hashbrown-held-out | mid|body | large-workspace | 467.2 | 2.8% | yes |
| pinned-hashbrown-held-out | mid|sig_dep | large-workspace | 6985.9 | 4.8% | yes |
| pinned-hashbrown | mid|body | large-workspace | 467.2 | 2.8% | yes |
| pinned-hashbrown | mid|sig_dep | large-workspace | 6985.9 | 4.8% | yes |
| rust-loop-medium | small|body | large-workspace | 467.2 | 2.8% | yes |
| rust-loop-cranelift | small|body | large-workspace | 1336.3 | 194.1% | yes |
| rust-loop-cranelift | small|noop | large-workspace | 167.7 | 11.2% | yes |
| rust-loop-steps | small|sig_dep | large-workspace | 6985.9 | 4.8% | yes |
| rust-loop-steps | small|cold | large-workspace | 54911.6 | 17.9% | yes |
| rust-loop-steps | small|body | large-workspace | 485.1 | 6.8% | yes |
| ripgrep | large|cold | hashbrown-from-large | 524.2 | 18.7% | yes |
| ripgrep | large|noop | hashbrown-from-large | 16.2 | 408.8% | yes |
| ripgrep | large|body | hashbrown-from-large | 119.1 | -2.9% | yes |
| ruff-check-line-tables | large|sig_dep | hashbrown-from-large | 124.5 | 10.0% | yes |
| ripgrep | large|cold | ripgrep-from-large | 3205.8 | 2.9% | yes |
| ripgrep | large|noop | ripgrep-from-large | 35.2 | 14.7% | yes |
| ripgrep | large|body | ripgrep-from-large | 166.1 | 6.6% | yes |
| ruff-check-line-tables | large|sig_dep | ripgrep-from-large | 160.3 | -97.5% | yes |
| ripgrep | large|cold | bhumi-from-large | 12145.6 | 27809.7% | yes |
| ripgrep | large|noop | bhumi-from-large | 63.5 | 4701.6% | yes |
| ripgrep | large|body | bhumi-from-large | 274.9 | 1024.5% | yes |
| ruff-check-line-tables | large|sig_dep | bhumi-from-large | 241.2 | 874.1% | yes |
| pinned-hashbrown | mid|cold | ruff-from-mid | 52073.8 | 1571.8% | yes |
| pinned-hashbrown | mid|noop | ruff-from-mid | 1288.4 | 4094.1% | yes |
| pinned-hashbrown | mid|body | ruff-from-mid | 469.8 | 201.7% | yes |
| pinned-hashbrown | mid|sig_dep | ruff-from-mid | 6708.0 | 4.1% | yes |
| ripgrep | large|cold | ruff-from-large | 52836.8 | 1596.3% | yes |
| ripgrep | large|noop | ruff-from-large | 196.4 | 539.2% | yes |
| ripgrep | large|body | ruff-from-large | 547.3 | 251.4% | yes |
| ruff-check-line-tables | large|sig_dep | ruff-from-large | 6519.1 | 1.2% | yes |
| rust-loop-kache-round | small|cold | rust-loop-from-elites | 39.1 | 5.6% | yes |
| rust-loop | small|noop | rust-loop-from-elites | 1.2 | -8.0% | yes |
| rust-loop-wrappers | small|body | rust-loop-from-elites | 22.2 | 2.2% | yes |
| rust-loop-wrappers | small|sig_dep | rust-loop-from-elites | 60.7 | 174.9% | yes |
| ripgrep-wrappers | large|cold | rust-loop-from-elites | 49.7 | 34.0% | yes |
| ripgrep | large|noop | rust-loop-from-elites | 20.0 | 1414.7% | yes |
| ripgrep | large|body | rust-loop-from-elites | 42.8 | 96.8% | yes |
| nalgebra-wrappers | large|sig_dep | rust-loop-from-elites | 23.2 | 4.9% | yes |
| pinned-hashbrown-kache-round | mid|cold | rust-loop-from-elites | 116.5 | 214.3% | yes |
| pinned-hashbrown | mid|noop | rust-loop-from-elites | 1.3 | -5.2% | yes |
| pinned-hashbrown-kache-round | mid|body | rust-loop-from-elites | 42.2 | 94.1% | yes |
| pinned-hashbrown | mid|sig_dep | rust-loop-from-elites | 57.4 | 160.1% | yes |
| rust-loop-wrappers | small|worktree | rust-loop-from-elites | 84.3 | 128.4% | yes |
| pinned-hashbrown-kache-round | mid|worktree | rust-loop-from-elites | 49.5 | 34.3% | yes |
| ripgrep-wrappers | large|worktree | rust-loop-from-elites | 35.9 | -2.6% | yes |
| rust-loop-kache-round | small|cold | hashbrown-from-elites | 522.6 | 61.4% | yes |
| rust-loop | small|noop | hashbrown-from-elites | 3.2 | -0.8% | yes |
| rust-loop-wrappers | small|body | hashbrown-from-elites | 282.2 | 147.6% | yes |
| rust-loop-wrappers | small|sig_dep | hashbrown-from-elites | 338.2 | 198.7% | yes |
| ripgrep-wrappers | large|cold | hashbrown-from-elites | 457.9 | 41.4% | yes |
| ripgrep | large|noop | hashbrown-from-elites | 16.6 | 420.6% | yes |
| ripgrep | large|body | hashbrown-from-elites | 116.2 | 2.0% | yes |
| nalgebra-wrappers | large|sig_dep | hashbrown-from-elites | 14.4 | -87.3% | yes |
| pinned-hashbrown-kache-round | mid|cold | hashbrown-from-elites | 378.8 | 17.0% | yes |
| pinned-hashbrown | mid|noop | hashbrown-from-elites | 4.9 | 54.2% | yes |
| pinned-hashbrown-kache-round | mid|body | hashbrown-from-elites | 120.2 | 5.4% | yes |
| pinned-hashbrown | mid|sig_dep | hashbrown-from-elites | 123.7 | 9.3% | yes |
| rust-loop-wrappers | small|worktree | hashbrown-from-elites | 430.2 | 27.9% | yes |
| pinned-hashbrown-kache-round | mid|worktree | hashbrown-from-elites | 561.4 | 66.9% | yes |
| ripgrep-wrappers | large|worktree | hashbrown-from-elites | 552.1 | 64.1% | yes |
| rust-loop-kache-round | small|cold | serde-from-elites | 2380.0 | 635.0% | yes |
| rust-loop | small|noop | serde-from-elites | 10.6 | 230.8% | yes |
| rust-loop-wrappers | small|body | serde-from-elites | 814.0 | 614.3% | yes |
| rust-loop-wrappers | small|sig_dep | serde-from-elites | 735.2 | 549.4% | yes |
| ripgrep-wrappers | large|cold | serde-from-elites | 1800.4 | 456.0% | yes |
| ripgrep | large|noop | serde-from-elites | 17.1 | 435.9% | yes |
| ripgrep | large|body | serde-from-elites | 281.0 | 146.6% | yes |
| nalgebra-wrappers | large|sig_dep | serde-from-elites | 34.0 | -70.0% | yes |
| pinned-hashbrown-kache-round | mid|cold | serde-from-elites | 1696.0 | 423.8% | yes |
| pinned-hashbrown | mid|noop | serde-from-elites | 23.3 | 629.5% | yes |
| pinned-hashbrown-kache-round | mid|body | serde-from-elites | 260.3 | 128.5% | yes |
| pinned-hashbrown | mid|sig_dep | serde-from-elites | 260.4 | 130.0% | yes |
| rust-loop-wrappers | small|worktree | serde-from-elites | 1663.5 | 394.6% | yes |
| pinned-hashbrown-kache-round | mid|worktree | serde-from-elites | 2025.2 | 502.1% | yes |
| ripgrep-wrappers | large|worktree | serde-from-elites | 2174.3 | 546.5% | yes |
| rust-loop-kache-round | small|cold | ripgrep-from-elites | 4824.7 | 65.7% | yes |
| rust-loop | small|noop | ripgrep-from-elites | 569.3 | 1753.2% | yes |
| rust-loop-wrappers | small|body | ripgrep-from-elites | 390.4 | 150.7% | yes |
| rust-loop-wrappers | small|sig_dep | ripgrep-from-elites | 505.2 | -33.6% | yes |
| ripgrep-wrappers | large|cold | ripgrep-from-elites | 3724.8 | 27.9% | yes |
| ripgrep | large|noop | ripgrep-from-elites | 32.1 | 4.5% | yes |
| ripgrep | large|body | ripgrep-from-elites | 207.8 | 33.4% | yes |
| nalgebra-wrappers | large|sig_dep | ripgrep-from-elites | 28.5 | -96.3% | yes |
| pinned-hashbrown-kache-round | mid|cold | ripgrep-from-elites | 4778.7 | 64.1% | yes |
| pinned-hashbrown | mid|noop | ripgrep-from-elites | 485.9 | 1481.6% | yes |
| pinned-hashbrown-kache-round | mid|body | ripgrep-from-elites | 191.7 | 23.1% | yes |
| pinned-hashbrown | mid|sig_dep | ripgrep-from-elites | 141.8 | -81.4% | yes |
| rust-loop-wrappers | small|worktree | ripgrep-from-elites | 3346.6 | 21.5% | yes |
| pinned-hashbrown-kache-round | mid|worktree | ripgrep-from-elites | 4845.2 | 75.9% | yes |
| ripgrep-wrappers | large|worktree | ripgrep-from-elites | 3084.7 | 12.0% | yes |

### Promoted defaults

Iteration default (cold/body/sig_dep): `{"codegen_units": null, "debuginfo": "full", "dev_backend": "llvm", "fast_check": "cargo-check", "incremental": true, "jobs": 3, "linker": "default", "loop": "check", "offline": true, "sccache": false, "wrapper": false}`

weighted majority on real-sample cold/body/sig_dep; fixture cells do not vote when real elites exist; warm-cache sccache cold is sample-specific, not a true-cold default

No-op default: `{"codegen_units": null, "debuginfo": "full", "dev_backend": "llvm", "fast_check": "cargo-check", "incremental": true, "jobs": 3, "linker": "default", "loop": "check", "offline": true, "sccache": false, "wrapper": false}`

weighted majority on real-sample noop; fixture graph elites do not set the default when a real noop exists

Sample-specific elites:

- `small|cold` `rust-loop-kache-round`: fixture elite; real samples outvote fixtures
- `small|noop` `rust-loop`: fixture elite; real samples outvote fixtures; loses the weighted vote for its edit family
- `small|body` `rust-loop-wrappers`: fixture elite; real samples outvote fixtures; loses the weighted vote for its edit family
- `small|sig_dep` `rust-loop-wrappers`: fixture elite; real samples outvote fixtures; loses the weighted vote for its edit family
- `large|cold` `ripgrep-wrappers`: loses the weighted vote for its edit family
- `mid|noop` `pinned-hashbrown`: loses the weighted vote for its edit family
- `small|worktree` `rust-loop-wrappers`: fixture elite; real samples outvote fixtures; loses the weighted vote for its edit family
- `large|worktree` `ripgrep-wrappers`: loses the weighted vote for its edit family

<!-- MAP_ELITES_GRID_END -->

## Hill-climb log

Iterations go below. Each row is one change: hypothesis, what landed, before/after
on the same sample, keep or revert.

| Iter | Sample | Hypothesis | Change | Result | Keep? |
| --- | --- | --- | --- | --- | --- |
| 0 | rust-loop | Establish the harness | `bench/rust_loop_bench` schema 1 | self-test correctness pass; check cold 47ms / noop 10ms / body 26ms | keep |
| 1 | rust-loop | Native driver is cheaper than Python | Port rust-loop to Zig | spec/run work; graph cold 295ms / noop 1.4ms | keep |
| 2 | rust-loop | Cold timing was a lie (warmup filled target) | Empty target + nano cache on every cold sample | check cold 45.7ms (was ~10ms) | keep |
| 3 | rust-loop | Edit timing was a no-op of the edited tree | Time only the first rebuild after the edit | body check 26.1ms (was ~10ms median) | keep |
| 4 | rust-loop | Task cache wins warm repeats | `loop=graph` + wrapper | noop 1.3ms vs check 10.1ms (**87%**) | keep for noop |
| 5 | rust-loop | Wrapper helps incremental check | `RUSTC_WRAPPER` + `CARGO_INCREMENTAL=0` | body check 46.7ms vs 26.1ms (**slower**); disk 7KB vs 35KB | revert as iteration default |
| 6 | rust-loop | Mold helps linked test | `-C link-arg=-fuse-ld=mold` | test cold 119ms vs 171ms (**30%**); body test 78ms vs 133ms (**41%**) | keep for test |
| 7 | rust-loop | sccache helps cold check | `RUSTC_WRAPPER=sccache` | check cold 53ms vs 46ms (loss); test similar | revert |
| 8 | rust-loop | codegen-units=256 helps | `-C codegen-units=256` | check/test within 3% of baseline | revert |
| 9 | rust-loop | line-tables-only shrinks disk | `-C debuginfo=line-tables-only` | test cold 164 vs 171ms (~4%); disk 6.96MB vs 7.08MB | keep for test disk, not iteration |
| 10 | rust-loop | Cranelift wins dev build | nightly `codegen-backend=cranelift` | cell `ok: no` on this toolchain pairing | unmeasured / failed |
| 11 | rust-loop-medium | Same elites generalize | held-out small genomes on mid | noop graph transfers (1.4ms, +0.5%); check body +7% | keep check + graph split |
| 12 | both | Further gene flips | incremental/linker/cgu on check loop | consecutive tries <3% on body/sig | stop |
| 13 | rust-loop | Cranelift needs nightly `-Zcodegen-backend` | `cargo +nightly -Zcodegen-backend` + `CARGO_PROFILE_*_CODEGEN_BACKEND` | build body 25.0 vs LLVM 26.8 (noise); **test body 77 vs 144 (−47%)**; test cold 108 vs 184 (−41%) | keep for linked test; not a check-loop elite |
| 14 | pinned-hashbrown | Mid cell needs a real crate | Vendor hashbrown 0.15.2 (23k LOC); size by LOC | rust-loop-medium (202 LOC) reclassified small; mid vacated for a real tree | keep |
| 15 | midsize (PR #11) | Merge ripgrep+tokio shard | Record `fitness_method` / `cache_state`; reject `package_scope=touched` on sig_dep | large cells occupied; sig_dep elite is line-tables-only 712ms (touched 530ms rejected: no dependent-crate gate); cold sccache 1387ms marked warm_compiler_cache | keep with annotations |
| 16 | midsize held-out | Fixture elites on real crates | Weight real samples in promote | small/mid fixtures **+10–213%** vs large elites; graph skipped on large. Iteration default = real `cargo check` + line-tables-only; noop = wrapper check (not fixture graph) | keep |
| 17 | rust-loop | Cranelift test win was nightly vs 1.83 | `bench/nightly_pair.py`: nightly LLVM vs nightly cranelift, `test --no-run` | build body 26.4 vs 27.4 (−3.6%); test compile body 81.0 vs 83.0 (−2.4%). The earlier −47% test body was the toolchain, not the backend | revert cranelift as a test elite; keep nightly-llvm as the control |
| 18 | pinned-hashbrown | Official harness fills vacated mid | `[lib] doctest = false`; `--map-elites` check seeds first; incremental shard writes | **grid change:** mid|cold 441.7 check (`incremental=false`); mid|noop **3.2 graph+wrapper** (was 15.4 check); mid|body 122.7 / sig_dep 113.2 check. Graph cold 8129ms loses. Promoted defaults unchanged (large noop still votes check+wrapper; graph does not transfer) | keep |
| 19 | pinned-hashbrown | sccache+mold cold 143ms is warm cache | Clear `SCCACHE_DIR` on cold; reject warm vs empty | 143ms sccache+mold does **not** occupy mid|cold (same class as midsize 1387ms). Empty-cache elite stays 441.7 | keep the gate; revert sccache as empty-cold |
| 20 | pinned-hashbrown | Official `--map-elites --mutations 4` finished | 45 evals; check/graph/test seeds + mutants | mid cells stalled at check body/sig 122.7/113.2, graph noop 3.2, empty-cold 441.7. Cranelift seed wrote no rows (evaluate with nightly_pair). large|sig_dep still n=1 | keep |
| 21 | pinned-hashbrown | Isolate cranelift on a real mid crate | `nightly_pair.py` nightly LLVM vs cranelift | **build body 140 vs 130 (+8%, lose)**; **test --no-run body 323 vs 390 (−17%)**, test cold 3262 vs 3474 (−6%). Cranelift is a test-codegen win, not a `loop=build` elite | keep as measured step; not a MAP-Elites gene |
| 22 | ripgrep 15.2.0 | Cranelift on a real large crate | `nightly_pair.py` | **build cold 4939 vs 6808 (−27%)**; **build body 382 vs 473 (−19%)**; test --no-run cold 6118 vs 7849 (−22%), body 430 vs 506 (−15%). Sig edit sites failed (callers of `sign`). Check-loop elites still beat build (121ms vs 382ms) | keep cranelift as a build/test-codegen step; not a check-cell elite |
| 23 | tokio 1.54.0 | Cranelift on tokio (`default=full`) | `nightly_pair.py` | **build cold 5808 vs 6749 (−14%)**; **build body 1033 vs 1120 (−8%)**; sig ~flat. `test --no-run` failed for **both** nightlies (cargo 101; workspace tests, not backend-specific) | keep the build win; do not read test cells |
| 24 | cross-test | Rerun matrix on pinned-hashbrown | held-out canonical elites | rust-loop **noop graph transfers** (3.2ms, +0.9%); rust-loop body/sig **+112/+130%**. midsize body +5.7%; midsize noop check **+409%** vs graph. Hashbrown elites on rust-loop: noop +10%, body +14%, sig **+697%**. Promoted defaults unchanged | keep |
| 25 | rach-repos (PR #12) | Merge bhumi / grep-core / forge_domain | Isolated `SCCACHE_DIR`; reject warm vs empty; held-out names include `-from-` | 144 evals, 12 ok elites. **No occupancy change.** sccache mid/large body 244/1058 lose to hashbrown 122.7 / are incomparable to midsize restore+mean. A `hashbrown-from-rach-repos` 403.1 cold was held-out (does not occupy mid\|cold). Promoted defaults unchanged | keep |
| 26 | hashbrown + ripgrep + bhumi | sccache mid/large wins were method/cache-specific | Identical official first-rebuild; per-genome `SCCACHE_DIR`; shared target | incremental check **beats** sccache+noinc: hashbrown body 115 vs 337 (2.9×); ripgrep 148 vs 363 (2.5×); bhumi 290 vs 354 (+22%). n=5 on rach-repos body/sig mixed the first miss with warm/sccache hits. **sccache is sample/cache-specific, not a default** | revert sccache as iteration default |
| 27 | crates/* workspaces | graph-loop `discover_inputs` missed globs | Expand `crates/*` in Zig + Python; test that an edit is a miss | rust-loop-medium graph noop 1.5ms still valid. Synthetic `members=["crates/*"]`: cold 630 / noop 1.4 / **body 509 miss** (was a bogus 1ms hit). Graph noop elites stay; they were never a glob-workspace occupy | keep |
| 28 | cranelift | `CARGO_PROFILE_*` needs `cargo-features` | `RUSTFLAGS=-Zcodegen-backend=cranelift` + `cargo +nightly -Zcodegen-backend` (no manifest edit) | `cargo +nightly -Zcodegen-backend build` on rust-loop (no cargo-features) rc=0. Isolated nightly pair unchanged: cranelift is a build/test-codegen step, not a check-cell elite | keep the flag path |
| 29 | cross-test | Hashbrown mid elites on bhumi + ripgrep | `--held-out` mid cells; `-from-` cannot occupy | bhumi: graph noop **15.4ms** (transfers), body 290 / sig 246. ripgrep: body 154 / sig 135 check; graph noop **2286ms** (does not transfer). Occupancy unchanged. Official 11/12 cells stalled. large\|sig_dep still n=1 (PR #11 method). Ruff PR #13 pending; forge_domain private here | keep |
| 30 | large-workspace (PR #13) | Merge ruff 0.17.1 / `cargo check -p ruff` | One `crates/*` expand (Zig + Python fallback + test); reject mold first-attempts (~260ms / 585KB, `ok=false`) | Official method supersedes PR #11 restore+mean. First occupy: large cold 54781 empty, noop 155, body 467, sig 6663 line-tables | keep |
| 31 | rust_loop_bench | Extra `--runs` were no-ops; no `--package`; 600s timeout | Apply/revert + untimed restore per run; `--package` / `--validate-package`; timeout 3600 | 13 harness tests; broken edit prefers `// nano-loop-body` so `check -p ruff` sees `ruff_command_line` | keep |
| 32 | ruff unified | Re-measure four genomes under official first-rebuild | Marks: body `ruff_command_line::is_response_file`; hub `ruff_text_size` private fn | incremental body **484** / sig **6522**; line-tables body **517** (+6.8%, lose) / sig **6442** (−1.2%); sccache body **1268** (+162%) / sig **19890**; wrapper body **1000** (+107%) / sig **15614**; wrapper empty-cold 53027 (−4%) | keep incremental; revert the rest as defaults |
| 33 | sccache | PR #13 −11% cold / −3.5% sig | Official empty `SCCACHE_DIR` + first-rebuild | sccache cold **+6.8%**, body **+162%**, sig **+205%** vs incremental. The shard “wins” were cache/sample-specific. **sccache is not a default** | revert |
| 34 | wrapper `CARGO_INCREMENTAL=0` | Should the wrapper stop forcing inc=0? | Unified ruff + prior hashbrown/ripgrep/bhumi | Wrapper body/sig **+88–139%** because it disables incremental. Keep the force (nanocompile cache is ineligible for incremental artifacts). Do **not** promote wrapper for iteration. Graph+wrapper stays a fixture noop gene | keep the force; not an iteration default |
| 35 | rematch | All four shards, official method | ripgrep 53k LOC is large; ruff 838k LOC / ` -p ruff` is large | **large cold/noop/body → ripgrep** 3115 / 30.7 / 155.7; **large sig → ruff line-tables** 6442. Promoted: `cargo check` LLVM `incremental=true` `debuginfo=full`, no wrapper, no sccache, no sample `package`. **12/12 stalled** | keep |
| 36 | four-shard cross-test | Unified official first-rebuild | mid elites → ruff `-p ruff`; large elites → hashbrown / ripgrep / bhumi / ruff | Hashbrown body **119 (−2.9%)** transfers; graph noop **+409%** does not. On ruff, hashbrown body **470** matches ruff incremental 484; graph noop **1288** does not transfer. Ripgrep self +3–15%. Same-project ruff sig elite **+1.2%**. **Stop: 12/12 stalled** | keep |
| 37 | genome | Add kache + worktree + nightly genes | `kache`/`warm_store` exclusive of wrapper/sccache; edit=`worktree`; shape metadata only; clippy/nextest timed loops | kache 1.2.2 installed with nightly + `-fuse-ld=bfd` (rust-lld `rust_eh_personality` failed). wild skipped. sccache+inc **ok=False** on every sample. | keep |
| 38 | rust-loop | New genes + worktree occupy small | `--map-elites --mutations 4` then `compare_wrappers` | **15/15 cells.** small cold **37.1** (`opt_level_deps=2`); body/sig **21.7/22.1 noinc**; worktree **36.9 noinc**. Graph body/sig <10ms dropped as cache hits. | keep |
| 39 | hashbrown | Empty-cache cold was inflated | Official `--map-elites` + clear compiler cache on body/sig | mid cold **323.8** (−27% vs 441.7); body **114** (−7%); worktree **336.3**. kache warm worktree **86** / cold **63** tagged held-out. | keep |
| 40 | kache H2H | Cold vs warm store × inc × every edit | `bench/compare_wrappers.py` on rust-loop, hashbrown, serde_derive, nalgebra, ripgrep | Warm kache **flips worktree/cold** (hashbrown worktree 86 vs 493; ripgrep 546 vs 3173; nalgebra 492 vs 5985). Empty-store incremental **wins body** except nalgebra kache-inc **782 vs 814**. Wrapper empty is last. | keep |
| 41 | held-out shapes | serde (proc_macro mid), nalgebra (generic large), axum hello-world | classify shape; axum example needs workspace `--package` | serde incremental body **265**; nalgebra occupies **large\|sig 761**. Isolated axum example path-dep failed (0 ok); rerun from workspace root. | keep |
| 42 | cross-test | Current 15 elites on rust-loop, hashbrown, serde_derive, ripgrep | `--held-out` `current-elites.json`; strip sample `package` on transfer | Ripgrep incremental body **transfers** to hashbrown (+2%). Graph noop transfers small→mid (−0.8%) and **does not** transfer to serde/ripgrep (+400–1700%). Small noinc body **+148%** on hashbrown. kache does not occupy; warm worktree stays comparison-only. **15/15 stalled** | keep |
