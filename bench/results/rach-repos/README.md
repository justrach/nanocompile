# Rach repos rust-loop MAP-Elites

Held-out sample: public Rust crates under [`github.com/justrach`](https://github.com/justrach).
Scratch clones were not copied into this repository (`/tmp/rach-scratch`).
Shard: [`bench/archive/rach-repos.json`](../../archive/rach-repos.json) — schema 1,
`kind: nanocompile.rust-loop.map-elites.shard`. This file does **not** overwrite
[`bench/map_elites.json`](../../map_elites.json).

Merge with `python3 tools/map_elites.py validate bench/archive/rach-repos.json`.

## Projects

| Sample | Size | Package | Commit | LOC | Linux build |
| --- | --- | --- | --- | ---: | --- |
| bhumi | small | `bhumi` | `355545d6b8ec` | 1323 | check/build after `libssl-dev`; cdylib |
| emergentDB | mid | `grep-core` | `1205db48e7bd` | 19734 | check/build/test OK; `vector-core` failed (rocksdb/c++) |
| codegraff2 | large | `forge_domain` | `e5610ede9cf3` | 164315 | check/build/test OK (default-members) |

## Per-cell elite (lowest correct fitness on this shard)

| Cell | Sample | Loop / genes | Median ms | Spread ms | Disk | Gate |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `small|cold` | — | — | — | — | — | — |
| `small|noop` | — | — | — | — | — | — |
| `small|body` | bhumi | `check` plain | 213.7 | 6.32 | 305603983 | pass |
| `small|sig_dep` | — | — | — | — | — | — |
| `mid|cold` | — | — | — | — | — | — |
| `mid|noop` | emergentDB | `check` wrapper noinc | 84.4 | 1.86 | 131623473 | pass |
| `mid|body` | emergentDB | `check` sccache noinc | 244.1 | 6.75 | 131621960 | pass |
| `mid|sig_dep` | emergentDB | `check` sccache noinc | 214.9 | 9.49 | 131623787 | pass |
| `large|cold` | — | — | — | — | — | — |
| `large|noop` | — | — | — | — | — | — |
| `large|body` | — | — | — | — | — | — |
| `large|sig_dep` | — | — | — | — | — | — |

## What helped / what did not (measured)

- **sccache** was the incremental `body` / `sig_dep` elite on emergentDB `grep-core`:
  244 ms vs 339 ms plain check on `body` (−28%), 215 ms vs 310 ms on `sig_dep` (−31%).
- **CARGO_INCREMENTAL=1** (plain cargo) won **noop** on grep-core (87 ms). Wrapper/sccache were within noise.
- **nanocompile-wrapper** and **plain-noinc** were slower on incremental edits (770–840 ms):
  they force `CARGO_INCREMENTAL=0`, which loses rustc's incremental store.
- **codegen-units=16/256** and **disk-hygiene** did not beat the 3% + spread rule on check.
- **mold/lld** do not help `cargo check` (no link). Build/test measurements are in the raw evals.
- **validate-graph** produced a 5.6 ms 'win' that was a **task-cache hit**: `tools/rust_loop.py`
  `discover_inputs` does not expand workspace `members = ["crates/*"]`, so the spec omitted
  the edited crate. Those graph evals are **excluded** from this shard so they cannot become
  a merged elite. Fast path is not a rustc result.
- **cranelift** failed here when `-Zcodegen-backend` was passed without `=cranelift`.

## Correctness

- **emergentDB**: agree_fail=True (check rc=101, test rc=101); validate refuses cranelift=True
- **bhumi**: agree_fail=True (check rc=101, test rc=101); validate refuses cranelift=True

## Failed to build

- **emergentDB `vector-core`**: `librocksdb-sys` C++ compile failed on this image
  (`c++` exit 1 while building write_batch_with_index). `grep-core` is the Linux sample.
- **bhumi** originally failed without `libssl-dev`; after installing OpenSSL, `cargo check --lib` passed.
  `cargo test` of the cdylib is not a useful rustc gate (pyo3 extension).

## Cross-test of other samples' elites

No foreign elites were on the branch when this shard was written.

## Hill-climb / MAP-Elites log

Replace only on ≥3% (and beyond spread). Stop a cell after several non-improving tries.
Raw evaluations: [`evals.json`](evals.json), [`timings.csv`](timings.csv),
pre-schema scratch log: [`pre-schema-shard.json`](pre-schema-shard.json).

Evaluations in shard: **37**.

