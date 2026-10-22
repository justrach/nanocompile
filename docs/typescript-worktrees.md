# TypeScript agent worktrees

MAP-Elites cells are **checker × scenario**. Each cell keeps a Pareto
set over wall time, files re-checked, store size, unique disk, and peak
RSS. Injected type errors are a hard gate: a false hit cannot occupy.

Checkers: `tsc` 5.9.3, TypeScript 7 (`tsgo`), `tsrs --checkers 4`, `bun check`.
Scenarios: cold worktree off warm main; leaf-file edit; shared-types edit;
tsconfig/config change; 3–4 worktrees checking concurrently.

Setup uses real `git worktree add` off a warm main. `node_modules` is a
**symlink to main's install** (one copy; unique disk counts that inode
set once). `nanocompile worktree init` writes `.cargo/config.toml` and
`.nanocompile/{env,bin/tsc,tsgo,tsrs,bun}` so a new worktree uses the
same shared `NANOCOMPILE_DIR`.

condensation-site is the intended train repo. This environment cannot
clone that private tree, so train is **condensation-standin** (126-file
public stand-in) with the same checker × scenario grid. Re-run on the
real app with:

```sh
python3 bench/ts_worktrees.py --repo /path/to/condensation-site --phase all
python3 bench/ts_worktrees.py --repo /path/to/any-ts-app --phase all
```

vite (github.com/vitejs/vite) is a pnpm-only monorepo with no root tsconfig; typecheck is workspace-wide. Held-out is ajv + prettier. Re-run with `python3 bench/ts_worktrees.py --repo /path/to/vite-app`.

## Frozen vs baselines (checker × scenario)

Shipped lever vs `none` / `incremental_local`. **front** = honest win:
strictly better on ≥1 objective and wall not worse beyond 3% noise.
Pareto non-domination alone is not a win when wall is equal or slower.

| split | cell | front | wall nano/none | files nano/none | store | disk nano/none | rss nano/none | correct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | condensation-standin/tsc|cold | yes | 4 / 395 | 0.0 / 126.0 | 67795 | 336138 / 316583 | 3540 / 154636 | yes |
| train | condensation-standin/tsc|leaf | yes | 370 / 372 | 1.0 / 126.0 | 97618 | 365961 / 316674 | 154096 / 154724 | yes |
| train | condensation-standin/tsc|shared | yes | 395 / 416 | 1.0 / 126.0 | 127532 | 395875 / 316765 | 155736 / 153984 | yes |
| train | condensation-standin/tsc|tsconfig | NO | 368 / 348 | 1.0 / 126.0 | 157446 | 425789 / 316765 | 155308 / 151076 | yes |
| train | condensation-standin/tsc|concurrent | yes | 9 / 812 | 0.0 / 126.0 | 157490 | 425833 / 316765 | 3472 / 152640 | yes |
| train | condensation-standin/tsgo|cold | yes | 4 / 72 | 0.0 / 126.0 | 57612 | 325977 / 265690 | 3472 / 51216 | yes |
| train | condensation-standin/tsgo|leaf | NO | 82 / 74 | 1.0 / 126.0 | 77242 | 345607 / 265771 | 51156 / 51540 | yes |
| train | condensation-standin/tsgo|shared | NO | 80 / 70 | 1.0 / 126.0 | 96953 | 365318 / 265852 | 51468 / 50444 | yes |
| train | condensation-standin/tsgo|tsconfig | yes | 78 / 76 | 1.0 / 126.0 | 116664 | 385029 / 265852 | 51156 / 49492 | yes |
| train | condensation-standin/tsgo|concurrent | yes | 10 / 129 | 0.0 / 126.0 | 116708 | 385073 / 265852 | 3472 / 51088 | yes |
| train | condensation-standin/tsrs|cold | yes | 4 / 45 | 0.0 / 126.0 | 58103 | 326468 / 268145 | 3472 / 47160 | yes |
| train | condensation-standin/tsrs|leaf | NO | 51 / 44 | 1.0 / 126.0 | 78224 | 346589 / 268226 | 47364 / 47156 | yes |
| train | condensation-standin/tsrs|shared | yes | 48 / 51 | 1.0 / 126.0 | 98426 | 366791 / 268307 | 47368 / 47156 | yes |
| train | condensation-standin/tsrs|tsconfig | NO | 49 / 42 | 1.0 / 126.0 | 118628 | 386993 / 268307 | 47376 / 47144 | yes |
| train | condensation-standin/tsrs|concurrent | yes | 10 / 65 | 0.0 / 126.0 | 118672 | 387037 / 268307 | 3600 / 47124 | yes |
| train | condensation-standin/bun|cold | yes | 5 / 33 | 0.0 / 126.0 | 37801 | 306144 / 268123 | 5056 / 58992 | yes |
| train | condensation-standin/bun|leaf | NO | 42 / 32 | 1.0 / 126.0 | 37853 | 306196 / 268123 | 57200 / 57904 | yes |
| train | condensation-standin/bun|shared | NO | 41 / 31 | 1.0 / 126.0 | 37905 | 306248 / 268123 | 56512 / 58412 | yes |
| train | condensation-standin/bun|tsconfig | NO | 40 / 32 | 1.0 / 126.0 | 37957 | 306300 / 268123 | 55284 / 58296 | yes |
| train | condensation-standin/bun|concurrent | yes | 12 / 54 | 0.0 / 126.0 | 38001 | 306344 / 268123 | 5056 / 57660 | yes |
| held_out | ajv/tsc|cold | yes | 7 / 1210 | 0.0 / 106.0 | 113605 | 204668367 / 204554718 | 3728 / 239164 | yes |
| held_out | ajv/tsc|leaf | yes | 622 / 1217 | 1.0 / 106.0 | 163698 | 204718460 / 204554718 | 206716 / 240532 | yes |
| held_out | ajv/tsc|shared | yes | 725 / 1237 | 1.0 / 106.0 | 214155 | 204768917 / 204554718 | 215948 / 238704 | yes |
| held_out | ajv/tsc|tsconfig | yes | 647 / 1240 | 1.0 / 106.0 | 264612 | 204819374 / 204554718 | 210728 / 238692 | yes |
| held_out | ajv/tsc|concurrent | yes | 17 / 3047 | 0.0 / 106.0 | 264656 | 204819418 / 204554718 | 3600 / 238432 | yes |
| held_out | prettier/tsc|cold | yes | 34 / 18622 | 0.0 / 494.0 | 711873 | 461662572 / 460950655 | 4496 / 1222960 | yes |
| held_out | prettier/tsc|leaf | yes | 4110 / 18373 | 1.0 / 494.0 | 1242555 | 462193254 / 460950655 | 544384 / 1222996 | yes |
| held_out | prettier/tsc|shared | yes | 2981 / 18055 | 1.0 / 494.0 | 1774659 | 462725358 / 460950655 | 509036 / 1219512 | yes |
| held_out | prettier/tsc|tsconfig | yes | 2205 / 18342 | 1.0 / 494.0 | 2306763 | 463257462 / 460950655 | 468556 / 1218108 | yes |
| held_out | prettier/tsc|concurrent | yes | 45 / 26602 | 0.0 / 494.0 | 2306807 | 463257506 / 460950655 | 4496 / 1226132 | yes |
| held_out | ajv/tsgo|cold | yes | 7 / 139 | 0.0 / 106.0 | 143046 | 204697985 / 204554895 | 3728 / 110420 | yes |
| held_out | ajv/tsgo|leaf | yes | 134 / 147 | 1.0 / 106.0 | 221389 | 204776328 / 204554895 | 88212 / 108816 | yes |
| held_out | ajv/tsgo|shared | yes | 125 / 151 | 1.0 / 106.0 | 300056 | 204854995 / 204554895 | 93072 / 109072 | yes |
| held_out | ajv/tsgo|tsconfig | yes | 131 / 137 | 1.0 / 106.0 | 378723 | 204933662 / 204554895 | 87376 / 109328 | yes |
| held_out | ajv/tsgo|concurrent | yes | 16 / 382 | 0.0 / 106.0 | 378767 | 204933706 / 204554895 | 3668 / 111124 | yes |
| held_out | prettier/tsgo|cold | yes | 32 / 4710 | 0.0 / 494.0 | 1123754 | 462074635 / 460950837 | 4880 / 1555180 | yes |
| held_out | prettier/tsgo|leaf | yes | 973 / 4516 | 1.0 / 494.0 | 1967635 | 462918516 / 460950837 | 369152 / 1472392 | yes |
| held_out | prettier/tsgo|shared | yes | 1063 / 4649 | 1.0 / 494.0 | 2812362 | 463763243 / 460950837 | 408720 / 1480412 | yes |
| held_out | prettier/tsgo|tsconfig | yes | 545 / 4652 | 1.0 / 494.0 | 3657089 | 464607970 / 460950837 | 321292 / 1467624 | yes |
| held_out | prettier/tsgo|concurrent | yes | 43 / 11996 | 0.0 / 494.0 | 3657133 | 464608014 / 460950837 | 4752 / 1519464 | yes |
| held_out | ajv/tsrs|cold | yes | 7 / 58 | 0.0 / 106.0 | 143118 | 204698057 / 204554895 | 3728 / 53884 | yes |
| held_out | ajv/tsrs|leaf | NO | 63 / 60 | 1.0 / 106.0 | 221533 | 204776472 / 204554895 | 58152 / 53980 | yes |
| held_out | ajv/tsrs|shared | yes | 64 / 63 | 1.0 / 106.0 | 300272 | 204855211 / 204554895 | 56456 / 53700 | yes |
| held_out | ajv/tsrs|tsconfig | NO | 69 / 54 | 1.0 / 106.0 | 379011 | 204933950 / 204554895 | 57456 / 53672 | yes |
| held_out | ajv/tsrs|concurrent | yes | 14 / 126 | 0.0 / 106.0 | 379055 | 204933994 / 204554895 | 3668 / 53932 | yes |
| held_out | prettier/tsrs|cold | yes | 32 / 754 | 0.0 / 494.0 | 1124267 | 462075148 / 460950837 | 4880 / 368528 | yes |
| held_out | prettier/tsrs|leaf | yes | 296 / 756 | 1.0 / 494.0 | 1968670 | 462919551 / 460950837 | 149156 / 369748 | yes |
| held_out | prettier/tsrs|shared | yes | 361 / 619 | 1.0 / 494.0 | 2813919 | 463764800 / 460950837 | 168368 / 326260 | yes |
| held_out | prettier/tsrs|tsconfig | yes | 191 / 759 | 1.0 / 494.0 | 3659168 | 464610049 / 460950837 | 134288 / 378172 | yes |
| held_out | prettier/tsrs|concurrent | yes | 42 / 2299 | 0.0 / 494.0 | 3659212 | 464610093 / 460950837 | 4752 / 373472 | yes |
| held_out | ajv/bun|cold | yes | 8 / 57 | 0.0 / 106.0 | 64636 | 204619553 / 204554873 | 5056 / 96008 | yes |
| held_out | ajv/bun|leaf | yes | 57 / 57 | 1.0 / 106.0 | 64688 | 204619605 / 204554873 | 82732 / 93344 | yes |
| held_out | ajv/bun|shared | NO | 69 / 59 | 1.0 / 106.0 | 64752 | 204619669 / 204554873 | 94944 / 95048 | yes |
| held_out | ajv/bun|tsconfig | yes | 47 / 62 | 1.0 / 106.0 | 64804 | 204619721 / 204554873 | 81560 / 95900 | yes |
| held_out | ajv/bun|concurrent | yes | 16 / 157 | 0.0 / 106.0 | 64848 | 204619765 / 204554873 | 5056 / 95812 | yes |
| held_out | prettier/bun|cold | yes | 33 / 3270 | 0.0 / 494.0 | 285799 | 461236658 / 460950815 | 5056 / 733052 | yes |
| held_out | prettier/bun|leaf | yes | 305 / 3176 | 1.0 / 494.0 | 285863 | 461236722 / 460950815 | 257828 / 740572 | yes |
| held_out | prettier/bun|shared | yes | 350 / 3135 | 1.0 / 494.0 | 285927 | 461236786 / 460950815 | 231296 / 726432 | yes |
| held_out | prettier/bun|tsconfig | yes | 147 / 3236 | 1.0 / 494.0 | 285979 | 461236838 / 460950815 | 193184 / 728528 | yes |
| held_out | prettier/bun|concurrent | yes | 43 / 6796 | 0.0 / 494.0 | 286023 | 461236882 / 460950815 | 5056 / 728116 | yes |

