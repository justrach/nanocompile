# rust-loop bench results

`bench/rust_loop_bench` writes one directory per sample:

```
bench/results/<sample>/result.json
bench/results/<sample>/result.md
```

Other agents may add `bench/results/<sample>/` trees or extra notes. Keep
`result.json` schema `1` (see `docs/rust-iteration-bench.md`). Do not overwrite
another sample's files.
