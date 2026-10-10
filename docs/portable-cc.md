# Portable compile-only C/C++ cache

`nanocompile cc` and `nanocompile c++` are opt-in object caches, separate from the Apple-native `clang` adapter. Select a compiler with `NANOCOMPILE_CC` / `NANOCOMPILE_CXX`. Linux defaults to cc/c++; macOS defaults to live xcrun-selected Apple Clang and SDK. Explicit compiler selections retain the caller's SDK configuration.

```sh
CC="/absolute/path/nanocompile cc" CXX="/absolute/path/nanocompile c++" \
  CC_KNOWN_WRAPPER_CUSTOM=nanocompile cargo build --release
```

Eligibility requires one C/C++ translation unit, `-c`, explicit `-o`, debug-info zero and a bounded flag set. Dependency side outputs require explicit `-MF`. Unsupported jobs execute the original compiler. Linking, stdin, response files, debug jobs, modules, plugins, profile inputs, complex or file-reading inline assembly, arbitrary frontend/assembler forwarding, custom GCC specs and Clang default configs bypass. Simple assembler symbol aliases in system headers are permitted. This is initial coverage, not a full replacement for ccache.

Every lookup preprocesses live with `-E -MD -MF`, then hashes the complete bytes of every reported source/system/header dependency. Preprocessed output, preprocessing diagnostics, original arguments, cwd, CPU/host and full environment enter the key. Include selection and `__has_include` are therefore re-observed; no header timestamp shortcut survives a lookup. Original compilation runs on a miss, and a second complete observation must match before storage. Object and declared dependency files restore together only after blob validation.

Installed tool files use the existing trusted-installation fingerprint contract. GCC frontends and assembler are resolved live; Linux loader dependencies enter tool identity. On macOS support is restricted to selected Apple Clang, with sealed system libraries partitioned by OS build. Dynamic-loader injection and dependency-output environment overrides bypass. The [GCC dependency/PCH options](https://gcc.gnu.org/onlinedocs/gcc/Preprocessor-Options.html) and [Clang configuration behavior](https://clang.llvm.org/docs/UsersManual.html) inform the refusal rules. GCC's PCH-preprocess marker causes refusal.

Entries use the existing sealed CAS, locks, blob budget, GC and explicit R2 snapshot transport. Hits/misses/bypasses have separate portable C/C++ stats. R2 path/environment matching restrictions still apply.

[Local correctness checks](../benchmarks/portable-cc-macos-checks.json) cover C/C++ object/depfile byte equality, linked behavior, preserved-mtime header changes, include precedence, optional-header appearance, corruption repair, failed jobs and GC. CI additionally runs GCC and upstream Clang on Linux. The [512-template C++ benchmark](../benchmarks/portable-cpp-macos-benchmark.json) measures 316 ms direct versus 43 ms warm restoration over nine samples; it is synthetic and its first miss is slower. Live preprocessing plus before/after hashing adds cold overhead, so this adapter is not the current macOS cold-build optimization.

Hosted GCC/Clang checks pass, but the pinned Linux Harness profile currently records 30 portable native bypasses and zero native hits. See [hosted coverage and raw results](hosted-three-directions.md); fixture speed does not establish whole-project coverage.
