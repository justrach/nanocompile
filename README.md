# nanocompile

A local, content-addressed compiler cache written in **stable Zig 0.17.0**, for Rust and Zig. It adapts kache's shared-blob storage, copy-on-write restoration, and single-flight compilation ideas into a small standalone program.

This implementation targets repeated compilation of unchanged inputs. It is an early implementation with explicit eligibility gates; unsupported invocations run the original compiler.

## Build and use

```sh
zig version                         # 0.17.0
zig build -Doptimize=ReleaseFast
./zig-out/bin/nanocompile --help
```

Run the compilation examples from your own Rust or Zig project. Set the wrapper path to the executable you just built.

```sh
nano_wrapper="/absolute/path/to/nanocompile/zig-out/bin/nanocompile"

# Cargo release library builds, including dependencies
RUSTC_WRAPPER="$nano_wrapper" cargo build --release

# Checking libraries also works; disable Cargo incremental compilation
RUSTC_WRAPPER="$nano_wrapper" CARGO_INCREMENTAL=0 cargo check

# Direct Rust compilation: explicit output directory and dependency information
mkdir -p out
"$nano_wrapper" rustc src/lib.rs --crate-name example \
  --crate-type rlib --emit=dep-info,metadata,link --out-dir out

# Pure Zig compilation, including executables, objects, and static libraries
"$nano_wrapper" zig build-exe src/main.zig \
  -O ReleaseFast -femit-bin=out/example

# Named Zig modules
"$nano_wrapper" zig build-exe -O ReleaseFast \
  --dep helpers -Mroot=src/main.zig -Mhelpers=src/helpers.zig \
  -femit-bin=out/example
```

The compiler executable can be selected with `NANOCOMPILE_ZIG` or `NANOCOMPILE_RUSTC`. Cargo supplies its actual rustc executable through the wrapper protocol.

Set `NANOCOMPILE_DIR` to choose a shared cache location. Its default is `$XDG_CACHE_HOME/nanocompile`, or `$HOME/.cache/nanocompile`. `NANOCOMPILE_TRACE=1` prints hit, miss, and bypass decisions. `NANOCOMPILE_DISABLE=1` runs the compiler directly. Environment values are compilation inputs: changing even an otherwise unrelated environment value currently causes a miss.

```sh
./zig-out/bin/nanocompile stats
./zig-out/bin/nanocompile doctor
./zig-out/bin/nanocompile gc             # orphan cleanup; 10 GiB blob budget
./zig-out/bin/nanocompile gc 1073741824  # 1 GiB blob budget
./zig-out/bin/nanocompile clear
```

GC is explicit, so the normal compilation path does not scan the entire store. It removes orphan blobs and evicts entries by recorded access time until the unique artifact bytes fit the requested budget. Filesystem access-time policies make this an approximate eviction order. The quota covers blobs; metadata and toolchain identities are additional space. `clear` removes artifacts and counters while retaining validated toolchain identities to avoid paying their initial fingerprinting cost again.

## Cache correctness and storage

Compilation keys include compiler arguments, the full environment, working directory, runtime host CPU/OS identity, and a toolchain content fingerprint. Rust dependencies come from rustc's dep-info, explicit externs, and library search paths. Source directory membership tracks file-versus-directory module resolution; library directory membership tracks newly appearing transitive dependencies. Zig dependencies come from tokenized literal imports, module definitions, and embedded files.

On a hit, source and library inputs are hashed again with BLAKE3. Every artifact and diagnostic blob is verified against its content hash before any output is replaced. Entry manifests and toolchain memos carry integrity checksums. A missing or corrupted entry causes recompilation. Failed compilations preserve their status and diagnostics and are never stored as successful entries.

On a miss, known inputs are checked before and after compilation. Newly discovered Rust dependencies must predate the compile; mtime and ctime guard against concurrent changes. If inputs change while compiling, the successful result is returned without caching it.

Per-key locks collapse identical concurrent requests into one compilation. Sorted output locks also protect different compilation keys that share destinations. A maintenance lock coordinates GC and clearing with all active cache operations. These guarantees apply to processes using this wrapper; independent tools writing the same destinations remain outside its coordination.

Blobs are shared by content, even between unrelated compilation entries. Restores try APFS `clonefile` on macOS and `FICLONE` on Linux, then fall back to an independent copy. Outputs are staged beside their destinations and atomically renamed into place. No hardlinks are used: changing a restored file cannot change a stored artifact. Permissions and compiler stdout/stderr are restored too. A multi-file restore is not one filesystem transaction; if interrupted, the next build or restore repairs the outputs.

Toolchain contents are hashed once and memoized. Warm validation checks file identity, size, mtime, ctime, and directory metadata. It observes rustup settings and ancestor override files, and detects changes to installed compiler/runtime resources. Source inputs and artifact blobs do not use this metadata shortcut. Official native compiler executables and rustup proxies are supported; arbitrary compiler scripts pass through. The cache is for a trusted local installation, not a remote cache or a defense against a hostile filesystem that can forge metadata and checksums.

## Current eligibility

