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
Merge shards from `bench/archive/<sample>.json` with
`nanocompile map-elites merge` or `python3 tools/map_elites.py merge`.

Axes: size (`small` / `mid` / `large`) × edit (`cold` / `noop` / `body` / `sig_dep`).
Fitness is median loop wall time in ms (lower is better). Disk is recorded, not an axis.

| Size \ Edit | cold | noop | body | sig_dep |
| --- | ---: | ---: | ---: | ---: |
| small | — | — | — | — |
| mid | — | — | — | — |
| large | — | — | — | — |

### Elites

No cells occupied yet.

### Generalization

No held-out evaluations yet.

### Promoted defaults

No genome has been promoted to nanocompile defaults yet.

<!-- MAP_ELITES_GRID_END -->

## Hill-climb log

Iterations go below. Each row is one change: hypothesis, what landed, before/after
on the same sample, keep or revert.

| Iter | Sample | Hypothesis | Change | Result | Keep? |
| --- | --- | --- | --- | --- | --- |
| 0 | — | Establish the harness | `bench/rust_loop_bench` schema 1 | pending first numbers | — |
