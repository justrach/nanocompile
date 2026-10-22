# wrapper compare: hashbrown

Project: `/workspace/examples/pinned-hashbrown`
Edits: cold, noop, body, sig_dep, worktree. Runs 3, warmup 1.
Correctness gate is cargo test + LLVM rustc. Clippy/nextest are not the gate.

| Family | Edit | Cache | Inc | Median ms | Spread ms | OK |
| --- | --- | --- | --- | ---: | ---: | --- |
| incremental | cold | empty | on | 492.2 | 2.4 | yes |
| incremental | noop | — | on | 14.9 | 0.3 | yes |
| incremental | body | — | on | 110.8 | 3.5 | yes |
| incremental | sig_dep | — | on | 111.8 | 3.9 | yes |
| incremental | worktree | empty | on | 492.6 | 3.4 | yes |
| noinc | cold | empty | off | 438.4 | 9.5 | yes |
| noinc | noop | — | off | 15.7 | 0.2 | yes |
| noinc | body | — | off | 273.8 | 5.9 | yes |
| noinc | sig_dep | — | off | 277.5 | 3.0 | yes |
| noinc | worktree | empty | off | 424.8 | 7.4 | yes |
| sccache-inc | cold | empty | on | 11.9 | 0.3 | no |
| sccache-inc | noop | — | on | 10.3 | 0.3 | no |
| sccache-inc | body | — | on | 10.2 | 0.4 | no |
| sccache-inc | sig_dep | — | on | 10.4 | 0.2 | no |
| sccache-inc | worktree | empty | on | 10.9 | 0.4 | no |
| sccache-noinc | cold | empty | off | 550.7 | 6.1 | yes |
| sccache-noinc | noop | — | off | 15.0 | 0.3 | yes |
| sccache-noinc | body | — | off | 341.1 | 3.2 | yes |
| sccache-noinc | sig_dep | — | off | 343.6 | 5.8 | yes |
| sccache-noinc | worktree | empty | off | 531.7 | 1.9 | yes |
| sccache-warm-inc | cold | warm_compiler_cache | on | 12.0 | 0.3 | no |
| sccache-warm-inc | noop | — | on | 10.2 | 0.1 | no |
| sccache-warm-inc | body | warm_compiler_cache | on | 9.9 | 0.3 | no |
| sccache-warm-inc | sig_dep | warm_compiler_cache | on | 10.1 | 0.0 | no |
| sccache-warm-inc | worktree | warm_compiler_cache | on | 11.3 | 0.3 | no |
| sccache-warm-noinc | cold | warm_compiler_cache | off | 534.1 | 7.1 | yes |
| sccache-warm-noinc | noop | — | off | 14.9 | 0.3 | yes |
| sccache-warm-noinc | body | warm_compiler_cache | off | 340.5 | 0.4 | yes |
| sccache-warm-noinc | sig_dep | warm_compiler_cache | off | 339.0 | 1.3 | yes |
| sccache-warm-noinc | worktree | warm_compiler_cache | off | 539.2 | 3.2 | yes |
| kache-inc | cold | empty | on | 582.3 | 7.1 | yes |
| kache-inc | noop | — | on | 15.0 | 0.4 | yes |
| kache-inc | body | — | on | 124.7 | 4.4 | yes |
| kache-inc | sig_dep | — | on | 126.7 | 2.6 | yes |
| kache-inc | worktree | empty | on | 565.9 | 11.2 | yes |
| kache-noinc | cold | empty | off | 577.7 | 1.9 | yes |
| kache-noinc | noop | — | off | 14.8 | 0.8 | yes |
| kache-noinc | body | — | off | 371.1 | 4.0 | yes |
| kache-noinc | sig_dep | — | off | 370.6 | 1.4 | yes |
| kache-noinc | worktree | empty | off | 563.9 | 8.0 | yes |
| kache-warm-inc | cold | warm_compiler_cache | on | 62.9 | 1.3 | yes |
| kache-warm-inc | noop | — | on | 15.0 | 0.2 | yes |
| kache-warm-inc | body | warm_compiler_cache | on | 125.1 | 8.6 | yes |
| kache-warm-inc | sig_dep | warm_compiler_cache | on | 117.3 | 138.3 | yes |
| kache-warm-inc | worktree | warm_compiler_cache | on | 84.3 | 1.2 | yes |
| kache-warm-noinc | cold | warm_compiler_cache | off | 63.5 | 1.4 | yes |
| kache-warm-noinc | noop | — | off | 14.4 | 0.3 | yes |
| kache-warm-noinc | body | warm_compiler_cache | off | 66.9 | 0.6 | yes |
| kache-warm-noinc | sig_dep | warm_compiler_cache | off | 70.6 | 1.3 | yes |
| kache-warm-noinc | worktree | warm_compiler_cache | off | 86.4 | 1.3 | yes |
| wrapper-noinc | cold | empty | off | 550.4 | 2.6 | yes |
| wrapper-noinc | noop | — | off | 15.5 | 0.6 | yes |
| wrapper-noinc | body | — | off | 386.0 | 3.5 | yes |
| wrapper-noinc | sig_dep | — | off | 379.7 | 4.6 | yes |
| wrapper-noinc | worktree | empty | off | 547.7 | 2.8 | yes |

