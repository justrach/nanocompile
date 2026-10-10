<p align="center">
  <img src="docs/images/readme-cache-banner.png" alt="nanocompile — Reuse the build work you've already done. A workshop rat in a coral coat shelves golden build artifacts." width="960">
</p>

<h1 align="center">nanocompile</h1>

<p align="center">Rust and Zig compiler caching · Xcode native cache · Turborepo task artifacts</p>

<p align="center">
  <a href="https://github.com/justrach/nanocompile/actions/workflows/ci.yml"><img src="https://github.com/justrach/nanocompile/actions/workflows/ci.yml/badge.svg" alt="Linux and macOS CI"></a>
  <a href="build.zig.zon"><img src="https://img.shields.io/badge/Zig-0.17.0-f7a41d" alt="Stable Zig 0.17.0"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache 2.0 license"></a>
</p>

<p align="center">
  <a href="#build-and-use">Build and use</a> ·
  <a href="examples/turborepo/README.md">Turborepo example</a> ·
  <a href="#xcode-native-cache">Xcode</a> ·
  <a href="benchmarks/README.md">Benchmarks</a> ·
  <a href="#current-eligibility">Supported builds</a> ·
  <a href="#experimental-r2-testing">R2 snapshots</a>
</p>

A local, content-addressed compiler cache written in **stable Zig 0.17.0**, for Rust and Zig, with opt-in Apple Clang and Xcode native-cache commands. It adapts kache's shared-blob storage, copy-on-write restoration, and single-flight compilation ideas into a small standalone program.

This implementation targets repeated compilation of unchanged inputs. It is an early implementation with explicit eligibility gates; unsupported invocations run the original compiler.

| Your build | Start here |
| --- | --- |
| Cargo libraries | Set `RUSTC_WRAPPER` to nanocompile; release builds and non-incremental checks are supported. |
| Pure Zig | Wrap a supported `zig build-exe`, `build-obj` or static `build-lib` invocation. |
| Xcode | Use `nanocompile xcodebuild` to manage Apple's native Swift/Clang compilation cache. |
| Turborepo | Run the [two-package example](examples/turborepo/README.md) with the loopback remote-cache adapter. |

Measured performance and its limits are published with raw samples: [Rust versus kache](benchmarks/harness-hill.md), [Xcode](benchmarks/xcode.md), and [Turborepo with R2 restores](benchmarks/turborepo.md).

The [producer profile](docs/producer-phase-profile.md), [restore breakdown](docs/restore-phase-profile.md), and [ordinary-hit profile](docs/library-phase-profile.md) record where warm-hit time goes and link optimization experiments, including rejected candidates.

**Try it today:** Cargo library builds, supported direct Zig invocations, and the runnable Turbo example. Rust proc-macro producers run directly by default. Xcode uses Apple's native cache, and R2 currently transports explicit snapshots. See [supported builds](#current-eligibility) before choosing a workload.

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

GC is explicit, so the normal compilation path does not scan the entire store. It removes orphan blobs and evicts entries by recorded access time until the unique artifact bytes fit the requested budget. Filesystem access-time policies make this an approximate eviction order. The quota covers blobs; metadata and toolchain identities are additional space. `clear` removes artifacts, Rust classification memos, private diagnostic files and counters while retaining validated toolchain identities and shared Rust toolchain-file digests to avoid paying their initial fingerprinting cost again.

## Turborepo task artifacts

The [Turborepo example](examples/turborepo/README.md) adds a signed remote task
cache backed by the same Zig CAS. Turbo discovers task inputs and restores
archives; a small Python loopback API adapter stores/verifies opaque artifacts
through `nanocompile artifact put|get|head`. The two-package JSON/HTML example
proves remote hits after outputs and client-local cache are removed, dependency
and environment invalidation, corruption repair, GC, clear and snapshot restore.
Task artifacts also travel through the existing R2 snapshot transport. This is
a development adapter. The [actual R2 restore check](benchmarks/turborepo.md)
passed on Linux and Mac; it is not a deployed public cache service.

```sh
npm ci --prefix examples/turborepo --ignore-scripts --no-audit --no-fund
python3 tests/turbo_integration.py zig-out/bin/nanocompile
```

## Cache correctness and storage

Compilation keys include compiler arguments, the full environment, working directory, runtime host CPU/OS identity, and a toolchain content fingerprint. Rust dependencies come from rustc's dep-info, explicit externs, and the compiled crate's dependency metadata. Source directory membership tracks file-versus-directory module resolution; library lookup guards track the dependency graph's full filename prefixes when matching metadata confirms rustc's primary search succeeds, and all candidates when it falls back. Unrelated Cargo outputs can appear without invalidating an entry. Zig dependencies come from tokenized literal imports, module definitions, and embedded files.

