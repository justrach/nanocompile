# Rach repos rust-loop MAP-Elites

Held-out sample: public Rust crates under [`github.com/justrach`](https://github.com/justrach).
Clones lived in `/tmp/rach-scratch` (not this repo).
Archive shard: [`bench/archive/rach-repos.json`](../../archive/rach-repos.json).
Schema 1, `kind: nanocompile.rust-loop.map-elites.shard`. This PR does **not** write `bench/map_elites.json`.

Validate: `python3 tools/map_elites.py validate bench/archive/rach-repos.json`.

Recorded fields: `fitness_method=official_first_rebuild`, `sample_class=real`,
`cache_state` on cold cells. Do not compare raw milliseconds to midsize
`restore_rebuild_mean_of_medians`.

## Projects

| Sample | Size | Package | Commit | Rust LOC | Linux |
| --- | --- | --- | --- | ---: | --- |
| bhumi | small | `bhumi` | `355545d6b8ec` | 1323 | check/build after `libssl-dev` |
| emergentDB | mid | `grep-core` | `1205db48e7bd` | 19734 | check/build/test OK |
| codegraff2 | large | `forge_domain` | `e5610ede9cf3` | 164315 | check/build/test OK |

## Per-cell elite (3% replace rule, graph-loop excluded)

| Cell | Sample | Genome | Median ms | Spread ms | Disk bytes | Gate | Cache |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| `small|cold` | bhumi | `check sccache noinc` | 7855.1 | 3701.47 | 292453407 | pass | warm_compiler_cache |
| `small|noop` | bhumi | `check incremental` | 70.5 | 2.68 | 299025379 | pass | — |
| `small|body` | bhumi | `check incremental cg=16` | 181.1 | 1.63 | 306094776 | pass | — |
| `small|sig_dep` | bhumi | `check incremental` | 196.3 | 2.47 | 305624537 | pass | — |
| `mid|cold` | emergentDB | `check sccache noinc` | 5769.6 | 1563.92 | 131621117 | pass | warm_compiler_cache |
| `mid|noop` | emergentDB | `check incremental` | 86.9 | 1.26 | 144598451 | pass | — |
| `mid|body` | emergentDB | `check sccache noinc` | 244.1 | 6.75 | 131621960 | pass | — |
| `mid|sig_dep` | emergentDB | `check sccache noinc` | 214.9 | 9.49 | 131623787 | pass | — |
| `large|cold` | codegraff2 | `check sccache noinc` | 12576.4 | 6289.89 | 396595962 | pass | warm_compiler_cache |
| `large|noop` | codegraff2 | `check incremental cg=16` | 191.7 | 11.24 | 463218451 | pass | — |
| `large|body` | codegraff2 | `check sccache noinc` | 1058.0 | 39.03 | 396597126 | pass | — |
| `large|sig_dep` | codegraff2 | `check sccache noinc` | 1018.6 | 15.05 | 396601504 | pass | — |

## Baseline vs best (incremental loop)

| Sample | Edit | Baseline check ms | Best ms | Best genome | Δ |
| --- | --- | ---: | ---: | --- | ---: |
| bhumi | body | 213.7 | 181.1 | `check incremental cg=16` | -15% |
| bhumi | sig_dep | 196.3 | 196.3 | `check incremental` | +0% |
| bhumi | noop | 70.5 | 70.5 | `check incremental` | +0% |
| bhumi | cold | 9891.4 | 7855.1 | `check sccache noinc` | -21% |
| emergentDB | body | 338.8 | 244.1 | `check sccache noinc` | -28% |
| emergentDB | sig_dep | 310.1 | 214.9 | `check sccache noinc` | -31% |
| emergentDB | noop | 86.9 | 86.9 | `check incremental` | +0% |
| emergentDB | cold | 11111.5 | 5769.6 | `check sccache noinc` | -48% |
| codegraff2 | body | 1604.0 | 1058.0 | `check sccache noinc` | -34% |
| codegraff2 | sig_dep | 1766.0 | 1018.6 | `check sccache noinc` | -42% |
| codegraff2 | noop | 200.6 | 191.7 | `check incremental cg=16` | -4% |
| codegraff2 | cold | 16178.7 | 12576.4 | `check sccache noinc` | -22% |

## Which steps helped, and by how much

- **sccache** — biggest kept win. Incremental mid/large body and sig_dep
  (emergentDB −28/−31%; codegraff2 −34/−42%). Cold on every size
  (bhumi −21%, emergentDB −48%, codegraff2 −22%), all marked
  `warm_compiler_cache` because `SCCACHE_DIR` survived a wiped `target/`.
  Cold spread is large (bhumi 3.7 s, codegraff2 6.3 s); the 3% archive rule
  still occupies sccache on median.
- **codegen-units=16** — kept on bhumi `body` (181 vs a later 194 ms incremental
  reseed, −7%; −15% vs the first 214 ms seed) and codegraff2 `noop` (−4%).
- **nanocompile wrapper** — helped **cold** bhumi (−15% vs plain) because it caches
  rustc artifacts across a wiped `target/`. It **hurt** incremental body/sig
  (2–2.6× slower) because the wrapper forces `CARGO_INCREMENTAL=0`.
- **plain incremental (`CARGO_INCREMENTAL=1`)** — best or tied for **noop** on small
  and mid. Large noop kept cg=16 over plain by 4%.

## Which steps did not help (or lost)

- **plain-noinc / nanocompile-wrapper / fast-check wrapper** on incremental edits:
  2–4× slower than incremental rustc (emergentDB 770–840 ms vs 339 ms; codegraff2
  3.9–4.2 s vs 1.6 s).
- **disk-hygiene** (`debuginfo=line-tables-only`) — no ≥3% check-loop win here
  (midsize's restore+rebuild method *did* keep line-tables-only on large|body;
  different fitness_method, not comparable).
- **codegen-units=256** — default-ish; no win.
- **mold / lld** — no help on `cargo check` (nothing to link). Build/test cells were
  slower than check, so they never became incremental-loop elites.
- **cranelift-dev** — not an elite. The rust-loop-cranelift `loop=build` genome
  failed unchanged on bhumi and emergentDB: nightly Cargo 1.101 still needs
  `cargo-features = ["codegen-backend"]` in the crate manifest
  (`CARGO_PROFILE_DEV` is not enough on these trees).
- **validate-graph / `loop=graph`** — 2–16 ms “wins” were **task-cache hits**.
  `tools/rust_loop.py discover_inputs` does not expand workspace `members = ["crates/*"]`,
  so the spec omitted the edited crate. Those evals are **dropped** from the shard
  so they cannot become a merged elite. A successful fast path is not a rustc result.

## Correctness

- **emergentDB / grep-core**: broken `compress_gzip` edit — `cargo check` and
  `cargo test` both exit 101. `rust_loop.py run --step validate` refuses cranelift.
- **bhumi**: broken `get_text` edit — check and test both fail; validate refuses cranelift.
- **codegraff2**: broken `json_repair` construction fails type-check under rustc;
  `sig_dep` edits live in depended-on `forge_json_repair` while the loop checks `forge_domain`,
  so dependents are compiled (`dependents_agree_on_broken`).
- Official `rust_loop_bench --map-elites` on emergentDB reported `agree_on_broken=false`
  because it edited an unused probe fn that still type-checked. Those rows stay in the
  shard with `correctness.ok=false` and cannot occupy a cell. Graph-loop rows are excluded.

## Failed to build

- **emergentDB `vector-core`**: `librocksdb-sys` C++ compile failed (`c++` exit 1).
  Sample used: `grep-core` (14 unit tests passed).
- **bhumi** failed until `libssl-dev` was installed (`openssl-sys`). Then `cargo check --lib` passed.
  The crate is a pyo3 `cdylib`; `cargo test` is not a rich rustc suite.

## Cross-test of other samples' elites (unchanged genomes)

Foreign elites from `bench/archive/*.json` evaluated on these repos. Fitness method here
is `official_first_rebuild`; midsize source numbers are `restore_rebuild_mean_of_medians`.

| Trained on | Genome cell | Tested on | Cell | Median ms | Δ vs local elite |
| --- | --- | --- | --- | ---: | ---: |
| rust-loop | `small|body` | bhumi | `small|body` | 426.5 | 135.58% |
| rust-loop | `small|body` | emergentDB | `mid|body` | 905.3 | 270.94% |
| rust-loop | `small|body` | codegraff2 | `large|body` | 4752.9 | 349.23% |
| rust-loop | `small|sig_dep` | bhumi | `small|sig_dep` | 439.1 | 123.67% |
| rust-loop | `small|sig_dep` | emergentDB | `mid|sig_dep` | 877.9 | 308.48% |
| rust-loop | `small|sig_dep` | codegraff2 | `large|sig_dep` | 4880.2 | 379.1% |
| rust-loop-medium | `mid|body` | bhumi | `small|body` | 218.1 | 20.46% |
| rust-loop-medium | `mid|body` | emergentDB | `mid|body` | 355.2 | 45.56% |
| rust-loop-medium | `mid|body` | codegraff2 | `large|body` | 1664.1 | 57.28% |
| rust-loop-steps | `small|body` | bhumi | `small|body` | 210.6 | 16.29% |
| rust-loop-steps | `small|body` | emergentDB | `mid|body` | 330.6 | 35.45% |
| rust-loop-steps | `small|body` | codegraff2 | `large|body` | 1603.2 | 51.52% |
| rust-loop-steps | `small|sig_dep` | bhumi | `small|sig_dep` | 199.6 | 1.65% |
| rust-loop-steps | `small|sig_dep` | emergentDB | `mid|sig_dep` | 316.6 | 47.32% |
| rust-loop-steps | `small|sig_dep` | codegraff2 | `large|sig_dep` | 1828.1 | 79.47% |
| rust-loop | `small|noop` | bhumi | `small|noop` | 72.0 | 2.06% |
| rust-loop | `small|noop` | emergentDB | `mid|noop` | 88.3 | 1.58% |
| rust-loop | `small|noop` | codegraff2 | `large|noop` | 206.8 | 7.9% |
| midsize | `large|cold` | bhumi | `small|cold` | 14088.0 | 79.35% |
| midsize | `large|cold` | emergentDB | `mid|cold` | 3990.0 | -30.84% |
| midsize | `large|noop` | bhumi | `small|noop` | 180.4 | 155.76% |
| midsize | `large|noop` | emergentDB | `mid|noop` | 107.3 | 23.46% |
| midsize | `large|body` | bhumi | `small|body` | 253.3 | 39.92% |
| midsize | `large|body` | emergentDB | `mid|body` | 318.0 | 30.32% |
| midsize | `large|sig_dep` | bhumi | `small|sig_dep` | 278.4 | 41.81% |
| midsize | `large|sig_dep` | emergentDB | `mid|sig_dep` | 406.8 | 89.27% |
| rust-loop-cranelift | `small|body` | bhumi | `small|body` | fail | n/a |
| rust-loop-cranelift | `small|body` | emergentDB | `mid|body` | fail | n/a |
| midsize | `large|cold` | codegraff2 | `large|cold` | 12485.2 | -0.73% |
| midsize | `large|noop` | codegraff2 | `large|noop` | 192.8 | 0.55% |
| midsize | `large|body` | codegraff2 | `large|body` | 1646.3 | 55.6% |
| midsize | `large|sig_dep` | codegraff2 | `large|sig_dep` | 1633.2 | 60.33% |

Transfer notes:

- The **small rust-loop elite** (`check`, `incremental=false`) is a poor held-out genome:
  +136% on bhumi, +271% on emergentDB, 4.8 s on codegraff2 body vs a 1.06 s local sccache elite.
- **rust-loop-steps incremental=true** is the best fixture transfer: +16% on bhumi body,
  +35% on emergentDB body, +52% on codegraff2 body (still loses to local sccache).
- **graph+wrapper noop elites** (~1.3 ms on the tiny fixtures) become ordinary cargo-check
  times here (72 / 88 / 207 ms). The fixture graph hit does not survive a real workspace.
- **midsize** (ripgrep/tokio) elites, evaluated unchanged after they landed on the parent
  branch: sccache **cold** transfers (even on codegraff2, −31% vs our mid cold seed — cold
  noise). Incremental `line-tables-only` body and `package_scope=touched` sig_dep lose to
  local sccache (+30–60%). Wrapper **noop** is even on codegraff2, +24–156% on the smaller
  crates. Source fitness_method is `restore_rebuild_mean_of_medians`; only the transfer
  times on these repos are ours.
- **rust-loop-cranelift** `loop=build` did not run on these manifests (see above).

## Hill-climb / MAP-Elites log

Axes: `small|mid|large` × `cold|noop|body|sig_dep`. Genome is the full loop config.
Fitness: median wall ms. Replace only if ≥3% faster (and beyond spread). Stop a cell after
several consecutive non-improving tries. Mutations flipped one or two genes.

Raw files: [`evals.json`](evals.json), [`timings.csv`](timings.csv),
[`pre-schema-shard.json`](pre-schema-shard.json), [`scratch-fill.json`](scratch-fill.json),
[`extra-evals.json`](extra-evals.json),
[`official/emergentDB.json`](official/emergentDB.json).

Evaluations in shard: **144**. Cross-test rows: **32**.

