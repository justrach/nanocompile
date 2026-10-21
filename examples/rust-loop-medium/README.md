# Mid-size rust-loop fixture

Three-crate workspace (`intern` → `graph` → `app`) used as the `mid` MAP-Elites
size bucket. Body and signature probe markers live in `crates/intern`, the
depended-on crate.

```sh
python3 bench/rust_loop_bench examples/rust-loop-medium \
  --nanocompile zig-out/bin/nanocompile \
  --map-elites --offline --name rust-loop-medium
```