On a hit, source and library inputs are hashed again with BLAKE3. Every artifact and diagnostic blob is verified against its content hash before any output is replaced. Entry manifests and toolchain memos carry integrity checksums. A missing or corrupted entry causes recompilation. Failed compilations preserve their status and diagnostics and are never stored as successful entries.

On a miss, known inputs are checked before and after compilation. Newly discovered Rust dependencies must predate the compile; mtime and ctime guard against concurrent changes. If inputs change while compiling, the successful result is returned without caching it.

Per-key locks collapse identical concurrent requests into one compilation. Sorted output locks also protect different compilation keys that share destinations. A maintenance lock coordinates GC and clearing with all active cache operations. These guarantees apply to processes using this wrapper; independent tools writing the same destinations remain outside its coordination.

Blobs are shared by content, even between unrelated compilation entries. Restores try APFS `clonefile` on macOS and `FICLONE` on Linux, then fall back to an independent copy. Outputs are staged beside their destinations and atomically renamed into place. No hardlinks are used: changing a restored file cannot change a stored artifact. Permissions and compiler stdout/stderr are restored too. A multi-file restore is not one filesystem transaction; if interrupted, the next build or restore repairs the outputs.

Toolchain contents are hashed once and memoized. Rust selection memos retain caller-directory and override checks, while installed-file digests are shared across those memos behind the same inode/size/mtime/ctime checks. Atomic sealed records and per-file locks prevent redundant concurrent first-use hashing. Warm validation checks file identity, size, mtime, ctime, and directory metadata. It observes rustup settings and ancestor override files, and detects changes to installed compiler/runtime resources. Source inputs and artifact blobs do not use this metadata shortcut. Official native compiler executables and rustup proxies are supported; arbitrary compiler scripts pass through. The cache is for a trusted local installation, not a remote cache or a defense against a hostile filesystem that can forge metadata and checksums.

## Current eligibility

| Compiler | Cached | Runs directly |
| --- | --- | --- |
| Rust | `lib`/`rlib`, dep-info plus metadata and/or link output, ordinary supported codegen flags, extern libraries, explicit `-L dependency=…` and `-L native=…`, plain bundled `-l static=NAME` from native directories, version-checked source dynamic link declarations, Cargo release libraries and non-incremental checks | Binaries, tests, build scripts, proc macros, proc-macro consumers in the default mode, incremental compilations, other native `-l` forms, source static/unsupported link declarations, thin native archives, framework/other search kinds, custom targets, unstable/unknown flags, split-debug link sidecars |
| Zig | Pure Zig `build-exe`, `build-obj`, static `build-lib`, explicit `-femit-bin=…`, literal imports/embed files, positional roots and named `-M` modules | `zig build`, `zig test`, C/C++ inputs, C imports, computed imports, module aliases, dynamic libraries, Windows/UEFI targets, custom SDK/linker options and unrecognized flags |

Rust source containing a possible `link(…)` declaration is conservatively left uncached, including declarations hidden inside `cfg_attr` or macro arguments. The scanner skips comments and literals and recognizes function declarations and member/qualified calls; ambiguous bare `link(…)` calls can still decline storage. Rust library search paths are scoped to the completed crate's metadata graph. Selected candidate inputs are content-hashed, and additions/removals invalidate the entry. Ordinary library builds omit a same-stem companion archive only when matching metadata is fully validated and rustc does not consume the archive. A library with a different suffix is ignored only after matching crate name, hash, target and macro kind confirm the primary phase. Broad fallback guards all candidates, including renamed artifacts. Each directory is enumerated once per restore and duplicate file dependencies are hashed once per restore. Large sets use up to four workers for full content hashing; there is no cross-invocation shortcut. On misses, a separate `rustc -Zls=root` subprocess reads the completed artifact with `RUSTC_BOOTSTRAP=1`. Content-addressed classification memos, scoped to a validated decoder identity shared across caller directories, reduce duplicate readers; they do not replace input content checks. Toolchain classification uses the selected compiler/resource identity; full compilation fingerprints retain existing and absent selector checks in their caller scope. Readers prefer `.rmeta` and run in a private cache directory with the originally selected toolchain. Actual compilations retain the user's original environment and arguments. Unsupported diagnostic formats decline storage.

