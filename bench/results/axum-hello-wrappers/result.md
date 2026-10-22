# wrapper compare: axum-hello

Project: `/tmp/real-samples/axum`
Edits: cold, noop, body, sig_dep, worktree. Runs 2, warmup 1.
Correctness gate is cargo test + LLVM rustc. Clippy/nextest are not the gate.

| Family | Edit | Cache | Inc | Median ms | Spread ms | OK |
| --- | --- | --- | --- | ---: | ---: | --- |
| incremental | cold | empty | on | 9348.0 | 340.8 | yes |
| incremental | noop | — | on | 135.9 | 17.4 | yes |
| incremental | body | — | on | 131.9 | 5.2 | yes |
| incremental | sig_dep | — | on | 125.2 | 0.9 | yes |
| incremental | worktree | empty | on | 8964.9 | 200.8 | yes |
| noinc | cold | empty | off | 8302.7 | 73.9 | yes |
| noinc | noop | — | off | 101.7 | 1.1 | yes |
| noinc | body | — | off | 130.9 | 1.5 | yes |
| noinc | sig_dep | — | off | 131.0 | 2.8 | yes |
| noinc | worktree | empty | off | 8385.7 | 127.5 | yes |
| sccache-inc | cold | empty | on | 18.2 | 0.2 | no |
| sccache-inc | noop | — | on | 17.2 | 0.2 | no |
| sccache-inc | body | — | on | 22.7 | 3.8 | no |
| sccache-inc | sig_dep | — | on | 20.0 | 0.9 | no |
| sccache-inc | worktree | empty | on | 25.9 | 1.5 | no |
| sccache-noinc | cold | empty | off | 11833.2 | 450.4 | yes |
| sccache-noinc | noop | — | off | 130.8 | 13.9 | yes |
| sccache-noinc | body | — | off | 194.7 | 7.5 | yes |
| sccache-noinc | sig_dep | — | off | 201.0 | 49.2 | yes |
| sccache-noinc | worktree | empty | off | 11435.3 | 737.3 | yes |
| sccache-warm-inc | cold | warm_compiler_cache | on | 18.0 | 0.5 | no |
| sccache-warm-inc | noop | — | on | 16.9 | 0.7 | no |
| sccache-warm-inc | body | warm_compiler_cache | on | 17.8 | 1.4 | no |
| sccache-warm-inc | sig_dep | warm_compiler_cache | on | 19.5 | 0.9 | no |
| sccache-warm-inc | worktree | warm_compiler_cache | on | 19.0 | 0.4 | no |
| sccache-warm-noinc | cold | warm_compiler_cache | off | 10644.7 | 601.6 | yes |
| sccache-warm-noinc | noop | — | off | 158.6 | 7.2 | yes |
| sccache-warm-noinc | body | warm_compiler_cache | off | 202.9 | 19.2 | yes |
| sccache-warm-noinc | sig_dep | warm_compiler_cache | off | 237.5 | 0.9 | yes |
| sccache-warm-noinc | worktree | warm_compiler_cache | off | 11166.8 | 203.5 | yes |
| kache-inc | cold | empty | on | 11604.6 | 38.1 | yes |
| kache-inc | noop | — | on | 102.7 | 0.8 | yes |
| kache-inc | body | — | on | 142.2 | 4.9 | yes |
| kache-inc | sig_dep | — | on | 138.5 | 4.6 | yes |
| kache-inc | worktree | empty | on | 8698.2 | 61.0 | yes |
| kache-noinc | cold | empty | off | 8785.2 | 79.1 | yes |
| kache-noinc | noop | — | off | 103.2 | 4.2 | yes |
| kache-noinc | body | — | off | 357.5 | 13.9 | yes |
| kache-noinc | sig_dep | — | off | 316.1 | 2.1 | yes |
| kache-noinc | worktree | empty | off | 8726.9 | 52.1 | yes |
| kache-warm-inc | cold | warm_compiler_cache | on | 338.7 | 4.1 | yes |
| kache-warm-inc | noop | — | on | 104.8 | 0.6 | yes |
| kache-warm-inc | body | warm_compiler_cache | on | 136.4 | 0.4 | yes |
| kache-warm-inc | sig_dep | warm_compiler_cache | on | 163.2 | 31.5 | yes |
| kache-warm-inc | worktree | warm_compiler_cache | on | 610.3 | 102.5 | yes |
| kache-warm-noinc | cold | warm_compiler_cache | off | 321.3 | 3.6 | yes |
| kache-warm-noinc | noop | — | off | 102.4 | 0.9 | yes |
| kache-warm-noinc | body | warm_compiler_cache | off | 153.6 | 1.5 | yes |
| kache-warm-noinc | sig_dep | warm_compiler_cache | off | 147.1 | 3.9 | yes |
| kache-warm-noinc | worktree | warm_compiler_cache | off | 613.8 | 94.6 | yes |
| wrapper-noinc | cold | empty | off | 7894.0 | 52.5 | yes |
| wrapper-noinc | noop | — | off | 105.6 | 0.1 | yes |
| wrapper-noinc | body | — | off | 147.9 | 0.6 | yes |
| wrapper-noinc | sig_dep | — | off | 146.2 | 2.0 | yes |
| wrapper-noinc | worktree | empty | off | 7885.1 | 26.4 | yes |

