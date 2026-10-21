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
| `cranelift-dev` | nightly `CARGO_PROFILE_DEV_CODEGEN_BACKEND=cranelift` `cargo build` |
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
`offline`). `validate` is **not** a gene: it is always `cargo test` with LLVM
rustc. Merge replaces a cell only when the new median is ≥3% faster and
`correctness.ok` is true.

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
| mid | 87.3 ms (rust-loop-medium, check) | 1.4 ms (rust-loop-medium, graph) | 62.9 ms (rust-loop-medium, check) | 34.3 ms (rust-loop-medium, check) |
| large | — | — | — | — |

### Elites

| Cell | Sample | Fitness ms | Spread | Disk | Loop | Wrapper | Linker | Backend |
| --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |
| small|cold | rust-loop | 43.5 | 0.4 | 7005 | check | no | default | llvm |
| small|noop | rust-loop | 1.3 | 0.1 | 6327284 | graph | yes | default | llvm |
| small|body | rust-loop | 24.4 | 0.0 | 7080 | check | no | default | llvm |
| small|sig_dep | rust-loop | 24.8 | 0.0 | 7085 | check | no | default | llvm |
| mid|cold | rust-loop-medium | 87.3 | 0.6 | 22924 | check | no | default | llvm |
| mid|noop | rust-loop-medium | 1.4 | 0.1 | 22309512 | graph | yes | default | llvm |
| mid|body | rust-loop-medium | 62.9 | 0.0 | 1453979 | check | no | default | llvm |
| mid|sig_dep | rust-loop-medium | 34.3 | 0.0 | 33131 | check | no | default | llvm |

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

### Promoted defaults

Iteration default (cold/body/sig_dep): `{"codegen_units": null, "debuginfo": "full", "dev_backend": "llvm", "fast_check": "cargo-check", "incremental": false, "jobs": null, "linker": "default", "loop": "check", "offline": true, "sccache": false, "wrapper": false}`

majority elite on cold/body/sig_dep across occupied size buckets; do not use graph wall time as the edit-loop default

No-op default: `{"codegen_units": null, "debuginfo": "full", "dev_backend": "llvm", "fast_check": "cargo-check", "incremental": false, "jobs": null, "linker": "default", "loop": "graph", "offline": true, "sccache": false, "wrapper": true}`

majority elite on noop: declared graph plus nanocompile task cache

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
