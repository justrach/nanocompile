# Agent worktrees

Use nanocompile so a main checkout plus N git worktrees (one per coding agent)
compile as little as possible. Each worktree has its own `CARGO_TARGET_DIR`.
One shared `NANOCOMPILE_DIR` restores everything main or a sibling already
compiled. Only crates the worktree's own edit invalidates should miss.

Occupancy of the size × edit MAP-Elites grid is unchanged. These rows are
tagged `split=train|held_out` in `bench/map_elites.json` → `agent_worktrees`.

## Setup Rach should use

```sh
zig build -Doptimize=ReleaseFast
./zig-out/bin/nanocompile worktree init
git worktree add --detach ../agent-1
git worktree add --detach ../agent-2
# each worktree keeps target/; the store is shared
cargo check
```

`worktree init` writes `.cargo/config.toml` with the **general** frozen
config (not per-repo knobs):

```toml
[build]
rustc-wrapper = "/absolute/path/nanocompile"

[env]
NANOCOMPILE_DIR = { value = "$XDG_CACHE_HOME/nanocompile", force = true }
CARGO_INCREMENTAL = { value = "0", force = true }
NANOCOMPILE_ALLOW_INCREMENTAL = { value = "1", force = true }
NANOCOMPILE_EXECUTABLE_PRODUCERS = { value = "1", force = true }
NANOCOMPILE_HARDLINK_TARGET = { value = "1", force = true }
NANOCOMPILE_NO_VARIANTS = { value = "1", force = true }
NANOCOMPILE_PROC_MACROS = { value = "reported", force = true }
NANOCOMPILE_PROC_MACRO_PRODUCERS = { value = "1", force = true }
NANOCOMPILE_REMAP_PATHS = { value = "1", force = true }
```

Do not stack `RUSTC_WRAPPER=nanocompile` with sccache or kache.

## Hill-climb (train = axum + ripgrep)

One lever at a time. Keep a change only when it beats the previous elite
by more than 3% on crates compiled per worktree, total wall, unique disk
(hardlinks counted once), or store size, and does not regress another
objective past 3%. Stop a metric after it stalls.

| lever | vs | crates/worktree | wall | disk | store | keep | note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `l0_nano_best` | none | n/a | n/a | n/a | n/a | yes | workspace-logical keys + reported proc-macros + executable producers |
| `l3_hardlink_target` | l0_nano_best | n/a | n/a | n/a | n/a | yes |  |
| `l5_no_incremental` | l3_hardlink_target | n/a | n/a | n/a | n/a | yes |  |
| `l12_no_variants` | l5_no_incremental | n/a | n/a | n/a | n/a | yes |  |
| `l14_slim_graph` | l12_no_variants | n/a | n/a | n/a | n/a | yes | Skip empty -L prefix guards; unique dependency records. Ruff entries 244MB -> ~1MB. |
| `l20_remap_paths` | l14_slim_graph | 0.0% | 1.8% | 9.2% | 9.6% | yes | Train disk -12% axum / -6% ripgrep via rustc --remap-path-prefix. |

Frozen lever: `frozen`.

## Generalization (held-out)

