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

## Rejected as a default: warm-cache regression

The [streaming trial](../benchmarks/harness-streaming-experiment.json) won all five cold pairs: Nano median 15.734520s versus kache 17.141541s, an 8.2% lower median in this session. All repeated outputs matched the streaming runtime's own cold hashes. This does **not** establish a generally better runtime: warm Nano median was 10.172058s versus kache 1.216989s. Nano recompiled 26, 10 and five Rust crates across those three warm runs. Keep streaming opt-in and exclude it from default speed claims.

The current dependency collector checks library-directory candidate membership before and after compilation, even when it can prove an rlib companion unused by metadata-only loading. Pipelining permits upstream rlibs to appear during downstream compilation. This is a concrete explanation to test for refused stores and repeated misses; it is not yet proven by error logs. Other leads are Cargo choosing `.rmeta` versus `.rlib` extern arguments and changes in candidate selection across hit/miss scheduling.

The initial direct A/B runner rejected cross-binary artifact equality in its prime builds. Future comparisons must retain this failure, record every differing artifact, and compare repeated builds against each implementation's own reference. The only differing artifact in the follow-up prime comparison is ring's `build-script-build`: the execution cache installs a copy of Nano at that path, so distinct runtime binaries necessarily produce different shim hashes. `src/build_script.zig::install` renames the compiler-produced executable to `.nano-real` before installing that shim. Other collected prime artifacts are equal. The historical collector did not include the `.nano-real` file, so it does not establish that executable's byte equality; expand collection for future trials. Functional integration checks remain mandatory.

Instructions for the next variation:

1. Capture streaming compilation refusal reasons and before/after library selections. Preserve full private logs; use diagnostic observations only to identify causes.
2. Build a deterministic fixture where an upstream metadata notification precedes its rlib publication. Exercise cold runs, hits, misses, mixed graphs and repeated clean targets.
3. If unused same-stem companions cause invalidation, prove their irrelevance with validated metadata and selected compiler behavior. Retain guards for competing crates, changed metadata, proc macros, native linkage, arbitrary extra filenames and fallback resolution. Do not remove directory guards globally.
4. Require full warm-hit coverage and unchanged execution behavior before another speed trial. Repeat alternating baseline/candidate and kache comparisons, including real source edits and reverts. Publish all samples, cache events and own-reference artifact hashes.

## Matched cold A/B result

The [five alternating baseline/candidate pairs](../benchmarks/harness-streaming-cold-ab.json) use both frozen binaries at one fixed wrapper path, identical environment (including the streaming flag), fixed target path and compiler caches emptied before every build. The accepted baseline ignores the flag. Streaming won all five pairs, with medians 15.873765s versus 16.883226s, a 6.0% reduction. All repeated outputs match each binary's own prime reference; the only cross-binary difference is the copied ring execution shim described above. The archived runner preserves exactly the measured version, including its historical `.nano-real` coverage limitation.

This confirms a cold improvement on this workload, alongside the substantial warm regression. It does not justify changing defaults. [Structured future-variation instructions](../benchmarks/harness-streaming-next-experiments.json) carry the measurements and required gates forward.

## Diagnostic refusal evidence

A separate streaming run with Nano tracing enabled records 16 `LibraryDirectoryChangedDuringCompilation` store refusals in the cold build and nine in its first warm build. That warm build has 25 Rust misses. These errors confirm that directory guards refuse stores during pipelined builds; they do not alone explain every miss or identify which candidate changed. [Log sizes, hashes and refusal counts](../benchmarks/harness-streaming-diagnostic.json) preserve the evidence. Complete per-build Cargo stdout/stderr logs stay in `/tmp/nano-stream-diagnostic-20261010`; this session uses no buffering capture frontend. Logging is diagnostic overhead and its timings are excluded from speed claims.

The updated collector includes ring's real `.nano-real` build-script executable. Its warm hash, launcher hash, all rlibs, macro dylibs and native objects/archives match the streaming runtime's own cold reference in this diagnostic run. Future work must resolve the refusals while keeping input validation intact.

## Follow-up: guarded companions

The [guarded companion variation](pipelined-companions.md) restores full warm coverage in three Harness rounds while retaining cold leads. It remains opt-in during source-edit and hosted validation. The rejected streaming-only evidence above remains historical evidence; enable both flags for the follow-up, rather than assuming streaming alone is fixed.
