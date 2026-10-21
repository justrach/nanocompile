# nightly LLVM vs cranelift: rust-loop

| Backend | Command | Phase | Median ms | OK |
| --- | --- | --- | ---: | --- |
| nightly-llvm | build | cold | 47.1 | yes |
| nightly-llvm | build | noop | 11.4 | yes |
| nightly-llvm | build | edit_body | 27.4 | yes |
| nightly-llvm | build | edit_sig | 27.0 | yes |
| nightly-cranelift | build | cold | 43.3 | yes |
| nightly-cranelift | build | noop | 11.4 | yes |
| nightly-cranelift | build | edit_body | 26.4 | yes |
| nightly-cranelift | build | edit_sig | 24.9 | yes |
| nightly-llvm | test | cold | 117.7 | yes |
| nightly-llvm | test | noop | 12.2 | yes |
| nightly-llvm | test | edit_body | 83.0 | yes |
| nightly-llvm | test | edit_sig | 78.5 | yes |
| nightly-cranelift | test | cold | 107.7 | yes |
| nightly-cranelift | test | noop | 11.9 | yes |
| nightly-cranelift | test | edit_body | 81.0 | yes |
| nightly-cranelift | test | edit_sig | 80.7 | yes |