## Setup Rach should use

```sh
zig build -Doptimize=ReleaseFast
./zig-out/bin/nanocompile worktree init   # Rust + TypeScript
git worktree add --detach ../agent-1
./zig-out/bin/nanocompile worktree init --store "$NANOCOMPILE_DIR" ../agent-1
ln -s "$PWD/node_modules" ../agent-1/node_modules   # shared install
export PATH="$PWD/.nanocompile/bin:$PATH"
tsc --noEmit          # or tsrs / tsgo / bun check
```

Frozen env:

```
{
  "NANOCOMPILE_TS_INCREMENTAL": "1",
  "NANOCOMPILE_TS_SEED": "1",
  "NANOCOMPILE_TS_DIRTY_SCOPE": "1",
  "NANOCOMPILE_TSRS_CHECKERS": "4"
}
```

Cache key: checker identity + argv + tsconfig + source hashes, paths as
`$NANO_ROOT`. Every exit code is stored (replay prefix
`NANOCOMPILE_TS_EXIT=N`). Edit misses do not add a new result entry.

## Hill-climb

| lever | vs | keep | note |
| --- | --- | --- | --- |
| `l0_result_cache` | none | yes | honest win in at least one cell |
| `l1_incremental` | l0_result_cache | yes | honest win in at least one cell |
| `l2_seed_buildinfo` | l1_incremental | yes | honest win in at least one cell |
| `l3_dirty_scope` | l2_seed_buildinfo | yes | honest win in at least one cell |
| `l0_result_cache` | none | yes | honest win in at least one cell |
| `l1_incremental` | l0_result_cache | yes | honest win in at least one cell |
| `l2_seed_buildinfo` | l1_incremental | yes | honest win in at least one cell |
| `l3_dirty_scope` | l2_seed_buildinfo | yes | honest win in at least one cell |
| `l0_result_cache` | none | yes | honest win in at least one cell |
| `l1_incremental` | l0_result_cache | yes | honest win in at least one cell |
| `l2_seed_buildinfo` | l1_incremental | yes | honest win in at least one cell |
| `l3_dirty_scope` | l2_seed_buildinfo | yes | honest win in at least one cell |
| `l0_result_cache` | none | yes | honest win in at least one cell |
| `l1_incremental` | l0_result_cache | yes | honest win in at least one cell |
| `l2_seed_buildinfo` | l1_incremental | yes | honest win in at least one cell |
| `l3_dirty_scope` | l2_seed_buildinfo | yes | honest win in at least one cell |

## Generalization (held-out vs none)

| metric | train gain vs none | held-out gain vs none | fraction that survived |
| --- | --- | --- | --- |
| wall_ms | 46.6% | 89.9% | 192.8% |
| files_rechecked | 99.5% | 99.8% | 100.3% |
| store_bytes | n/a | n/a | n/a |
| disk_bytes | -26.9% | -0.3% | 1.1% |
| rss_kb | 37.9% | 76.1% | 200.7% |

## Pareto frontier per cell

### Train

**condensation-standin/tsc|cold** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 395 | 126.0 | 0 | 316583 | 154636 |
| incremental_local | incremental_local | 385 | 126.0 | 0 | 416699 | 156248 |
| nanocompile | l0_result_cache | 4 | 0.0 | 37759 | 315816 | 3472 |
| nanocompile | l2_seed_buildinfo | 4 | 0.0 | 67795 | 336204 | 3472 |
| nanocompile | l3_dirty_scope | 4 | 0.0 | 67795 | 336138 | 3540 |
- dominated by `nanocompile` (l0_result_cache)

**condensation-standin/tsc|leaf** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 372 | 126.0 | 0 | 316674 | 154724 |
| incremental_local | incremental_local | 368 | 126.0 | 0 | 416790 | 155240 |
| nanocompile | l0_result_cache | 397 | 1.0 | 37798 | 325547 | 154704 |
| nanocompile | l1_incremental | 385 | 1.0 | 37798 | 365475 | 155644 |
| nanocompile | l3_dirty_scope | 370 | 1.0 | 97618 | 365961 | 154096 |
- dominated by `nanocompile` (l3_dirty_scope)

