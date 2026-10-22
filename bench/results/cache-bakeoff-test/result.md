# nanocompile vs kache

Isolated stores. Apply/revert per run. Gate is cargo test + LLVM rustc.

| Sample | Loop | Scenario | Family | Config | Inc | Cache | Median ms | Hit rate | Store B | Target B | Restore ms | OK |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| rust-loop | test | empty_cold | nanocompile-shipped | shipped | off | empty | 222.7 | 0.00 | 0 | 7286582 | — | yes |
| rust-loop | test | warm_emptied_target | nanocompile-shipped | shipped | off | warm_compiler_cache | 223.6 | 0.00 | 0 | 7286582 | — | yes |
| rust-loop | test | body | nanocompile-shipped | shipped | off | warm_compiler_cache | 170.9 | 0.00 | 0 | 7286690 | — | yes |
| rust-loop | test | empty_cold | nanocompile-best | best | on | empty | 232.4 | 0.00 | 0 | 7946439 | — | yes |
| rust-loop | test | warm_emptied_target | nanocompile-best | best | on | warm_compiler_cache | 232.9 | 0.00 | 0 | 7946434 | — | yes |
| rust-loop | test | body | nanocompile-best | best | on | warm_compiler_cache | 169.5 | 0.00 | 0 | 7950135 | — | yes |
| rust-loop | test | empty_cold | kache-shipped | shipped | on | empty | 388.2 | 0.00 | 7278843 | 7287322 | — | yes |
| rust-loop | test | warm_emptied_target | kache-shipped | shipped | on | warm_compiler_cache | 62.4 | 1.00 | 7278843 | 7287322 | 3.50 | yes |
| rust-loop | test | body | kache-shipped | shipped | on | warm_compiler_cache | 203.7 | 1.00 | 7278843 | 7946716 | 3.50 | yes |
| rust-loop | test | empty_cold | kache-noinc | noinc | off | empty | 388.5 | 0.00 | 7278843 | 7286413 | — | yes |
| rust-loop | test | warm_emptied_target | kache-noinc | noinc | off | warm_compiler_cache | 58.4 | 1.00 | 7278843 | 7286413 | 3.50 | yes |
| rust-loop | test | body | kache-noinc | noinc | off | warm_compiler_cache | 187.3 | 0.80 | 7286445 | 7286521 | 8.50 | yes |

