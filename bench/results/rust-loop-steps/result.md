# rust-loop bench: rust-loop-steps

Project: `/workspace/examples/rust-loop`
Runs: 3 timed, 1 warmup. Schema 1.

| Step | Command | Phase | Median ms | Spread ms | Target bytes | OK |
| --- | --- | --- | ---: | ---: | ---: | --- |
| baseline | check | cold | 45.7 | 0.5 | 35325 | yes |
| baseline | check | noop | 10.1 | 0.1 | 35325 | yes |
| baseline | check | edit_body | 26.1 | 0.0 | 35715 | yes |
| baseline | check | edit_sig | 24.8 | 0.0 | 35713 | yes |
| baseline | test | cold | 170.7 | 1.8 | 7082315 | yes |
| baseline | test | noop | 22.2 | 0.5 | 7082315 | yes |
| baseline | test | edit_body | 133.4 | 0.0 | 7081086 | yes |
| baseline | test | edit_sig | 133.7 | 0.0 | 7081161 | yes |
| nanocompile-wrapper | check | cold | 131.3 | 1.1 | 7022 | yes |
| nanocompile-wrapper | check | noop | 9.8 | 0.4 | 7022 | yes |
| nanocompile-wrapper | check | edit_body | 46.7 | 0.0 | 7076 | yes |
| nanocompile-wrapper | check | edit_sig | 40.1 | 0.0 | 7086 | yes |
| nanocompile-wrapper | test | cold | 182.0 | 8.0 | 6321295 | yes |
| nanocompile-wrapper | test | noop | 21.4 | 0.4 | 6321295 | yes |
| nanocompile-wrapper | test | edit_body | 138.5 | 0.0 | 6321403 | yes |
| nanocompile-wrapper | test | edit_sig | 140.9 | 0.0 | 6321423 | yes |
| fast-check | check | cold | 44.9 | 0.3 | 35329 | yes |
| fast-check | check | noop | 10.0 | 0.4 | 35329 | yes |
| fast-check | check | edit_body | 25.5 | 0.0 | 35719 | yes |
| fast-check | check | edit_sig | 25.2 | 0.0 | 35717 | yes |
| validate-graph | graph | cold | 294.5 | 2.4 | 6327249 | yes |
| validate-graph | graph | noop | 1.4 | 0.1 | 6327249 | yes |
| validate-graph | graph | edit_body | 189.3 | 0.0 | 6327411 | yes |
| validate-graph | graph | edit_sig | 183.5 | 0.0 | 6327441 | yes |
| fast-linker | test | cold | 119.0 | 0.4 | 7156508 | yes |
| fast-linker | test | noop | 21.5 | 0.2 | 7156508 | yes |
| fast-linker | test | edit_body | 78.3 | 0.0 | 7155278 | yes |
| fast-linker | test | edit_sig | 77.9 | 0.0 | 7155353 | yes |
| sccache | check | cold | 53.4 | 0.5 | 35323 | yes |
| sccache | check | noop | 9.6 | 0.2 | 35323 | yes |
| sccache | check | edit_body | 28.2 | 0.0 | 35713 | yes |
| sccache | check | edit_sig | 27.9 | 0.0 | 35711 | yes |
| sccache | test | cold | 177.8 | 1.8 | 7082310 | yes |
| sccache | test | noop | 22.0 | 0.5 | 7082310 | yes |
| sccache | test | edit_body | 135.4 | 0.0 | 7081081 | yes |
| sccache | test | edit_sig | 133.4 | 0.0 | 7081156 | yes |
| crate-shape | check | cold | 44.6 | 0.8 | 35354 | yes |
| crate-shape | check | noop | 10.1 | 0.2 | 35354 | yes |
| crate-shape | check | edit_body | 25.2 | 0.0 | 35744 | yes |
| crate-shape | check | edit_sig | 25.8 | 0.0 | 35742 | yes |
| crate-shape | test | cold | 170.7 | 2.4 | 7082377 | yes |
| crate-shape | test | noop | 22.3 | 0.7 | 7082377 | yes |
| crate-shape | test | edit_body | 131.0 | 0.0 | 7081148 | yes |
| crate-shape | test | edit_sig | 133.9 | 0.0 | 7081223 | yes |
| disk-hygiene | test | cold | 164.2 | 0.3 | 6956185 | yes |
| disk-hygiene | test | noop | 21.9 | 0.8 | 6956185 | yes |
| disk-hygiene | test | edit_body | 134.9 | 0.0 | 6954955 | yes |
| disk-hygiene | test | edit_sig | 135.1 | 0.0 | 6955030 | yes |

## Correctness

- broken edit applied: True
- fast-check failed: True
- validate failed or did not run: True
- fast and rustc agree (both fail): True