**condensation-standin/tsc|shared** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 416 | 126.0 | 0 | 316765 | 153984 |
| incremental_local | incremental_local | 402 | 126.0 | 0 | 416881 | 152544 |
| nanocompile | l0_result_cache | 394 | 1.0 | 37837 | 335278 | 153444 |
| nanocompile | l1_incremental | 388 | 1.0 | 37837 | 395181 | 154280 |
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)
- dominated by `nanocompile` (l3_dirty_scope)
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)

**condensation-standin/tsc|tsconfig** — nanocompile honest win: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 348 | 126.0 | 0 | 316765 | 151076 |
| nanocompile | l0_result_cache | 386 | 1.0 | 37876 | 345009 | 153620 |
| nanocompile | l2_seed_buildinfo | 386 | 1.0 | 157446 | 425855 | 153312 |
| nanocompile | l3_dirty_scope | 368 | 1.0 | 157446 | 425789 | 155308 |
- dominated by `nanocompile` (l0_result_cache)

**condensation-standin/tsc|concurrent** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 812 | 126.0 | 0 | 316765 | 152640 |
| nanocompile | l0_result_cache | 10 | 0.0 | 37920 | 345053 | 3472 |
| nanocompile | l1_incremental | 9 | 0.0 | 37920 | 424931 | 3468 |
| nanocompile | l3_dirty_scope | 9 | 0.0 | 157490 | 425833 | 3472 |
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)
- dominated by `nanocompile` (l3_dirty_scope)

**condensation-standin/tsgo|cold** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 72 | 126.0 | 0 | 265690 | 51216 |
| incremental_local | incremental_local | 72 | 126.0 | 0 | 365811 | 51284 |
| nanocompile | l0_result_cache | 4 | 0.0 | 37759 | 305655 | 3472 |
| nanocompile | l3_dirty_scope | 4 | 0.0 | 57612 | 325977 | 3472 |
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l3_dirty_scope)

**condensation-standin/tsgo|leaf** — nanocompile honest win: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 74 | 126.0 | 0 | 265771 | 51540 |
| incremental_local | incremental_local | 72 | 126.0 | 0 | 365892 | 50772 |
| nanocompile | l0_result_cache | 77 | 1.0 | 37798 | 305203 | 50700 |
| nanocompile | l1_incremental | 77 | 1.0 | 37798 | 345131 | 49236 |
- dominated by `nanocompile` (l1_incremental)
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)

**condensation-standin/tsgo|shared** — nanocompile honest win: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 70 | 126.0 | 0 | 265852 | 50444 |
| nanocompile | l0_result_cache | 77 | 1.0 | 37837 | 304751 | 51540 |
| nanocompile | l1_incremental | 75 | 1.0 | 37837 | 364654 | 51284 |
| nanocompile | l2_seed_buildinfo | 74 | 1.0 | 96953 | 365384 | 50704 |
- dominated by `nanocompile` (l1_incremental)

**condensation-standin/tsgo|tsconfig** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 76 | 126.0 | 0 | 265852 | 49492 |
| incremental_local | incremental_local | 70 | 126.0 | 0 | 365973 | 48724 |
| nanocompile | l0_result_cache | 72 | 1.0 | 37876 | 304299 | 50704 |
| nanocompile | l1_incremental | 74 | 1.0 | 37876 | 384177 | 50448 |
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)

**condensation-standin/tsgo|concurrent** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 129 | 126.0 | 0 | 265852 | 51088 |
| incremental_local | incremental_local | 126 | 126.0 | 0 | 365973 | 51540 |
| nanocompile | l0_result_cache | 10 | 0.0 | 37920 | 304343 | 3472 |
| nanocompile | l1_incremental | 10 | 0.0 | 37920 | 384221 | 3472 |
| nanocompile | l2_seed_buildinfo | 10 | 0.0 | 116708 | 385139 | 3472 |
| nanocompile | l3_dirty_scope | 10 | 0.0 | 116708 | 385073 | 3472 |

**condensation-standin/tsrs|cold** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 45 | 126.0 | 0 | 268145 | 47160 |
| nanocompile | l0_result_cache | 4 | 0.0 | 37759 | 306146 | 3472 |
| nanocompile | l1_incremental | 4 | 0.0 | 37759 | 326099 | 3600 |
| nanocompile | l3_dirty_scope | 4 | 0.0 | 58103 | 326468 | 3472 |
- dominated by `nanocompile` (l3_dirty_scope)

**condensation-standin/tsrs|leaf** — nanocompile honest win: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 44 | 126.0 | 0 | 268226 | 47156 |
| nanocompile | l0_result_cache | 51 | 1.0 | 37798 | 306266 | 47148 |
| nanocompile | l1_incremental | 50 | 1.0 | 37798 | 346113 | 47376 |
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)
- dominated by `nanocompile` (l3_dirty_scope)
- dominated by `nanocompile` (l0_result_cache)

**condensation-standin/tsrs|shared** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 51 | 126.0 | 0 | 268307 | 47156 |
| incremental_local | incremental_local | 48 | 126.0 | 0 | 368428 | 47368 |
| nanocompile | l0_result_cache | 54 | 1.0 | 37837 | 306386 | 47144 |
| nanocompile | l1_incremental | 49 | 1.0 | 37837 | 366127 | 47368 |
| nanocompile | l3_dirty_scope | 48 | 1.0 | 98426 | 366791 | 47368 |
- dominated by `nanocompile` (l1_incremental)
- dominated by `nanocompile` (l3_dirty_scope)

**condensation-standin/tsrs|tsconfig** — nanocompile honest win: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 42 | 126.0 | 0 | 268307 | 47144 |
| nanocompile | l0_result_cache | 54 | 1.0 | 37876 | 306425 | 47160 |
| nanocompile | l1_incremental | 47 | 1.0 | 37876 | 386141 | 47372 |
- dominated by `nanocompile` (l1_incremental)
- dominated by `nanocompile` (l1_incremental)

**condensation-standin/tsrs|concurrent** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 65 | 126.0 | 0 | 268307 | 47124 |
| incremental_local | incremental_local | 64 | 126.0 | 0 | 368428 | 47404 |
| nanocompile | l0_result_cache | 9 | 0.0 | 37920 | 306469 | 3472 |
| nanocompile | l2_seed_buildinfo | 9 | 0.0 | 118672 | 387103 | 3540 |
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l0_result_cache)

**condensation-standin/bun|cold** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 33 | 126.0 | 0 | 268123 | 58992 |
| nanocompile | l3_dirty_scope | 5 | 0.0 | 37801 | 306144 | 5056 |
- dominated by `nanocompile` (l3_dirty_scope)
- dominated by `nanocompile` (l3_dirty_scope)
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)
- dominated by `nanocompile` (l3_dirty_scope)

**condensation-standin/bun|leaf** — nanocompile honest win: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 32 | 126.0 | 0 | 268123 | 57904 |
| nanocompile | l0_result_cache | 40 | 1.0 | 37840 | 306205 | 56684 |
| nanocompile | l1_incremental | 45 | 1.0 | 37840 | 306183 | 58856 |
| nanocompile | l3_dirty_scope | 42 | 1.0 | 37853 | 306196 | 57200 |
- dominated by `nanocompile` (l0_result_cache)

**condensation-standin/bun|shared** — nanocompile honest win: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 31 | 126.0 | 0 | 268123 | 58412 |
| nanocompile | l0_result_cache | 41 | 1.0 | 37879 | 306244 | 57016 |
| nanocompile | l1_incremental | 44 | 1.0 | 37879 | 306222 | 57980 |
| nanocompile | l2_seed_buildinfo | 40 | 1.0 | 37879 | 306288 | 59488 |
| nanocompile | l3_dirty_scope | 41 | 1.0 | 37905 | 306248 | 56512 |

**condensation-standin/bun|tsconfig** — nanocompile honest win: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 32 | 126.0 | 0 | 268123 | 58296 |
| nanocompile | l0_result_cache | 42 | 1.0 | 37918 | 306283 | 57144 |
| nanocompile | l1_incremental | 45 | 1.0 | 37918 | 306261 | 59316 |
| nanocompile | l2_seed_buildinfo | 39 | 1.0 | 37918 | 306327 | 56448 |
| nanocompile | l3_dirty_scope | 40 | 1.0 | 37957 | 306300 | 55284 |

