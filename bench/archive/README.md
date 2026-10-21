# MAP-Elites shards

Write one shard per sample as `bench/archive/<sample>.json`. The canonical
archive is [`../map_elites.json`](../map_elites.json). Schema:
[`../map_elites.schema.json`](../map_elites.schema.json).

```sh
# After evaluating a sample:
python3 tools/map_elites.py validate bench/archive/my-sample.json
python3 tools/map_elites.py merge --into bench/map_elites.json bench/archive/*.json

# Same commands on the native driver once built:
./zig-out/bin/nanocompile map-elites validate bench/archive/my-sample.json
./zig-out/bin/nanocompile map-elites merge --into bench/map_elites.json bench/archive/*.json
```

A shard is schema 1, kind `nanocompile.rust-loop.map-elites.shard`:

```json
{
  "schema_version": 1,
  "kind": "nanocompile.rust-loop.map-elites.shard",
  "sample": "rust-loop",
  "commit": "optional-git-sha",
  "timestamp": "2026-10-21T00:00:00+00:00",
  "evaluations": [
    {
      "cell": "small|body",
      "size": "small",
      "edit": "body",
      "genome": {
        "wrapper": false,
        "dev_backend": "llvm",
        "linker": "default",
        "sccache": false,
        "codegen_units": null,
        "incremental": true,
        "debuginfo": "full",
        "fast_check": "cargo-check",
        "loop": "check",
        "jobs": null,
        "offline": true
      },
      "fitness_ms": 26.7,
      "spread_ms": 1.2,
      "disk_bytes": 123456,
      "correctness": {
        "ok": true,
        "agree_on_broken": true,
        "validate_is_final": true
      },
      "sample": "rust-loop",
      "n_evals": 3
    }
  ]
}
```

Cell key is `size|edit`. Size buckets: `small` / `mid` / `large` (see
`size_rules` in the archive). `small` is Rust LOC < 2000; `mid` is
2000 ≤ LOC < 50000 and ≤20 crates. Edit types: `cold`, `noop`, `body`,
`sig_dep`. On a one-crate sample, `sig_dep` is a local signature change.
`loop=build` is allowed and is the cranelift-dev gene. `loop=test` cannot
use `dev_backend=cranelift`.

`validate` is not a gene. Do not put cranelift, rustd, Lust, or Relax on the
gate. Merge keeps the lowest `fitness_ms` that still has `correctness.ok`.
