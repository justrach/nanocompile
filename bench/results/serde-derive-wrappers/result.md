# wrapper compare: serde-derive

Project: `/tmp/real-samples/serde`
Edits: cold, noop, body, sig_dep, worktree. Runs 2, warmup 1.
Correctness gate is cargo test + LLVM rustc. Clippy/nextest are not the gate.

| Family | Edit | Cache | Inc | Median ms | Spread ms | OK |
| --- | --- | --- | --- | ---: | ---: | --- |
| incremental | cold | empty | on | 1672.4 | 12.8 | yes |
| incremental | noop | — | on | 17.6 | 0.0 | yes |
| incremental | body | — | on | 265.3 | 1.9 | yes |
| incremental | sig_dep | — | on | 260.0 | 6.1 | yes |
| incremental | worktree | empty | on | 1703.4 | 45.9 | yes |
| noinc | cold | empty | off | 1618.4 | 60.6 | yes |
| noinc | noop | — | off | 17.4 | 0.6 | yes |
| noinc | body | — | off | 694.6 | 2.4 | yes |
| noinc | sig_dep | — | off | 694.9 | 2.5 | yes |
| noinc | worktree | empty | off | 1581.8 | 24.0 | yes |
| sccache-inc | cold | empty | on | 12.9 | 0.7 | no |
| sccache-inc | noop | — | on | 11.1 | 0.2 | no |
| sccache-inc | body | — | on | 11.3 | 0.5 | no |
| sccache-inc | sig_dep | — | on | 11.7 | 0.3 | no |
| sccache-inc | worktree | empty | on | 11.6 | 0.3 | no |
| sccache-noinc | cold | empty | off | 1794.5 | 33.1 | yes |
| sccache-noinc | noop | — | off | 16.7 | 0.5 | yes |
| sccache-noinc | body | — | off | 688.6 | 2.6 | yes |
| sccache-noinc | sig_dep | — | off | 710.5 | 5.9 | yes |
| sccache-noinc | worktree | empty | off | 1801.9 | 0.3 | yes |
| sccache-warm-inc | cold | warm_compiler_cache | on | 14.1 | 0.4 | no |
| sccache-warm-inc | noop | — | on | 11.6 | 0.1 | no |
| sccache-warm-inc | body | warm_compiler_cache | on | 11.2 | 0.0 | no |
| sccache-warm-inc | sig_dep | warm_compiler_cache | on | 11.0 | 0.3 | no |
| sccache-warm-inc | worktree | warm_compiler_cache | on | 11.9 | 0.1 | no |
| sccache-warm-noinc | cold | warm_compiler_cache | off | 2077.1 | 50.2 | yes |
| sccache-warm-noinc | noop | — | off | 19.0 | 0.4 | yes |
| sccache-warm-noinc | body | warm_compiler_cache | off | 713.6 | 5.4 | yes |
| sccache-warm-noinc | sig_dep | warm_compiler_cache | off | 701.9 | 2.3 | yes |
| sccache-warm-noinc | worktree | warm_compiler_cache | off | 1799.3 | 25.5 | yes |
| kache-inc | cold | empty | on | 2119.2 | 1.2 | yes |
| kache-inc | noop | — | on | 16.9 | 0.9 | yes |
| kache-inc | body | — | on | 260.5 | 3.2 | yes |
| kache-inc | sig_dep | — | on | 267.7 | 2.9 | yes |
| kache-inc | worktree | empty | on | 2128.9 | 6.0 | yes |
| kache-noinc | cold | empty | off | 2167.4 | 31.8 | yes |
| kache-noinc | noop | — | off | 17.6 | 0.4 | yes |
| kache-noinc | body | — | off | 942.1 | 6.5 | yes |
| kache-noinc | sig_dep | — | off | 931.1 | 3.9 | yes |
| kache-noinc | worktree | empty | off | 2100.0 | 3.9 | yes |
| kache-warm-inc | cold | warm_compiler_cache | on | 90.2 | 0.1 | yes |
| kache-warm-inc | noop | — | on | 16.3 | 0.6 | yes |
| kache-warm-inc | body | warm_compiler_cache | on | 256.8 | 0.6 | yes |
| kache-warm-inc | sig_dep | warm_compiler_cache | on | 616.8 | 349.1 | yes |
| kache-warm-inc | worktree | warm_compiler_cache | on | 143.9 | 2.0 | yes |
| kache-warm-noinc | cold | warm_compiler_cache | off | 92.0 | 2.6 | yes |
| kache-warm-noinc | noop | — | off | 15.9 | 0.0 | yes |
| kache-warm-noinc | body | warm_compiler_cache | off | 196.2 | 2.1 | yes |
| kache-warm-noinc | sig_dep | warm_compiler_cache | off | 194.7 | 1.3 | yes |
| kache-warm-noinc | worktree | warm_compiler_cache | off | 155.7 | 0.1 | yes |
| wrapper-noinc | cold | empty | off | 1847.2 | 19.1 | yes |
| wrapper-noinc | noop | — | off | 17.3 | 0.2 | yes |
| wrapper-noinc | body | — | off | 664.8 | 0.9 | yes |
| wrapper-noinc | sig_dep | — | off | 751.3 | 23.6 | yes |
| wrapper-noinc | worktree | empty | off | 1885.0 | 8.1 | yes |