**condensation-standin/bun|concurrent** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 54 | 126.0 | 0 | 268123 | 57660 |
| nanocompile | l0_result_cache | 12 | 0.0 | 37962 | 306327 | 5056 |
| nanocompile | l1_incremental | 14 | 0.0 | 37962 | 306305 | 5056 |
| nanocompile | l2_seed_buildinfo | 11 | 0.0 | 37962 | 306371 | 5056 |
- dominated by `nanocompile` (l0_result_cache)

### Held-out

**ajv/bun|cold** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 57 | 106.0 | 0 | 204554873 | 96008 |
| nanocompile | l3_dirty_scope | 8 | 0.0 | 64636 | 204619553 | 5056 |

**ajv/bun|leaf** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 57 | 106.0 | 0 | 204554873 | 93344 |
| nanocompile | l3_dirty_scope | 57 | 1.0 | 64688 | 204619605 | 82732 |

**ajv/bun|shared** — nanocompile honest win: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 59 | 106.0 | 0 | 204554873 | 95048 |
| nanocompile | l3_dirty_scope | 69 | 1.0 | 64752 | 204619669 | 94944 |

**ajv/bun|tsconfig** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 62 | 106.0 | 0 | 204554873 | 95900 |
| nanocompile | l3_dirty_scope | 47 | 1.0 | 64804 | 204619721 | 81560 |

**ajv/bun|concurrent** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 157 | 106.0 | 0 | 204554873 | 95812 |
| nanocompile | l3_dirty_scope | 16 | 0.0 | 64848 | 204619765 | 5056 |

**prettier/bun|cold** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 3270 | 494.0 | 0 | 460950815 | 733052 |
| nanocompile | l3_dirty_scope | 33 | 0.0 | 285799 | 461236658 | 5056 |

**prettier/bun|leaf** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 3176 | 494.0 | 0 | 460950815 | 740572 |
| nanocompile | l3_dirty_scope | 305 | 1.0 | 285863 | 461236722 | 257828 |

**prettier/bun|shared** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 3135 | 494.0 | 0 | 460950815 | 726432 |
| nanocompile | l3_dirty_scope | 350 | 1.0 | 285927 | 461236786 | 231296 |

**prettier/bun|tsconfig** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 3236 | 494.0 | 0 | 460950815 | 728528 |
| nanocompile | l3_dirty_scope | 147 | 1.0 | 285979 | 461236838 | 193184 |

**prettier/bun|concurrent** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 6796 | 494.0 | 0 | 460950815 | 728116 |
| nanocompile | l3_dirty_scope | 43 | 0.0 | 286023 | 461236882 | 5056 |

**ajv/tsc|cold** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 1210 | 106.0 | 0 | 204554718 | 239164 |
| nanocompile | l3_dirty_scope | 7 | 0.0 | 113605 | 204668367 | 3728 |

**ajv/tsc|leaf** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 1217 | 106.0 | 0 | 204554718 | 240532 |
| incremental_local | incremental_local | 592 | 106.0 | 0 | 204804735 | 206880 |
| nanocompile | l3_dirty_scope | 622 | 1.0 | 163698 | 204718460 | 206716 |

**ajv/tsc|shared** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 1237 | 106.0 | 0 | 204554718 | 238704 |
| incremental_local | incremental_local | 711 | 106.0 | 0 | 204805099 | 213788 |
| nanocompile | l3_dirty_scope | 725 | 1.0 | 214155 | 204768917 | 215948 |

**ajv/tsc|tsconfig** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 1240 | 106.0 | 0 | 204554718 | 238692 |
| incremental_local | incremental_local | 566 | 106.0 | 0 | 204805099 | 203844 |
| nanocompile | l3_dirty_scope | 647 | 1.0 | 264612 | 204819374 | 210728 |

**ajv/tsc|concurrent** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 3047 | 106.0 | 0 | 204554718 | 238432 |
| incremental_local | incremental_local | 1438 | 106.0 | 0 | 204805099 | 207256 |
| nanocompile | l3_dirty_scope | 17 | 0.0 | 264656 | 204819418 | 3600 |

**prettier/tsc|cold** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 18622 | 494.0 | 0 | 460950655 | 1222960 |
| incremental_local | incremental_local | 18248 | 494.0 | 0 | 463596871 | 1245612 |
| nanocompile | l3_dirty_scope | 34 | 0.0 | 711873 | 461662572 | 4496 |

**prettier/tsc|leaf** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 18373 | 494.0 | 0 | 460950655 | 1222996 |
| incremental_local | incremental_local | 4112 | 494.0 | 0 | 463598293 | 542960 |
| nanocompile | l3_dirty_scope | 4110 | 1.0 | 1242555 | 462193254 | 544384 |

**prettier/tsc|shared** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 18055 | 494.0 | 0 | 460950655 | 1219512 |
| incremental_local | incremental_local | 2912 | 494.0 | 0 | 463600189 | 509972 |
| nanocompile | l3_dirty_scope | 2981 | 1.0 | 1774659 | 462725358 | 509036 |

**prettier/tsc|tsconfig** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 18342 | 494.0 | 0 | 460950655 | 1218108 |
| incremental_local | incremental_local | 1505 | 494.0 | 0 | 463600189 | 412296 |
| nanocompile | l3_dirty_scope | 2205 | 1.0 | 2306763 | 463257462 | 468556 |

**prettier/tsc|concurrent** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 26602 | 494.0 | 0 | 460950655 | 1226132 |
| incremental_local | incremental_local | 4486 | 494.0 | 0 | 463600189 | 466460 |
| nanocompile | l3_dirty_scope | 45 | 0.0 | 2306807 | 463257506 | 4496 |

**ajv/tsgo|cold** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 139 | 106.0 | 0 | 204554895 | 110420 |
| incremental_local | incremental_local | 151 | 106.0 | 0 | 204946066 | 106640 |
| nanocompile | l3_dirty_scope | 7 | 0.0 | 143046 | 204697985 | 3728 |

**ajv/tsgo|leaf** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 147 | 106.0 | 0 | 204554895 | 108816 |
| incremental_local | incremental_local | 124 | 106.0 | 0 | 204946147 | 87640 |
| nanocompile | l3_dirty_scope | 134 | 1.0 | 221389 | 204776328 | 88212 |

**ajv/tsgo|shared** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 151 | 106.0 | 0 | 204554895 | 109072 |
| incremental_local | incremental_local | 132 | 106.0 | 0 | 204946471 | 91980 |
| nanocompile | l3_dirty_scope | 125 | 1.0 | 300056 | 204854995 | 93072 |

**ajv/tsgo|tsconfig** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 137 | 106.0 | 0 | 204554895 | 109328 |
| incremental_local | incremental_local | 110 | 106.0 | 0 | 204946471 | 84628 |
| nanocompile | l3_dirty_scope | 131 | 1.0 | 378723 | 204933662 | 87376 |

**ajv/tsgo|concurrent** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 382 | 106.0 | 0 | 204554895 | 111124 |
| incremental_local | incremental_local | 260 | 106.0 | 0 | 204946471 | 89232 |
| nanocompile | l3_dirty_scope | 16 | 0.0 | 378767 | 204933706 | 3668 |

**prettier/tsgo|cold** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 4710 | 494.0 | 0 | 460950837 | 1555180 |
| nanocompile | l3_dirty_scope | 32 | 0.0 | 1123754 | 462074635 | 4880 |

**prettier/tsgo|leaf** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 4516 | 494.0 | 0 | 460950837 | 1472392 |
| incremental_local | incremental_local | 975 | 494.0 | 0 | 465166719 | 368208 |
| nanocompile | l3_dirty_scope | 973 | 1.0 | 1967635 | 462918516 | 369152 |

**prettier/tsgo|shared** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 4649 | 494.0 | 0 | 460950837 | 1480412 |
| incremental_local | incremental_local | 1030 | 494.0 | 0 | 465167847 | 380812 |
| nanocompile | l3_dirty_scope | 1063 | 1.0 | 2812362 | 463763243 | 408720 |

**prettier/tsgo|tsconfig** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 4652 | 494.0 | 0 | 460950837 | 1467624 |
| incremental_local | incremental_local | 299 | 494.0 | 0 | 465167847 | 257872 |
| nanocompile | l3_dirty_scope | 545 | 1.0 | 3657089 | 464607970 | 321292 |

