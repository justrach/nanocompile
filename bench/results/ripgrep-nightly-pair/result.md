# nightly LLVM vs cranelift: ripgrep

| Backend | Command | Phase | Median ms | OK |
| --- | --- | --- | ---: | --- |
| nightly-llvm | build | cold | 6807.5 | yes |
| nightly-llvm | build | noop | 26.8 | yes |
| nightly-llvm | build | edit_body | 472.7 | yes |
| nightly-llvm | build | edit_sig | 165.7 | no |
| nightly-cranelift | build | cold | 4938.9 | yes |
| nightly-cranelift | build | noop | 26.8 | yes |
| nightly-cranelift | build | edit_body | 382.1 | yes |
| nightly-cranelift | build | edit_sig | 146.4 | no |
| nightly-llvm | test | cold | 7849.5 | yes |
| nightly-llvm | test | noop | 26.3 | yes |
| nightly-llvm | test | edit_body | 505.7 | yes |
| nightly-llvm | test | edit_sig | 432.8 | no |
| nightly-cranelift | test | cold | 6118.4 | yes |
| nightly-cranelift | test | noop | 28.0 | yes |
| nightly-cranelift | test | edit_body | 429.5 | yes |
| nightly-cranelift | test | edit_sig | 405.8 | no |
