# Harness production results and compiler streaming experiment

The accepted 5fbc03d runtime passed Linux and macOS CI. Its [untraced production measurements](../benchmarks/harness-accepted-script-cache.json) use the real dirty Harness adapters snapshot, Rust 1.97.1, kache 1.0.0 and eight jobs. This is `cargo build --release --lib --locked --offline -p harness-adapters`, not the full GUI build.

| Phase | Nano median | kache median | Nano paired wins |
| --- | ---: | ---: | ---: |
| Empty compiler caches, clean Cargo target | 17.243540s | 17.051149s | 2/5 |
| Primed compiler caches, clean Cargo target | 0.987806s | 1.313685s | 3/3 |

Nano's warm median is 24.8% lower; its cold median is 1.1% higher. These samples do not establish cold superiority. Every repeated output matches its own implementation's cold artifact hashes; tracked Rust sources and manifests are unchanged. Each Nano cold run has 167 Rust misses and one build-script miss; each warm run has 167 Rust hits and one script hit. Build order alternates, the private kache daemon is restarted outside timing for every cold pair, OS filesystem caches are unflushed, fetching and R2 are excluded. The frozen binary SHA-256 is `1eb3ecdb58b66a0876b34400c83bbbdf7c53fcb8561dce26c3b40543521c1d87`.

## Next variation: forward metadata notifications immediately

Regular Rust compilation currently collects stdout and stderr before replaying them. Cargo uses rustc metadata notifications to begin dependent compilation before upstream code generation finishes. The [Rust compiler guide](https://rustc-dev-guide.rust-lang.org/backend/libs-and-metadata.html) explains this pipelining. Delaying these notifications is a concrete scheduling hypothesis, separate from cache lookup and hashing cost.

The experimental `NANOCOMPILE_STREAM_COMPILER=1` variation forwards regular Rust miss output as it arrives while retaining the exact bytes for cache replay. Producer invocations still buffer output because their private output paths require publication and rewriting. Cache hits retain existing verified artifact restoration and replay behavior. Zig compilation is unchanged. This flag is experimental until repeated benchmarks and integration checks pass.

`tests/compiler_stream.py` checks a notification handshake before compiler completion, 2 MiB of binary data on each stream, byte-exact capture, a failed compilation and signal propagation using `tools/compiler_stream_probe.zig`. Run untraced whole-build comparisons with `tests/project_comparison.py --compiler-stream`. The existing diagnostic capture frontend itself buffers compiler output: it would erase the scheduling effect and cannot establish this variation's performance.

Future variants must preserve compiler output, failure status and artifact correctness. Freeze both binaries, use the same environment and fixed target path, alternate fresh-cache baseline/candidate pairs, verify zero cold hits and compare outputs against each implementation's own cold references. Repeat against kache separately. Publish every sample and rejected hypothesis. A faster median in a separate session is insufficient to attribute the change to streaming.