**prettier/tsgo|concurrent** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 11996 | 494.0 | 0 | 460950837 | 1519464 |
| incremental_local | incremental_local | 1043 | 494.0 | 0 | 465167847 | 313992 |
| nanocompile | l3_dirty_scope | 43 | 0.0 | 3657133 | 464608014 | 4752 |

**ajv/tsrs|cold** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 58 | 106.0 | 0 | 204554895 | 53884 |
| incremental_local | incremental_local | 56 | 106.0 | 0 | 204946426 | 56036 |
| nanocompile | l3_dirty_scope | 7 | 0.0 | 143118 | 204698057 | 3728 |

**ajv/tsrs|leaf** — nanocompile honest win: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 60 | 106.0 | 0 | 204554895 | 53980 |
| nanocompile | l3_dirty_scope | 63 | 1.0 | 221533 | 204776472 | 58152 |

**ajv/tsrs|shared** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 63 | 106.0 | 0 | 204554895 | 53700 |
| incremental_local | incremental_local | 56 | 106.0 | 0 | 204946831 | 58828 |
| nanocompile | l3_dirty_scope | 64 | 1.0 | 300272 | 204855211 | 56456 |

**ajv/tsrs|tsconfig** — nanocompile honest win: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 54 | 106.0 | 0 | 204554895 | 53672 |
| incremental_local | incremental_local | 50 | 106.0 | 0 | 204946831 | 48460 |
| nanocompile | l3_dirty_scope | 69 | 1.0 | 379011 | 204933950 | 57456 |

**ajv/tsrs|concurrent** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 126 | 106.0 | 0 | 204554895 | 53932 |
| incremental_local | incremental_local | 98 | 106.0 | 0 | 204946831 | 57764 |
| nanocompile | l3_dirty_scope | 14 | 0.0 | 379055 | 204933994 | 3668 |

**prettier/tsrs|cold** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 754 | 494.0 | 0 | 460950837 | 368528 |
| incremental_local | incremental_local | 832 | 494.0 | 0 | 465168483 | 310984 |
| nanocompile | l3_dirty_scope | 32 | 0.0 | 1124267 | 462075148 | 4880 |

**prettier/tsrs|leaf** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 756 | 494.0 | 0 | 460950837 | 369748 |
| incremental_local | incremental_local | 264 | 494.0 | 0 | 465169329 | 150048 |
| nanocompile | l3_dirty_scope | 296 | 1.0 | 1968670 | 462919551 | 149156 |

**prettier/tsrs|shared** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 619 | 494.0 | 0 | 460950837 | 326260 |
| incremental_local | incremental_local | 329 | 494.0 | 0 | 465170457 | 169728 |
| nanocompile | l3_dirty_scope | 361 | 1.0 | 2813919 | 463764800 | 168368 |

**prettier/tsrs|tsconfig** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 759 | 494.0 | 0 | 460950837 | 378172 |
| incremental_local | incremental_local | 119 | 494.0 | 0 | 465170457 | 115112 |
| nanocompile | l3_dirty_scope | 191 | 1.0 | 3659168 | 464610049 | 134288 |

**prettier/tsrs|concurrent** — nanocompile honest win: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 2299 | 494.0 | 0 | 460950837 | 373472 |
| incremental_local | incremental_local | 333 | 494.0 | 0 | 465170457 | 135976 |
| nanocompile | l3_dirty_scope | 42 | 0.0 | 3659212 | 464610093 | 4752 |


## Rows

