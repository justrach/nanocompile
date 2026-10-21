# Large workspace (ruff) MAP-Elites shard

Sample: [astral-sh/ruff](https://github.com/astral-sh/ruff) `0.17.1`
(`4683270c69cb`). Size bucket **`large`** (55 workspace crates).
Measured command: `cargo -p ruff` (the product Charlie Marsh's thread
named). The workspace also contains `ty*`; a full `--workspace` check
was skipped so cold cells stay repeatable on this 4-core / 16 GiB VM.
Disk was never the limiter (~247 GiB free).

Shard schema: `nanocompile.rust-loop.map-elites.shard` (see
`bench/map_elites.schema.json`). Cell key is `large|<edit>` with
edits `cold`, `noop`, `body` (fn body in leaf crate `ruff_command_line`),
`sig_dep` (public API addition on hub crate `ruff_text_size`).
Fitness is median wall-clock ms. A genome cannot occupy a cell unless a
deliberate type-error edit fails both the fast path and real `cargo test`
(LLVM rustc validate; `validate_is_final`).

`bench/rust_loop_bench` exists on the parent branch but has no `--package`
flag, a 600s timeout, and applies incremental edits once per cell so extra
`--runs` become no-ops. This shard times apply/revert per sample.

## Elites

| Cell | Median ms | Spread ms | Disk | Loop | Wrapper | sccache | Linker | Backend | Incremental | Gate |
| --- | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- | --- |
| `large|cold` | 46575.1 | 8173.3 | 936845430 | check | yes | no | default | llvm | False | pass |
| `large|noop` | 150.9 | 5.5 | 1393718232 | check | no | no | default | llvm | True | pass |
| `large|body` | 454.4 | 4.2 | 1496414609 | check | no | no | default | llvm | True | pass |
| `large|sig_dep` | 6663.2 | 15.7 | 1901008717 | check | no | no | default | llvm | True | pass |

## All evaluations

| Hypothesis | Cell | Median ms | Spread | Disk | Wrapper | sccache | CGUs | Incremental | Keep-as-elite |
| --- | --- | ---: | ---: | ---: | --- | --- | ---: | --- | --- |
| baseline cargo check | `large|cold` | 54781.0 | 65.0 | 1393628013 | none | no | def | True |  |
| nanocompile wrapper + incremental=0 | `large|cold` | 46575.1 | 8173.3 | 936845430 | nano | no | def | False | yes |
| sccache wrapper | `large|cold` | 48678.1 | 8451.4 | 1393628012 | none | yes | def | True |  |
| crate-shape codegen-units=256 | `large|cold` | 54911.6 | 311.3 | 1397828773 | none | no | 256 | True |  |
| cargo check incremental=0 | `large|cold` | 53275.1 | 238.8 | 936845429 | none | no | def | False |  |
| baseline cargo build | `large|cold` | 138882.8 | 751.0 | 3077149433 | none | no | def | True |  |
| baseline cargo check | `large|noop` | 168.0 | 1.0 | 1393628013 | none | no | def | True |  |
| nanocompile wrapper + incremental=0 | `large|noop` | 168.7 | 8.5 | 936845430 | nano | no | def | False |  |
| sccache wrapper | `large|noop` | 160.0 | 1.3 | 1393628012 | none | yes | def | True |  |
| crate-shape codegen-units=256 | `large|noop` | 165.1 | 0.8 | 1397828773 | none | no | 256 | True |  |
| cargo check incremental=0 | `large|noop` | 155.9 | 4.8 | 936845429 | none | no | def | False |  |
| baseline cargo build | `large|noop` | 155.2 | 3.5 | 3077149433 | none | no | def | True |  |
| baseline cargo check | `large|body` | 507.8 | 6.5 | 1408616542 | none | no | def | True |  |
| nanocompile wrapper + incremental=0 | `large|body` | 957.1 | 4.3 | 936845430 | nano | no | def | False |  |
| sccache wrapper | `large|body` | 527.4 | 22.4 | 1408616541 | none | yes | def | True |  |
| crate-shape codegen-units=256 | `large|body` | 485.1 | 9.4 | 1412817302 | none | no | 256 | True |  |
| cargo check incremental=0 | `large|body` | 937.6 | 4.4 | 936845429 | none | no | def | False |  |
| baseline cargo build | `large|body` | 1123.3 | 4.4 | 3137719047 | none | no | def | True |  |
| baseline cargo check | `large|sig_dep` | 7258.0 | 124.1 | 1809397699 | none | no | def | True |  |
| nanocompile wrapper + incremental=0 | `large|sig_dep` | 15652.5 | 414.2 | 936846421 | nano | no | def | False |  |
| sccache wrapper | `large|sig_dep` | 7003.2 | 91.1 | 1809397696 | none | yes | def | True |  |
| crate-shape codegen-units=256 | `large|sig_dep` | 6958.5 | 9.9 | 1813598448 | none | no | 256 | True |  |
| cargo check incremental=0 | `large|sig_dep` | 14769.2 | 45.7 | 936846420 | none | no | def | False |  |
| baseline cargo build | `large|sig_dep` | 8914.3 | 39.9 | 4096292555 | none | no | def | True |  |
| mold cargo build | `large|noop` | 157.5 | 5.4 | 3126738468 | none | no | def | True |  |
| mold cargo build | `large|body` | 1129.0 | 27.9 | 3187308063 | none | no | def | True |  |
| lld cargo build | `large|body` | 1144.3 | 13.9 | 3137730755 | none | no | def | True |  |
| cranelift nightly build | `large|body` | 1336.3 | 9.8 | 2843431697 | none | no | def | True |  |
| test -p ruff_text_size | `large|cold` | 2230.6 | 8.1 | 65040530 | none | no | def | True |  |
| test -p ruff_text_size | `large|noop` | 270.8 | 3.6 | 65040530 | none | no | def | True |  |
| test -p ruff_text_size | `large|body` | 266.4 | 3.8 | 65040530 | none | no | def | True |  |
| sccache + codegen-units=256 | `large|noop` | 155.5 | 2.7 | 1397828843 | none | yes | 256 | True |  |
| sccache + codegen-units=256 | `large|body` | 495.6 | 12.3 | 1412817372 | none | yes | 256 | True |  |
| sccache + codegen-units=256 | `large|sig_dep` | 6938.3 | 146.4 | 1813598542 | none | yes | 256 | True |  |
| cargo check -j4 | `large|noop` | 167.7 | 1.9 | 1393628111 | none | no | def | True |  |
| cargo check -j4 | `large|body` | 467.2 | 4.2 | 1408616640 | none | no | def | True |  |
| cargo check -j4 | `large|sig_dep` | 6985.9 | 27.2 | 1809397803 | none | no | def | True |  |
| explicit line-tables-only | `large|noop` | 153.6 | 2.9 | 1481426080 | none | no | def | True |  |
| explicit line-tables-only | `large|body` | 454.4 | 4.2 | 1496414609 | none | no | def | True | yes |
| explicit line-tables-only | `large|sig_dep` | 6663.2 | 15.7 | 1901008717 | none | no | def | True | yes |
| sccache + incremental=1 | `large|noop` | 160.0 | 2.4 | 1809004315 | none | yes | def | True |  |
| sccache + incremental=1 | `large|body` | 474.2 | 2.8 | 1808906918 | none | yes | def | True |  |
| sccache + incremental=1 | `large|sig_dep` | 7023.3 | 140.1 | 1809397728 | none | yes | def | True |  |
| codegen-units=16 | `large|noop` | 150.9 | 5.5 | 1393718232 | none | no | 16 | True | yes |
| codegen-units=16 | `large|body` | 469.3 | 3.4 | 1408706761 | none | no | 16 | True |  |
| codegen-units=16 | `large|sig_dep` | 6843.1 | 159.2 | 1808977940 | none | no | 16 | True |  |
| line-tables-only + -j4 | `large|noop` | 160.6 | 1.1 | 1481426105 | none | no | def | True |  |
| line-tables-only + -j4 | `large|body` | 484.7 | 12.0 | 1496414634 | none | no | def | True |  |
| line-tables-only + -j4 | `large|sig_dep` | 6853.3 | 87.3 | 1901008741 | none | no | def | True |  |

## Hill-climb / seed log

| Iter | Cell | Hypothesis | Fitness ms | Delta % | Keep? |
| --- | --- | --- | ---: | ---: | --- |
| 1 | cold | baseline cargo check | 54780.96847799998 | None | keep |
| 1 | noop | baseline cargo check | 167.97514400002456 | None | keep |
| 1 | fn_body | baseline cargo check | 507.8114340000184 | None | keep |
| 1 | signature | baseline cargo check | 7257.977048999919 | None | keep |
| 2 | cold | nanocompile wrapper + incremental=0 | 46575.10117200002 | 14.98 | revert |
| 2 | noop | nanocompile wrapper + incremental=0 | 168.70295600006102 | -0.43 | revert |
| 2 | fn_body | nanocompile wrapper + incremental=0 | 957.125281999879 | -88.48 | revert |
| 2 | signature | nanocompile wrapper + incremental=0 | 15652.522196000064 | -115.66 | revert |
| 3 | cold | sccache wrapper | 48678.068086999934 | 11.14 | revert |
| 3 | noop | sccache wrapper | 160.00780800004577 | 4.74 | keep |
| 3 | fn_body | sccache wrapper | 527.4304189999839 | -3.86 | revert |
| 3 | signature | sccache wrapper | 7003.150605999963 | 3.51 | keep |
| 4 | cold | crate-shape codegen-units=256 | 54911.63250550005 | -0.24 | revert |
| 4 | noop | crate-shape codegen-units=256 | 165.08294000004753 | -3.17 | revert |
| 4 | fn_body | crate-shape codegen-units=256 | 485.0828640001055 | 4.48 | keep |
| 4 | signature | crate-shape codegen-units=256 | 6958.524607000072 | 0.64 | revert |
| 5 | cold | cargo check incremental=0 | 53275.11193500004 | 2.75 | revert |
| 5 | noop | cargo check incremental=0 | 155.90738900004908 | 2.56 | revert |
| 5 | fn_body | cargo check incremental=0 | 937.6161509999292 | -93.29 | revert |
| 5 | signature | cargo check incremental=0 | 14769.167882000147 | -110.89 | revert |
| 6 | cold | baseline cargo build | 138882.82472649997 | -153.52 | revert |
| 6 | noop | baseline cargo build | 155.15035599992189 | 3.04 | keep |
| 6 | fn_body | baseline cargo build | 1123.3310519996849 | -131.58 | revert |
| 6 | signature | baseline cargo build | 8914.331961000244 | -27.29 | revert |
| 7 | cold | mold linker | 323.0541749999247 | None | revert |
| 7 | noop | mold linker | 268.27755700014677 | None | revert |
| 7 | fn_body | mold linker | 269.1832689997682 | None | revert |
| 7 | signature | mold linker | 261.72428400013814 | None | revert |
| 29 | noop | mold cargo build | 157.53772600010052 | None | revert |
| 30 | body | mold cargo build | 1128.9901589998408 | None | revert |
| 31 | body | lld cargo build | 1144.2971319997923 | None | revert |
| 32 | body | cranelift nightly build | 1336.3288279997505 | None | revert |
| 33 | cold | test -p ruff_text_size | 2230.612327500012 | None | revert |
| 34 | noop | test -p ruff_text_size | 270.8267069997419 | None | revert |
| 35 | body | test -p ruff_text_size | 266.3764000003539 | None | revert |
| 36 | noop | sccache + codegen-units=256 | 155.51032200028203 | None | revert |
| 37 | body | sccache + codegen-units=256 | 495.5723630000648 | None | revert |
| 38 | sig_dep | sccache + codegen-units=256 | 6938.325202000215 | None | keep |
| 39 | noop | cargo check -j4 | 167.7387690001524 | None | revert |
| 40 | body | cargo check -j4 | 467.20387699997445 | None | keep |
| 41 | sig_dep | cargo check -j4 | 6985.912018999898 | None | revert |
| 42 | noop | explicit line-tables-only | 153.60833600016122 | None | keep |
| 43 | body | explicit line-tables-only | 454.4071140003325 | None | keep |
| 44 | sig_dep | explicit line-tables-only | 6663.227140999879 | None | keep |
| 45 | noop | sccache + incremental=1 | 160.0366750003559 | None | revert |
| 46 | body | sccache + incremental=1 | 474.2006040000888 | None | revert |
| 47 | sig_dep | sccache + incremental=1 | 7023.310069999752 | None | revert |
| 48 | noop | codegen-units=16 | 150.90810600031546 | None | keep |
| 49 | body | codegen-units=16 | 469.3298940001114 | None | revert |
| 50 | sig_dep | codegen-units=16 | 6843.124728000021 | None | revert |
| 51 | noop | line-tables-only + -j4 | 160.6067479997364 | None | revert |
| 52 | body | line-tables-only + -j4 | 484.67447300026834 | None | revert |
| 53 | sig_dep | line-tables-only + -j4 | 6853.265128000203 | None | revert |

## Held-out cross-tests

| Trained on | Cell | Ruff fitness ms | Source fitness | Gate |
| --- | --- | ---: | ---: | --- |
| midsize | large|body | 471.53281800001423 | 1387.3198349999143 | True |
| midsize | large|noop | 169.8876199998267 | 31.221453999933146 | True |
| midsize | large|sig_dep | 7052.345192999383 | 529.7661290000519 | True |
| pinned-hashbrown-held-out | large|cold | 53275.11193500004 | 411.5250719996766 | True |
| rust-loop | large|cold | 53275.11193500004 | 43.517553999663505 | True |
| rust-loop | large|sig_dep | 14769.167882000147 | 24.11353900015456 | True |
| rust-loop-medium | large|cold | 53275.11193500004 | 85.17907899977217 | True |
| rust-loop-medium | large|sig_dep | 14769.167882000147 | 34.26494699988325 | True |
| rust-loop | large|sig_dep | 14769.167882000147 | 24.76190700008374 | True |
| pinned-hashbrown-held-out | large|body | 467.20387699997445 | 122.79382300039288 | True |
| pinned-hashbrown-held-out | large|sig_dep | 6985.912018999898 | 128.3432330001233 | True |
| pinned-hashbrown | large|body | 467.20387699997445 | 122.67688400061161 | True |
| pinned-hashbrown | large|sig_dep | 6985.912018999898 | 113.21087200030888 | True |
| rust-loop-medium | large|body | 467.20387699997445 | 63.34535499991034 | True |
| rust-loop-medium | large|body | 467.20387699997445 | 62.92476099997657 | True |
| rust-loop-cranelift | large|body | 1336.3288279997505 | 24.97602600033133 | True |
| rust-loop-cranelift | large|noop | 167.7387690001524 | 10.563622000063333 | True |
| rust-loop-steps | large|sig_dep | 6985.912018999898 | 24.840631000188296 | True |
| rust-loop-steps | large|cold | 54911.63250550005 | 44.61392799976238 | True |
| rust-loop-steps | large|body | 485.0828640001055 | 25.15832400013096 | True |
| rust-loop | large|cold | 54911.63250550005 | 43.92367899981764 | True |

## Baseline vs best (same VM, rustc 1.99.0, 4 cores)

| Scenario | Baseline (plain `cargo check -p ruff`) | Best passing genome | Delta |
| --- | ---: | ---: | ---: |
| `large|cold` | 54781.0 ms | **46575.1 ms** (`nanocompile wrapper + incremental=0`) | 15.0% |
| `large|noop` | 168.0 ms | **150.9 ms** (`codegen-units=16`) | 10.2% |
| `large|body` | 507.8 ms | **454.4 ms** (`explicit line-tables-only`) | 10.5% |
| `large|sig_dep` | 7258.0 ms | **6663.2 ms** (`explicit line-tables-only`) | 8.2% |

## What helped and by how much

- **`fast-check` (`cargo check`) is the incremental loop.** Leaf `body` ~0.45–0.51 s vs `cargo build` ~1.12 s vs cranelift build ~1.34 s. Hub `sig_dep` check ~6.7–7.3 s vs build ~8.9 s.
- **Explicit `debuginfo=line-tables-only` (disk-hygiene rustflag)** is the incremental elite: `body` 454 ms (−10.5% vs 508 ms baseline) and `sig_dep` 6663 ms (−8.2% vs 7258 ms). Ruff's `profile.dev` already sets this, but `RUSTFLAGS` also covers path deps.
- **`cargo check -j4`** helped `body` (467 ms, −8.0%). Diminishing returns on this 4-core VM.
- **`codegen-units=256` / `16`:** small `body` wins (485 / 469 ms). `cgu=16` took `noop` at 151 ms (noise-scale vs 168 ms).
- **`sccache`:** cold check 48.7 s vs 54.8 s (−11%); incremental `body` 527 ms (worse than plain); `sig_dep` 7003 ms (−3.5%). Combining sccache+cgu256 reached `sig_dep` 6938 ms.
- **nanocompile wrapper + `CARGO_INCREMENTAL=0`:** cold check median 46.6 s (−15% vs 54.8 s) but 8.2 s spread (2 samples). Incremental `body` 957 ms (**+88%**) and `sig_dep` 15.7 s (**+116%**). Cache helps cold replay, hurts the edit loop.
- **mold / lld:** first attempt failed (`cc: invalid linker name -fuse-ld=mold`) until `ld.mold` was on `PATH`. After that, incremental `body` build was 1129 ms (mold) / 1144 ms (lld) vs 1123 ms default — **no win**. Linking is not the leaf-edit bottleneck.
- **cranelift nightly `cargo build -p ruff`:** worked on this pin; incremental `body` 1336 ms, slower than LLVM check and slightly slower than LLVM build.
- **`cargo test -p ruff_text_size`:** bounded and fast (cold 2.2 s) but **failed the correctness gate** (`agree_on_broken=false`): a type error in `ruff_command_line` does not fail tests of an unrelated crate. Gate did its job.

## What did not help

- Forcing `CARGO_INCREMENTAL=0` without a wrapper: `body` 938 ms, `sig_dep` 14.8 s.
- Declared `fast-check → validate` **graph was not timed** as a ruff loop: `rust_loop spec` has no `-p` filter and would `cargo test` the whole workspace including `ty`. Held-out graph elites are cross-tested with a 180 s timeout.
- rust-analyzer / bacon / hot-reload: not batch-measurable here (editor/daemon).
- Experimental compilers (rustd, Relax, Lust, Astral fork): not usable-now; Charlie's thread said they did not build Ruff.

## Correctness

Broken edit: `let _nano_loop_body: u32 = "nope"` in `ruff_command_line::is_response_file`.
Validate: `cargo test -p ruff_command_line` with LLVM, no wrapper, no cranelift.
Every `cargo check -p ruff` genome agreed (fast fail + validate fail; no `validate.ok` stamp).
`cargo test -p ruff_text_size` did **not** agree: it never compiled the broken crate.
`tools/rust_loop.py` workspace glob: 4 inputs / 0 crate sources → **5710 inputs / 2020 `.rs` / 55 crates**.

## Stop rule

Hill-climb mutated one or two genes of the incremental elites. Combining
the two incremental winners (`line-tables-only` + `-j4`) lost on `body`
(485 vs 454 ms) and `sig_dep` (6853 vs 6663 ms). `codegen-units=16` took
`noop` at 151 ms (noise-scale). Search stopped after those consecutive
<3% / losing tries on the incremental cells.
- rust_loop.discover_inputs on ruff 0.17.1: 5710 paths, 2020 crate .rs files (glob expansion on)
- gate 1d33291b8a76 baseline cargo check agree=True fast=True validate=True
- gate ba92760509b7 nanocompile wrapper + incremental=0 agree=True fast=True validate=True
- gate d81c89bf8541 sccache wrapper agree=True fast=True validate=True
- gate 75ca5b092e0b crate-shape codegen-units=256 agree=True fast=True validate=True
- gate 8235bfd05080 cargo check incremental=0 agree=True fast=True validate=True
- gate 48c0c8f2fa78 baseline cargo build agree=True fast=True validate=True
- gate 0537829a212d mold linker agree=True fast=True validate=True
- gate 0537829a212d mold cargo build agree=True
- gate b63c84240f76 lld cargo build agree=True
- gate ca06f49ab008 cranelift nightly build agree=True
- gate 44d4d52b092e test -p ruff_text_size agree=False
- gate 0da2617d8132 sccache + codegen-units=256 agree=True
- gate e0633adb60b7 cargo check -j4 agree=True
- gate c588cd8f1822 explicit line-tables-only agree=True
- gate d81c89bf8541 sccache + incremental=1 agree=True
- gate cef2a085d2b6 codegen-units=16 agree=True
- gate a7e22369508e line-tables-only + -j4 agree=True
- cross-test fill: 18 reused local equivalent genomes; 3 live midsize rows; missing [('midsize', 'large|cold', 'no local cold'), ('pinned-hashbrown-held-out', 'mid|noop', 'no local noop'), ('rust-loop', 'small|noop', 'no local noop'), ('rust-loop-medium', 'small|noop', 'no local noop'), ('rust-loop', 'small|noop', 'no local noop'), ('pinned-hashbrown', 'mid|cold', 'no local cold'), ('rust-loop-from-hashbrown', 'small|cold', 'no local cold'), ('pinned-hashbrown', 'mid|noop', 'no local noop')]