Explicit native search directories track all immediate file contents, symlink targets and directory names before/after compilation and on hits. Native search is not recursive. This permits Rust consumers that inherit native search paths, and plain bundled `-l static=NAME` libraries found in explicit native directories. Other native command-line link forms and explicit target overrides for static libraries remain ineligible. Source link declarations qualify only when a separate completed `.rmeta`, read with exactly Rust 1.97.1, records no native libraries or only default/dynamic/framework libraries on Darwin or GNU/musl Linux. Static and unsupported records, other compiler versions and link-only outputs retain refusal; see the [classification checks](docs/native-metadata-investigation.md). Thin archives may reference external objects and are declined. Entry schema 5 uses a new key namespace; Rust native classification adds a separate eligibility tag. Earlier Rust entries are rebuilt or removed by GC.

### Optional compiler-reported proc-macro inputs

The default mode leaves actual proc-macro consumers uncached. To use the same reported-input contract as kache, explicitly set `NANOCOMPILE_PROC_MACROS=reported`. Macro libraries and their resolved crate graph are content-tracked, along with rustc's dep-info and the full compilation environment.

A proc macro can read files that rustc never reports, including SQL query metadata or migration files. Declare each such file in a JSON array and set `NANOCOMPILE_EXTRA_INPUTS_FILE` to its absolute path. Paths in the array are relative to the declaration file's directory. The declaration and all listed files are tracked for **every Rust consumer**, so changing a macro's data invalidates consumers even if the macro library stays unchanged. This initial declaration format accepts explicit files, not directories or globs; add new files to the array too. Missing or invalid inputs cause compilation to run without caching.

```sh
# .nanocompile-inputs.json: [".sqlx/query-example.json", "migrations/001.sql"]
export NANOCOMPILE_PROC_MACROS=reported
export NANOCOMPILE_EXTRA_INPUTS_FILE="$PWD/.nanocompile-inputs.json"
RUSTC_WRAPPER="$nano_wrapper" CARGO_INCREMENTAL=0 cargo build --release
```

Reported mode cannot detect undeclared reads, network access, clocks, or randomness inside macros. Use it for builds whose macro inputs are reported or declared; retain the default for unknown macro behavior. Neither this mode nor kache makes an arbitrary proc macro hermetic.

Zig already has a native cache. This wrapper skips the compiler process on a matching hit and shares deduplicated outputs in the same store as Rust. It currently does not intercept compilation steps inside `zig build`; those continue to use Zig's native cache.

Working directories and output paths remain in keys, preserving embedded paths and diagnostics. Cross-worktree path normalization, automatic remote lookup, a daemon/scheduler, and broader Rust/linker coverage are future work. This is not full kache feature parity.

