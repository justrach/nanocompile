# Native library metadata investigation

This is a candidate for increasing ordinary Rust library cache coverage. It has **not changed production eligibility or measured Harness performance**.

The current source-level native link gate refuses Harness's `libc` compilation. Its completed metadata records one default-kind link named `iconv` on this Apple machine. The source contains static-link branches for other configurations, so reading attribute text alone cannot distinguish consumed archives from inactive branches.

`tests/native_metadata_probe.py` decodes the native library array from metadata produced by exactly `rustc 1.97.1 (8bab26f4f 2026-07-14)`. This Python probe is an investigation tool; nanocompile remains a Zig executable. The reader rejects other versions, malformed headers, truncated records, unsupported conditional records, and DLL import records. It classifies static, raw-dylib, linker argument, and WebAssembly records outside the dynamic-only candidate set. Zero records and ordinary dynamic/framework/default records are candidates, not an authorization to restore them.

The layout is derived from the pinned compiler's [metadata root](https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/compiler/rustc_metadata/src/rmeta/mod.rs), [decoder](https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/compiler/rustc_metadata/src/rmeta/decoder.rs), [native library record](https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/compiler/rustc_session/src/cstore.rs), and [native kind enum](https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/compiler/rustc_hir/src/attrs/data_structures.rs). These private formats require an exact compiler gate and conservative fallback.

The local evidence in `benchmarks/native-metadata-probe.json` includes actual compiler outputs for no native links, default and explicit dynamic links, two dynamic records, static links, an inactive static branch, and a macro-generated static link. Default/dynamic library output bytes remain identical when the native archive is removed. Both active static fixtures change their output bytes when the native implementation changes from 12 to 13. The probe also classifies the existing real Harness `libc` metadata.

Run the portable fixtures with:

```sh
python3 tests/native_metadata_probe.py --output /tmp/native-metadata-probe.json
```

An existing completed `libc` `.rmeta` can be supplied with `--libc /absolute/path/to/liblibc-HASH.rmeta`. No Harness source files are changed. Linux and macOS CI run the portable fixtures and upload their results.

Before adoption, implement the reader in Zig, validate its root against independently checked compiler metadata, preserve full dependency content and file-state checks, and exclude proc-macro/executable producers. Verify native archive invalidation and downstream execution with real restore fixtures, then run the full project comparison and a controlled paired benchmark. A dynamic-only metadata classification alone does not establish producer safety or a performance improvement.
