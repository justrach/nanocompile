# rust-loop bench: pinned-hashbrown-cranelift

Project: `/workspace/examples/pinned-hashbrown`
Runs: 3 timed, 1 warmup. Schema 1.

| Step | Command | Phase | Median ms | Spread ms | Target bytes | OK |
| --- | --- | --- | ---: | ---: | ---: | --- |
| baseline | build | cold | 549.7 | 12.0 | 13126790 | yes |
| baseline | build | noop | 17.7 | 0.8 | 13126790 | yes |
| baseline | build | edit_body | 162.8 | 0.0 | 13124502 | yes |
| baseline | build | edit_sig | 150.0 | 0.0 | 13128775 | yes |
| baseline | test | cold | 40526.8 | 1128.2 | 179378802 | yes |
| baseline | test | noop | 37181.7 | 195.5 | 179378802 | yes |
| baseline | test | edit_body | 39279.4 | 0.0 | 179165705 | yes |
| baseline | test | edit_sig | 39283.4 | 0.0 | 179192654 | yes |
| cranelift-dev | build | cold | 24.5 | 0.2 | 1770 | no |
| cranelift-dev | build | noop | 11.4 | 0.5 | 1770 | no |
| cranelift-dev | build | edit_body | 11.0 | 0.0 | 1770 | no |
| cranelift-dev | build | edit_sig | 10.6 | 0.0 | 1770 | no |
| cranelift-dev | test | cold | 23.1 | 1.0 | 1770 | no |
| cranelift-dev | test | noop | 11.1 | 0.2 | 1770 | no |
| cranelift-dev | test | edit_body | 11.7 | 0.0 | 1770 | no |
| cranelift-dev | test | edit_sig | 10.7 | 0.0 | 1770 | no |

## Correctness

- broken edit applied: True
- fast-check failed: True
- validate failed or did not run: True
- fast and rustc agree (both fail): True

