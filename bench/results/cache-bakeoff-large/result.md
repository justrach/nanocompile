# nanocompile vs kache

Isolated stores. Apply/revert per run. Gate is cargo test + LLVM rustc.

| Sample | Loop | Scenario | Family | Config | Inc | Cache | Median ms | Hit rate | Store B | Target B | Restore ms | OK |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| nalgebra | check | empty_cold | nanocompile-shipped | shipped | off | empty | 8838.6 | 0.00 | 9287381 | 77617174 | 0.03 | yes |
| nalgebra | check | warm_emptied_target | nanocompile-shipped | shipped | off | warm_compiler_cache | 6023.2 | 0.42 | 9320247 | 77617174 | 9.91 | yes |
| nalgebra | check | body | nanocompile-shipped | shipped | off | warm_compiler_cache | 3037.6 | 0.83 | 9320247 | 77617174 | 18.91 | yes |
| nalgebra | check | worktree | nanocompile-shipped | shipped | off | warm_compiler_cache | 5808.7 | 0.42 | 9352353 | 77617346 | 8.91 | yes |
| nalgebra | check | empty_cold | nanocompile-best | best | on | empty | 9995.9 | 0.00 | 9287267 | 152870526 | 0.03 | yes |
| nalgebra | check | warm_emptied_target | nanocompile-best | best | on | warm_compiler_cache | 6737.0 | 0.38 | 9320019 | 152870525 | 9.50 | yes |
| nalgebra | check | body | nanocompile-best | best | on | warm_compiler_cache | 791.7 | 0.77 | 9320019 | 152823496 | 16.52 | yes |
| nalgebra | check | worktree | nanocompile-best | best | on | warm_compiler_cache | 6842.3 | 0.38 | 9352125 | 152871700 | 8.17 | yes |
| nalgebra | check | empty_cold | kache-shipped | shipped | on | empty | 6369.1 | 0.00 | 77573858 | 105850901 | — | yes |
| nalgebra | check | warm_emptied_target | kache-shipped | shipped | on | warm_compiler_cache | 157.0 | 1.00 | 77573858 | 105850901 | 3.25 | yes |
| nalgebra | check | body | kache-shipped | shipped | on | warm_compiler_cache | 3882.0 | 1.00 | 77573858 | 178623562 | 3.33 | yes |
| nalgebra | check | worktree | kache-shipped | shipped | on | warm_compiler_cache | 511.8 | 1.00 | 77573858 | 105850601 | 9.62 | yes |
| nalgebra | check | empty_cold | kache-noinc | noinc | off | empty | 6353.8 | 0.00 | 77573858 | 105849878 | — | yes |
| nalgebra | check | warm_emptied_target | kache-noinc | noinc | off | warm_compiler_cache | 167.7 | 1.00 | 77573858 | 105849878 | 3.40 | yes |
| nalgebra | check | body | kache-noinc | noinc | off | warm_compiler_cache | 3201.1 | 0.97 | 84119002 | 105849878 | 11.10 | yes |
| nalgebra | check | worktree | kache-noinc | noinc | off | warm_compiler_cache | 522.2 | 1.00 | 84119002 | 105849698 | 9.75 | yes |
| ripgrep | check | empty_cold | nanocompile-shipped | shipped | off | empty | 7539.9 | 0.00 | 14710240 | 71397664 | 0.03 | yes |
| ripgrep | check | warm_emptied_target | nanocompile-shipped | shipped | off | warm_compiler_cache | 3817.6 | 0.32 | 19028428 | 71397664 | 7.37 | yes |
| ripgrep | check | body | nanocompile-shipped | shipped | off | warm_compiler_cache | 364.3 | 0.65 | 19028428 | 71397664 | 14.79 | yes |
| ripgrep | check | worktree | nanocompile-shipped | shipped | off | warm_compiler_cache | 4669.1 | 0.32 | 23457256 | 71396778 | 7.59 | yes |
| ripgrep | check | empty_cold | nanocompile-best | best | on | empty | 6649.6 | 0.00 | 14596361 | 104499158 | 0.03 | yes |
| ripgrep | check | warm_emptied_target | nanocompile-best | best | on | warm_compiler_cache | 2979.6 | 0.40 | 18913224 | 104499158 | 9.27 | yes |
| ripgrep | check | body | nanocompile-best | best | on | warm_compiler_cache | 164.5 | 0.81 | 18913224 | 104503834 | 18.64 | yes |
| ripgrep | check | worktree | nanocompile-best | best | on | warm_compiler_cache | 3761.9 | 0.40 | 23228487 | 104498926 | 9.34 | yes |
| ripgrep | check | empty_cold | kache-shipped | shipped | on | empty | 3397.1 | 0.00 | 71348754 | 99752551 | — | yes |
| ripgrep | check | warm_emptied_target | kache-shipped | shipped | on | warm_compiler_cache | 199.9 | 1.00 | 71348754 | 99752551 | 4.11 | yes |
| ripgrep | check | body | kache-shipped | shipped | on | warm_compiler_cache | 664.9 | 0.98 | 71348754 | 109565373 | 3.80 | yes |
| ripgrep | check | worktree | kache-shipped | shipped | on | warm_compiler_cache | 1122.8 | 1.00 | 71348754 | 99752021 | 22.69 | yes |
| ripgrep | check | empty_cold | kache-noinc | noinc | off | empty | 3396.0 | 0.00 | 71348754 | 99748285 | — | yes |
| ripgrep | check | warm_emptied_target | kache-noinc | noinc | off | warm_compiler_cache | 183.2 | 1.00 | 71348754 | 99748285 | 3.69 | yes |
| ripgrep | check | body | kache-noinc | noinc | off | warm_compiler_cache | 579.0 | 0.98 | 71348754 | 99748285 | 5.09 | yes |
| ripgrep | check | worktree | kache-noinc | noinc | off | warm_compiler_cache | 1086.5 | 1.00 | 71348754 | 99747968 | 21.78 | yes |
| emergentDB | check | empty_cold | nanocompile-shipped | shipped | off | empty | 40496.5 | 0.00 | 36138803 | 604726947 | 0.04 | no |
| emergentDB | check | warm_emptied_target | nanocompile-shipped | shipped | off | warm_compiler_cache | 35452.0 | 0.33 | 40694751 | 604726947 | 6.17 | no |
| emergentDB | check | None | nanocompile-shipped | — | — | — | skipped | no safe body edit site | — | — | — | — |
| emergentDB | check | worktree | nanocompile-shipped | shipped | off | warm_compiler_cache | 37211.0 | 0.33 | 45242815 | 604719638 | 5.97 | no |
| emergentDB | check | empty_cold | nanocompile-best | best | on | empty | 46710.2 | 0.00 | 37194856 | 625912120 | 0.04 | no |
| emergentDB | check | warm_emptied_target | nanocompile-best | best | on | warm_compiler_cache | 40161.9 | 0.31 | 42351005 | 625912120 | 7.38 | no |
| emergentDB | check | None | nanocompile-best | — | — | — | skipped | no safe body edit site | — | — | — | — |
| emergentDB | check | worktree | nanocompile-best | best | on | warm_compiler_cache | 43827.4 | 0.31 | 47499800 | 625906920 | 7.37 | no |
| emergentDB | check | empty_cold | kache-shipped | shipped | on | empty | 37030.1 | 0.00 | 604146341 | 633571048 | — | no |
| emergentDB | check | warm_emptied_target | kache-shipped | shipped | on | warm_compiler_cache | 13641.1 | 1.00 | 604146341 | 633571048 | 3.65 | no |
| emergentDB | check | None | kache-shipped | — | — | — | skipped | no safe body edit site | — | — | — | — |
| emergentDB | check | worktree | kache-shipped | shipped | on | warm_compiler_cache | 13997.5 | 1.00 | 604146341 | 633567793 | 6.38 | no |
| emergentDB | check | empty_cold | kache-noinc | noinc | off | empty | 38489.3 | 0.00 | 604146341 | 633568392 | — | no |
| emergentDB | check | warm_emptied_target | kache-noinc | noinc | off | warm_compiler_cache | 13672.9 | 1.00 | 604146341 | 633568392 | 3.63 | no |
| emergentDB | check | None | kache-noinc | — | — | — | skipped | no safe body edit site | — | — | — | — |
| emergentDB | check | worktree | kache-noinc | noinc | off | warm_compiler_cache | 13759.1 | 1.00 | 604146341 | 633566439 | 6.70 | no |

