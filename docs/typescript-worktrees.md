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
clone that private tree, so train is a 126-file public stand-in with the
same checker × scenario grid. Re-run on the real app with:

```sh
python3 bench/ts_worktrees.py --repo /path/to/condensation-site --phase all
python3 bench/ts_worktrees.py --repo /path/to/any-ts-app --phase all
```

vite (github.com/vitejs/vite) is a pnpm-only monorepo with no root tsconfig; typecheck is workspace-wide. Held-out is ajv + prettier.

## Frozen vs baselines (checker × scenario)

Shipped lever vs `none` / `incremental_local`. **front** = nanocompile is
non-dominated in that cell.

| split | cell | front | wall nano/none | files nano/none | store | disk nano/none | rss nano/none | correct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | condensation-site/tsc|cold | yes | 5 / 391 | 0.0 / 126.0 | 56228 | 472124 / 315735 | 3944 / 154440 | yes |
| train | condensation-site/tsc|leaf | yes | 369 / 377 | 1.0 / 126.0 | 112095 | 528082 / 315826 | 152812 / 153036 | yes |
| train | condensation-site/tsc|shared | yes | 387 / 377 | 1.0 / 126.0 | 168053 | 584222 / 315917 | 154280 / 154412 | yes |
| train | condensation-site/tsc|tsconfig | yes | 380 / 340 | 1.0 / 126.0 | 224011 | 640362 / 315917 | 153840 / 151556 | yes |
| train | condensation-site/tsc|concurrent | yes | 12 / 832 | 0.0 / 126.0 | 224107 | 640731 / 315917 | 3960 / 153400 | yes |
| train | condensation-site/tsgo|cold | yes | 5 / 72 | 0.0 / 126.0 | 46045 | 411048 / 264842 | 3808 / 51284 | yes |
| train | condensation-site/tsgo|leaf | yes | 74 / 75 | 1.0 / 126.0 | 91719 | 456803 / 264923 | 50388 / 51156 | yes |
| train | condensation-site/tsgo|shared | yes | 76 / 69 | 1.0 / 126.0 | 137474 | 502720 / 265004 | 50388 / 50388 | yes |
| train | condensation-site/tsgo|tsconfig | yes | 72 / 71 | 1.0 / 126.0 | 183229 | 548637 / 265004 | 50772 / 47888 | yes |
| train | condensation-site/tsgo|concurrent | yes | 11 / 124 | 0.0 / 126.0 | 183325 | 548976 / 265004 | 3816 / 50388 | yes |
| train | condensation-site/tsrs|cold | yes | 5 / 44 | 0.0 / 126.0 | 46536 | 413994 / 267297 | 3832 / 47140 | yes |
| train | condensation-site/tsrs|leaf | yes | 52 / 42 | 1.0 / 126.0 | 92701 | 460240 / 267378 | 47340 / 47096 | yes |
| train | condensation-site/tsrs|shared | yes | 45 / 45 | 1.0 / 126.0 | 138947 | 506648 / 267459 | 47356 / 47136 | yes |
| train | condensation-site/tsrs|tsconfig | yes | 49 / 41 | 1.0 / 126.0 | 185193 | 553056 / 267459 | 47364 / 47148 | yes |
| train | condensation-site/tsrs|concurrent | yes | 9 / 60 | 0.0 / 126.0 | 185289 | 553395 / 267459 | 3588 / 47120 | yes |
| train | condensation-site/bun|cold | yes | 7 / 32 | 0.0 / 126.0 | 26182 | 293743 / 267275 | 5056 / 58540 | yes |
| train | condensation-site/bun|leaf | yes | 39 / 32 | 1.0 / 126.0 | 52320 | 319881 / 267275 | 58480 / 58724 | yes |
| train | condensation-site/bun|shared | yes | 35 / 31 | 1.0 / 126.0 | 78458 | 346019 / 267275 | 57308 / 57664 | yes |
| train | condensation-site/bun|tsconfig | yes | 37 / 31 | 1.0 / 126.0 | 104596 | 372157 / 267275 | 58024 / 57456 | yes |
| train | condensation-site/bun|concurrent | yes | 15 / 57 | 0.0 / 126.0 | 104640 | 372201 / 267275 | 5056 / 59448 | yes |
| held_out | ajv/tsc|cold | yes | 7 / 1215 | 0.0 / 198.0 | 94931 | 204898596 / 204553936 | 4200 / 239212 | yes |
| held_out | ajv/tsc|leaf | yes | 580 / 1219 | 1.0 / 198.0 | 139473 | 204943138 / 204553936 | 203516 / 237864 | yes |
| held_out | ajv/tsc|shared | yes | 729 / 1226 | 1.0 / 198.0 | 234316 | 205038345 / 204553936 | 216712 / 237640 | yes |
| held_out | ajv/tsc|tsconfig | yes | 637 / 1228 | 1.0 / 198.0 | 329159 | 205133552 / 204553936 | 212996 / 239000 | yes |
| held_out | ajv/tsc|concurrent | yes | 18 / 3087 | 0.0 / 198.0 | 329255 | 205134376 / 204553936 | 4216 / 238372 | yes |
| held_out | prettier/tsc|cold | yes | 103 / 18578 | 0.0 / 556.0 | 1889060 | 465484952 / 460949873 | 18168 / 1233608 | yes |
| held_out | prettier/tsc|leaf | yes | 1616 / 18245 | 1.0 / 556.0 | 3777747 | 467373718 / 460949873 | 415128 / 1221752 | yes |
| held_out | prettier/tsc|shared | yes | 3004 / 18401 | 1.0 / 556.0 | 5668330 | 469266276 / 460949873 | 511380 / 1219628 | yes |
| held_out | prettier/tsc|tsconfig | yes | 2180 / 18620 | 1.0 / 556.0 | 7558913 | 471158834 / 460949873 | 468780 / 1222548 | yes |
| held_out | prettier/tsc|concurrent | yes | 216 / 26858 | 0.0 / 556.0 | 7559009 | 471162801 / 460949873 | 18280 / 1251104 | yes |
| held_out | ajv/tsgo|cold | yes | 144 / 142 | 1.0 / 198.0 | 125 | 204945207 / 204554113 | 106060 / 109324 | yes |
| held_out | ajv/tsgo|leaf | yes | 101 / 153 | 1.0 / 198.0 | 150 | 204945232 / 204554113 | 85520 / 110036 | yes |
| held_out | ajv/tsgo|shared | yes | 128 / 146 | 1.0 / 198.0 | 175 | 204945581 / 204554113 | 90960 / 110032 | yes |
| held_out | ajv/tsgo|tsconfig | yes | 105 / 148 | 1.0 / 198.0 | 200 | 204945606 / 204554113 | 85712 / 108560 | yes |
| held_out | ajv/tsgo|concurrent | yes | 417 / 381 | 1.0 / 198.0 | 300 | 204945706 / 204554113 | 87568 / 111952 | yes |
| held_out | ajv/tsrs|cold | yes | 63 / 57 | 1.0 / 198.0 | 125 | 204945567 / 204554113 | 56064 / 55852 | yes |
| held_out | ajv/tsrs|leaf | yes | 53 / 57 | 1.0 / 198.0 | 150 | 204945592 / 204554113 | 48344 / 54148 | yes |
| held_out | ajv/tsrs|shared | yes | 64 / 58 | 1.0 / 198.0 | 175 | 204945941 / 204554113 | 55608 / 54012 | yes |
| held_out | ajv/tsrs|tsconfig | yes | 54 / 57 | 1.0 / 198.0 | 200 | 204945966 / 204554113 | 47332 / 53956 | yes |
| held_out | ajv/tsrs|concurrent | yes | 202 / 126 | 1.0 / 198.0 | 300 | 204946066 / 204554113 | 59480 / 53572 | yes |
| held_out | ajv/bun|cold | yes | 69 / 60 | 1.0 / 198.0 | 125 | 204554260 / 204554091 | 95328 / 95320 | yes |
| held_out | ajv/bun|leaf | yes | 71 / 66 | 1.0 / 198.0 | 150 | 204554285 / 204554091 | 95952 / 95244 | yes |
| held_out | ajv/bun|shared | yes | 70 / 66 | 1.0 / 198.0 | 175 | 204554310 / 204554091 | 95516 / 94484 | yes |
| held_out | ajv/bun|tsconfig | yes | 66 / 63 | 1.0 / 198.0 | 200 | 204554335 / 204554091 | 95004 / 96284 | yes |
| held_out | ajv/bun|concurrent | yes | 246 / 161 | 1.0 / 198.0 | 300 | 204554435 / 204554091 | 96216 / 96268 | yes |
| held_out | prettier/tsgo|cold | NO | 412 / 297 | 1.0 / 556.0 | 125 | 464521654 / 460950050 | 279632 / 222672 | no |
| held_out | prettier/tsgo|leaf | NO | 402 / 572 | 1.0 / 556.0 | 150 | 464521778 / 460950050 | 274304 / 228296 | no |
| held_out | prettier/tsgo|shared | NO | 420 / 538 | 1.0 / 556.0 | 175 | 464521902 / 460950050 | 279184 / 229312 | no |
| held_out | prettier/tsgo|tsconfig | NO | 352 / 482 | 1.0 / 556.0 | 200 | 464521927 / 460950050 | 250700 / 229264 | no |
| held_out | prettier/tsgo|concurrent | NO | 1380 / 870 | 1.0 / 556.0 | 300 | 464521865 / 460950050 | 274896 / 230288 | no |
| held_out | prettier/tsrs|cold | NO | 160 / 88 | 1.0 / 556.0 | 125 | 464524409 / 460950050 | 109104 / 93052 | no |
| held_out | prettier/tsrs|leaf | NO | 152 / 94 | 1.0 / 556.0 | 150 | 464524533 / 460950050 | 117432 / 92560 | no |
| held_out | prettier/tsrs|shared | NO | 155 / 87 | 1.0 / 556.0 | 175 | 464524657 / 460950050 | 118120 / 90952 | no |
| held_out | prettier/tsrs|tsconfig | NO | 148 / 95 | 1.0 / 556.0 | 200 | 464524682 / 460950050 | 115944 / 90288 | no |
| held_out | prettier/tsrs|concurrent | NO | 457 / 212 | 1.0 / 556.0 | 300 | 464524620 / 460950050 | 119888 / 91948 | no |
| held_out | prettier/bun|cold | NO | 190 / 123 | 1.0 / 556.0 | 125 | 460950197 / 460950028 | 193316 / 189552 | no |
| held_out | prettier/bun|leaf | NO | 175 / 134 | 1.0 / 556.0 | 150 | 460950222 / 460950028 | 187936 / 192928 | no |
| held_out | prettier/bun|shared | NO | 179 / 126 | 1.0 / 556.0 | 175 | 460950247 / 460950028 | 193188 / 182560 | no |
| held_out | prettier/bun|tsconfig | NO | 172 / 133 | 1.0 / 556.0 | 200 | 460950272 / 460950028 | 188568 / 192808 | no |
| held_out | prettier/bun|concurrent | NO | 560 / 309 | 1.0 / 556.0 | 300 | 460950372 / 460950028 | 192340 / 191508 | no |

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
  "NANOCOMPILE_TSRS_CHECKERS": "4"
}
```

Cache key: checker identity + argv + tsconfig + source hashes, paths as
`$NANO_ROOT`. Only zero-error results are stored.

## Hill-climb

| lever | vs | keep | note |
| --- | --- | --- | --- |
| `l0_result_cache` | none | yes | on frontier in at least one cell |
| `l1_incremental` | l0_result_cache | yes | on frontier in at least one cell |
| `l2_seed_buildinfo` | l1_incremental | yes | on frontier in at least one cell |
| `l0_result_cache` | none | yes | on frontier in at least one cell |
| `l1_incremental` | l0_result_cache | yes | on frontier in at least one cell |
| `l2_seed_buildinfo` | l1_incremental | yes | on frontier in at least one cell |
| `l0_result_cache` | none | yes | on frontier in at least one cell |
| `l1_incremental` | l0_result_cache | yes | on frontier in at least one cell |
| `l2_seed_buildinfo` | l1_incremental | yes | on frontier in at least one cell |
| `l0_result_cache` | none | yes | on frontier in at least one cell |
| `l1_incremental` | l0_result_cache | yes | on frontier in at least one cell |
| `l2_seed_buildinfo` | l1_incremental | yes | on frontier in at least one cell |

## Generalization (held-out vs none)

| metric | train gain vs none | held-out gain vs none | fraction that survived |
| --- | --- | --- | --- |
| wall_ms | 46.4% | 90.1% | 194.1% |
| files_rechecked | 99.5% | 99.7% | 100.2% |
| store_bytes | n/a | n/a | n/a |
| disk_bytes | -70.8% | -0.7% | 1.0% |
| rss_kb | 37.8% | 62.1% | 164.3% |

## Pareto frontier per cell

### Train

**condensation-site/tsc|cold** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 391 | 126.0 | 0 | 315735 | 154440 |
| incremental_local | incremental_local | 386 | 126.0 | 0 | 415851 | 155460 |
| nanocompile | l0_result_cache | 4 | 0.0 | 26140 | 303349 | 3504 |
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)

**condensation-site/tsc|leaf** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 377 | 126.0 | 0 | 315826 | 153036 |
| incremental_local | incremental_local | 377 | 126.0 | 0 | 415942 | 152560 |
| nanocompile | l0_result_cache | 383 | 1.0 | 52236 | 339137 | 154856 |
| nanocompile | l1_incremental | 383 | 1.0 | 52236 | 379065 | 154676 |
| nanocompile | l2_seed_buildinfo | 369 | 1.0 | 112095 | 528082 | 152812 |

**condensation-site/tsc|shared** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 377 | 126.0 | 0 | 315917 | 154412 |
| incremental_local | incremental_local | 395 | 126.0 | 0 | 416033 | 151848 |
| nanocompile | l0_result_cache | 383 | 1.0 | 78332 | 374925 | 150356 |
| nanocompile | l1_incremental | 368 | 1.0 | 78332 | 434828 | 156788 |
- dominated by `nanocompile` (l0_result_cache)

**condensation-site/tsc|tsconfig** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 340 | 126.0 | 0 | 315917 | 151556 |
| incremental_local | incremental_local | 360 | 126.0 | 0 | 416033 | 149900 |
| nanocompile | l0_result_cache | 378 | 1.0 | 104428 | 410713 | 155476 |
| nanocompile | l2_seed_buildinfo | 380 | 1.0 | 224011 | 640362 | 153840 |
- dominated by `nanocompile` (l0_result_cache)

**condensation-site/tsc|concurrent** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 832 | 126.0 | 0 | 315917 | 153400 |
| nanocompile | l0_result_cache | 11 | 0.0 | 104472 | 410757 | 3632 |
| nanocompile | l1_incremental | 11 | 0.0 | 104472 | 490635 | 3592 |
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)

**condensation-site/tsgo|cold** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 72 | 126.0 | 0 | 264842 | 51284 |
| incremental_local | incremental_local | 68 | 126.0 | 0 | 364963 | 50516 |
| nanocompile | l0_result_cache | 4 | 0.0 | 26140 | 293188 | 3592 |
| nanocompile | l1_incremental | 4 | 0.0 | 26140 | 313141 | 3584 |
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)

**condensation-site/tsgo|leaf** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 75 | 126.0 | 0 | 264923 | 51156 |
| incremental_local | incremental_local | 74 | 126.0 | 0 | 365044 | 51028 |
| nanocompile | l0_result_cache | 72 | 1.0 | 52236 | 318793 | 50388 |
| nanocompile | l1_incremental | 71 | 1.0 | 52236 | 358721 | 50516 |
- dominated by `nanocompile` (l0_result_cache)

**condensation-site/tsgo|shared** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 69 | 126.0 | 0 | 265004 | 50388 |
| incremental_local | incremental_local | 71 | 126.0 | 0 | 365125 | 50256 |
| nanocompile | l0_result_cache | 74 | 1.0 | 78332 | 344398 | 51088 |
| nanocompile | l1_incremental | 71 | 1.0 | 78332 | 404301 | 49940 |
- dominated by `nanocompile` (l1_incremental)

**condensation-site/tsgo|tsconfig** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 71 | 126.0 | 0 | 265004 | 47888 |
| incremental_local | incremental_local | 70 | 126.0 | 0 | 365125 | 49104 |
| nanocompile | l0_result_cache | 75 | 1.0 | 104428 | 370003 | 51540 |
| nanocompile | l1_incremental | 76 | 1.0 | 104428 | 449881 | 50132 |
| nanocompile | l2_seed_buildinfo | 72 | 1.0 | 183229 | 548637 | 50772 |

**condensation-site/tsgo|concurrent** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 124 | 126.0 | 0 | 265004 | 50388 |
| incremental_local | incremental_local | 121 | 126.0 | 0 | 365125 | 51412 |
| nanocompile | l0_result_cache | 9 | 0.0 | 104472 | 370047 | 3604 |
| nanocompile | l1_incremental | 9 | 0.0 | 104472 | 449925 | 3592 |
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)

**condensation-site/tsrs|cold** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 44 | 126.0 | 0 | 267297 | 47140 |
| incremental_local | incremental_local | 43 | 126.0 | 0 | 367418 | 47360 |
| nanocompile | l0_result_cache | 4 | 0.0 | 26140 | 293679 | 3612 |
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)

**condensation-site/tsrs|leaf** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 42 | 126.0 | 0 | 267378 | 47096 |
| nanocompile | l0_result_cache | 47 | 1.0 | 52236 | 319856 | 47092 |
| nanocompile | l1_incremental | 46 | 1.0 | 52236 | 359703 | 47364 |
- dominated by `nanocompile` (l0_result_cache)

**condensation-site/tsrs|shared** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 45 | 126.0 | 0 | 267459 | 47136 |
| incremental_local | incremental_local | 41 | 126.0 | 0 | 367580 | 47356 |
| nanocompile | l0_result_cache | 46 | 1.0 | 78332 | 346033 | 47144 |
| nanocompile | l1_incremental | 46 | 1.0 | 78332 | 405774 | 47352 |
| nanocompile | l2_seed_buildinfo | 45 | 1.0 | 138947 | 506648 | 47356 |

**condensation-site/tsrs|tsconfig** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 41 | 126.0 | 0 | 267459 | 47148 |
| incremental_local | incremental_local | 39 | 126.0 | 0 | 367580 | 47348 |
| nanocompile | l0_result_cache | 45 | 1.0 | 104428 | 372129 | 47140 |
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)

**condensation-site/tsrs|concurrent** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 60 | 126.0 | 0 | 267459 | 47120 |
| nanocompile | l0_result_cache | 10 | 0.0 | 104472 | 372173 | 3612 |
| nanocompile | l1_incremental | 9 | 0.0 | 104472 | 451889 | 3500 |
- dominated by `nanocompile` (l1_incremental)

**condensation-site/bun|cold** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 32 | 126.0 | 0 | 267275 | 58540 |
| nanocompile | l0_result_cache | 5 | 0.0 | 26182 | 293699 | 5056 |
| nanocompile | l1_incremental | 6 | 0.0 | 26182 | 293677 | 5056 |
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)

**condensation-site/bun|leaf** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 32 | 126.0 | 0 | 267275 | 58724 |
| nanocompile | l0_result_cache | 36 | 1.0 | 52320 | 319837 | 57912 |
| nanocompile | l1_incremental | 37 | 1.0 | 52320 | 319815 | 57768 |
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)

**condensation-site/bun|shared** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 31 | 126.0 | 0 | 267275 | 57664 |
| nanocompile | l0_result_cache | 35 | 1.0 | 78458 | 345975 | 57404 |
| nanocompile | l1_incremental | 36 | 1.0 | 78458 | 345953 | 58272 |
| nanocompile | l2_seed_buildinfo | 35 | 1.0 | 78458 | 346019 | 57308 |

**condensation-site/bun|tsconfig** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 31 | 126.0 | 0 | 267275 | 57456 |
| nanocompile | l1_incremental | 34 | 1.0 | 104596 | 372091 | 57076 |
- dominated by `nanocompile` (l1_incremental)
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)

**condensation-site/bun|concurrent** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 57 | 126.0 | 0 | 267275 | 59448 |
| nanocompile | l1_incremental | 11 | 0.0 | 104640 | 372135 | 5056 |
- dominated by `nanocompile` (l1_incremental)
- dominated by `nanocompile` (l0_result_cache)
- dominated by `nanocompile` (l1_incremental)

### Held-out

**ajv/bun|cold** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 60 | 198.0 | 0 | 204554091 | 95320 |
| nanocompile | l2_seed_buildinfo | 69 | 1.0 | 125 | 204554260 | 95328 |

**ajv/bun|leaf** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 66 | 198.0 | 0 | 204554091 | 95244 |
| nanocompile | l2_seed_buildinfo | 71 | 1.0 | 150 | 204554285 | 95952 |

**ajv/bun|shared** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 66 | 198.0 | 0 | 204554091 | 94484 |
| nanocompile | l2_seed_buildinfo | 70 | 1.0 | 175 | 204554310 | 95516 |

**ajv/bun|tsconfig** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 63 | 198.0 | 0 | 204554091 | 96284 |
| nanocompile | l2_seed_buildinfo | 66 | 1.0 | 200 | 204554335 | 95004 |

**ajv/bun|concurrent** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 161 | 198.0 | 0 | 204554091 | 96268 |
| nanocompile | l2_seed_buildinfo | 246 | 1.0 | 300 | 204554435 | 96216 |

**prettier/bun|cold** — nanocompile on frontier: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |

**prettier/bun|leaf** — nanocompile on frontier: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |

**prettier/bun|shared** — nanocompile on frontier: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |

**prettier/bun|tsconfig** — nanocompile on frontier: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |

**prettier/bun|concurrent** — nanocompile on frontier: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |

**ajv/tsc|cold** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 1215 | 198.0 | 0 | 204553936 | 239212 |
| nanocompile | l2_seed_buildinfo | 7 | 0.0 | 94931 | 204898596 | 4200 |

**ajv/tsc|leaf** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 1219 | 198.0 | 0 | 204553936 | 237864 |
| incremental_local | incremental_local | 573 | 198.0 | 0 | 204803862 | 204376 |
| nanocompile | l2_seed_buildinfo | 580 | 1.0 | 139473 | 204943138 | 203516 |

**ajv/tsc|shared** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 1226 | 198.0 | 0 | 204553936 | 237640 |
| incremental_local | incremental_local | 703 | 198.0 | 0 | 204804226 | 214024 |
| nanocompile | l2_seed_buildinfo | 729 | 1.0 | 234316 | 205038345 | 216712 |

**ajv/tsc|tsconfig** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 1228 | 198.0 | 0 | 204553936 | 239000 |
| incremental_local | incremental_local | 593 | 198.0 | 0 | 204804226 | 207648 |
| nanocompile | l2_seed_buildinfo | 637 | 1.0 | 329159 | 205133552 | 212996 |

**ajv/tsc|concurrent** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 3087 | 198.0 | 0 | 204553936 | 238372 |
| incremental_local | incremental_local | 1438 | 198.0 | 0 | 204804226 | 207616 |
| nanocompile | l2_seed_buildinfo | 18 | 0.0 | 329255 | 205134376 | 4216 |

**prettier/tsc|cold** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 18578 | 556.0 | 0 | 460949873 | 1233608 |
| incremental_local | incremental_local | 18560 | 556.0 | 0 | 463596089 | 1232136 |
| nanocompile | l2_seed_buildinfo | 103 | 0.0 | 1889060 | 465484952 | 18168 |

**prettier/tsc|leaf** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 18245 | 556.0 | 0 | 460949873 | 1221752 |
| incremental_local | incremental_local | 1536 | 556.0 | 0 | 463596168 | 415860 |
| nanocompile | l2_seed_buildinfo | 1616 | 1.0 | 3777747 | 467373718 | 415128 |

**prettier/tsc|shared** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 18401 | 556.0 | 0 | 460949873 | 1219628 |
| incremental_local | incremental_local | 2994 | 556.0 | 0 | 463598064 | 511228 |
| nanocompile | l2_seed_buildinfo | 3004 | 1.0 | 5668330 | 469266276 | 511380 |

**prettier/tsc|tsconfig** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 18620 | 556.0 | 0 | 460949873 | 1222548 |
| incremental_local | incremental_local | 1501 | 556.0 | 0 | 463598064 | 409760 |
| nanocompile | l2_seed_buildinfo | 2180 | 1.0 | 7558913 | 471158834 | 468780 |

**prettier/tsc|concurrent** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 26858 | 556.0 | 0 | 460949873 | 1251104 |
| incremental_local | incremental_local | 4265 | 556.0 | 0 | 463598064 | 469500 |
| nanocompile | l2_seed_buildinfo | 216 | 0.0 | 7559009 | 471162801 | 18280 |

**ajv/tsgo|cold** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 142 | 198.0 | 0 | 204554113 | 109324 |
| incremental_local | incremental_local | 144 | 198.0 | 0 | 204945284 | 105868 |
| nanocompile | l2_seed_buildinfo | 144 | 1.0 | 125 | 204945207 | 106060 |

**ajv/tsgo|leaf** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 153 | 198.0 | 0 | 204554113 | 110036 |
| incremental_local | incremental_local | 117 | 198.0 | 0 | 204945284 | 84368 |
| nanocompile | l2_seed_buildinfo | 101 | 1.0 | 150 | 204945232 | 85520 |

**ajv/tsgo|shared** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 146 | 198.0 | 0 | 204554113 | 110032 |
| incremental_local | incremental_local | 123 | 198.0 | 0 | 204945608 | 92304 |
| nanocompile | l2_seed_buildinfo | 128 | 1.0 | 175 | 204945581 | 90960 |

**ajv/tsgo|tsconfig** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 148 | 198.0 | 0 | 204554113 | 108560 |
| incremental_local | incremental_local | 105 | 198.0 | 0 | 204945608 | 86612 |
| nanocompile | l2_seed_buildinfo | 105 | 1.0 | 200 | 204945606 | 85712 |

**ajv/tsgo|concurrent** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 381 | 198.0 | 0 | 204554113 | 111952 |
| incremental_local | incremental_local | 256 | 198.0 | 0 | 204945608 | 88340 |
| nanocompile | l2_seed_buildinfo | 417 | 1.0 | 300 | 204945706 | 87568 |

**prettier/tsgo|cold** — nanocompile on frontier: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |

**prettier/tsgo|leaf** — nanocompile on frontier: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |

**prettier/tsgo|shared** — nanocompile on frontier: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |

**prettier/tsgo|tsconfig** — nanocompile on frontier: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |

**prettier/tsgo|concurrent** — nanocompile on frontier: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |

**ajv/tsrs|cold** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 57 | 198.0 | 0 | 204554113 | 55852 |
| nanocompile | l2_seed_buildinfo | 63 | 1.0 | 125 | 204945567 | 56064 |

**ajv/tsrs|leaf** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 57 | 198.0 | 0 | 204554113 | 54148 |
| incremental_local | incremental_local | 47 | 198.0 | 0 | 204945644 | 48132 |
| nanocompile | l2_seed_buildinfo | 53 | 1.0 | 150 | 204945592 | 48344 |

**ajv/tsrs|shared** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 58 | 198.0 | 0 | 204554113 | 54012 |
| nanocompile | l2_seed_buildinfo | 64 | 1.0 | 175 | 204945941 | 55608 |

**ajv/tsrs|tsconfig** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 57 | 198.0 | 0 | 204554113 | 53956 |
| incremental_local | incremental_local | 46 | 198.0 | 0 | 204945968 | 48352 |
| nanocompile | l2_seed_buildinfo | 54 | 1.0 | 200 | 204945966 | 47332 |

**ajv/tsrs|concurrent** — nanocompile on frontier: yes

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |
| none | none | 126 | 198.0 | 0 | 204554113 | 53572 |
| incremental_local | incremental_local | 100 | 198.0 | 0 | 204945968 | 54876 |
| nanocompile | l2_seed_buildinfo | 202 | 1.0 | 300 | 204946066 | 59480 |

**prettier/tsrs|cold** — nanocompile on frontier: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |

**prettier/tsrs|leaf** — nanocompile on frontier: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |

**prettier/tsrs|shared** — nanocompile on frontier: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |

**prettier/tsrs|tsconfig** — nanocompile on frontier: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |

**prettier/tsrs|concurrent** — nanocompile on frontier: NO

| approach | lever | wall | files | store | disk | rss kb |
| --- | --- | --- | --- | --- | --- | --- |


## Rows

| sample | cell | approach | wall | files | store | disk | rss | correct | ok |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| condensation-site | tsc|cold | none | 391 | 126.0 |  | 315735 | 154440 | yes | yes |
| condensation-site | tsc|leaf | none | 377 | 126.0 |  | 315826 | 153036 | yes | yes |
| condensation-site | tsc|shared | none | 377 | 126.0 |  | 315917 | 154412 | yes | yes |
| condensation-site | tsc|tsconfig | none | 340 | 126.0 |  | 315917 | 151556 | yes | yes |
| condensation-site | tsc|concurrent | none | 832 | 126.0 |  | 315917 | 153400 | yes | yes |
| condensation-site | tsc|cold | incremental_local | 386 | 126.0 |  | 415851 | 155460 | yes | yes |
| condensation-site | tsc|leaf | incremental_local | 377 | 126.0 |  | 415942 | 152560 | yes | yes |
| condensation-site | tsc|shared | incremental_local | 395 | 126.0 |  | 416033 | 151848 | yes | yes |
| condensation-site | tsc|tsconfig | incremental_local | 360 | 126.0 |  | 416033 | 149900 | yes | yes |
| condensation-site | tsc|concurrent | incremental_local | 846 | 126.0 |  | 416033 | 153824 | yes | yes |
| condensation-site | tsc|cold | nanocompile | 4 | 0.0 | 26140 | 303349 | 3504 | yes | yes |
| condensation-site | tsc|leaf | nanocompile | 383 | 1.0 | 52236 | 339137 | 154856 | yes | yes |
| condensation-site | tsc|shared | nanocompile | 383 | 1.0 | 78332 | 374925 | 150356 | yes | yes |
| condensation-site | tsc|tsconfig | nanocompile | 378 | 1.0 | 104428 | 410713 | 155476 | yes | yes |
| condensation-site | tsc|concurrent | nanocompile | 11 | 0.0 | 104472 | 410757 | 3632 | yes | yes |
| condensation-site | tsc|cold | nanocompile | 4 | 0.0 | 26140 | 323302 | 3600 | yes | yes |
| condensation-site | tsc|leaf | nanocompile | 383 | 1.0 | 52236 | 379065 | 154676 | yes | yes |
| condensation-site | tsc|shared | nanocompile | 368 | 1.0 | 78332 | 434828 | 156788 | yes | yes |
| condensation-site | tsc|tsconfig | nanocompile | 394 | 1.0 | 104428 | 490591 | 156940 | yes | yes |
| condensation-site | tsc|concurrent | nanocompile | 11 | 0.0 | 104472 | 490635 | 3592 | yes | yes |
| condensation-site | tsc|cold | nanocompile | 5 | 0.0 | 56228 | 472124 | 3944 | yes | yes |
| condensation-site | tsc|leaf | nanocompile | 369 | 1.0 | 112095 | 528082 | 152812 | yes | yes |
| condensation-site | tsc|shared | nanocompile | 387 | 1.0 | 168053 | 584222 | 154280 | yes | yes |
| condensation-site | tsc|tsconfig | nanocompile | 380 | 1.0 | 224011 | 640362 | 153840 | yes | yes |
| condensation-site | tsc|concurrent | nanocompile | 12 | 0.0 | 224107 | 640731 | 3960 | yes | yes |
| condensation-site | tsgo|cold | none | 72 | 126.0 |  | 264842 | 51284 | yes | yes |
| condensation-site | tsgo|leaf | none | 75 | 126.0 |  | 264923 | 51156 | yes | yes |
| condensation-site | tsgo|shared | none | 69 | 126.0 |  | 265004 | 50388 | yes | yes |
| condensation-site | tsgo|tsconfig | none | 71 | 126.0 |  | 265004 | 47888 | yes | yes |
| condensation-site | tsgo|concurrent | none | 124 | 126.0 |  | 265004 | 50388 | yes | yes |
| condensation-site | tsgo|cold | incremental_local | 68 | 126.0 |  | 364963 | 50516 | yes | yes |
| condensation-site | tsgo|leaf | incremental_local | 74 | 126.0 |  | 365044 | 51028 | yes | yes |
| condensation-site | tsgo|shared | incremental_local | 71 | 126.0 |  | 365125 | 50256 | yes | yes |
| condensation-site | tsgo|tsconfig | incremental_local | 70 | 126.0 |  | 365125 | 49104 | yes | yes |
| condensation-site | tsgo|concurrent | incremental_local | 121 | 126.0 |  | 365125 | 51412 | yes | yes |
| condensation-site | tsgo|cold | nanocompile | 4 | 0.0 | 26140 | 293188 | 3592 | yes | yes |
| condensation-site | tsgo|leaf | nanocompile | 72 | 1.0 | 52236 | 318793 | 50388 | yes | yes |
| condensation-site | tsgo|shared | nanocompile | 74 | 1.0 | 78332 | 344398 | 51088 | yes | yes |
| condensation-site | tsgo|tsconfig | nanocompile | 75 | 1.0 | 104428 | 370003 | 51540 | yes | yes |
| condensation-site | tsgo|concurrent | nanocompile | 9 | 0.0 | 104472 | 370047 | 3604 | yes | yes |
| condensation-site | tsgo|cold | nanocompile | 4 | 0.0 | 26140 | 313141 | 3584 | yes | yes |
| condensation-site | tsgo|leaf | nanocompile | 71 | 1.0 | 52236 | 358721 | 50516 | yes | yes |
| condensation-site | tsgo|shared | nanocompile | 71 | 1.0 | 78332 | 404301 | 49940 | yes | yes |
| condensation-site | tsgo|tsconfig | nanocompile | 76 | 1.0 | 104428 | 449881 | 50132 | yes | yes |
| condensation-site | tsgo|concurrent | nanocompile | 9 | 0.0 | 104472 | 449925 | 3592 | yes | yes |
| condensation-site | tsgo|cold | nanocompile | 5 | 0.0 | 46045 | 411048 | 3808 | yes | yes |
| condensation-site | tsgo|leaf | nanocompile | 74 | 1.0 | 91719 | 456803 | 50388 | yes | yes |
| condensation-site | tsgo|shared | nanocompile | 76 | 1.0 | 137474 | 502720 | 50388 | yes | yes |
| condensation-site | tsgo|tsconfig | nanocompile | 72 | 1.0 | 183229 | 548637 | 50772 | yes | yes |
| condensation-site | tsgo|concurrent | nanocompile | 11 | 0.0 | 183325 | 548976 | 3816 | yes | yes |
| condensation-site | tsrs|cold | none | 44 | 126.0 |  | 267297 | 47140 | yes | yes |
| condensation-site | tsrs|leaf | none | 42 | 126.0 |  | 267378 | 47096 | yes | yes |
| condensation-site | tsrs|shared | none | 45 | 126.0 |  | 267459 | 47136 | yes | yes |
| condensation-site | tsrs|tsconfig | none | 41 | 126.0 |  | 267459 | 47148 | yes | yes |
| condensation-site | tsrs|concurrent | none | 60 | 126.0 |  | 267459 | 47120 | yes | yes |
| condensation-site | tsrs|cold | incremental_local | 43 | 126.0 |  | 367418 | 47360 | yes | yes |
| condensation-site | tsrs|leaf | incremental_local | 47 | 126.0 |  | 367499 | 47360 | yes | yes |
| condensation-site | tsrs|shared | incremental_local | 41 | 126.0 |  | 367580 | 47356 | yes | yes |
| condensation-site | tsrs|tsconfig | incremental_local | 39 | 126.0 |  | 367580 | 47348 | yes | yes |
| condensation-site | tsrs|concurrent | incremental_local | 61 | 126.0 |  | 367580 | 47364 | yes | yes |
| condensation-site | tsrs|cold | nanocompile | 4 | 0.0 | 26140 | 293679 | 3612 | yes | yes |
| condensation-site | tsrs|leaf | nanocompile | 47 | 1.0 | 52236 | 319856 | 47092 | yes | yes |
| condensation-site | tsrs|shared | nanocompile | 46 | 1.0 | 78332 | 346033 | 47144 | yes | yes |
| condensation-site | tsrs|tsconfig | nanocompile | 45 | 1.0 | 104428 | 372129 | 47140 | yes | yes |
| condensation-site | tsrs|concurrent | nanocompile | 10 | 0.0 | 104472 | 372173 | 3612 | yes | yes |
| condensation-site | tsrs|cold | nanocompile | 4 | 0.0 | 26140 | 313632 | 3632 | yes | yes |
| condensation-site | tsrs|leaf | nanocompile | 46 | 1.0 | 52236 | 359703 | 47364 | yes | yes |
| condensation-site | tsrs|shared | nanocompile | 46 | 1.0 | 78332 | 405774 | 47352 | yes | yes |
| condensation-site | tsrs|tsconfig | nanocompile | 45 | 1.0 | 104428 | 451845 | 47360 | yes | yes |
| condensation-site | tsrs|concurrent | nanocompile | 9 | 0.0 | 104472 | 451889 | 3500 | yes | yes |
| condensation-site | tsrs|cold | nanocompile | 5 | 0.0 | 46536 | 413994 | 3832 | yes | yes |
| condensation-site | tsrs|leaf | nanocompile | 52 | 1.0 | 92701 | 460240 | 47340 | yes | yes |
| condensation-site | tsrs|shared | nanocompile | 45 | 1.0 | 138947 | 506648 | 47356 | yes | yes |
| condensation-site | tsrs|tsconfig | nanocompile | 49 | 1.0 | 185193 | 553056 | 47364 | yes | yes |
| condensation-site | tsrs|concurrent | nanocompile | 9 | 0.0 | 185289 | 553395 | 3588 | yes | yes |
| condensation-site | bun|cold | none | 32 | 126.0 |  | 267275 | 58540 | yes | yes |
| condensation-site | bun|leaf | none | 32 | 126.0 |  | 267275 | 58724 | yes | yes |
| condensation-site | bun|shared | none | 31 | 126.0 |  | 267275 | 57664 | yes | yes |
| condensation-site | bun|tsconfig | none | 31 | 126.0 |  | 267275 | 57456 | yes | yes |
| condensation-site | bun|concurrent | none | 57 | 126.0 |  | 267275 | 59448 | yes | yes |
| condensation-site | bun|cold | nanocompile | 5 | 0.0 | 26182 | 293699 | 5056 | yes | yes |
| condensation-site | bun|leaf | nanocompile | 36 | 1.0 | 52320 | 319837 | 57912 | yes | yes |
| condensation-site | bun|shared | nanocompile | 35 | 1.0 | 78458 | 345975 | 57404 | yes | yes |
| condensation-site | bun|tsconfig | nanocompile | 36 | 1.0 | 104596 | 372113 | 57824 | yes | yes |
| condensation-site | bun|concurrent | nanocompile | 11 | 0.0 | 104640 | 372157 | 5056 | yes | yes |
| condensation-site | bun|cold | nanocompile | 6 | 0.0 | 26182 | 293677 | 5056 | yes | yes |
| condensation-site | bun|leaf | nanocompile | 37 | 1.0 | 52320 | 319815 | 57768 | yes | yes |
| condensation-site | bun|shared | nanocompile | 36 | 1.0 | 78458 | 345953 | 58272 | yes | yes |
| condensation-site | bun|tsconfig | nanocompile | 34 | 1.0 | 104596 | 372091 | 57076 | yes | yes |
| condensation-site | bun|concurrent | nanocompile | 11 | 0.0 | 104640 | 372135 | 5056 | yes | yes |
| condensation-site | bun|cold | nanocompile | 7 | 0.0 | 26182 | 293743 | 5056 | yes | yes |
| condensation-site | bun|leaf | nanocompile | 39 | 1.0 | 52320 | 319881 | 58480 | yes | yes |
| condensation-site | bun|shared | nanocompile | 35 | 1.0 | 78458 | 346019 | 57308 | yes | yes |
| condensation-site | bun|tsconfig | nanocompile | 37 | 1.0 | 104596 | 372157 | 58024 | yes | yes |
| condensation-site | bun|concurrent | nanocompile | 15 | 0.0 | 104640 | 372201 | 5056 | yes | yes |
| ajv | tsc|cold | none | 1215 | 198.0 |  | 204553936 | 239212 | yes | yes |
| ajv | tsc|leaf | none | 1219 | 198.0 |  | 204553936 | 237864 | yes | yes |
| ajv | tsc|shared | none | 1226 | 198.0 |  | 204553936 | 237640 | yes | yes |
| ajv | tsc|tsconfig | none | 1228 | 198.0 |  | 204553936 | 239000 | yes | yes |
| ajv | tsc|concurrent | none | 3087 | 198.0 |  | 204553936 | 238372 | yes | yes |
| ajv | tsc|cold | incremental_local | 1240 | 198.0 |  | 204803862 | 240824 | yes | yes |
| ajv | tsc|leaf | incremental_local | 573 | 198.0 |  | 204803862 | 204376 | yes | yes |
| ajv | tsc|shared | incremental_local | 703 | 198.0 |  | 204804226 | 214024 | yes | yes |
| ajv | tsc|tsconfig | incremental_local | 593 | 198.0 |  | 204804226 | 207648 | yes | yes |
| ajv | tsc|concurrent | incremental_local | 1438 | 198.0 |  | 204804226 | 207616 | yes | yes |
| ajv | tsc|cold | nanocompile | 7 | 0.0 | 94931 | 204898596 | 4200 | yes | yes |
| ajv | tsc|leaf | nanocompile | 580 | 1.0 | 139473 | 204943138 | 203516 | yes | yes |
| ajv | tsc|shared | nanocompile | 729 | 1.0 | 234316 | 205038345 | 216712 | yes | yes |
| ajv | tsc|tsconfig | nanocompile | 637 | 1.0 | 329159 | 205133552 | 212996 | yes | yes |
| ajv | tsc|concurrent | nanocompile | 18 | 0.0 | 329255 | 205134376 | 4216 | yes | yes |
| prettier | tsc|cold | none | 18578 | 556.0 |  | 460949873 | 1233608 | yes | yes |
| prettier | tsc|leaf | none | 18245 | 556.0 |  | 460949873 | 1221752 | yes | yes |
| prettier | tsc|shared | none | 18401 | 556.0 |  | 460949873 | 1219628 | yes | yes |
| prettier | tsc|tsconfig | none | 18620 | 556.0 |  | 460949873 | 1222548 | yes | yes |
| prettier | tsc|concurrent | none | 26858 | 556.0 |  | 460949873 | 1251104 | yes | yes |
| prettier | tsc|cold | incremental_local | 18560 | 556.0 |  | 463596089 | 1232136 | yes | yes |
| prettier | tsc|leaf | incremental_local | 1536 | 556.0 |  | 463596168 | 415860 | yes | yes |
| prettier | tsc|shared | incremental_local | 2994 | 556.0 |  | 463598064 | 511228 | yes | yes |
| prettier | tsc|tsconfig | incremental_local | 1501 | 556.0 |  | 463598064 | 409760 | yes | yes |
| prettier | tsc|concurrent | incremental_local | 4265 | 556.0 |  | 463598064 | 469500 | yes | yes |
| prettier | tsc|cold | nanocompile | 103 | 0.0 | 1889060 | 465484952 | 18168 | yes | yes |
| prettier | tsc|leaf | nanocompile | 1616 | 1.0 | 3777747 | 467373718 | 415128 | yes | yes |
| prettier | tsc|shared | nanocompile | 3004 | 1.0 | 5668330 | 469266276 | 511380 | yes | yes |
| prettier | tsc|tsconfig | nanocompile | 2180 | 1.0 | 7558913 | 471158834 | 468780 | yes | yes |
| prettier | tsc|concurrent | nanocompile | 216 | 0.0 | 7559009 | 471162801 | 18280 | yes | yes |
| ajv | tsgo|cold | none | 142 | 198.0 |  | 204554113 | 109324 | yes | yes |
| ajv | tsgo|leaf | none | 153 | 198.0 |  | 204554113 | 110036 | yes | yes |
| ajv | tsgo|shared | none | 146 | 198.0 |  | 204554113 | 110032 | yes | yes |
| ajv | tsgo|tsconfig | none | 148 | 198.0 |  | 204554113 | 108560 | yes | yes |
| ajv | tsgo|concurrent | none | 381 | 198.0 |  | 204554113 | 111952 | yes | yes |
| ajv | tsgo|cold | incremental_local | 144 | 198.0 |  | 204945284 | 105868 | yes | yes |
| ajv | tsgo|leaf | incremental_local | 117 | 198.0 |  | 204945284 | 84368 | yes | yes |
| ajv | tsgo|shared | incremental_local | 123 | 198.0 |  | 204945608 | 92304 | yes | yes |
| ajv | tsgo|tsconfig | incremental_local | 105 | 198.0 |  | 204945608 | 86612 | yes | yes |
| ajv | tsgo|concurrent | incremental_local | 256 | 198.0 |  | 204945608 | 88340 | yes | yes |
| ajv | tsgo|cold | nanocompile | 144 | 1.0 | 125 | 204945207 | 106060 | yes | yes |
| ajv | tsgo|leaf | nanocompile | 101 | 1.0 | 150 | 204945232 | 85520 | yes | yes |
| ajv | tsgo|shared | nanocompile | 128 | 1.0 | 175 | 204945581 | 90960 | yes | yes |
| ajv | tsgo|tsconfig | nanocompile | 105 | 1.0 | 200 | 204945606 | 85712 | yes | yes |
| ajv | tsgo|concurrent | nanocompile | 417 | 1.0 | 300 | 204945706 | 87568 | yes | yes |
| ajv | tsrs|cold | none | 57 | 198.0 |  | 204554113 | 55852 | yes | yes |
| ajv | tsrs|leaf | none | 57 | 198.0 |  | 204554113 | 54148 | yes | yes |
| ajv | tsrs|shared | none | 58 | 198.0 |  | 204554113 | 54012 | yes | yes |
| ajv | tsrs|tsconfig | none | 57 | 198.0 |  | 204554113 | 53956 | yes | yes |
| ajv | tsrs|concurrent | none | 126 | 198.0 |  | 204554113 | 53572 | yes | yes |
| ajv | tsrs|cold | incremental_local | 58 | 198.0 |  | 204945644 | 55896 | yes | yes |
| ajv | tsrs|leaf | incremental_local | 47 | 198.0 |  | 204945644 | 48132 | yes | yes |
| ajv | tsrs|shared | incremental_local | 58 | 198.0 |  | 204945968 | 56352 | yes | yes |
| ajv | tsrs|tsconfig | incremental_local | 46 | 198.0 |  | 204945968 | 48352 | yes | yes |
| ajv | tsrs|concurrent | incremental_local | 100 | 198.0 |  | 204945968 | 54876 | yes | yes |
| ajv | tsrs|cold | nanocompile | 63 | 1.0 | 125 | 204945567 | 56064 | yes | yes |
| ajv | tsrs|leaf | nanocompile | 53 | 1.0 | 150 | 204945592 | 48344 | yes | yes |
| ajv | tsrs|shared | nanocompile | 64 | 1.0 | 175 | 204945941 | 55608 | yes | yes |
| ajv | tsrs|tsconfig | nanocompile | 54 | 1.0 | 200 | 204945966 | 47332 | yes | yes |
| ajv | tsrs|concurrent | nanocompile | 202 | 1.0 | 300 | 204946066 | 59480 | yes | yes |
| ajv | bun|cold | none | 60 | 198.0 |  | 204554091 | 95320 | yes | yes |
| ajv | bun|leaf | none | 66 | 198.0 |  | 204554091 | 95244 | yes | yes |
| ajv | bun|shared | none | 66 | 198.0 |  | 204554091 | 94484 | yes | yes |
| ajv | bun|tsconfig | none | 63 | 198.0 |  | 204554091 | 96284 | yes | yes |
| ajv | bun|concurrent | none | 161 | 198.0 |  | 204554091 | 96268 | yes | yes |
| ajv | bun|cold | nanocompile | 69 | 1.0 | 125 | 204554260 | 95328 | yes | yes |
| ajv | bun|leaf | nanocompile | 71 | 1.0 | 150 | 204554285 | 95952 | yes | yes |
| ajv | bun|shared | nanocompile | 70 | 1.0 | 175 | 204554310 | 95516 | yes | yes |
| ajv | bun|tsconfig | nanocompile | 66 | 1.0 | 200 | 204554335 | 95004 | yes | yes |
| ajv | bun|concurrent | nanocompile | 246 | 1.0 | 300 | 204554435 | 96216 | yes | yes |
| prettier | tsgo|cold | none | 297 | 556.0 |  | 460950050 | 222672 | no | no |
| prettier | tsgo|leaf | none | 572 | 556.0 |  | 460950050 | 228296 | no | no |
| prettier | tsgo|shared | none | 538 | 556.0 |  | 460950050 | 229312 | no | no |
| prettier | tsgo|tsconfig | none | 482 | 556.0 |  | 460950050 | 229264 | no | no |
| prettier | tsgo|concurrent | none | 870 | 556.0 |  | 460950050 | 230288 | no | no |
| prettier | tsgo|cold | incremental_local | 668 | 556.0 |  | 464521731 | 280584 | no | no |
| prettier | tsgo|leaf | incremental_local | 419 | 556.0 |  | 464521830 | 271376 | no | no |
| prettier | tsgo|shared | incremental_local | 348 | 556.0 |  | 464521929 | 277832 | no | no |
| prettier | tsgo|tsconfig | incremental_local | 325 | 556.0 |  | 464521929 | 252104 | no | no |
| prettier | tsgo|concurrent | incremental_local | 910 | 556.0 |  | 464521767 | 272008 | no | no |
| prettier | tsgo|cold | nanocompile | 412 | 1.0 | 125 | 464521654 | 279632 | no | no |
| prettier | tsgo|leaf | nanocompile | 402 | 1.0 | 150 | 464521778 | 274304 | no | no |
| prettier | tsgo|shared | nanocompile | 420 | 1.0 | 175 | 464521902 | 279184 | no | no |
| prettier | tsgo|tsconfig | nanocompile | 352 | 1.0 | 200 | 464521927 | 250700 | no | no |
| prettier | tsgo|concurrent | nanocompile | 1380 | 1.0 | 300 | 464521865 | 274896 | no | no |
| prettier | tsrs|cold | none | 88 | 556.0 |  | 460950050 | 93052 | no | no |
| prettier | tsrs|leaf | none | 94 | 556.0 |  | 460950050 | 92560 | no | no |
| prettier | tsrs|shared | none | 87 | 556.0 |  | 460950050 | 90952 | no | no |
| prettier | tsrs|tsconfig | none | 95 | 556.0 |  | 460950050 | 90288 | no | no |
| prettier | tsrs|concurrent | none | 212 | 556.0 |  | 460950050 | 91948 | no | no |
| prettier | tsrs|cold | incremental_local | 110 | 556.0 |  | 464524486 | 109808 | no | no |
| prettier | tsrs|leaf | incremental_local | 112 | 556.0 |  | 464524585 | 114880 | no | no |
| prettier | tsrs|shared | incremental_local | 122 | 556.0 |  | 464524684 | 116444 | no | no |
| prettier | tsrs|tsconfig | incremental_local | 111 | 556.0 |  | 464524684 | 115716 | no | no |
| prettier | tsrs|concurrent | incremental_local | 256 | 556.0 |  | 464524522 | 119452 | no | no |
| prettier | tsrs|cold | nanocompile | 160 | 1.0 | 125 | 464524409 | 109104 | no | no |
| prettier | tsrs|leaf | nanocompile | 152 | 1.0 | 150 | 464524533 | 117432 | no | no |
| prettier | tsrs|shared | nanocompile | 155 | 1.0 | 175 | 464524657 | 118120 | no | no |
| prettier | tsrs|tsconfig | nanocompile | 148 | 1.0 | 200 | 464524682 | 115944 | no | no |
| prettier | tsrs|concurrent | nanocompile | 457 | 1.0 | 300 | 464524620 | 119888 | no | no |
| prettier | bun|cold | none | 123 | 556.0 |  | 460950028 | 189552 | no | no |
| prettier | bun|leaf | none | 134 | 556.0 |  | 460950028 | 192928 | no | no |
| prettier | bun|shared | none | 126 | 556.0 |  | 460950028 | 182560 | no | no |
| prettier | bun|tsconfig | none | 133 | 556.0 |  | 460950028 | 192808 | no | no |
| prettier | bun|concurrent | none | 309 | 556.0 |  | 460950028 | 191508 | no | no |
| prettier | bun|cold | nanocompile | 190 | 1.0 | 125 | 460950197 | 193316 | no | no |
| prettier | bun|leaf | nanocompile | 175 | 1.0 | 150 | 460950222 | 187936 | no | no |
| prettier | bun|shared | nanocompile | 179 | 1.0 | 175 | 460950247 | 193188 | no | no |
| prettier | bun|tsconfig | nanocompile | 172 | 1.0 | 200 | 460950272 | 188568 | no | no |
| prettier | bun|concurrent | nanocompile | 560 | 1.0 | 300 | 460950372 | 192340 | no | no |

## What climbed

- **L0** content-addressed result cache (file hashes + `$NANO_ROOT`).
- **L1** store/restore `.tsbuildinfo` with the result.
- **L2** seed key (no source hashes) so an edit starts from sibling buildinfo.

`bun check` has no incremental file; L1/L2 do not apply.
prettier + tsgo/tsrs/bun: the program is `checkJs` with `module: NodeNext`.
TS 7 rejects a bundler override on NodeNext and stops before typechecking, so
the inject gate cannot be certified. tsc 5.9 on prettier is on the frontier.
Correctness: `tests/typescript_worktrees.py` uses real `git worktree add`.

Harness: `python3 bench/ts_worktrees.py --repo PATH`.
Archive: `bench/archive/ts-worktrees.json` → `map_elites.json` `typescript_worktrees`.
