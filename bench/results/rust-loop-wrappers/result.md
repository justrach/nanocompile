# wrapper compare: rust-loop

Project: `/workspace/examples/rust-loop`
Edits: cold, noop, body, sig_dep, worktree. Runs 3, warmup 1.
Correctness gate is cargo test + LLVM rustc. Clippy/nextest are not the gate.

| Family | Edit | Cache | Inc | Median ms | Spread ms | OK |
| --- | --- | --- | --- | ---: | ---: | --- |
| incremental | cold | empty | on | 38.7 | 0.5 | yes |
| incremental | noop | — | on | 10.5 | 0.1 | yes |
| incremental | body | — | on | 23.6 | 0.1 | yes |
| incremental | sig_dep | — | on | 55.1 | 9.2 | yes |
| incremental | worktree | empty | on | 79.1 | 4.1 | yes |
| noinc | cold | empty | off | 82.4 | 7.9 | yes |
| noinc | noop | — | off | 31.6 | 7.0 | yes |
| noinc | body | — | off | 21.7 | 0.7 | yes |
| noinc | sig_dep | — | off | 22.1 | 1.5 | yes |
| noinc | worktree | empty | off | 36.9 | 1.2 | yes |
| sccache-inc | cold | empty | on | 11.5 | 0.1 | no |
| sccache-inc | noop | — | on | 10.5 | 0.4 | no |
| sccache-inc | body | — | on | 10.2 | 1.1 | no |
| sccache-inc | sig_dep | — | on | 10.0 | 0.1 | no |
| sccache-inc | worktree | empty | on | 11.0 | 0.2 | no |
| sccache-noinc | cold | empty | off | 70.9 | 1.2 | yes |
| sccache-noinc | noop | — | off | 11.0 | 0.3 | yes |
| sccache-noinc | body | — | off | 44.5 | 1.4 | yes |
| sccache-noinc | sig_dep | — | off | 42.1 | 1.1 | yes |
| sccache-noinc | worktree | empty | off | 67.2 | 5.3 | yes |
| sccache-warm-inc | cold | warm_compiler_cache | on | 11.0 | 0.3 | no |
| sccache-warm-inc | noop | — | on | 10.0 | 0.2 | no |
| sccache-warm-inc | body | warm_compiler_cache | on | 10.6 | 0.1 | no |
| sccache-warm-inc | sig_dep | warm_compiler_cache | on | 10.1 | 0.6 | no |
| sccache-warm-inc | worktree | warm_compiler_cache | on | 11.2 | 0.1 | no |
| sccache-warm-noinc | cold | warm_compiler_cache | off | 68.0 | 1.4 | yes |
| sccache-warm-noinc | noop | — | off | 11.7 | 0.5 | yes |
| sccache-warm-noinc | body | warm_compiler_cache | off | 43.1 | 2.1 | yes |
| sccache-warm-noinc | sig_dep | warm_compiler_cache | off | 43.8 | 1.0 | yes |
| sccache-warm-noinc | worktree | warm_compiler_cache | off | 64.1 | 0.6 | yes |
| kache-inc | cold | empty | on | 73.5 | 0.6 | yes |
| kache-inc | noop | — | on | 11.3 | 0.4 | yes |
| kache-inc | body | — | on | 33.3 | 1.8 | yes |
| kache-inc | sig_dep | — | on | 29.3 | 2.0 | yes |
| kache-inc | worktree | empty | on | 71.7 | 0.9 | yes |
| kache-noinc | cold | empty | off | 71.3 | 0.6 | yes |
| kache-noinc | noop | — | off | 11.2 | 0.9 | yes |
| kache-noinc | body | — | off | 45.8 | 2.1 | yes |
| kache-noinc | sig_dep | — | off | 43.6 | 0.4 | yes |
| kache-noinc | worktree | empty | off | 71.1 | 1.1 | yes |
| kache-warm-inc | cold | warm_compiler_cache | on | 43.8 | 0.8 | yes |
| kache-warm-inc | noop | — | on | 11.4 | 0.2 | yes |
| kache-warm-inc | body | warm_compiler_cache | on | 26.7 | 0.1 | yes |
| kache-warm-inc | sig_dep | warm_compiler_cache | on | 28.5 | 5.6 | yes |
| kache-warm-inc | worktree | warm_compiler_cache | on | 50.4 | 1.6 | yes |
| kache-warm-noinc | cold | warm_compiler_cache | off | 45.3 | 14.8 | yes |
| kache-warm-noinc | noop | — | off | 12.0 | 1.1 | yes |
| kache-warm-noinc | body | warm_compiler_cache | off | 30.6 | 0.9 | yes |
| kache-warm-noinc | sig_dep | warm_compiler_cache | off | 29.1 | 5.2 | yes |
| kache-warm-noinc | worktree | warm_compiler_cache | off | 43.9 | 0.2 | yes |
| wrapper-noinc | cold | empty | off | 165.8 | 7.6 | yes |
| wrapper-noinc | noop | — | off | 11.4 | 0.2 | yes |
| wrapper-noinc | body | — | off | 145.7 | 8.1 | yes |
| wrapper-noinc | sig_dep | — | off | 147.0 | 11.8 | yes |
| wrapper-noinc | worktree | empty | off | 164.5 | 16.0 | yes |

