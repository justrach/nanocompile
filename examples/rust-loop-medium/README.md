# Multi-crate rust-loop fixture

Three-crate workspace (`intern` → `graph` → `app`). Body and signature probe
markers live in `crates/intern`, the depended-on crate. Size classification
is by Rust LOC, so this 202-line fixture is **small**, not mid. The mid
bucket uses [`examples/pinned-hashbrown`](../pinned-hashbrown).

```sh
python3 bench/rust_loop_bench examples/rust-loop-medium \
  --nanocompile zig-out/bin/nanocompile \
  --map-elites --offline --name rust-loop-medium
```
