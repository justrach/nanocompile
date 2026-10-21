# pinned-hashbrown

Controlled mid-size rust-loop sample: [hashbrown 0.15.2](https://crates.io/crates/hashbrown/0.15.2)
from crates.io, vendored at that exact version.

- crates.io crate sha256: `bf151400ff0baff5465007dd2f3e717f3fe502074ca563069ce3a6629d07b289`
- source: `https://static.crates.io/crates/hashbrown/hashbrown-0.15.2.crate`
- license: MIT OR Apache-2.0 (see `LICENSE-MIT`, `LICENSE-APACHE`)
- classification: **mid** (one crate, ~23k Rust LOC)

`src/lib.rs` carries `// nano-loop-body` and `// nano-loop-sig` probes for
`bench/rust_loop_bench`. `[lib] doctest = false` keeps official `cargo test`
on unit/integration tests; rustdoc snippets are not the edit-loop signal.
Do not bump the crate version without updating this pin and re-running the
mid MAP-Elites cells.
