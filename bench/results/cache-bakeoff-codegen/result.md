# nanocompile vs kache

Isolated stores. Apply/revert per run. Gate is cargo test + LLVM rustc.

| Sample | Loop | Scenario | Family | Config | Inc | Cache | Median ms | Hit rate | Store B | Target B | Restore ms | OK |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| rust-loop | build | empty_cold | nanocompile-shipped | shipped | off | empty | 2866.9 | 0.00 | 11169 | 18035 | 0.04 | yes |
| rust-loop | build | warm_emptied_target | nanocompile-shipped | shipped | off | warm_compiler_cache | 73.8 | 0.50 | 14692 | 18035 | 0.42 | yes |
| rust-loop | build | body | nanocompile-shipped | shipped | off | warm_compiler_cache | 40.6 | 0.67 | 25383 | 18089 | 0.60 | yes |
| rust-loop | test | empty_cold | nanocompile-shipped | shipped | off | empty | 2964.1 | 0.00 | 11163 | 7286583 | 0.04 | yes |
| rust-loop | test | warm_emptied_target | nanocompile-shipped | shipped | off | warm_compiler_cache | 226.9 | 0.50 | 14680 | 7286583 | 0.45 | yes |
| rust-loop | test | body | nanocompile-shipped | shipped | off | warm_compiler_cache | 171.5 | 0.67 | 25368 | 7286691 | 0.63 | yes |
| rust-loop | build | empty_cold | nanocompile-best | best | on | empty | 85.4 | 0.00 | 0 | 62726 | — | yes |
| rust-loop | build | warm_emptied_target | nanocompile-best | best | on | warm_compiler_cache | 83.1 | 0.00 | 0 | 62726 | — | yes |
| rust-loop | build | body | nanocompile-best | best | on | warm_compiler_cache | 34.2 | 0.00 | 0 | 62706 | — | yes |
| rust-loop | test | empty_cold | nanocompile-best | best | on | empty | 238.6 | 0.00 | 0 | 7946440 | — | yes |
| rust-loop | test | warm_emptied_target | nanocompile-best | best | on | warm_compiler_cache | 235.0 | 0.00 | 0 | 7946435 | — | yes |
| rust-loop | test | body | nanocompile-best | best | on | warm_compiler_cache | 174.0 | 0.00 | 0 | 7950135 | — | yes |
| rust-loop | build | empty_cold | kache-shipped | shipped | on | empty | 74.7 | 0.00 | 7957 | 18330 | — | yes |
| rust-loop | build | warm_emptied_target | kache-shipped | shipped | on | warm_compiler_cache | 43.6 | 1.00 | 7957 | 18330 | 2.00 | yes |
| rust-loop | build | body | kache-shipped | shipped | on | warm_compiler_cache | 46.4 | 1.00 | 7957 | 63124 | 2.00 | yes |
| rust-loop | test | empty_cold | kache-shipped | shipped | on | empty | 367.3 | 0.00 | 7278843 | 7287322 | — | yes |
| rust-loop | test | warm_emptied_target | kache-shipped | shipped | on | warm_compiler_cache | 58.6 | 1.00 | 7278843 | 7287322 | 3.50 | yes |
| rust-loop | test | body | kache-shipped | shipped | on | warm_compiler_cache | 198.8 | 1.00 | 7278843 | 7946715 | 3.50 | yes |
| rust-loop | build | empty_cold | kache-noinc | noinc | off | empty | 70.9 | 0.00 | 7957 | 17873 | — | yes |
| rust-loop | build | warm_emptied_target | kache-noinc | noinc | off | warm_compiler_cache | 43.6 | 1.00 | 7957 | 17873 | 2.00 | yes |
| rust-loop | build | body | kache-noinc | noinc | off | warm_compiler_cache | 40.6 | 0.67 | 15559 | 17927 | 6.00 | yes |
| rust-loop | test | empty_cold | kache-noinc | noinc | off | empty | 374.0 | 0.00 | 7278843 | 7286413 | — | yes |
| rust-loop | test | warm_emptied_target | kache-noinc | noinc | off | warm_compiler_cache | 59.7 | 1.00 | 7278843 | 7286413 | 3.50 | yes |
| rust-loop | test | body | kache-noinc | noinc | off | warm_compiler_cache | 185.5 | 0.80 | 7286445 | 7286521 | 8.25 | yes |
| hashbrown | build | empty_cold | nanocompile-shipped | shipped | off | empty | 3294.1 | 0.00 | 2266497 | 2334402 | 0.03 | yes |
| hashbrown | build | warm_emptied_target | nanocompile-shipped | shipped | off | warm_compiler_cache | 144.9 | 0.50 | 2279754 | 2334402 | 7.05 | yes |
| hashbrown | build | body | nanocompile-shipped | shipped | off | warm_compiler_cache | 406.3 | 0.83 | 3563211 | 2334402 | 18.10 | yes |
| hashbrown | test | empty_cold | nanocompile-shipped | shipped | off | empty | 9152.9 | 0.00 | 13801769 | 103455926 | 0.03 | yes |
| hashbrown | test | warm_emptied_target | nanocompile-shipped | shipped | off | warm_compiler_cache | 5782.9 | 0.35 | 13858055 | 103455926 | 7.77 | yes |
| hashbrown | test | body | nanocompile-shipped | shipped | off | warm_compiler_cache | 5736.3 | 0.59 | 15141512 | 103455926 | 19.31 | yes |
| hashbrown | build | empty_cold | nanocompile-best | best | on | empty | 3425.7 | 0.00 | 980669 | 12194309 | 0.03 | yes |
| hashbrown | build | warm_emptied_target | nanocompile-best | best | on | warm_compiler_cache | 497.3 | 0.50 | 991501 | 12194307 | 3.17 | yes |
| hashbrown | build | body | nanocompile-best | best | on | warm_compiler_cache | 137.0 | 1.00 | 991501 | 12183476 | 6.45 | yes |
| hashbrown | test | empty_cold | nanocompile-best | best | on | empty | 9609.9 | 0.00 | 12515731 | 154832687 | 0.04 | yes |
| hashbrown | test | warm_emptied_target | nanocompile-best | best | on | warm_compiler_cache | 6352.7 | 0.34 | 12569382 | 154832671 | 7.28 | yes |
| hashbrown | test | body | nanocompile-best | best | on | warm_compiler_cache | 4807.1 | 0.59 | 12569382 | 154361595 | 18.16 | yes |
| hashbrown | build | empty_cold | kache-shipped | shipped | on | empty | 621.4 | 0.00 | 2261926 | 2333484 | — | yes |
| hashbrown | build | warm_emptied_target | kache-shipped | shipped | on | warm_compiler_cache | 56.6 | 1.00 | 2261926 | 2333484 | 2.12 | yes |
| hashbrown | build | body | kache-shipped | shipped | on | warm_compiler_cache | 465.7 | 1.00 | 2261926 | 12190669 | 1.75 | yes |
| hashbrown | test | empty_cold | kache-shipped | shipped | on | empty | 6327.7 | 0.00 | 103418154 | 131700004 | — | yes |
| hashbrown | test | warm_emptied_target | kache-shipped | shipped | on | warm_compiler_cache | 2767.5 | 1.00 | 103418154 | 131700004 | 3.50 | yes |
| hashbrown | test | body | kache-shipped | shipped | on | warm_compiler_cache | 4337.0 | 1.00 | 103418154 | 183060955 | 3.44 | yes |
| hashbrown | build | empty_cold | kache-noinc | noinc | off | empty | 623.8 | 0.00 | 2261926 | 2333009 | — | yes |
| hashbrown | build | warm_emptied_target | kache-noinc | noinc | off | warm_compiler_cache | 57.1 | 1.00 | 2261926 | 2333009 | 2.25 | yes |
| hashbrown | build | body | kache-noinc | noinc | off | warm_compiler_cache | 382.7 | 0.83 | 3544295 | 2333009 | 11.20 | yes |
| hashbrown | test | empty_cold | kache-noinc | noinc | off | empty | 6375.4 | 0.00 | 103416538 | 131695052 | — | yes |
| hashbrown | test | warm_emptied_target | kache-noinc | noinc | off | warm_compiler_cache | 2688.6 | 1.00 | 103416538 | 131695052 | 3.44 | yes |
| hashbrown | test | body | kache-noinc | noinc | off | warm_compiler_cache | 3833.7 | 0.98 | 104698907 | 131695052 | 7.98 | yes |