| Compiler | Cached | Runs directly |
| --- | --- | --- |
| Rust | `lib`/`rlib`, dep-info plus metadata and/or link output, ordinary supported codegen flags, extern libraries, Cargo release libraries and non-incremental checks | Binaries, tests, build scripts, proc macros, dependency directories containing proc-macro libraries, incremental compilations, native search/link flags, custom targets, unstable/unknown flags, split-debug link sidecars |
| Zig | Pure Zig `build-exe`, `build-obj`, static `build-lib`, explicit `-femit-bin=…`, literal imports/embed files, positional roots and named `-M` modules | `zig build`, `zig test`, C/C++ inputs, C imports, computed imports, module aliases, dynamic libraries, Windows/UEFI targets, custom SDK/linker options and unrecognized flags |

Rust source containing a possible `link(…)` declaration is conservatively left uncached, including declarations hidden inside `cfg_attr`. This heuristic can also decline a normal function named `link`. Rust library search paths are conservatively fingerprinted in full, except the current unit's outputs; large dependency directories therefore cost more than the small benchmark fixture.

Zig already has a native cache. This wrapper skips the compiler process on a matching hit and shares deduplicated outputs in the same store as Rust. It currently does not intercept compilation steps inside `zig build`; those continue to use Zig's native cache.

Working directories and output paths remain in keys, preserving embedded paths and diagnostics. Cross-worktree path normalization, automatic remote lookup, a daemon/scheduler, and broader Rust/linker coverage are future work. This is not full kache feature parity.

## Experimental R2 testing

`tools/r2_cache.py` transports snapshots of entries and content-addressed blobs to a private R2 bucket. The compiler/cache core remains Zig; this optional benchmark transport uses Python and boto3. It is explicit prefetch/upload, rather than an HTTP request on each compiler invocation. Archives have SHA-256 checks, extraction accepts only regular cache files with valid names, and the Zig cache validates dependencies and BLAKE3 artifact hashes before use. Only share a bucket with trusted writers.

Install `boto3` in a separate virtual environment. Keep a mode-0600 JSON file outside the repository containing `endpoint`, `bucket`, `access_key_id`, and `secret_access_key`. Alternatively supply `R2_ENDPOINT`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, and `R2_SECRET_ACCESS_KEY` to the transport process. Do not export credentials into compilation environments: the current cache key hashes the full environment.

```sh
python3 tools/r2_cache.py push --cache /path/to/cache \
  --snapshot my-build --config /private/path/r2-config.json
python3 tools/r2_cache.py pull --cache /path/to/cache \
  --snapshot my-build --config /private/path/r2-config.json
```

Snapshots exclude locks, events, and machine-specific toolchain memos. Pull merges entries/blobs under the maintenance lock. It never restores compiler outputs directly; normal compilation invokes the validator. There is no automatic remote eviction yet: repeated snapshots retain immutable archives and may consume storage. Compilation artifacts can contain source paths or embedded data, so keep the bucket private.

R2 preserves the cache for repeated **matching builds**. Current keys include absolute paths, all environment values, and host identity, so downloading a snapshot on another runner may produce zero hits. A snapshot download alone is not evidence of cross-machine reuse. Remote latency and archive size are measured separately.

For a real Cargo workload, use a dedicated new state directory; the script deletes only its own target directory before every build. It fetches dependencies before timing, builds offline, records hits/misses/bypasses, and hashes resulting Rust libraries. It tests a release library package and its dependencies, not the entire Harness GUI application.

```sh
python3 tests/project_benchmark.py zig-out/bin/nanocompile /path/to/harness \
  --package harness-adapters --state /tmp/nano-harness-bench \
  --runs 2 --output bench-results/harness.json \
  --r2-config /private/path/r2-config.json --snapshot harness-macos
```

## Validation and performance

```sh
zig build test
zig build integration -Doptimize=ReleaseFast
python3 tests/benchmark.py zig-out/bin/nanocompile --runs 25 \
  --output bench-results/local.json

# Optional comparison with an installed kache binary
python3 tests/benchmark.py zig-out/bin/nanocompile --runs 25 \
  --kache /path/to/kache --output bench-results/comparison.json
```

The integration suite uses real rustc, Cargo, and Zig processes. It exercises artifact equality, executable permissions, input changes with preserved mtimes, environment inputs, escaped dependency paths, module-resolution changes, diagnostic replay, corrupt artifacts/manifests, destination conflicts, concurrent single-flight compilation, Cargo build/check, and GC.

Benchmarks time complete process invocations. They remove the primary output before every run, prime native compiler caches, rotate the measurement order, and require recorded cache hits. Restored artifacts are compared byte-for-byte. Kache may remap embedded paths, so its own restores are checked against its cold artifact and a linked consumer verifies its Rust output. Its comparison uses a standalone local cache without a daemon during timed compiles; the stats command may briefly start one afterward, which the script stops.

Measured results and the optimization trail are in `benchmarks/`. These synthetic workloads demonstrate warm-hit latency, not whole-project speed or an advantage across all workloads. A first-seen toolchain requires a full content fingerprint and makes the initial miss slower than direct compilation or kache. Later compilation units share that validated identity.

GitHub Actions runs real compiler tests and the synthetic benchmark on Linux and macOS. Each run uploads its measured JSON as an artifact. No R2 credentials are needed by pull-request jobs.

## Attribution

Inspired by [kunobi-ninja/kache](https://github.com/kunobi-ninja/kache), inspected at commit `943dd2b0bbbf28958623eba689e7ad71bf8888e5`. The Zig implementation is original; it adapts architectural ideas rather than copying Rust source. Apache-2.0; see `LICENSE` and `NOTICE`.
