# wrapper compare: nalgebra

Project: `/tmp/real-samples/nalgebra`
Edits: cold, noop, body, sig_dep, worktree. Runs 2, warmup 1.
Correctness gate is cargo test + LLVM rustc. Clippy/nextest are not the gate.

| Family | Edit | Cache | Inc | Median ms | Spread ms | OK |
| --- | --- | --- | --- | ---: | ---: | --- |
| incremental | cold | empty | on | 6053.6 | 35.3 | yes |
| incremental | noop | — | on | 46.4 | 0.6 | yes |
| incremental | body | — | on | 814.1 | 17.8 | yes |
| incremental | sig_dep | — | on | 761.2 | 6.0 | yes |
| incremental | worktree | empty | on | 5985.4 | 30.6 | yes |
| noinc | cold | empty | off | 5427.9 | 137.6 | yes |
| noinc | noop | — | off | 52.8 | 0.4 | yes |
| noinc | body | — | off | 3073.8 | 12.2 | yes |
| noinc | sig_dep | — | off | 3034.4 | 28.4 | yes |
| noinc | worktree | empty | off | 5524.7 | 11.3 | yes |
| sccache-inc | cold | empty | on | 12.7 | 0.1 | no |
| sccache-inc | noop | — | on | 11.2 | 0.5 | no |
| sccache-inc | body | — | on | 11.4 | 0.0 | no |
| sccache-inc | sig_dep | — | on | 11.2 | 0.1 | no |
| sccache-inc | worktree | empty | on | 12.6 | 0.0 | no |
| sccache-noinc | cold | empty | off | 6487.2 | 26.0 | yes |
| sccache-noinc | noop | — | off | 47.5 | 0.8 | yes |
| sccache-noinc | body | — | off | 3242.7 | 42.8 | yes |
| sccache-noinc | sig_dep | — | off | 3263.2 | 26.4 | yes |
| sccache-noinc | worktree | empty | off | 6236.6 | 29.3 | yes |
| sccache-warm-inc | cold | warm_compiler_cache | on | 12.3 | 0.2 | no |
| sccache-warm-inc | noop | — | on | 11.9 | 0.1 | no |
| sccache-warm-inc | body | warm_compiler_cache | on | 11.5 | 0.2 | no |
| sccache-warm-inc | sig_dep | warm_compiler_cache | on | 11.3 | 0.2 | no |
| sccache-warm-inc | worktree | warm_compiler_cache | on | 12.3 | 0.3 | no |
| sccache-warm-noinc | cold | warm_compiler_cache | off | 6223.0 | 30.9 | yes |
| sccache-warm-noinc | noop | — | off | 49.8 | 1.1 | yes |
| sccache-warm-noinc | body | warm_compiler_cache | off | 3264.4 | 54.4 | yes |
| sccache-warm-noinc | sig_dep | warm_compiler_cache | off | 3270.3 | 0.3 | yes |
| sccache-warm-noinc | worktree | warm_compiler_cache | off | 6099.5 | 11.3 | yes |
| kache-inc | cold | empty | on | 6219.1 | 163.0 | yes |
| kache-inc | noop | — | on | 46.8 | 1.4 | yes |
| kache-inc | body | — | on | 782.0 | 4.5 | yes |
| kache-inc | sig_dep | — | on | 784.4 | 4.9 | yes |
| kache-inc | worktree | empty | on | 6394.2 | 93.2 | yes |
| kache-noinc | cold | empty | off | 6376.0 | 14.0 | yes |
| kache-noinc | noop | — | off | 45.8 | 1.5 | yes |
| kache-noinc | body | — | off | 3414.2 | 55.2 | yes |
| kache-noinc | sig_dep | — | off | 3415.2 | 27.1 | yes |
| kache-noinc | worktree | empty | off | 6775.2 | 23.5 | yes |
| kache-warm-inc | cold | warm_compiler_cache | on | 161.6 | 4.7 | yes |
| kache-warm-inc | noop | — | on | 48.2 | 1.1 | yes |
| kache-warm-inc | body | warm_compiler_cache | on | 776.8 | 13.2 | yes |
| kache-warm-inc | sig_dep | warm_compiler_cache | on | 2243.4 | 1483.8 | yes |
| kache-warm-inc | worktree | warm_compiler_cache | on | 489.2 | 5.0 | yes |
| kache-warm-noinc | cold | warm_compiler_cache | off | 156.3 | 4.1 | yes |
| kache-warm-noinc | noop | — | off | 45.1 | 0.8 | yes |
| kache-warm-noinc | body | warm_compiler_cache | off | 287.3 | 4.8 | yes |
| kache-warm-noinc | sig_dep | warm_compiler_cache | off | 285.7 | 2.1 | yes |
| kache-warm-noinc | worktree | warm_compiler_cache | off | 492.3 | 1.7 | yes |
| wrapper-noinc | cold | empty | off | 5643.8 | 9.8 | yes |
| wrapper-noinc | noop | — | off | 49.1 | 2.1 | yes |
| wrapper-noinc | body | — | off | 3074.6 | 34.0 | yes |
| wrapper-noinc | sig_dep | — | off | 2982.6 | 34.6 | yes |
| wrapper-noinc | worktree | empty | off | 6045.2 | 63.8 | yes |

