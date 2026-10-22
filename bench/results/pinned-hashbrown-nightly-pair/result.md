# nightly LLVM vs cranelift: pinned-hashbrown

| Backend | Command | Phase | Median ms | OK |
| --- | --- | --- | ---: | --- |
| nightly-llvm | build | cold | 584.8 | yes |
| nightly-llvm | build | noop | 15.2 | yes |
| nightly-llvm | build | edit_body | 130.4 | yes |
| nightly-llvm | build | edit_sig | 129.2 | yes |
| nightly-cranelift | build | cold | 596.7 | yes |
| nightly-cranelift | build | noop | 15.5 | yes |
| nightly-cranelift | build | edit_body | 140.3 | yes |
| nightly-cranelift | build | edit_sig | 132.9 | yes |
| nightly-llvm | test | cold | 3474.0 | yes |
| nightly-llvm | test | noop | 27.8 | yes |
| nightly-llvm | test | edit_body | 389.9 | yes |
| nightly-llvm | test | edit_sig | 352.5 | yes |
| nightly-cranelift | test | cold | 3262.4 | yes |
| nightly-cranelift | test | noop | 18.2 | yes |
| nightly-cranelift | test | edit_body | 322.9 | yes |
| nightly-cranelift | test | edit_sig | 327.3 | yes |
