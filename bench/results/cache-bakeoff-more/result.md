# nanocompile vs kache

Isolated stores. Apply/revert per run. Gate is cargo test + LLVM rustc.

| Sample | Loop | Scenario | Family | Config | Inc | Cache | Median ms | Hit rate | Store B | Target B | Restore ms | OK |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| serde_derive | check | empty_cold | nanocompile-shipped | shipped | off | empty | 5139.9 | 0.00 | 355494 | 16825908 | 0.04 | yes |
| serde_derive | check | warm_emptied_target | nanocompile-shipped | shipped | off | warm_compiler_cache | 1712.5 | 0.30 | 361939 | 16825908 | 1.14 | yes |
| serde_derive | check | body | nanocompile-shipped | shipped | off | warm_compiler_cache | 725.8 | 0.60 | 361939 | 16825908 | 2.40 | yes |
| serde_derive | check | worktree | nanocompile-shipped | shipped | off | warm_compiler_cache | 1887.5 | 0.30 | 368184 | 16825723 | 1.12 | yes |
| serde_derive | check | cargo_clean | nanocompile-shipped | shipped | off | warm_compiler_cache | 1678.1 | 0.60 | 368184 | 16825908 | 2.17 | yes |
| serde_derive | check | empty_cold | nanocompile-best | best | on | empty | 4949.5 | 0.00 | 355464 | 26115856 | 0.04 | yes |
| serde_derive | check | warm_emptied_target | nanocompile-best | best | on | warm_compiler_cache | 1801.8 | 0.30 | 361879 | 26115856 | 1.14 | yes |
| serde_derive | check | body | nanocompile-best | best | on | warm_compiler_cache | 288.5 | 0.60 | 361879 | 26128173 | 2.05 | yes |
| serde_derive | check | worktree | nanocompile-best | best | on | warm_compiler_cache | 1945.7 | 0.30 | 368124 | 26115752 | 1.14 | yes |
| serde_derive | check | cargo_clean | nanocompile-best | best | on | warm_compiler_cache | 1784.2 | 0.60 | 368124 | 26115856 | 2.15 | yes |
| serde_derive | check | empty_cold | kache-shipped | shipped | on | empty | 2158.3 | 0.00 | 16815571 | 45023881 | — | yes |
| serde_derive | check | warm_emptied_target | kache-shipped | shipped | on | warm_compiler_cache | 92.6 | 1.00 | 16815571 | 45023881 | 2.91 | yes |
| serde_derive | check | body | kache-shipped | shipped | on | warm_compiler_cache | 999.0 | 1.00 | 16815571 | 54225674 | 2.82 | yes |
| serde_derive | check | worktree | kache-shipped | shipped | on | warm_compiler_cache | 162.1 | 1.00 | 16815571 | 45023786 | 7.23 | yes |
| serde_derive | check | cargo_clean | kache-shipped | shipped | on | warm_compiler_cache | 94.3 | 1.00 | 16815571 | 45023881 | 3.64 | yes |
| serde_derive | check | empty_cold | kache-noinc | noinc | off | empty | 2143.8 | 0.00 | 16815571 | 45023393 | — | yes |
| serde_derive | check | warm_emptied_target | kache-noinc | noinc | off | warm_compiler_cache | 91.1 | 1.00 | 16815571 | 45023393 | 2.64 | yes |
| serde_derive | check | body | kache-noinc | noinc | off | warm_compiler_cache | 887.0 | 0.92 | 16897149 | 45023393 | 17.58 | yes |
| serde_derive | check | worktree | kache-noinc | noinc | off | warm_compiler_cache | 163.0 | 1.00 | 16897149 | 45023336 | 7.27 | yes |
| serde_derive | check | cargo_clean | kache-noinc | noinc | off | warm_compiler_cache | 91.2 | 1.00 | 16897149 | 45023393 | 3.64 | yes |
| axum | check | empty_cold | nanocompile-shipped | shipped | off | empty | 10256.0 | 0.00 | 14354401 | 105101889 | 0.03 | yes |
| axum | check | warm_emptied_target | nanocompile-shipped | shipped | off | warm_compiler_cache | 6995.4 | 0.39 | 19061506 | 105101889 | 6.27 | yes |
| axum | check | body | nanocompile-shipped | shipped | off | warm_compiler_cache | 126.3 | 0.77 | 19061506 | 105101889 | 12.76 | yes |
| axum | check | worktree | nanocompile-shipped | shipped | off | warm_compiler_cache | 7512.9 | 0.39 | 23765689 | 105100790 | 6.57 | yes |
| axum | check | cargo_clean | nanocompile-shipped | shipped | off | warm_compiler_cache | 7044.1 | 0.77 | 23765689 | 105101889 | 13.30 | yes |
| axum | check | empty_cold | nanocompile-best | best | on | empty | 11590.9 | 0.00 | 14353963 | 165102647 | 0.03 | yes |
| axum | check | warm_emptied_target | nanocompile-best | best | on | warm_compiler_cache | 8351.5 | 0.38 | 19060630 | 165102641 | 6.27 | yes |
| axum | check | body | nanocompile-best | best | on | warm_compiler_cache | 125.9 | 0.76 | 19060630 | 165102644 | 13.63 | yes |
| axum | check | worktree | nanocompile-best | best | on | warm_compiler_cache | 8704.0 | 0.38 | 23764813 | 165102614 | 6.52 | yes |
| axum | check | cargo_clean | nanocompile-best | best | on | warm_compiler_cache | 8054.5 | 0.76 | 23764813 | 165102646 | 12.16 | yes |
| axum | check | empty_cold | kache-shipped | — | — | — | skipped | [Errno 39] Directory not empty: '/tmp/nano-cache-race-axum-z4plgknv/stores/kache-shipped/check' | — | — | — | — |
| axum | check | warm_emptied_target | kache-shipped | shipped | on | warm_compiler_cache | 360.9 | 0.50 | 105033435 | 133424386 | 3.49 | yes |
| axum | check | body | kache-shipped | shipped | on | warm_compiler_cache | 116.0 | 1.00 | 105033435 | 133424386 | 3.31 | yes |
| axum | check | worktree | kache-shipped | shipped | on | warm_compiler_cache | 1815.8 | 1.00 | 105033435 | 133423631 | 19.83 | yes |
| axum | check | cargo_clean | kache-shipped | shipped | on | warm_compiler_cache | 344.6 | 1.00 | 105033435 | 133424386 | 5.27 | yes |
| axum | check | empty_cold | kache-noinc | noinc | off | empty | 7943.9 | 0.00 | 105033270 | 133422124 | — | yes |
| axum | check | warm_emptied_target | kache-noinc | noinc | off | warm_compiler_cache | 345.5 | 1.00 | 105033270 | 133422124 | 3.53 | yes |
| axum | check | body | kache-noinc | noinc | off | warm_compiler_cache | 124.2 | 1.00 | 105033270 | 133422124 | 3.40 | yes |
| axum | check | worktree | kache-noinc | noinc | off | warm_compiler_cache | 1822.7 | 1.00 | 105033270 | 133421671 | 19.50 | yes |
| axum | check | cargo_clean | kache-noinc | noinc | off | warm_compiler_cache | 341.2 | 1.00 | 105033270 | 133422124 | 3.94 | yes |
| bhumi | check | empty_cold | nanocompile-shipped | shipped | off | empty | 14559.4 | 0.00 | 12907250 | 298372208 | 0.03 | yes |
| bhumi | check | warm_emptied_target | nanocompile-shipped | shipped | off | warm_compiler_cache | 11671.2 | 0.37 | 13105717 | 298372204 | 4.55 | yes |
| bhumi | check | body | nanocompile-shipped | shipped | off | warm_compiler_cache | 370.6 | 0.75 | 13105717 | 298372208 | 8.59 | yes |
| bhumi | check | worktree | nanocompile-shipped | shipped | off | warm_compiler_cache | 11472.7 | 0.37 | 13299504 | 298368658 | 4.29 | yes |
| bhumi | check | cargo_clean | nanocompile-shipped | shipped | off | warm_compiler_cache | 11629.3 | 0.75 | 13299504 | 298372208 | 8.67 | yes |
| bhumi | check | empty_cold | nanocompile-best | best | on | empty | 21398.7 | 0.00 | 16002850 | 304244385 | 0.03 | yes |
| bhumi | check | warm_emptied_target | nanocompile-best | best | on | warm_compiler_cache | 18085.8 | 0.32 | 16208139 | 304244388 | 5.38 | yes |
| bhumi | check | body | nanocompile-best | best | on | warm_compiler_cache | 288.8 | 0.65 | 16208139 | 304354169 | 10.98 | yes |
| bhumi | check | worktree | nanocompile-best | best | on | warm_compiler_cache | 18533.8 | 0.32 | 16409314 | 304241801 | 5.47 | yes |
| bhumi | check | cargo_clean | nanocompile-best | best | on | warm_compiler_cache | 17818.0 | 0.65 | 16409314 | 304244386 | 10.98 | yes |
| bhumi | check | empty_cold | kache-shipped | shipped | on | empty | 11896.2 | 0.00 | 298209056 | 326868907 | — | yes |
| bhumi | check | warm_emptied_target | kache-shipped | shipped | on | warm_compiler_cache | 445.8 | 0.98 | 334711460 | 326868907 | 3.60 | yes |
| bhumi | check | body | kache-shipped | shipped | on | warm_compiler_cache | 542.2 | 1.00 | 334711460 | 332742193 | 3.25 | yes |
| bhumi | check | worktree | kache-shipped | shipped | on | warm_compiler_cache | 3933.9 | 0.98 | 371213816 | 326867299 | 4.59 | yes |
| bhumi | check | cargo_clean | kache-shipped | shipped | on | warm_compiler_cache | 459.0 | 1.00 | 371213816 | 326868907 | 3.66 | yes |
| bhumi | check | empty_cold | kache-noinc | noinc | off | empty | 11584.3 | 0.00 | 298209050 | 326867810 | — | yes |
| bhumi | check | warm_emptied_target | kache-noinc | noinc | off | warm_compiler_cache | 422.2 | 0.98 | 334711422 | 326867810 | 3.56 | yes |
| bhumi | check | body | kache-noinc | noinc | off | warm_compiler_cache | 455.6 | 1.00 | 334711422 | 326867810 | 3.79 | yes |
| bhumi | check | worktree | kache-noinc | noinc | off | warm_compiler_cache | 3874.5 | 0.98 | 371213778 | 326866850 | 4.59 | yes |
| bhumi | check | cargo_clean | kache-noinc | noinc | off | warm_compiler_cache | 399.7 | 1.00 | 371213778 | 326867810 | 3.39 | yes |

