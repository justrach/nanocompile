# Mid-size rust-loop bench: ripgrep 15.2.0 + tokio 1.54.0

MAP-Elites + hill-climb on two public crates, cloned into `/tmp/midsize-scratch`
(not this repo). Fitness is the **mean of the two projects' median wall times**.
The archive shard is [`bench/archive/midsize.json`](../../archive/midsize.json)
(`python3 tools/map_elites.py validate` → `PASS`, kind
`nanocompile.rust-loop.map-elites.shard`).

`tools/map_elites.py classify` reports **large** for both trees (ripgrep: 9
crates / 53 030 LOC; tokio scratch workspace: 5 crates / 188 515 LOC). Cell
keys are therefore `large|*`. The filename stays `midsize.json` as requested.

Pinned:

| Project | Tag | Commit |
| --- | --- | --- |
| [BurntSushi/ripgrep](https://github.com/BurntSushi/ripgrep) | `15.2.0` | `e89fff89ac9af12e8d4ce9d5fd07beb408ca730f` |
| [tokio-rs/tokio](https://github.com/tokio-rs/tokio) | `tokio-1.54.0` | `66d34e45c9c850ed72bc61f2ad107368217f040d` |

Tokio scratch copy: workspace members limited to `tokio`, `tokio-macros`,
`tokio-test`, `tokio-stream`, `tokio-util` (dropped benches/examples/stress/integration);
`tokio` default features set to `full` so the loop matches how people actually
hack on it.

Host: Linux x86_64, 4 cores, rustc 1.99.1, nightly 1.101.0 (cranelift preview),
mold 3.0.0, sccache 0.18.0, hyperfine 2.0.0, nanocompile ReleaseFast.

## Method

- **Genome**: full loop config (`loop`, wrapper, sccache, incremental, linker,
  cranelift, codegen-units, debuginfo, package scope, quiet, jobs).
- **Axes**: size bucket × edit type (`cold` / `noop` / `body` / `sig_dep`).
- **Edits**: `// nano-loop-body` in a leaf crate (`ripgrep` binary `fn sign`,
  `tokio-test::block_on`); `// nano-loop-sig` on an unused `pub fn` in a crate
  others depend on (`globset`, `tokio`).
- **Incremental timing**: restore sources, rebuild to the warm baseline, apply
  the edit, then time. The official `bench/rust_loop_bench` applies the edit
  once and then repeats the command (so its timed `edit_*` samples are mostly
  no-ops). This shard does **not** use that protocol.
- **Fitness**: mean of ripgrep and tokio medians. Lower is better.
- **Correctness gate** (hard): a type-error body edit must fail both `cargo
  check` and `tools/rust_loop.py run --step validate` (real rustc `cargo test
  --no-run`). Validate refuses cranelift and must not write `validate.ok`.
- **Replace**: only if the challenger is ≥3% faster **and** the improvement is
  larger than the champion's spread.
- **Stop**: four consecutive non-improving tries on a cell.

Raw JSON/CSV and the search log live in [`raw/`](raw/).

## Elites (baseline vs best)

Combined fitness is the mean of the two project medians, in milliseconds.

| Cell | Baseline genome | Baseline ms | Elite genome | Elite ms | Δ vs baseline | Disk bytes |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| `large\|cold` | `cargo check`, incremental default | 4467 | `cargo check` + **sccache**, `incremental=false` | **1387** | **−69%** | 196 MB |
| `large\|noop` | `cargo check` | 33.2 | `cargo check` + **nanocompile wrapper** | **31.2** | −6% | 196 MB |
| `large\|body` | `cargo check`, incremental | 127.4 | `cargo check` + **`debuginfo=line-tables-only`** | **121.9** | −4.3% | 314 MB |
| `large\|sig_dep` | `cargo check` workspace | 777.3 | `cargo check -p` **touched hub crate** | **529.8** | **−32%** | 433 MB |

### Per project, elite vs that cell's baseline

| Cell | ripgrep baseline → best | tokio baseline → best |
| --- | --- | --- |
| cold (elite = sccache) | (combined 4467) → 1476 ms | (combined 4467) → 1299 ms |
| noop (elite = nanocompile) | → 25.8 ms | → 36.7 ms |
| body (elite = line-tables-only) | → 163.6 ms | → 80.3 ms |
| sig_dep (elite = `-p` hub) | → 84.1 ms (`-p globset`) | → 975.4 ms (`-p tokio`) |

The signature-edit win is almost entirely ripgrep: checking only `globset` is
cheap. Tokio's hub crate *is* the large crate, so `-p tokio` is still a full
tokio check (~1 s). Combined mean still beat the workspace check (777 → 530).

Cold sccache/nanocompile wins keep a compiler cache across emptied `target/`
dirs. First-run cold check is closer to the 4.5 s baseline; later "cold"
samples hit sccache/nanocompile. That is a real cache property, not rustc
incremental. Spread on the first nanocompile cold seed was huge (~1.2 s); the
sccache elite's spread shrank to 25 ms after the cache filled.

## Which steps helped

| Step | Where it helped | How much |
| --- | --- | --- |
| `sccache` as rustc wrapper, `CARGO_INCREMENTAL=0` | cold check, after the cache is warm | 4467 → 1387 ms combined (−69%) |
| `nanocompile` wrapper | cold (3388 ms, later beaten by sccache); noop (33.2 → 31.2) | small noop win; useful cold cache |
| `disk-hygiene` (`line-tables-only`) | body incremental check | 127.4 → 121.9 ms (−4.3%); also beat baseline on signature (777 → 712) before package-scope won |
| `package_scope=touched` (`cargo check -p` hub) | signature in a depended-on crate | 712 → 530 ms (−26% vs then-elite, −32% vs baseline) |
| rustc incremental (`CARGO_INCREMENTAL=1`) | body / signature vs wrapper paths | wrappers force incremental=0 and lost those cells (body 255 ms, sig 1416 ms) |

## Which steps did not help (on this pair)

| Step | Result |
| --- | --- |
| `sccache` + `CARGO_INCREMENTAL=1` | compile failed (`ok=false`); do not stack incremental rustc with sccache here |
| `nanocompile` on incremental body/sig | slower (255 / 1416 ms) because the wrapper disables rustc incremental |
| `quiet` (`cargo -q`) | <3% (body 128 ms, sig 716 ms) |
| explicit `codegen-units=256` | <3% vs default dev units (body 123 ms) |
| `codegen-units=1` | no win (body 128 ms) |
| `CARGO_INCREMENTAL=0` without a cache | body 238 ms, worse |
| mold / lld | only apply to `build`/`test`; those loops lost to `cargo check` (cold build ~7.6 s vs check 3.4–4.5 s; noop build 36–45 ms vs check 31 ms) |
| cranelift nightly dev backend | cold build 7120 ms, noop 44 ms — lost to check; not allowed on validate |
| declared `fast-check` → `validate` graph (`nanocompile task`) | failed on these trees (spec/task + full `cargo test` is the wrong fitness for a large workspace). Skipped in held-out re-runs |

No `tools/rust_loop.py` change is landed. The only measured incremental-loop
win that could become a helper flag is `--package` / touched-crate scope for
`sig_dep`. That is a genome gene in this shard, not a rewrite of the shared
helper the other agent owns.

## Correctness

On a deliberate type error in the leaf function:

| Check | ripgrep | tokio |
| --- | --- | --- |
| `cargo check` fails | yes | yes |
| `rust_loop.py run --step validate` fails (no `validate.ok`) | yes | yes |
| validate refuses `CARGO_PROFILE_DEV_CODEGEN_BACKEND=cranelift` | yes | yes |
| fast path and rustc agree (both fail) | **yes** | **yes** |

A successful fast path is never recorded as the gate.

## Held-out cross-test

Unchanged elites from `bench/map_elites.json` (trained on `examples/rust-loop`
and `examples/rust-loop-medium`) were evaluated on ripgrep+tokio. Graph elites
were not re-run: the declared graph executes full `cargo test` via
`nanocompile task`, which is not a fair large-workspace iteration loop.

| Trained cell | Trained on | Held-out ms (ripgrep+tokio) | Local large elite ms | Δ vs local |
| --- | --- | ---: | ---: | ---: |
| `small\|cold` | rust-loop | 3909 | 1387 | **+182%** (worse) |
| `small\|noop` | rust-loop | skipped (graph) | 31.2 | — |
| `small\|body` | rust-loop | 246 | 122 | **+102%** (`incremental=false`) |
| `small\|sig_dep` | rust-loop | 1561 | 530 | **+195%** (no `-p` hub) |
| `mid\|cold` | rust-loop-medium | 4212 | 1387 | **+204%** |
| `mid\|noop` | rust-loop-medium | skipped (graph) | 31.2 | — |
| `mid\|body` | rust-loop-medium | 134 | 122 | +10% (closest transfer) |
| `mid\|sig_dep` | rust-loop-medium | 1659 | 530 | **+213%** |

Tiny-fixture elites do **not** transfer to these codebases. The mid-body
genome (`cargo check`, incremental on, LLVM) is the same family as our
baseline and lands within ~10%. Everything that won on a 1-crate or 3-crate
tree by turning incremental off, or by using the declared graph, loses here.

## Hill-climb / MAP-Elites log

Seeds: baseline and the usable-now steps, then 1–2 gene mutations of each
cell elite. Full history is `raw/history.csv` and `bench/archive/midsize.json`.

| Iter | Cell | Hypothesis | Result | Keep? |
| --- | --- | --- | --- | --- |
| 0 | all | baseline `cargo check` | cold 4467 / noop 33 / body 127 / sig 777 | seed |
| 1 | cold, noop | nanocompile wrapper | cold 3388, noop 31.2 | yes (both) |
| 2 | body, sig | nanocompile wrapper | 255 / 1416 | no |
| 3 | all | sccache + incremental | compile fail | no |
| 4 | body, sig, cold | line-tables-only | body 122, sig 712, cold 4285 | body+sig yes |
| 5 | sig | `-p` touched hub | 530 | yes |
| 6 | body | quiet / incremental=0 / cgu=256 | 128 / 238 / 123 | no |
| 7 | cold/noop | mold, lld, cranelift, disk-hygiene build | 7–8 s cold build; 36–45 ms noop | no |
| 8 | cold | mutate: sccache + incremental=0 | 2988 (within noise), then **1387** | yes |
| 9 | all | four further mutants each | all <3% or slower | stop |

Every cell stopped after four consecutive <3% / within-noise tries.

## What failed

- Official `bench/rust_loop_bench` on full `cargo test` for ripgrep (serial
  integration tests) was aborted; MAP-Elites uses `cargo check` as the
  iteration loop and `cargo test --no-run` only on the validate gate.
- `sccache` + rustc incremental: broken on these trees.
- Declared-task graph: not usable as a large-workspace fitness (full test
  suite + huge input hashing).
- Canonical `bench/map_elites.json` was not present when this search started;
  the shard was rewritten to schema 1 after `19fa491` landed. This PR does
  **not** merge into the canonical file.

## Reproduce

```sh
# clones were at /tmp/midsize-scratch/samples/{ripgrep,tokio} on the bench host
python3 tools/map_elites.py validate bench/archive/midsize.json
python3 tools/map_elites.py classify path/to/ripgrep   # large
python3 tools/map_elites.py classify path/to/tokio     # large
# merge is owned by the rust-iteration branch:
# python3 tools/map_elites.py merge --into bench/map_elites.json bench/archive/*.json
```
