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
CARGO_INCREMENTAL = { value = "1", force = true }
NANOCOMPILE_ALLOW_INCREMENTAL = { value = "1", force = true }
NANOCOMPILE_EXECUTABLE_PRODUCERS = { value = "1", force = true }
NANOCOMPILE_PROC_MACROS = { value = "reported", force = true }
NANOCOMPILE_PROC_MACRO_PRODUCERS = { value = "1", force = true }
```

Do not stack `RUSTC_WRAPPER=nanocompile` with sccache or kache.

## Hill-climb (train = axum + ripgrep)

One lever at a time. Keep a change only when it beats the previous elite
by more than 3% on crates compiled per worktree, total wall, or disk
(hardlinks counted once). Stop a metric after it stalls.

| lever | vs | crates/worktree | wall | disk | keep |
| --- | --- | --- | --- | --- | --- |
| `l0_nano_best` | none | 55.0% | 32.6% | -1.1% | yes |
| `l1_script_cache` | l0_nano_best | -1.3% | 0.7% | -82.2% | stall |
| `l2_test_bins` | coverage | n/a | n/a | n/a | coverage |

cargo test --no-run coverage; --test is eligible under EXECUTABLE_PRODUCERS. No prior test-loop elite to beat by 3%.


Frozen lever: `l0_nano_best`.

## Generalization (held-out)

Config was frozen on axum+ripgrep, then run unchanged on bhumi, hashbrown,
nalgebra, serde, ruff, and tokio (Rach repo).

| metric | train gain vs none | held-out gain vs none | fraction that survived |
| --- | --- | --- | --- |
| crates_compiled_mean | 54.6% | 61.4% | 112.5% |
| disk_bytes | -1.1% | 1.7% | n/a |
| wall_ms | 39.5% | 30.8% | 78.0% |

### Repo-specific vs general

Settings that kept at least half the train wall-time gain on a held-out
repo are treated as **general**. The rest are **repo-specific**; we still
ship the general config.

- general: ruff, tokio, nalgebra, bhumi
- repo-specific: serde, hashbrown

### Where the shared store breaks

Held-out variants: 8 worktrees, larger edits (several files), worktrees
branching from an older main. Shared-target (one `CARGO_TARGET_DIR`) is
the lock-contention control.

| sample | n | edit | older main | approach | crates/wt | wall ms | disk | ok |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bhumi | 4 | mixed | False | none | 120.0 | 39461 | 1521245700 | yes |
| bhumi | 4 | mixed | False | kache | 0.0 | 1763 | 1715163481 | yes |
| bhumi | 4 | mixed | False | nanocompile | 35.5 | 14424 | 1275633093 | yes |
| hashbrown | 4 | mixed | False | none | 4.0 | 1971 | 41304411 | yes |
| hashbrown | 4 | mixed | False | kache | 0.5 | 991 | 8169531 | yes |
| hashbrown | 4 | mixed | False | nanocompile | 1.8 | 1684 | 45098324 | yes |
| nalgebra | 4 | mixed | False | none | 20.0 | 24768 | 731524979 | yes |
| nalgebra | 4 | mixed | False | kache | 0.5 | 7530 | 451819598 | yes |
| nalgebra | 4 | mixed | False | nanocompile | 8.0 | 18155 | 754355649 | yes |
| serde | 4 | mixed | False | none | 2.0 | 6201 | 235840300 | yes |
| serde | 4 | mixed | False | kache | 0.5 | 1454 | 94180689 | yes |
| serde | 4 | mixed | False | nanocompile | 4.0 | 6345 | 261914635 | yes |
| ruff | 4 | mixed | False | none | 313.0 | 167845 | 5959580465 | yes |
| ruff | 4 | mixed | False | kache | 5.0 | 88058 | 4246942267 | yes |
| ruff | 4 | mixed | False | nanocompile | 127.0 | 123959 | 5923610158 | yes |
| tokio | 4 | mixed | False | none | 19.0 | 19279 | 547789878 | yes |
| tokio | 4 | mixed | False | kache | 0.5 | 6440 | 319470485 | yes |
| tokio | 4 | mixed | False | nanocompile | 8.2 | 14993 | 626518255 | yes |
| bhumi | 8 | mixed | False | nanocompile | 18.8 | 20508 | 1734223975 | yes |
| bhumi | 4 | large | False | nanocompile | 35.5 | 14848 | 1275834349 | yes |
| bhumi | 4 | mixed | True | nanocompile | 35.5 | 14281 | 1275747577 | yes |
| hashbrown | 8 | mixed | False | nanocompile | 1.4 | 3276 | 79890280 | yes |
| hashbrown | 4 | large | False | nanocompile | 1.8 | 1704 | 45111553 | yes |
| hashbrown | 4 | None | None | None |  |  |  | no |
| nalgebra | 8 | mixed | False | nanocompile | 5.0 | 34036 | 1245116390 | yes |
| nalgebra | 4 | large | False | nanocompile | 8.2 | 19506 | 763684687 | yes |
| nalgebra | 4 | mixed | True | nanocompile | 8.0 | 19096 | 754376508 | yes |
| serde | 8 | mixed | False | nanocompile | 4.0 | 12852 | 463891593 | yes |
| serde | 4 | large | False | nanocompile | 4.0 | 6337 | 261997048 | yes |
| serde | 4 | mixed | True | nanocompile | 4.0 | 6616 | 261920736 | yes |
| ruff | 8 | mixed | False | nanocompile | 86.0 | 226909 | 9417014499 | yes |
| ruff | 4 | large | False | nanocompile | 127.0 | 122475 | 5927308403 | yes |
| ruff | 4 | mixed | True | nanocompile | 127.0 | 124330 | 5925848409 | yes |
| tokio | 8 | mixed | False | nanocompile | 5.8 | 29382 | 1089032691 | yes |
| tokio | 4 | large | False | nanocompile | 8.2 | 15147 | 626598534 | yes |
| tokio | 4 | mixed | True | nanocompile | 1.2 | 1711 | 174441251 | yes |

## Train table (4 worktrees, sequential + concurrent)

| sample | lever | approach | n | mode | crates/wt | wall ms | disk | ok |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| axum | none | none | 4 | sequential | 51.0 | 28854 | 792034485 | yes |
| axum | none | none | 4 | concurrent | 51.0 | 18575 | 792034488 | yes |
| axum | shared_target | shared_target | 4 | sequential | 0.5 | 3212 | 158411085 | yes |
| axum | shared_target | shared_target | 4 | concurrent | 0.5 | 4073 | 158411079 | yes |
| axum | kache | kache | 4 | sequential | 1.0 | 6529 | 617820903 | yes |
| axum | kache | kache | 4 | concurrent | 1.0 | 3557 | 561252126 | yes |
| axum | l0_nano_best | nanocompile | 4 | sequential | 19.8 | 19903 | 781952740 | yes |
| axum | l0_nano_best | nanocompile | 4 | concurrent | 20.2 | 9792 | 780955066 | yes |
| axum | l1_script_cache | nanocompile | 4 | sequential | 19.5 | 19767 | 1296551582 | yes |
| axum | l1_script_cache | nanocompile | 4 | concurrent | 20.5 | 10511 | 1296884408 | yes |
| axum | l2_test_bins | nanocompile | 4 | sequential | 63.2 | 83205 | 9073244086 | yes |
| axum | l2_test_bins | nanocompile | 4 | concurrent | 62.8 | 56321 | 9014383787 | yes |
| ripgrep | none | none | 4 | sequential | 34.0 | 12077 | 514429975 | yes |
| ripgrep | none | none | 4 | concurrent | 34.0 | 9976 | 514429973 | yes |
| ripgrep | shared_target | shared_target | 4 | sequential | 1.0 | 1398 | 102888800 | yes |
| ripgrep | shared_target | shared_target | 4 | concurrent | 0.8 | 898 | 102888879 | yes |
| ripgrep | kache | kache | 4 | sequential | 1.2 | 2209 | 433646262 | yes |
| ripgrep | kache | kache | 4 | concurrent | 1.2 | 1042 | 391688410 | yes |
| ripgrep | l0_nano_best | nanocompile | 4 | sequential | 18.5 | 7688 | 539011125 | yes |
| ripgrep | l0_nano_best | nanocompile | 4 | concurrent | 18.8 | 4658 | 539414439 | yes |
| ripgrep | l1_script_cache | nanocompile | 4 | sequential | 19.2 | 7627 | 1110875185 | yes |
| ripgrep | l1_script_cache | nanocompile | 4 | concurrent | 19.5 | 4641 | 1110182180 | yes |
| ripgrep | l2_test_bins | nanocompile | 4 | sequential | 24.0 | 21374 | 3815814170 | yes |
| ripgrep | l2_test_bins | nanocompile | 4 | concurrent | 24.2 | 19130 | 3833845741 | yes |

## What climbed

- **L0** nanocompile best (incremental + reported proc-macros + executable
  producers + path-normalized logical restore) vs none / shared-target / kache.
- **L1** default-safe build-script RUN cache (`NANOCOMPILE_BUILD_SCRIPT_CACHE=1`).
  Key is `nano-build-script-default-v1`: binary digest + `CARGO_PKG_*` /
  `CARGO_FEATURE_*` / `CARGO_CFG_*` / `TARGET` / `HOST` / `OPT_LEVEL` /
  `DEBUG` / `PROFILE` + rustc fingerprint. `OUT_DIR`, cwd, and
  `CARGO_MANIFEST_DIR` stay out of the key so sibling worktrees hit.
  After a miss, `cargo:rerun-if-changed` / `rerun-if-env-changed` are
  parsed and checked on restore. Nested `OUT_DIR` files are stored.
  Concurrent agents take an exclusive per-key lock; entries stay atomic.
- **L2** `--test` is a cacheable executable when
  `NANOCOMPILE_EXECUTABLE_PRODUCERS=1` (cargo test harnesses).

Harness: `bench/agent_worktrees.py`. Raw rows: `bench/archive/agent-worktrees.json`.
