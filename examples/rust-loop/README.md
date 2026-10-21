# Rust edit-check-validate example

A no-dependency library that exercises the schema-1 graph described in
[docs/rust-iteration.md](../../docs/rust-iteration.md): `cargo check`, then a
mandatory `cargo test` that still uses rustc.

```sh
# From the nanocompile repository root
zig build -Doptimize=ReleaseFast
./zig-out/bin/nanocompile rust-loop spec --manifest examples/rust-loop/Cargo.toml \
  --write examples/rust-loop/nanocompile.tasks.json --offline \
  --wrapper "$PWD/zig-out/bin/nanocompile"
./zig-out/bin/nanocompile rust-loop check-spec examples/rust-loop/nanocompile.tasks.json
./zig-out/bin/nanocompile task examples/rust-loop/nanocompile.tasks.json
```

The committed `nanocompile.tasks.json` is the same graph without a machine-local
wrapper path, so `nanocompile` and `cargo` must be on `PATH`. Regenerate with
`--wrapper` when you want nanocompile under both tasks. `target/` is Cargo's
work directory and is not a declared output.

This crate is a contract fixture, not a speed claim.
