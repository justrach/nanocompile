# nanocompile vs kache

Isolated stores. Apply/revert per run. Gate is cargo test + LLVM rustc.

| Sample | Loop | Scenario | Family | Config | Inc | Cache | Median ms | Hit rate | Store B | Target B | Restore ms | OK |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| rust-loop | build | empty_cold | nanocompile-shipped | shipped | off | empty | 85.1 | 0.00 | 0 | 18034 | — | yes |
| rust-loop | build | warm_emptied_target | nanocompile-shipped | shipped | off | warm_compiler_cache | 83.0 | 0.00 | 0 | 18034 | — | yes |
| rust-loop | build | body | nanocompile-shipped | shipped | off | warm_compiler_cache | 34.9 | 0.00 | 0 | 18088 | — | yes |
| rust-loop | build | empty_cold | nanocompile-best | best | on | empty | 82.8 | 0.00 | 0 | 62725 | — | yes |
| rust-loop | build | warm_emptied_target | nanocompile-best | best | on | warm_compiler_cache | 83.4 | 0.00 | 0 | 62725 | — | yes |
| rust-loop | build | body | nanocompile-best | best | on | warm_compiler_cache | 33.9 | 0.00 | 0 | 62705 | — | yes |
| rust-loop | build | empty_cold | kache-shipped | shipped | on | empty | 76.8 | 0.00 | 7957 | 18330 | — | yes |
| rust-loop | build | warm_emptied_target | kache-shipped | shipped | on | warm_compiler_cache | 45.1 | 1.00 | 7957 | 18330 | 2.00 | yes |
| rust-loop | build | body | kache-shipped | shipped | on | warm_compiler_cache | 44.6 | 1.00 | 7957 | 63124 | 2.00 | yes |
| rust-loop | build | empty_cold | kache-noinc | noinc | off | empty | 77.6 | 0.00 | 7957 | 17873 | — | yes |
| rust-loop | build | warm_emptied_target | kache-noinc | noinc | off | warm_compiler_cache | 44.6 | 1.00 | 7957 | 17873 | 2.00 | yes |
| rust-loop | build | body | kache-noinc | noinc | off | warm_compiler_cache | 39.0 | 0.67 | 15559 | 17927 | 6.50 | yes |
| hashbrown | build | empty_cold | nanocompile-shipped | shipped | off | empty | 534.9 | 0.00 | 0 | 2334401 | — | yes |
| hashbrown | build | warm_emptied_target | nanocompile-shipped | shipped | off | warm_compiler_cache | 540.7 | 0.00 | 0 | 2334401 | — | yes |
| hashbrown | build | body | nanocompile-shipped | shipped | off | warm_compiler_cache | 343.2 | 0.00 | 0 | 2334401 | — | yes |
| hashbrown | build | empty_cold | nanocompile-best | best | on | empty | 642.7 | 0.00 | 0 | 12194303 | — | yes |
| hashbrown | build | warm_emptied_target | nanocompile-best | best | on | warm_compiler_cache | 634.0 | 0.00 | 0 | 12194305 | — | yes |
| hashbrown | build | body | nanocompile-best | best | on | warm_compiler_cache | 146.3 | 0.00 | 0 | 12183475 | — | yes |
| hashbrown | build | empty_cold | kache-shipped | shipped | on | empty | 621.2 | 0.00 | 2261926 | 2333484 | — | yes |
| hashbrown | build | warm_emptied_target | kache-shipped | shipped | on | warm_compiler_cache | 63.9 | 1.00 | 2261926 | 2333484 | 3.12 | yes |
| hashbrown | build | body | kache-shipped | shipped | on | warm_compiler_cache | 475.3 | 1.00 | 2261926 | 12190667 | 2.75 | yes |
| hashbrown | build | empty_cold | kache-noinc | noinc | off | empty | 629.6 | 0.00 | 2261926 | 2333009 | — | yes |
| hashbrown | build | warm_emptied_target | kache-noinc | noinc | off | warm_compiler_cache | 56.6 | 1.00 | 2261926 | 2333009 | 3.00 | yes |
| hashbrown | build | body | kache-noinc | noinc | off | warm_compiler_cache | 384.1 | 0.83 | 3544295 | 2333009 | 11.40 | yes |

