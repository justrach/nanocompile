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

Each cell records sample wall times, median, population stdev, min/max, and
`target/` byte size.

### Step ids

| id | Command under test |
| --- | --- |
| `baseline` | plain `cargo check` / `build` / `test` |
| `nanocompile-wrapper` | `RUSTC_WRAPPER=nanocompile CARGO_INCREMENTAL=0` |
| `fast-check` | `cargo check` only |
| `validate-graph` | declared `fast-check` → `cargo test` via `nanocompile task` |
| `nightly-llvm` | `cargo +nightly` LLVM `build` / `test` (control for cranelift) |
| `cranelift-dev` | `cargo +nightly -Zcodegen-backend` with `CARGO_PROFILE_{DEV,TEST}_CODEGEN_BACKEND=cranelift` (`build` and `test`) |
| `fast-linker` | `-C link-arg=-fuse-ld=mold` or `lld` on build/test |
| `sccache` | `RUSTC_WRAPPER=sccache` |
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
`body` / `sig_dep`). Disk use is recorded per elite, not a third axis — a disk
tertile would make 36 cells and leave most empty while four agents are seeding.

A genome is the full loop config (`wrapper`, `dev_backend`, `linker`, `sccache`,
`codegen_units`, `incremental`, `debuginfo`, `fast_check`, `loop`, `jobs`,
`offline`). `loop` is `check`, `graph`, `test`, or `build`. `build` is the
cranelift-dev gene because `cargo check` skips codegen. `validate` is **not**
a gene: it is always `cargo test` with LLVM rustc. Merge replaces a cell only
when the new median is ≥3% faster and `correctness.ok` is true.

Size is by Rust LOC, not crate-count tricks: `small` is LOC < 2000,
`mid` is 2000 ≤ LOC < 50000 and ≤20 crates, else `large`. The three-crate
`examples/rust-loop-medium` fixture is small. `examples/pinned-hashbrown`
(hashbrown 0.15.2, ~23k LOC) is the mid sample this agent controls.
PR #11's ripgrep 15.2.0 + tokio 1.54.0 trees classify as **large**.

Each elite records `fitness_method` and, for cold cells, `cache_state`.
`official_first_rebuild` is this harness. `restore_rebuild_mean_of_medians`
is the PR #11 protocol (restore+rebuild before every timed edit, then mean
of the two project medians). Do not compare raw ms across methods.
`warm_compiler_cache` means sccache/nanocompile stayed populated after
`target/` was emptied — not a true empty-cache cold.

`package_scope=touched` (`cargo check -p` the hub crate) cannot occupy
`sig_dep` unless `correctness.dependents_agree_on_broken` is true. Promote
weights **real** samples over rust-loop fixtures.

<!-- MAP_ELITES_GRID_BEGIN -->

## MAP-Elites grid

Canonical archive: [`bench/map_elites.json`](../bench/map_elites.json).
Schema: [`bench/map_elites.schema.json`](../bench/map_elites.schema.json).
Merge shards from `bench/archive/<sample>.json` with `nanocompile map-elites merge` or `python3 tools/map_elites.py merge`.

Axes: size (`small` / `mid` / `large`) × edit (`cold` / `noop` / `body` / `sig_dep`).
Fitness is median loop wall time in ms (lower is better). Disk is recorded, not an axis.

| Size \ Edit | cold | noop | body | sig_dep |
| --- | ---: | ---: | ---: | ---: |
| small | 43.5 ms (rust-loop, check) | 1.3 ms (rust-loop, graph) | 24.4 ms (rust-loop, check) | 24.8 ms (rust-loop, check) |
| mid | 441.7 ms (pinned-hashbrown, check) | 3.2 ms (pinned-hashbrown, graph) | 122.7 ms (pinned-hashbrown, check) | 113.2 ms (pinned-hashbrown, check) |
| large | 1387.3 ms (midsize, check) | 31.2 ms (midsize, check) | 121.9 ms (midsize, check) | 712.0 ms (midsize, check) |

### Elites

| Cell | Sample | Fitness ms | Method | Cache | Loop | Wrapper | Backend |
| --- | --- | ---: | --- | --- | --- | --- | --- |
| small|cold | rust-loop | 43.5 | first-rebuild | empty | check | no | llvm |
| small|noop | rust-loop | 1.3 | first-rebuild | — | graph | yes | llvm |
| small|body | rust-loop | 24.4 | first-rebuild | — | check | no | llvm |
| small|sig_dep | rust-loop | 24.8 | first-rebuild | — | check | no | llvm |
| mid|cold | pinned-hashbrown | 441.7 | first-rebuild | empty | check | no | llvm |
| mid|noop | pinned-hashbrown | 3.2 | first-rebuild | — | graph | yes | llvm |
| mid|body | pinned-hashbrown | 122.7 | first-rebuild | — | check | no | llvm |
| mid|sig_dep | pinned-hashbrown | 113.2 | first-rebuild | — | check | no | llvm |
| large|cold | midsize | 1387.3 | restore+mean | warm_compiler_cache | check | no | llvm |
| large|noop | midsize | 31.2 | restore+mean | — | check | yes | llvm |
| large|body | midsize | 121.9 | restore+mean | — | check | no | llvm |
| large|sig_dep | midsize | 712.0 | restore+mean | — | check | no | llvm |

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

### Promoted defaults

Iteration default (cold/body/sig_dep): `{"codegen_units": null, "command_build": false, "debuginfo": "line-tables-only", "dev_backend": "llvm", "fast_check": "cargo-check", "incremental": true, "jobs": 3, "linker": "default", "loop": "check", "offline": true, "package_scope": null, "quiet": false, "sccache": false, "wrapper": false}`

weighted majority on real-sample cold/body/sig_dep; fixture cells do not vote when real elites exist; warm-cache sccache cold is sample-specific, not a true-cold default

No-op default: `{"codegen_units": null, "command_build": false, "debuginfo": "full", "dev_backend": "llvm", "fast_check": "cargo-check", "incremental": false, "jobs": 3, "linker": "default", "loop": "check", "offline": true, "package_scope": null, "quiet": false, "sccache": false, "wrapper": true}`

weighted majority on real-sample noop; fixture graph elites do not set the default when a real noop exists

Sample-specific elites:

- `small|cold` `rust-loop`: fixture elite; real samples outvote fixtures; loses the weighted vote for its edit family
- `small|noop` `rust-loop`: fixture elite; real samples outvote fixtures; loses the weighted vote for its edit family
- `small|body` `rust-loop`: fixture elite; real samples outvote fixtures; loses the weighted vote for its edit family
- `small|sig_dep` `rust-loop`: fixture elite; real samples outvote fixtures; loses the weighted vote for its edit family
- `large|cold` `midsize`: warm compiler cache (sccache/wrapper retained), not empty-cache cold; loses the weighted vote for its edit family
- `mid|cold` `pinned-hashbrown`: loses the weighted vote for its edit family
- `mid|noop` `pinned-hashbrown`: loses the weighted vote for its edit family
- `mid|body` `pinned-hashbrown`: loses the weighted vote for its edit family
- `mid|sig_dep` `pinned-hashbrown`: loses the weighted vote for its edit family

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
