# Mixed Rust/staticlib companion trial

`NANOCOMPILE_RUST_STATICLIB=1` opts into caching a native macOS ARM64 `lib`/`rlib` plus `staticlib` compilation. `--staticlib-companions` enables and records the same control in the project comparison and full Harness source-edit runners. The default mixed-output guard remains active.

The trial restores `.d`, `.rlib` and `.a` together and includes every destination in output locking. It requires `--emit=dep-info,link`, zero debug information, no explicit target, no LTO or custom relocation configuration, no prefer-dynamic option, and the byte-pinned physical Rust 1.97.1 installation. Generic drivers and unsupported configurations pass through. The installation identity includes standard-library archives, backend and helper resources. Dependency collection runs even without external dependency directories and hashes complete transitive `.rlib` candidates rather than metadata alone. Search membership and competing candidates remain guarded.

Rust 1.97.1's [staticlib assembly](https://github.com/rust-lang/rust/blob/1.97.1/compiler/rustc_codegen_ssa/src/back/link.rs) reads upstream object bytes and packed native archives from `.rlib` files. Unbundled upstream libraries remain external for the final executable link. Native search directories and plain supported command-line static libraries retain their existing complete snapshots. Hidden native link attributes in the compiling crate refuse storage; this trial does not add a general native-library resolver. Reported procedural macro inputs remain a separate opt-in assumption.

[The 49-execution fixture](../benchmarks/staticlib-companion-fixture.json) checks both type orders, comma-separated types, every output's bytes/mode, Rust and C linked probes, source edits/reverts, corrupt cached archives, failed compiles, default refusal and unsupported configurations. A bundled C object edit leaves the dependency's Rust metadata unchanged but still causes a miss and changes both probes. An unbundled external archive edit leaves the cached companion archive unchanged while new linked probes observe the changed external code. Hidden native inputs on the compiling crate refuse storage repeatedly. Compiler-resource mutation in a copied installation has not been separately tested for this trial.

[The actual Harness dependency replay](../benchmarks/harness-highlight-staticlib-replay.json) uses the captured `tree_sitter_highlight` request, a private source copy and existing read-only compiled dependencies/native outputs. All 12 executions preserve direct output hashes and modes, and Rust/C probes pass. Three alternating default-off/hit pairs give medians **0.547157s / 0.041059s** on this machine. The initial direct request is **0.587283s**, initial empty-cache candidate **1.403915s**; startup/resource/metadata work makes that first cold request slower. These are isolated compilation measurements, not whole-build results, and kache was not remeasured in this replay.

The real source edit changes the existing `ts_highlight_buffer_len` return expression by one: both linked probes change from 0 to 1, the cache misses, fresh direct artifacts match, and reverting hits the original complete artifacts. Raw stdout/stderr and runner snapshots are retained privately; the public reports record their SHA-256 values.

For the next variation, run matched full-Harness cold/hit repetitions against kache with this flag recorded and all other controls fixed. Preserve the whole-build capture manifest, every compiler stream, Cargo units, source/output hashes and modes, CLI probes, and cache-decision counts. Separately run the prepared full-app source-edit sequence. Reject any invalidation/output failure or repeatable cold regression. Profile final executable restoration next; do not add overlapping per-request improvements to predict total savings. Existing full-build results still show Nano losing the warm comparison.

Local fixture commands (the exact supported compiler/resources are required):

```sh
python3 tests/staticlib_companions.py zig-out/bin/nanocompile --state /tmp/nano-staticlib-fixture-new
python3 tests/highlight_staticlib_replay.py zig-out/bin/nanocompile --request /path/to/completed/compiler-record.json --state /tmp/nano-highlight-replay-new
```