| sample | cell | approach | wall | files | store | disk | rss | correct | ok |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| condensation-standin | tsc|cold | none | 395 | 126.0 |  | 316583 | 154636 | yes | yes |
| condensation-standin | tsc|leaf | none | 372 | 126.0 |  | 316674 | 154724 | yes | yes |
| condensation-standin | tsc|shared | none | 416 | 126.0 |  | 316765 | 153984 | yes | yes |
| condensation-standin | tsc|tsconfig | none | 348 | 126.0 |  | 316765 | 151076 | yes | yes |
| condensation-standin | tsc|concurrent | none | 812 | 126.0 |  | 316765 | 152640 | yes | yes |
| condensation-standin | tsc|cold | incremental_local | 385 | 126.0 |  | 416699 | 156248 | yes | yes |
| condensation-standin | tsc|leaf | incremental_local | 368 | 126.0 |  | 416790 | 155240 | yes | yes |
| condensation-standin | tsc|shared | incremental_local | 402 | 126.0 |  | 416881 | 152544 | yes | yes |
| condensation-standin | tsc|tsconfig | incremental_local | 380 | 126.0 |  | 416881 | 152796 | yes | yes |
| condensation-standin | tsc|concurrent | incremental_local | 838 | 126.0 |  | 416881 | 153476 | yes | yes |
| condensation-standin | tsc|cold | nanocompile | 4 | 0.0 | 37759 | 315816 | 3472 | yes | yes |
| condensation-standin | tsc|leaf | nanocompile | 397 | 1.0 | 37798 | 325547 | 154704 | yes | yes |
| condensation-standin | tsc|shared | nanocompile | 394 | 1.0 | 37837 | 335278 | 153444 | yes | yes |
| condensation-standin | tsc|tsconfig | nanocompile | 386 | 1.0 | 37876 | 345009 | 153620 | yes | yes |
| condensation-standin | tsc|concurrent | nanocompile | 10 | 0.0 | 37920 | 345053 | 3472 | yes | yes |
| condensation-standin | tsc|cold | nanocompile | 5 | 0.0 | 37759 | 335769 | 3540 | yes | yes |
| condensation-standin | tsc|leaf | nanocompile | 385 | 1.0 | 37798 | 365475 | 155644 | yes | yes |
| condensation-standin | tsc|shared | nanocompile | 388 | 1.0 | 37837 | 395181 | 154280 | yes | yes |
| condensation-standin | tsc|tsconfig | nanocompile | 389 | 1.0 | 37876 | 424887 | 155092 | yes | yes |
| condensation-standin | tsc|concurrent | nanocompile | 9 | 0.0 | 37920 | 424931 | 3468 | yes | yes |
| condensation-standin | tsc|cold | nanocompile | 4 | 0.0 | 67795 | 336204 | 3472 | yes | yes |
| condensation-standin | tsc|leaf | nanocompile | 387 | 1.0 | 97618 | 366027 | 154544 | yes | yes |
| condensation-standin | tsc|shared | nanocompile | 403 | 1.0 | 127532 | 395941 | 156260 | yes | yes |
| condensation-standin | tsc|tsconfig | nanocompile | 386 | 1.0 | 157446 | 425855 | 153312 | yes | yes |
| condensation-standin | tsc|concurrent | nanocompile | 10 | 0.0 | 157490 | 425899 | 3472 | yes | yes |
| condensation-standin | tsc|cold | nanocompile | 4 | 0.0 | 67795 | 336138 | 3540 | yes | yes |
| condensation-standin | tsc|leaf | nanocompile | 370 | 1.0 | 97618 | 365961 | 154096 | yes | yes |
| condensation-standin | tsc|shared | nanocompile | 395 | 1.0 | 127532 | 395875 | 155736 | yes | yes |
| condensation-standin | tsc|tsconfig | nanocompile | 368 | 1.0 | 157446 | 425789 | 155308 | yes | yes |
| condensation-standin | tsc|concurrent | nanocompile | 9 | 0.0 | 157490 | 425833 | 3472 | yes | yes |
| condensation-standin | tsgo|cold | none | 72 | 126.0 |  | 265690 | 51216 | yes | yes |
| condensation-standin | tsgo|leaf | none | 74 | 126.0 |  | 265771 | 51540 | yes | yes |
| condensation-standin | tsgo|shared | none | 70 | 126.0 |  | 265852 | 50444 | yes | yes |
| condensation-standin | tsgo|tsconfig | none | 76 | 126.0 |  | 265852 | 49492 | yes | yes |
| condensation-standin | tsgo|concurrent | none | 129 | 126.0 |  | 265852 | 51088 | yes | yes |
| condensation-standin | tsgo|cold | incremental_local | 72 | 126.0 |  | 365811 | 51284 | yes | yes |
| condensation-standin | tsgo|leaf | incremental_local | 72 | 126.0 |  | 365892 | 50772 | yes | yes |
| condensation-standin | tsgo|shared | incremental_local | 76 | 126.0 |  | 365973 | 51540 | yes | yes |
| condensation-standin | tsgo|tsconfig | incremental_local | 70 | 126.0 |  | 365973 | 48724 | yes | yes |
| condensation-standin | tsgo|concurrent | incremental_local | 126 | 126.0 |  | 365973 | 51540 | yes | yes |
| condensation-standin | tsgo|cold | nanocompile | 4 | 0.0 | 37759 | 305655 | 3472 | yes | yes |
| condensation-standin | tsgo|leaf | nanocompile | 77 | 1.0 | 37798 | 305203 | 50700 | yes | yes |
| condensation-standin | tsgo|shared | nanocompile | 77 | 1.0 | 37837 | 304751 | 51540 | yes | yes |
| condensation-standin | tsgo|tsconfig | nanocompile | 72 | 1.0 | 37876 | 304299 | 50704 | yes | yes |
| condensation-standin | tsgo|concurrent | nanocompile | 10 | 0.0 | 37920 | 304343 | 3472 | yes | yes |
| condensation-standin | tsgo|cold | nanocompile | 4 | 0.0 | 37759 | 325608 | 3600 | yes | yes |
| condensation-standin | tsgo|leaf | nanocompile | 77 | 1.0 | 37798 | 345131 | 49236 | yes | yes |
| condensation-standin | tsgo|shared | nanocompile | 75 | 1.0 | 37837 | 364654 | 51284 | yes | yes |
| condensation-standin | tsgo|tsconfig | nanocompile | 74 | 1.0 | 37876 | 384177 | 50448 | yes | yes |
| condensation-standin | tsgo|concurrent | nanocompile | 10 | 0.0 | 37920 | 384221 | 3472 | yes | yes |
| condensation-standin | tsgo|cold | nanocompile | 5 | 0.0 | 57612 | 326043 | 3472 | yes | yes |
| condensation-standin | tsgo|leaf | nanocompile | 78 | 1.0 | 77242 | 345673 | 49876 | yes | yes |
| condensation-standin | tsgo|shared | nanocompile | 74 | 1.0 | 96953 | 365384 | 50704 | yes | yes |
| condensation-standin | tsgo|tsconfig | nanocompile | 76 | 1.0 | 116664 | 385095 | 50832 | yes | yes |
| condensation-standin | tsgo|concurrent | nanocompile | 10 | 0.0 | 116708 | 385139 | 3472 | yes | yes |
| condensation-standin | tsgo|cold | nanocompile | 4 | 0.0 | 57612 | 325977 | 3472 | yes | yes |
| condensation-standin | tsgo|leaf | nanocompile | 82 | 1.0 | 77242 | 345607 | 51156 | yes | yes |
| condensation-standin | tsgo|shared | nanocompile | 80 | 1.0 | 96953 | 365318 | 51468 | yes | yes |
| condensation-standin | tsgo|tsconfig | nanocompile | 78 | 1.0 | 116664 | 385029 | 51156 | yes | yes |
| condensation-standin | tsgo|concurrent | nanocompile | 10 | 0.0 | 116708 | 385073 | 3472 | yes | yes |
| condensation-standin | tsrs|cold | none | 45 | 126.0 |  | 268145 | 47160 | yes | yes |
| condensation-standin | tsrs|leaf | none | 44 | 126.0 |  | 268226 | 47156 | yes | yes |
| condensation-standin | tsrs|shared | none | 51 | 126.0 |  | 268307 | 47156 | yes | yes |
| condensation-standin | tsrs|tsconfig | none | 42 | 126.0 |  | 268307 | 47144 | yes | yes |
| condensation-standin | tsrs|concurrent | none | 65 | 126.0 |  | 268307 | 47124 | yes | yes |
| condensation-standin | tsrs|cold | incremental_local | 46 | 126.0 |  | 368266 | 47372 | yes | yes |
| condensation-standin | tsrs|leaf | incremental_local | 48 | 126.0 |  | 368347 | 47364 | yes | yes |
| condensation-standin | tsrs|shared | incremental_local | 48 | 126.0 |  | 368428 | 47368 | yes | yes |
| condensation-standin | tsrs|tsconfig | incremental_local | 46 | 126.0 |  | 368428 | 47368 | yes | yes |
| condensation-standin | tsrs|concurrent | incremental_local | 64 | 126.0 |  | 368428 | 47404 | yes | yes |
| condensation-standin | tsrs|cold | nanocompile | 4 | 0.0 | 37759 | 306146 | 3472 | yes | yes |
| condensation-standin | tsrs|leaf | nanocompile | 51 | 1.0 | 37798 | 306266 | 47148 | yes | yes |
| condensation-standin | tsrs|shared | nanocompile | 54 | 1.0 | 37837 | 306386 | 47144 | yes | yes |
| condensation-standin | tsrs|tsconfig | nanocompile | 54 | 1.0 | 37876 | 306425 | 47160 | yes | yes |
| condensation-standin | tsrs|concurrent | nanocompile | 9 | 0.0 | 37920 | 306469 | 3472 | yes | yes |
| condensation-standin | tsrs|cold | nanocompile | 4 | 0.0 | 37759 | 326099 | 3600 | yes | yes |
| condensation-standin | tsrs|leaf | nanocompile | 50 | 1.0 | 37798 | 346113 | 47376 | yes | yes |
| condensation-standin | tsrs|shared | nanocompile | 49 | 1.0 | 37837 | 366127 | 47368 | yes | yes |
| condensation-standin | tsrs|tsconfig | nanocompile | 47 | 1.0 | 37876 | 386141 | 47372 | yes | yes |
| condensation-standin | tsrs|concurrent | nanocompile | 10 | 0.0 | 37920 | 386185 | 3472 | yes | yes |
| condensation-standin | tsrs|cold | nanocompile | 4 | 0.0 | 58103 | 326534 | 3472 | yes | yes |
| condensation-standin | tsrs|leaf | nanocompile | 52 | 1.0 | 78224 | 346655 | 47376 | yes | yes |
| condensation-standin | tsrs|shared | nanocompile | 53 | 1.0 | 98426 | 366857 | 47372 | yes | yes |
| condensation-standin | tsrs|tsconfig | nanocompile | 50 | 1.0 | 118628 | 387059 | 47372 | yes | yes |
| condensation-standin | tsrs|concurrent | nanocompile | 9 | 0.0 | 118672 | 387103 | 3540 | yes | yes |
| condensation-standin | tsrs|cold | nanocompile | 4 | 0.0 | 58103 | 326468 | 3472 | yes | yes |
| condensation-standin | tsrs|leaf | nanocompile | 51 | 1.0 | 78224 | 346589 | 47364 | yes | yes |
| condensation-standin | tsrs|shared | nanocompile | 48 | 1.0 | 98426 | 366791 | 47368 | yes | yes |
| condensation-standin | tsrs|tsconfig | nanocompile | 49 | 1.0 | 118628 | 386993 | 47376 | yes | yes |
| condensation-standin | tsrs|concurrent | nanocompile | 10 | 0.0 | 118672 | 387037 | 3600 | yes | yes |
| condensation-standin | bun|cold | none | 33 | 126.0 |  | 268123 | 58992 | yes | yes |
| condensation-standin | bun|leaf | none | 32 | 126.0 |  | 268123 | 57904 | yes | yes |
| condensation-standin | bun|shared | none | 31 | 126.0 |  | 268123 | 58412 | yes | yes |
| condensation-standin | bun|tsconfig | none | 32 | 126.0 |  | 268123 | 58296 | yes | yes |
| condensation-standin | bun|concurrent | none | 54 | 126.0 |  | 268123 | 57660 | yes | yes |
| condensation-standin | bun|cold | nanocompile | 6 | 0.0 | 37801 | 306166 | 5056 | yes | yes |
| condensation-standin | bun|leaf | nanocompile | 40 | 1.0 | 37840 | 306205 | 56684 | yes | yes |
| condensation-standin | bun|shared | nanocompile | 41 | 1.0 | 37879 | 306244 | 57016 | yes | yes |
| condensation-standin | bun|tsconfig | nanocompile | 42 | 1.0 | 37918 | 306283 | 57144 | yes | yes |
| condensation-standin | bun|concurrent | nanocompile | 12 | 0.0 | 37962 | 306327 | 5056 | yes | yes |
| condensation-standin | bun|cold | nanocompile | 6 | 0.0 | 37801 | 306144 | 5056 | yes | yes |
| condensation-standin | bun|leaf | nanocompile | 45 | 1.0 | 37840 | 306183 | 58856 | yes | yes |
| condensation-standin | bun|shared | nanocompile | 44 | 1.0 | 37879 | 306222 | 57980 | yes | yes |
| condensation-standin | bun|tsconfig | nanocompile | 45 | 1.0 | 37918 | 306261 | 59316 | yes | yes |
| condensation-standin | bun|concurrent | nanocompile | 14 | 0.0 | 37962 | 306305 | 5056 | yes | yes |
| condensation-standin | bun|cold | nanocompile | 6 | 0.0 | 37801 | 306210 | 5056 | yes | yes |
| condensation-standin | bun|leaf | nanocompile | 40 | 1.0 | 37840 | 306249 | 58020 | yes | yes |
| condensation-standin | bun|shared | nanocompile | 40 | 1.0 | 37879 | 306288 | 59488 | yes | yes |
| condensation-standin | bun|tsconfig | nanocompile | 39 | 1.0 | 37918 | 306327 | 56448 | yes | yes |
| condensation-standin | bun|concurrent | nanocompile | 11 | 0.0 | 37962 | 306371 | 5056 | yes | yes |
| condensation-standin | bun|cold | nanocompile | 5 | 0.0 | 37801 | 306144 | 5056 | yes | yes |
| condensation-standin | bun|leaf | nanocompile | 42 | 1.0 | 37853 | 306196 | 57200 | yes | yes |
| condensation-standin | bun|shared | nanocompile | 41 | 1.0 | 37905 | 306248 | 56512 | yes | yes |
| condensation-standin | bun|tsconfig | nanocompile | 40 | 1.0 | 37957 | 306300 | 55284 | yes | yes |
| condensation-standin | bun|concurrent | nanocompile | 12 | 0.0 | 38001 | 306344 | 5056 | yes | yes |
| ajv | tsc|cold | none | 1210 | 106.0 |  | 204554718 | 239164 | yes | yes |
| ajv | tsc|leaf | none | 1217 | 106.0 |  | 204554718 | 240532 | yes | yes |
| ajv | tsc|shared | none | 1237 | 106.0 |  | 204554718 | 238704 | yes | yes |
| ajv | tsc|tsconfig | none | 1240 | 106.0 |  | 204554718 | 238692 | yes | yes |
| ajv | tsc|concurrent | none | 3047 | 106.0 |  | 204554718 | 238432 | yes | yes |
| ajv | tsc|cold | incremental_local | 1221 | 106.0 |  | 204804644 | 240728 | yes | yes |
| ajv | tsc|leaf | incremental_local | 592 | 106.0 |  | 204804735 | 206880 | yes | yes |
| ajv | tsc|shared | incremental_local | 711 | 106.0 |  | 204805099 | 213788 | yes | yes |
| ajv | tsc|tsconfig | incremental_local | 566 | 106.0 |  | 204805099 | 203844 | yes | yes |
| ajv | tsc|concurrent | incremental_local | 1438 | 106.0 |  | 204805099 | 207256 | yes | yes |
| ajv | tsc|cold | nanocompile | 7 | 0.0 | 113605 | 204668367 | 3728 | yes | yes |
| ajv | tsc|leaf | nanocompile | 622 | 1.0 | 163698 | 204718460 | 206716 | yes | yes |
| ajv | tsc|shared | nanocompile | 725 | 1.0 | 214155 | 204768917 | 215948 | yes | yes |
| ajv | tsc|tsconfig | nanocompile | 647 | 1.0 | 264612 | 204819374 | 210728 | yes | yes |
| ajv | tsc|concurrent | nanocompile | 17 | 0.0 | 264656 | 204819418 | 3600 | yes | yes |
| prettier | tsc|cold | none | 18622 | 494.0 |  | 460950655 | 1222960 | yes | yes |
| prettier | tsc|leaf | none | 18373 | 494.0 |  | 460950655 | 1222996 | yes | yes |
| prettier | tsc|shared | none | 18055 | 494.0 |  | 460950655 | 1219512 | yes | yes |
| prettier | tsc|tsconfig | none | 18342 | 494.0 |  | 460950655 | 1218108 | yes | yes |
| prettier | tsc|concurrent | none | 26602 | 494.0 |  | 460950655 | 1226132 | yes | yes |
| prettier | tsc|cold | incremental_local | 18248 | 494.0 |  | 463596871 | 1245612 | yes | yes |
| prettier | tsc|leaf | incremental_local | 4112 | 494.0 |  | 463598293 | 542960 | yes | yes |
| prettier | tsc|shared | incremental_local | 2912 | 494.0 |  | 463600189 | 509972 | yes | yes |
| prettier | tsc|tsconfig | incremental_local | 1505 | 494.0 |  | 463600189 | 412296 | yes | yes |
| prettier | tsc|concurrent | incremental_local | 4486 | 494.0 |  | 463600189 | 466460 | yes | yes |
| prettier | tsc|cold | nanocompile | 34 | 0.0 | 711873 | 461662572 | 4496 | yes | yes |
| prettier | tsc|leaf | nanocompile | 4110 | 1.0 | 1242555 | 462193254 | 544384 | yes | yes |
| prettier | tsc|shared | nanocompile | 2981 | 1.0 | 1774659 | 462725358 | 509036 | yes | yes |
| prettier | tsc|tsconfig | nanocompile | 2205 | 1.0 | 2306763 | 463257462 | 468556 | yes | yes |
| prettier | tsc|concurrent | nanocompile | 45 | 0.0 | 2306807 | 463257506 | 4496 | yes | yes |
| ajv | tsgo|cold | none | 139 | 106.0 |  | 204554895 | 110420 | yes | yes |
| ajv | tsgo|leaf | none | 147 | 106.0 |  | 204554895 | 108816 | yes | yes |
| ajv | tsgo|shared | none | 151 | 106.0 |  | 204554895 | 109072 | yes | yes |
| ajv | tsgo|tsconfig | none | 137 | 106.0 |  | 204554895 | 109328 | yes | yes |
| ajv | tsgo|concurrent | none | 382 | 106.0 |  | 204554895 | 111124 | yes | yes |
| ajv | tsgo|cold | incremental_local | 151 | 106.0 |  | 204946066 | 106640 | yes | yes |
| ajv | tsgo|leaf | incremental_local | 124 | 106.0 |  | 204946147 | 87640 | yes | yes |
| ajv | tsgo|shared | incremental_local | 132 | 106.0 |  | 204946471 | 91980 | yes | yes |
| ajv | tsgo|tsconfig | incremental_local | 110 | 106.0 |  | 204946471 | 84628 | yes | yes |
| ajv | tsgo|concurrent | incremental_local | 260 | 106.0 |  | 204946471 | 89232 | yes | yes |
| ajv | tsgo|cold | nanocompile | 7 | 0.0 | 143046 | 204697985 | 3728 | yes | yes |
| ajv | tsgo|leaf | nanocompile | 134 | 1.0 | 221389 | 204776328 | 88212 | yes | yes |
| ajv | tsgo|shared | nanocompile | 125 | 1.0 | 300056 | 204854995 | 93072 | yes | yes |
| ajv | tsgo|tsconfig | nanocompile | 131 | 1.0 | 378723 | 204933662 | 87376 | yes | yes |
| ajv | tsgo|concurrent | nanocompile | 16 | 0.0 | 378767 | 204933706 | 3668 | yes | yes |
| prettier | tsgo|cold | none | 4710 | 494.0 |  | 460950837 | 1555180 | yes | yes |
| prettier | tsgo|leaf | none | 4516 | 494.0 |  | 460950837 | 1472392 | yes | yes |
| prettier | tsgo|shared | none | 4649 | 494.0 |  | 460950837 | 1480412 | yes | yes |
| prettier | tsgo|tsconfig | none | 4652 | 494.0 |  | 460950837 | 1467624 | yes | yes |
| prettier | tsgo|concurrent | none | 11996 | 494.0 |  | 460950837 | 1519464 | yes | yes |
| prettier | tsgo|cold | incremental_local | 4794 | 494.0 |  | 465165873 | 1606960 | yes | yes |
| prettier | tsgo|leaf | incremental_local | 975 | 494.0 |  | 465166719 | 368208 | yes | yes |
| prettier | tsgo|shared | incremental_local | 1030 | 494.0 |  | 465167847 | 380812 | yes | yes |
| prettier | tsgo|tsconfig | incremental_local | 299 | 494.0 |  | 465167847 | 257872 | yes | yes |
| prettier | tsgo|concurrent | incremental_local | 1043 | 494.0 |  | 465167847 | 313992 | yes | yes |
| prettier | tsgo|cold | nanocompile | 32 | 0.0 | 1123754 | 462074635 | 4880 | yes | yes |
| prettier | tsgo|leaf | nanocompile | 973 | 1.0 | 1967635 | 462918516 | 369152 | yes | yes |
| prettier | tsgo|shared | nanocompile | 1063 | 1.0 | 2812362 | 463763243 | 408720 | yes | yes |
| prettier | tsgo|tsconfig | nanocompile | 545 | 1.0 | 3657089 | 464607970 | 321292 | yes | yes |
| prettier | tsgo|concurrent | nanocompile | 43 | 0.0 | 3657133 | 464608014 | 4752 | yes | yes |
| ajv | tsrs|cold | none | 58 | 106.0 |  | 204554895 | 53884 | yes | yes |
| ajv | tsrs|leaf | none | 60 | 106.0 |  | 204554895 | 53980 | yes | yes |
| ajv | tsrs|shared | none | 63 | 106.0 |  | 204554895 | 53700 | yes | yes |
| ajv | tsrs|tsconfig | none | 54 | 106.0 |  | 204554895 | 53672 | yes | yes |
| ajv | tsrs|concurrent | none | 126 | 106.0 |  | 204554895 | 53932 | yes | yes |
| ajv | tsrs|cold | incremental_local | 56 | 106.0 |  | 204946426 | 56036 | yes | yes |
| ajv | tsrs|leaf | incremental_local | 63 | 106.0 |  | 204946507 | 55780 | yes | yes |
| ajv | tsrs|shared | incremental_local | 56 | 106.0 |  | 204946831 | 58828 | yes | yes |
| ajv | tsrs|tsconfig | incremental_local | 50 | 106.0 |  | 204946831 | 48460 | yes | yes |
| ajv | tsrs|concurrent | incremental_local | 98 | 106.0 |  | 204946831 | 57764 | yes | yes |
| ajv | tsrs|cold | nanocompile | 7 | 0.0 | 143118 | 204698057 | 3728 | yes | yes |
| ajv | tsrs|leaf | nanocompile | 63 | 1.0 | 221533 | 204776472 | 58152 | yes | yes |
| ajv | tsrs|shared | nanocompile | 64 | 1.0 | 300272 | 204855211 | 56456 | yes | yes |
| ajv | tsrs|tsconfig | nanocompile | 69 | 1.0 | 379011 | 204933950 | 57456 | yes | yes |
| ajv | tsrs|concurrent | nanocompile | 14 | 0.0 | 379055 | 204933994 | 3668 | yes | yes |
| prettier | tsrs|cold | none | 754 | 494.0 |  | 460950837 | 368528 | yes | yes |
| prettier | tsrs|leaf | none | 756 | 494.0 |  | 460950837 | 369748 | yes | yes |
| prettier | tsrs|shared | none | 619 | 494.0 |  | 460950837 | 326260 | yes | yes |
| prettier | tsrs|tsconfig | none | 759 | 494.0 |  | 460950837 | 378172 | yes | yes |
| prettier | tsrs|concurrent | none | 2299 | 494.0 |  | 460950837 | 373472 | yes | yes |
| prettier | tsrs|cold | incremental_local | 832 | 494.0 |  | 465168483 | 310984 | yes | yes |
| prettier | tsrs|leaf | incremental_local | 264 | 494.0 |  | 465169329 | 150048 | yes | yes |
| prettier | tsrs|shared | incremental_local | 329 | 494.0 |  | 465170457 | 169728 | yes | yes |
| prettier | tsrs|tsconfig | incremental_local | 119 | 494.0 |  | 465170457 | 115112 | yes | yes |
| prettier | tsrs|concurrent | incremental_local | 333 | 494.0 |  | 465170457 | 135976 | yes | yes |
| prettier | tsrs|cold | nanocompile | 32 | 0.0 | 1124267 | 462075148 | 4880 | yes | yes |
| prettier | tsrs|leaf | nanocompile | 296 | 1.0 | 1968670 | 462919551 | 149156 | yes | yes |
| prettier | tsrs|shared | nanocompile | 361 | 1.0 | 2813919 | 463764800 | 168368 | yes | yes |
| prettier | tsrs|tsconfig | nanocompile | 191 | 1.0 | 3659168 | 464610049 | 134288 | yes | yes |
| prettier | tsrs|concurrent | nanocompile | 42 | 0.0 | 3659212 | 464610093 | 4752 | yes | yes |
| ajv | bun|cold | none | 57 | 106.0 |  | 204554873 | 96008 | yes | yes |
| ajv | bun|leaf | none | 57 | 106.0 |  | 204554873 | 93344 | yes | yes |
| ajv | bun|shared | none | 59 | 106.0 |  | 204554873 | 95048 | yes | yes |
| ajv | bun|tsconfig | none | 62 | 106.0 |  | 204554873 | 95900 | yes | yes |
| ajv | bun|concurrent | none | 157 | 106.0 |  | 204554873 | 95812 | yes | yes |
| ajv | bun|cold | nanocompile | 8 | 0.0 | 64636 | 204619553 | 5056 | yes | yes |
| ajv | bun|leaf | nanocompile | 57 | 1.0 | 64688 | 204619605 | 82732 | yes | yes |
| ajv | bun|shared | nanocompile | 69 | 1.0 | 64752 | 204619669 | 94944 | yes | yes |
| ajv | bun|tsconfig | nanocompile | 47 | 1.0 | 64804 | 204619721 | 81560 | yes | yes |
| ajv | bun|concurrent | nanocompile | 16 | 0.0 | 64848 | 204619765 | 5056 | yes | yes |
| prettier | bun|cold | none | 3270 | 494.0 |  | 460950815 | 733052 | yes | yes |
| prettier | bun|leaf | none | 3176 | 494.0 |  | 460950815 | 740572 | yes | yes |
| prettier | bun|shared | none | 3135 | 494.0 |  | 460950815 | 726432 | yes | yes |
| prettier | bun|tsconfig | none | 3236 | 494.0 |  | 460950815 | 728528 | yes | yes |
| prettier | bun|concurrent | none | 6796 | 494.0 |  | 460950815 | 728116 | yes | yes |
| prettier | bun|cold | nanocompile | 33 | 0.0 | 285799 | 461236658 | 5056 | yes | yes |
| prettier | bun|leaf | nanocompile | 305 | 1.0 | 285863 | 461236722 | 257828 | yes | yes |
| prettier | bun|shared | nanocompile | 350 | 1.0 | 285927 | 461236786 | 231296 | yes | yes |
| prettier | bun|tsconfig | nanocompile | 147 | 1.0 | 285979 | 461236838 | 193184 | yes | yes |
| prettier | bun|concurrent | nanocompile | 43 | 0.0 | 286023 | 461236882 | 5056 | yes | yes |

## What climbed

- **L0** content-addressed result cache (file hashes + `$NANO_ROOT`).
- **L1** store/restore `.tsbuildinfo` with the result.
- **L2** seed key (no source hashes) so an edit starts from sibling buildinfo.
- **L3** dirty-file scope for `bun check` (≤4 dirty paths).

`bun check` has no incremental file; L1/L2 do not apply. Seed
`.tsbuildinfo` is deleted locally after CAS store (hardlink on restore).
TS 7 / bun: NodeNext keeps matching `moduleResolution`; extends/node10
gets `bundler`. Inject gate requires `_nano_ts_error` /
`_nano_undefined_ident`, not a generic TS2304.
Correctness: `tests/typescript_worktrees.py` uses real `git worktree add`.

Harness: `python3 bench/ts_worktrees.py --repo PATH`.
Archive: `bench/archive/ts-worktrees.json` → `map_elites.json` `typescript_worktrees`.
