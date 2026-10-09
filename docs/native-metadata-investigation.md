# Native library metadata classification

Ordinary Rust libraries with source-level native link attributes can be cached when their completed `.rmeta` contains only default/dynamic/framework native records, or no native records. The reader accepts exactly `rustc 1.97.1 (8bab26f4f 2026-07-14)` on Darwin and GNU/musl Linux triples. Other versions, custom targets, unsupported fields and static records retain refusal. This does not expand proc-macro or executable producer eligibility.

The earlier source-level gate refused Harness's `libc` compilation. Its completed metadata records one default-kind link named `iconv` on the Apple benchmark machine. The source also contains static-link branches for other configurations. Reading attribute text alone cannot distinguish consumed archives from inactive branches.

`src/native_metadata.zig` reads the completed artifact after the actual compiler finishes. The original compilation arguments and environment remain unchanged. The existing diagnostic rustc reader independently checks the same artifact's root; the Zig reader checks its target, crate hash, macro/stub flags and suffix/name where the name is stored inline. Full content hashes and file states before and after the diagnostic bind classification to that artifact. All existing source, extern, native search directory and transitive dependency guards remain in place. A separate Rust eligibility key tag prevents older binaries from restoring newly eligible entries.

The layout follows the pinned compiler's [metadata root](https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/compiler/rustc_metadata/src/rmeta/mod.rs), [decoder](https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/compiler/rustc_metadata/src/rmeta/decoder.rs), [native library record](https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/compiler/rustc_session/src/cstore.rs), and [native kind enum](https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/compiler/rustc_hir/src/attrs/data_structures.rs). These private formats require the exact compiler gate and conservative fallback. Static, raw-dylib, linker-argument, WebAssembly, bundled-filename, conditional native and DLL-import records do not qualify. Link-only outputs without a separate `.rmeta` retain refusal for source-level native attributes.

The original Python investigation remains in `tests/native_metadata_probe.py` and `benchmarks/native-metadata-probe.json`. It did not change production behavior at the time of that measurement. It checks actual outputs for no native links, default/dynamic links, two dynamic records, active and inactive static branches, a macro-generated static link, and the existing real Harness `libc` metadata.

`tests/native_metadata_cache.py` exercises the Zig implementation through real compiler invocations. Direct, cold and restored library bytes and modes match. Dynamic/default/framework records and an inactive static branch restore; active static and macro-generated static records remain uncached. Replacing the native implementation changes downstream execution from 12 to 13 while restored dynamic library bytes remain unchanged. Source edits with identical size and preserved mtime invalidate restoration. The local run also checks refusal with an installed Rust 1.94.1 compiler. CI checks another installed compiler when available, without installing one for this optional probe.

Run the portable probes with:

```sh
python3 tests/native_metadata_probe.py --output /tmp/native-metadata-probe.json
python3 tests/native_metadata_cache.py /absolute/path/to/nanocompile \
  --output /tmp/native-metadata-cache.json
```

An existing completed `libc` `.rmeta` can be supplied to the first probe with `--libc /absolute/path/to/liblibc-HASH.rmeta`. No Harness source files are changed. Linux and macOS CI run both portable probes and upload their results. This classification covers ordinary library compilation; it does not establish producer safety or a general native linker cache.
