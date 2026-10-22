# nanocompile vs kache

Isolated stores. Apply/revert per run. Gate is cargo test + LLVM rustc.

| Sample | Loop | Scenario | Family | Config | Inc | Cache | Median ms | Hit rate | Store B | Target B | Restore ms | OK |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| ruff | check | warm_emptied_target | nanocompile-shipped | shipped | off | warm_compiler_cache | 49703.7 | 0.00 | 99466215 | 720990108 | 0.10 | yes |
| ruff | check | body | nanocompile-shipped | shipped | off | warm_compiler_cache | 25615.1 | 0.50 | 99466215 | 720990108 | 9.59 | yes |
| ruff | check | warm_emptied_target | nanocompile-best | best | on | warm_compiler_cache | 54507.2 | 0.00 | 100625110 | 1224887533 | 0.09 | yes |
| ruff | check | body | nanocompile-best | best | on | warm_compiler_cache | 20790.3 | 0.53 | 100625110 | 1224862165 | 17.64 | yes |
| ruff | check | warm_emptied_target | kache-shipped | shipped | on | warm_compiler_cache | 19603.7 | 0.50 | 726700021 | 749810534 | 12.41 | yes |
| ruff | check | body | kache-shipped | shipped | on | warm_compiler_cache | 1316.9 | 1.00 | 726700021 | 767023996 | 12.82 | yes |
| ruff | check | warm_emptied_target | kache-noinc | noinc | off | warm_compiler_cache | 19667.4 | 0.50 | 726701833 | 749792673 | 12.83 | yes |
| ruff | check | body | kache-noinc | noinc | off | warm_compiler_cache | 1150.2 | 1.00 | 726706466 | 749792673 | 12.93 | yes |