Config was frozen on axum+ripgrep, then run unchanged on bhumi, hashbrown,
nalgebra, serde, ruff, tokio, and emergentDB (Rach's repo; tokio is not).

| metric | train gain vs none | held-out gain vs none | fraction that survived |
| --- | --- | --- | --- |
| crates_compiled_mean | 62.3% | 57.2% | 92.0% |
| disk_bytes | 85.5% | 81.8% | 95.8% |
| store_bytes | n/a | n/a | n/a |
| wall_ms | 54.6% | 38.4% | 70.3% |

### Repo-specific vs general

Settings that kept at least half the train wall-time gain on a held-out
repo are treated as **general**. The rest are **repo-specific**; we still
ship the general config.

- general: nalgebra, ruff, emergentDB, tokio
- repo-specific: hashbrown, serde

### Where the shared store breaks

Held-out variants: 8 worktrees, larger edits (several files), worktrees
branching from an older main. Shared-target (one `CARGO_TARGET_DIR`) is
the lock-contention control.

| sample | n | edit | older main | approach | crates/wt | wall ms | disk | store | ok |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bhumi | 4 | None | None | None |  |  |  |  | no |
| bhumi | 4 | mixed | False | shared_target | 0.2 | 679 | 301503851 | 0 | yes |
| bhumi | 4 | mixed | False | kache | 0.0 | 4355 | 4590479442 | 48866938 | yes |
| bhumi | 4 | mixed | False | sccache | 120.0 | 54219 | 1182501458 | 0 | yes |
| bhumi | 4 | mixed | False | nanocompile | 36.0 | 18823 | 299270183 | 275175877 | yes |
| hashbrown | 4 | mixed | False | none | 4.0 | 2404 | 33046600 | 0 | yes |
| hashbrown | 4 | mixed | False | shared_target | 0.2 | 461 | 8261952 | 0 | yes |
| hashbrown | 4 | mixed | False | kache | 1.2 | 1392 | 6638859 | 3307801 | yes |
| hashbrown | 4 | mixed | False | sccache | 4.0 | 2543 | 5623064 | 0 | yes |
| hashbrown | 4 | mixed | False | nanocompile | 1.8 | 1822 | 2532352 | 2527657 | yes |
| nalgebra | 4 | mixed | False | none | 20.0 | 29713 | 583295707 | 0 | yes |
| nalgebra | 4 | mixed | False | shared_target | 0.2 | 4524 | 145827028 | 0 | yes |
| nalgebra | 4 | mixed | False | kache | 7.8 | 13141 | 372020513 | 88811710 | yes |
| nalgebra | 4 | mixed | False | sccache | 20.0 | 30676 | 308572712 | 0 | yes |
| nalgebra | 4 | mixed | False | nanocompile | 8.2 | 20310 | 84529916 | 84494045 | yes |
| serde | 4 | mixed | False | none | 2.0 | 7571 | 188334026 | 0 | yes |
| serde | 4 | mixed | False | shared_target | 0.2 | 393 | 47084150 | 0 | yes |
| serde | 4 | mixed | False | kache | 1.8 | 3198 | 82071888 | 16356834 | yes |
| serde | 4 | mixed | False | sccache | 2.0 | 7243 | 50562768 | 0 | yes |
| serde | 4 | mixed | False | nanocompile | 4.0 | 6339 | 13355434 | 13346819 | yes |
| ruff | 4 | mixed | False | none | 313.0 | 190774 | 4742876358 | 0 | yes |
| ruff | 4 | mixed | False | shared_target | 1.0 | 4596 | 1185761641 | 0 | yes |
| ruff | 4 | mixed | False | kache | 103.5 | 118888 | 3457471756 | 819599267 | yes |
| ruff | 4 | mixed | False | sccache | 313.0 | 196134 | 2884290543 | 0 | yes |
| ruff | 4 | mixed | False | nanocompile | 127.8 | 124216 | 794872899 | 679381619 | yes |
| tokio | 4 | mixed | False | none | 19.0 | 20664 | 436882601 | 0 | yes |
| tokio | 4 | mixed | False | shared_target | 0.2 | 2967 | 109226449 | 0 | yes |
| tokio | 4 | mixed | False | kache | 7.0 | 9285 | 265003809 | 66814682 | yes |
| tokio | 4 | mixed | False | sccache | 19.0 | 21164 | 212067438 | 0 | yes |
| tokio | 4 | mixed | False | nanocompile | 8.5 | 14923 | 62163951 | 58122920 | yes |
| emergentDB | 4 | mixed | False | none | 53.0 | 22261 | 582195312 | 0 | yes |
| emergentDB | 4 | mixed | False | shared_target | 0.0 | 302 | 145550858 | 0 | yes |
| emergentDB | 4 | mixed | False | kache | 19.8 | 7593 | 651949453 | 136991520 | yes |
| emergentDB | 4 | mixed | False | sccache | 53.0 | 23983 | 528271852 | 0 | yes |
| emergentDB | 4 | mixed | False | nanocompile | 18.8 | 10184 | 133791754 | 130119246 | yes |

## Pareto frontier (minimize crates, wall, unique disk, store)

A config is non-dominated when no competitor is better or equal on every
objective and strictly better on one. Shipped `worktree init` must sit on
the held-out frontier for every repo.

### Train

**axum** — nanocompile on frontier: yes

| approach | lever | crates/wt | wall ms | disk | store |
| --- | --- | --- | --- | --- | --- |
| shared_target | shared_target | 0.5 | 3454 | 157767267 | 0 |
| nanocompile | frozen | 20.0 | 20746 | 111392465 | 107322059 |

**ripgrep** — nanocompile on frontier: yes

| approach | lever | crates/wt | wall ms | disk | store |
| --- | --- | --- | --- | --- | --- |
| shared_target | shared_target | 1.0 | 1611 | 102451447 | 0 |
| nanocompile | frozen | 18.5 | 7190 | 72101212 | 68369982 |

### Held-out

**bhumi** — nanocompile on frontier: yes

| approach | lever | crates/wt | wall ms | disk | store |
| --- | --- | --- | --- | --- | --- |
| shared_target | shared_target | 0.2 | 679 | 301503851 | 0 |
| kache | kache | 0.0 | 4355 | 4590479442 | 48866938 |
| nanocompile | frozen | 36.0 | 18823 | 299270183 | 275175877 |

**emergentDB** — nanocompile on frontier: yes

| approach | lever | crates/wt | wall ms | disk | store |
| --- | --- | --- | --- | --- | --- |
| shared_target | shared_target | 0.0 | 302 | 145550858 | 0 |
| nanocompile | frozen | 18.8 | 10184 | 133791754 | 130119246 |

**hashbrown** — nanocompile on frontier: yes

| approach | lever | crates/wt | wall ms | disk | store |
| --- | --- | --- | --- | --- | --- |
| shared_target | shared_target | 0.2 | 461 | 8261952 | 0 |
| kache | kache | 1.2 | 1392 | 6638859 | 3307801 |
| sccache | sccache | 4.0 | 2543 | 5623064 | 0 |
| nanocompile | frozen | 1.8 | 1822 | 2532352 | 2527657 |

**nalgebra** — nanocompile on frontier: yes

| approach | lever | crates/wt | wall ms | disk | store |
| --- | --- | --- | --- | --- | --- |
| shared_target | shared_target | 0.2 | 4524 | 145827028 | 0 |
| nanocompile | frozen | 8.2 | 20310 | 84529916 | 84494045 |

**ruff** — nanocompile on frontier: yes

| approach | lever | crates/wt | wall ms | disk | store |
| --- | --- | --- | --- | --- | --- |
| shared_target | shared_target | 1.0 | 4596 | 1185761641 | 0 |
| nanocompile | frozen | 127.8 | 124216 | 794872899 | 679381619 |

**serde** — nanocompile on frontier: yes

| approach | lever | crates/wt | wall ms | disk | store |
| --- | --- | --- | --- | --- | --- |
| shared_target | shared_target | 0.2 | 393 | 47084150 | 0 |
| nanocompile | frozen | 4.0 | 6339 | 13355434 | 13346819 |

**tokio** — nanocompile on frontier: yes

| approach | lever | crates/wt | wall ms | disk | store |
| --- | --- | --- | --- | --- | --- |
| shared_target | shared_target | 0.2 | 2967 | 109226449 | 0 |
| nanocompile | frozen | 8.5 | 14923 | 62163951 | 58122920 |


## Train table (4 worktrees, sequential + concurrent)

| sample | lever | approach | n | mode | crates/wt | wall ms | disk | store | ok |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| axum | none | none | 4 | sequential | 51.0 | 30744 | 631055157 | 0 | yes |
| axum | shared_target | shared_target | 4 | sequential | 0.5 | 3454 | 157767267 | 0 | yes |
| axum | kache | kache | 4 | sequential | 18.5 | 13249 | 509315624 | 114904790 | yes |
| axum | sccache | sccache | 4 | sequential | 51.0 | 34043 | 476398235 | 58538823 | yes |
| axum | frozen | nanocompile | 4 | sequential | 20.0 | 20746 | 111392465 | 107322059 | yes |
| ripgrep | none | none | 4 | sequential | 34.0 | 13540 | 409797233 | 0 | no |
| ripgrep | shared_target | shared_target | 4 | sequential | 1.0 | 1611 | 102451447 | 0 | yes |
| ripgrep | kache | kache | 4 | sequential | 3.2 | 4507 | 2579098072 | 11235295 | yes |
| ripgrep | sccache | sccache | 4 | sequential | 34.0 | 13637 | 283858704 | 0 | yes |
| ripgrep | frozen | nanocompile | 4 | sequential | 18.5 | 7190 | 72101212 | 68369982 | yes |

## What climbed

- **L0** workspace-logical keys (`$NANO_MANIFEST` / `$NANO_WORKSPACE`) so
  sibling worktrees share rustc identities. Incremental + reported
  proc-macros + executable producers. Jobserver env and `PWD` are not
  part of the key.
- **L3** `NANOCOMPILE_HARDLINK_TARGET=1`: after store, replace immutable
  `.rlib`/`.rmeta`/`.so`/`.a`/bins in `target/` with a hardlink to the CAS blob.
- **L5** `CARGO_INCREMENTAL=0` to drop per-worktree incremental dirs.
- **L12** `NANOCOMPILE_NO_VARIANTS=1`: write-once entries (no 3-slot history).
- **L13/L14** unique dependency records + skip empty `-L` prefix guards so
  fat graphs (ruff) stop storing the same directory 200+ times.
- **L16** `nanocompile worktree seed`: hardlink a warm target into a new
  worktree (immutable) before cargo runs.
- **L17** `nanocompile worktree gc`: drop store blobs the live targets no
  longer materialize (working set of N worktrees).
- **L18** `worktree dedup` includes the store so leftover copies collapse.
- **L20** `NANOCOMPILE_REMAP_PATHS=1`: `--remap-path-prefix` so rustc
  embeds logical `$NANO_*` paths and sibling rmetas share one blob.

Stalled or discarded: zstd-on-hot-blobs (inflates unique disk vs hardlink),
debuginfo=1/0 (regressed train disk), build-script RUN cache (+82% disk),
RUSTFLAGS=-Cdebuginfo=0 (did not reach bypassed openssl-sys leftover).

Competitors on the same chart: no cache, shared `CARGO_TARGET_DIR`, kache,
sccache (if it runs), and every nanocompile config tried.

Harness: `bench/agent_worktrees.py`. Raw rows: `bench/archive/agent-worktrees.json`.