The accepted Rust-only [Harness hill climb](benchmarks/harness-hill.md#two-active-native-queries-adopted) measures **2.89 s versus 22.81 s direct**, with 167 warm hits under explicit reported-input macros, experimental Apple macro/executable producers and pinned-compiler native classification. Kache still leads at 2.04 s. Capping the four live Apple selection queries at two active commands improved controlled Harness medians by 2.0% and 1.3% in two 27-pair batches, winning 42 of 54 pairs. The separate three-way Nano samples are 3.06, 2.89 and 2.64 s; the paired batches supply the before/after evidence. Cold Nano was 37.55 s versus kache's 26.72 s, with no demonstrated cold-build improvement. Earlier accepted live-driver-plan and native-classification changes gained 4.7% and 2.0% in their controlled comparisons. The last default-policy project run, on an earlier revision, took 17.36 s versus 22.96 s direct and 2.18 s kache, with 97 hits. Earlier full-prefix hosted comparisons passed on both Linux and Mac; those workloads are separate from this local run. Raw samples, executable checksums and policy limits are published alongside the results.

The [Xcode comparison](benchmarks/xcode.md) measures real `xcodebuild` workloads against kache and Xcode's native compilation cache. On the latest Harness iOS app comparison, direct builds take **45.60 s**, the external nanocompile Clang launcher 47.09 s, kache 46.96 s, and **`nanocompile xcodebuild` 4.16 s**. The new command uses Apple's native Swift/Clang cache; the two external compiler launchers record zero cache hits for this Xcode command profile. Correctness checks and the five-pipeline comparison also passed on a hosted Mac.

## Experimental proc-macro producer cache

Mac producer caching is available with `NANOCOMPILE_PROC_MACRO_PRODUCERS=1`.
It currently supports Apple's default tools, native builds with debug information
disabled, and a restricted set of codegen flags. Linux, cross targets and broader
linker/debug configurations still run directly. The [requirements and limits](docs/proc-macro-producers.md)
describe the tested restore/invalidation path. The latest [Harness comparison](benchmarks/harness-hill.md#cargo-macro-flag-coverage)
restores all ten macro producers and records 142 total hits: **4.23 s** warm
versus **22.86 s** direct and **2.01 s** kache. This flag does not opt macro consumers into reported-input mode.

```sh
NANOCOMPILE_PROC_MACRO_PRODUCERS=1 RUSTC_WRAPPER="$nano_wrapper" cargo build --release
```

## Experimental executable compilation cache

`NANOCOMPILE_EXECUTABLE_PRODUCERS=1` enables caching native Apple Rust `bin`
compilations, including Cargo build-script executables, with zero debug
information and supported codegen flags. It uses the same private linker capture
and dependency validation as macro producers. Cargo still runs each restored
build script; execution and its runtime file reads are not cached. Default,
Linux, test, custom-linker, cross-target, LTO and debug configurations retain
fallback. See [executable requirements](docs/executable-producers.md).

```sh
NANOCOMPILE_EXECUTABLE_PRODUCERS=1 RUSTC_WRAPPER="$nano_wrapper" cargo build --release
```

## Cargo native Clang cache

On macOS, `nanocompile clang` opts into Apple's compiler-owned CAS for eligible
compile jobs. Use it for native C/assembly built by Cargo's `cc` crate:

```sh
PATH="$(dirname "$nano_wrapper"):$PATH" \
CC="nanocompile clang" CC_KNOWN_WRAPPER_CUSTOM=nanocompile \
RUSTC_WRAPPER="$nano_wrapper" cargo build --release

# Show native cache remarks and record observed hits/misses
NANOCOMPILE_CLANG_REMARKS=1 "$nano_wrapper" clang -c example.c -o example.o
```

Build scripts continue to execute. The command queries the selected Clang and
SDK live (overlapping the two default lookups), namespaces the managed
`NANOCOMPILE_DIR/native-clang` CAS by installed
compiler content, SDK selection and host architecture, and lets Clang discover
inputs and replay compilations. Caller sysroots and SDKROOT take precedence;
`NANOCOMPILE_CLANG` selects an explicit compiler. Unsupported compiler capability,
opaque helpers, probes, stdin jobs, response files, caller-owned CAS flags and
non-macOS targets pass through. Native caching is available when the selected
Apple Clang supports the required flags and passes a first-use replay probe.
Apple Clang 17 on the hosted Mac advertises the flags but fails that qualification
and passes through. The probe result is memoized by compiler content. Other
hosts use compiler passthrough.

Inline scanning changes Clang's debug representation: the tested compiler omits
`DW_AT_comp_dir`. Native cache output is validated against the same scanner
with replay disabled and against its own cold output. This is an explicit
compiler mode. `clear` removes the managed CAS under the maintenance lock;
`gc` and R2 snapshots cover the existing Rust/Zig blobs, while this native CAS
remains local. `stats` reports native invocations/failures; hit/miss observations
require `NANOCOMPILE_CLANG_REMARKS=1`, which adds remarks and uses bounded capture.
Default mode streams the compiler's inherited descriptors normally.
Eligible native-CAS jobs run Clang's cc1 frontend in-process to reduce replay
overhead; caller execution flags can override this default.

The [earlier nine-sample comparison](docs/direct-rmeta-nine-samples.md)
measures warm medians of **2.007 s Nano versus 23.42 s direct and 2.269 s kache**
on Harness, with 167 Rust and 24 native warm hits. It uses explicit reported-macro
and Apple macro/executable-producer policies. Nano is faster in all nine
corresponding rounds, with a mean same-round lead of 273 ms and descriptive
standard error 61 ms. This is a local session result, not a general cross-machine
advantage or proof that direct metadata decoding improves warm hits.
The [previous nine-round comparison](docs/selected-decoder-nine-samples.md) and
sessions favoring kache remain public.
Two independent [27-pair lookup comparisons](docs/clang-selection-overlap-experiment.md)
confirm the adopted live-query overlap gains **5.6% and 5.1%**, winning 51/54
pairs with 193 exact artifacts. Compiler and SDK selection remain live.
Two further [27-pair integrated-cc1 comparisons](docs/clang-integrated-cc1-experiment.md)
confirm **5.1% and 5.6%** median improvements, winning 51/54 pairs with
193 exact artifacts. These measure the native adapter change against its
predecessor; the complete comparison above separately measures the installed version.
Nano cold is 27.64 s versus kache's 27.01 s in that session. Kache still leads cold;
the controlled decoder comparisons below establish Nano's improvement over its predecessor. All warm modes match their own cold Rust/native
artifacts; scanner debug changes and kache remapping prevent treating every
mode as byte-identical to default direct builds.

The subsequent [decoder-scope optimization](docs/decoder-scope-experiment.md)
reduces controlled cold Harness medians by **21.6% and 22.7%** in two batches,
winning 9/9 pairs against the previous Nano version. Full compilation keys,
selector guards and mutable-input hashing remain intact. All cold builds
match 193 artifacts; a 27-pair warm check shows no convincing regression.
These batches do not compare kache or demonstrate a cross-machine gain.

The further [selected-resource decoder update](docs/selected-decoder-experiment.md)
reduces cold medians by **5.2% and 9.7%** against the schema-4 version,
winning 8/9 pairs. A 27-pair warm comparison has essentially equal medians
(2.0606 s baseline, 2.0582 s candidate). Full compilation fingerprints and
all selector guards remain; switching the actual selected compiler still
invalidates classification reuse. These measurements do not compare kache.

## Xcode native cache

Use `nanocompile xcodebuild` on macOS to enable Xcode's own Swift/Clang compilation cache. This command manages a private CAS directory under `NANOCOMPILE_DIR/xcode`, separated by Xcode version/build, developer directory and CPU architecture. Xcode owns the dependency discovery, cache keys and diagnostic replay. Signing, destinations, project settings and output paths retain their normal Xcode behavior.

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
  "$nano_wrapper" xcodebuild -project MyApp.xcodeproj -scheme MyApp build

# Verify native restoration and changed-header invalidation with real Xcode
python3 tests/xcode_integration.py --nanocompile "$nano_wrapper"
```

The command defaults `COMPILATION_CACHE_ENABLE_CACHING=YES`, `COMPILATION_CACHE_KEEP_CAS_DIRECTORY=YES` and a managed `COMPILATION_CACHE_CAS_PATH`. Explicit command-line values take precedence. `NANOCOMPILE_DISABLE=1`, explicit caching `NO`/`0`, queries and package-resolution/export commands pass through. A full Xcode installation must already be selected or supplied through `DEVELOPER_DIR`.

`stats` reports native invocations/failures separately from Rust/Zig hits. `clear` removes the managed Xcode CAS while coordinating with active wrapper builds; it preserves explicit external CAS paths. The blob budget in `gc` and the R2 transport currently cover Rust/Zig storage only. Native Xcode CAS storage is local and has no nanocompile size quota yet.

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

The [initial Harness comparison with kache](benchmarks/kache-harness.md) measured clean release builds of a real Cargo dependency graph: direct 22.77 s, nanocompile 22.95 s, kache with its daemon 2.01 s. The [subsequent hill climb](benchmarks/harness-hill.md) improves default nanocompile builds to 19.31 s against 25.16 s direct and 2.16 s kache, with three warm samples per implementation. Kache is substantially faster under that default policy. The separate opt-in native/producers profile above reports the newer complete comparison. Small-fixture hit latency does not predict this project result. The separate [R2 snapshot benchmark](benchmarks/harness.md) verifies cache preservation and restoration.

GitHub Actions runs real compiler tests and the synthetic benchmark on Linux and macOS. Each run uploads its measured JSON as an artifact. No R2 credentials are needed by pull-request jobs.

The [direct Rust metadata experiment](docs/direct-rmeta-experiment.md) removes own-artifact query subprocesses for supported Rust 1.97.1 metadata. Two controlled Harness cold batches improve by **3.5% and 5.0%** against the previous Nano implementation, with six of six pair wins and 193 matching artifacts. Two 27-pair warm batches are mixed; no general warm speedup is claimed. Unknown versions and encodings retain the rustc query fallback. See the [next performance experiments](docs/performance-roadmap.md) for native caching, source-edit builds and restore validation.

The next three performance directions now have implementations and checks: [portable C/C++ object caching](docs/portable-cc.md), [overlapping restore validation](docs/restore-validation-overlap.md) and a [verified Harness source-edit comparison](docs/harness-source-edits.md). The new edit sequence favors kache: cold 28.709 s Nano versus 27.297 s kache; leaf edits 10.715 versus 10.205 s; shared edits 12.308 versus 11.858 s; reverts 11.981 versus 2.058 s. These are single samples with clean targets, verified against fresh artifact bytes and linked behavior. Restore overlap improves two 27-pair Harness warm batches by about 2.1%. A separate [experimental declared-task runner](docs/declared-tasks.md) compares the same two-package Node pipeline against real Turbo local caching; this small pipeline does not establish a general scheduler advantage.

## Attribution

Inspired by [kunobi-ninja/kache](https://github.com/kunobi-ninja/kache), inspected at commit `943dd2b0bbbf28958623eba689e7ad71bf8888e5`. The Zig implementation is original; it adapts architectural ideas rather than copying Rust source. Apache-2.0; see `LICENSE` and `NOTICE`.
