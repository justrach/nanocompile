# nightly LLVM vs cranelift: tokio

| Backend | Command | Phase | Median ms | OK |
| --- | --- | --- | ---: | --- |
| nightly-llvm | build | cold | 6749.0 | yes |
| nightly-llvm | build | noop | 38.7 | yes |
| nightly-llvm | build | edit_body | 1120.2 | yes |
| nightly-llvm | build | edit_sig | 1050.7 | yes |
| nightly-cranelift | build | cold | 5808.4 | yes |
| nightly-cranelift | build | noop | 38.4 | yes |
| nightly-cranelift | build | edit_body | 1033.1 | yes |
| nightly-cranelift | build | edit_sig | 1059.8 | yes |
| nightly-llvm | test | cold | 10233.3 | no |
| nightly-llvm | test | noop | 646.8 | no |
| nightly-llvm | test | edit_body | 2466.9 | no |
| nightly-llvm | test | edit_sig | 5449.0 | no |
| nightly-cranelift | test | cold | 9218.7 | no |
| nightly-cranelift | test | noop | 705.3 | no |
| nightly-cranelift | test | edit_body | 2111.0 | no |
| nightly-cranelift | test | edit_sig | 1703.1 | no |
