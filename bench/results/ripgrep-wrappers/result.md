# wrapper compare: ripgrep

Project: `/tmp/real-samples/ripgrep`
Edits: cold, noop, body, sig_dep, worktree. Runs 2, warmup 1.
Correctness gate is cargo test + LLVM rustc. Clippy/nextest are not the gate.

| Family | Edit | Cache | Inc | Median ms | Spread ms | OK |
| --- | --- | --- | --- | ---: | ---: | --- |
| incremental | cold | empty | on | 3174.4 | 33.7 | yes |
| incremental | noop | — | on | 34.4 | 0.8 | yes |
| incremental | body | — | on | 166.2 | 2.2 | yes |
| incremental | sig_dep | — | on | 140.3 | 0.3 | no |
| incremental | worktree | empty | on | 3173.4 | 4.8 | yes |
| noinc | cold | empty | off | 2911.7 | 14.6 | yes |
| noinc | noop | — | off | 32.4 | 0.3 | yes |
| noinc | body | — | off | 357.7 | 1.6 | yes |
| noinc | sig_dep | — | off | 354.2 | 6.0 | no |
| noinc | worktree | empty | off | 2754.0 | 15.0 | yes |
| sccache-inc | cold | empty | on | 13.3 | 0.2 | no |
| sccache-inc | noop | — | on | 11.9 | 0.1 | no |
| sccache-inc | body | — | on | 11.6 | 0.2 | no |
| sccache-inc | sig_dep | — | on | 11.3 | 0.3 | no |
| sccache-inc | worktree | empty | on | 12.8 | 0.1 | no |
| sccache-noinc | cold | empty | off | 3237.8 | 5.2 | yes |
| sccache-noinc | noop | — | off | 32.2 | 0.6 | yes |
| sccache-noinc | body | — | off | 369.5 | 3.9 | yes |
| sccache-noinc | sig_dep | — | off | 346.6 | 1.7 | no |
| sccache-noinc | worktree | empty | off | 3235.1 | 30.8 | yes |
| sccache-warm-inc | cold | warm_compiler_cache | on | 12.3 | 0.1 | no |
| sccache-warm-inc | noop | — | on | 11.8 | 0.0 | no |
| sccache-warm-inc | body | warm_compiler_cache | on | 11.6 | 0.2 | no |
| sccache-warm-inc | sig_dep | warm_compiler_cache | on | 11.8 | 0.1 | no |
| sccache-warm-inc | worktree | warm_compiler_cache | on | 12.5 | 0.0 | no |
| sccache-warm-noinc | cold | warm_compiler_cache | off | 3239.2 | 13.6 | yes |
| sccache-warm-noinc | noop | — | off | 32.7 | 0.3 | yes |
| sccache-warm-noinc | body | warm_compiler_cache | off | 378.7 | 4.5 | yes |
| sccache-warm-noinc | sig_dep | warm_compiler_cache | off | 351.5 | 6.0 | no |
| sccache-warm-noinc | worktree | warm_compiler_cache | off | 3254.8 | 20.7 | yes |
| kache-inc | cold | empty | on | 3434.0 | 37.4 | yes |
| kache-inc | noop | — | on | 32.2 | 0.0 | yes |
| kache-inc | body | — | on | 470.3 | 0.3 | yes |
| kache-inc | sig_dep | — | on | 447.9 | 1.4 | no |
| kache-inc | worktree | empty | on | 3380.5 | 20.9 | yes |
| kache-noinc | cold | empty | off | 3363.1 | 1.8 | yes |
| kache-noinc | noop | — | off | 31.8 | 0.5 | yes |
| kache-noinc | body | — | off | 883.6 | 7.7 | yes |
| kache-noinc | sig_dep | — | off | 853.6 | 5.1 | no |
| kache-noinc | worktree | empty | off | 3368.7 | 13.3 | yes |
| kache-warm-inc | cold | warm_compiler_cache | on | 182.5 | 1.6 | yes |
| kache-warm-inc | noop | — | on | 29.7 | 0.7 | yes |
| kache-warm-inc | body | warm_compiler_cache | on | 165.3 | 2.9 | yes |
| kache-warm-inc | sig_dep | warm_compiler_cache | on | 339.8 | 194.6 | no |
| kache-warm-inc | worktree | warm_compiler_cache | on | 546.4 | 287.8 | yes |
| kache-warm-noinc | cold | warm_compiler_cache | off | 182.4 | 1.5 | yes |
| kache-warm-noinc | noop | — | off | 32.2 | 1.2 | yes |
| kache-warm-noinc | body | warm_compiler_cache | off | 135.1 | 0.3 | yes |
| kache-warm-noinc | sig_dep | warm_compiler_cache | off | 455.2 | 18.7 | no |
| kache-warm-noinc | worktree | warm_compiler_cache | off | 546.2 | 281.6 | yes |
| wrapper-noinc | cold | empty | off | 3095.2 | 17.2 | yes |
| wrapper-noinc | noop | — | off | 32.1 | 0.2 | yes |
| wrapper-noinc | body | — | off | 350.1 | 9.0 | yes |
| wrapper-noinc | sig_dep | — | off | 341.8 | 1.0 | no |
| wrapper-noinc | worktree | empty | off | 3168.1 | 16.6 | yes |

