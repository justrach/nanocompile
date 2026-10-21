# rust-loop bench: rust-loop-cranelift

Project: `/workspace/examples/rust-loop`
Runs: 3 timed, 1 warmup. Schema 1.

| Step | Command | Phase | Median ms | Spread ms | Target bytes | OK |
| --- | --- | --- | ---: | ---: | ---: | --- |
| baseline | build | cold | 48.6 | 0.4 | 56404 | yes |
| baseline | build | noop | 10.6 | 0.4 | 56404 | yes |
| baseline | build | edit_body | 26.8 | 0.0 | 56668 | yes |
| baseline | build | edit_sig | 26.7 | 0.0 | 56764 | yes |
| baseline | test | cold | 183.6 | 1.6 | 7082318 | yes |
| baseline | test | noop | 22.1 | 0.0 | 7082318 | yes |
| baseline | test | edit_body | 144.0 | 0.0 | 7081087 | yes |
| baseline | test | edit_sig | 144.6 | 0.0 | 7081162 | yes |
| cranelift-dev | build | cold | 45.5 | 1.4 | 62372 | yes |
| cranelift-dev | build | noop | 10.8 | 0.1 | 62372 | yes |
| cranelift-dev | build | edit_body | 25.0 | 0.0 | 62352 | yes |
| cranelift-dev | build | edit_sig | 26.3 | 0.0 | 62383 | yes |
| cranelift-dev | test | cold | 108.3 | 4.0 | 7780976 | yes |
| cranelift-dev | test | noop | 21.6 | 0.5 | 7780976 | yes |
| cranelift-dev | test | edit_body | 77.0 | 0.0 | 7794096 | yes |
| cranelift-dev | test | edit_sig | 78.4 | 0.0 | 7794044 | yes |

## Correctness

- broken edit applied: True
- fast-check failed: True
- validate failed or did not run: True
- fast and rustc agree (both fail): True

