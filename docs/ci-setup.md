# Pinned CI setup without rebuilding the executable on every hit

`tools/setup_nanocompile.py` installs a **native ReleaseFast executable** from
an exact-key executable cache, with a source-build fallback. It uses Python
3.9+ and the standard library. This is the source-cache option in issue #6;
it does not invent a release URL, select `latest`, or download unsigned
executables.

## Local or CI use

Check out a reviewed **full commit SHA**, not a moving branch, and install
verified Zig 0.17.0 using `tools/install_zig.py` (or an already trusted
installation). Then, from that checkout:

```sh
REVISION="$(git rev-parse HEAD)"
python3 tools/setup_nanocompile.py --revision "$REVISION" \
  --cache-dir .zig-cache/ci-setup --prefix .zig-cache/ci-setup-install \
  --report .zig-cache/ci-setup-report.json
.zig-cache/ci-setup-install/bin/nanocompile --version

# Repeating setup verifies and restores the executable instead of compiling it.
python3 tools/setup_nanocompile.py --revision "$REVISION" \
  --cache-dir .zig-cache/ci-setup --prefix .zig-cache/ci-setup-install
```

On Windows use `python` and `nanocompile.exe`. The supported native targets
are macOS ARM64/x86_64, Linux ARM64/x86_64 with musl, and Windows x86_64 GNU.
The existing verified Zig installer does not supply Linux ARM64; provide a
trusted Zig 0.17.0 installation there. macOS requires its native SDK. The
setup helper does not cross-compile or claim compatibility with older hosts.
A matching native executable must successfully answer both `--version`
(exact package and Zig versions) and `--help` before it is installed.
These are startup compatibility checks, not a substitute for compiler tests.

The helper validates `--revision` against checkout HEAD. Its cache identity
also hashes the current build inputs, so dirty source is supported without
aliasing a clean revision. CI should normally use a clean checkout. A version
number alone is deliberately insufficient: changes at the same `0.1.0`
version still invalidate the executable.

The key includes:

- Full source revision, plus names and freshly hashed bytes of `build.zig`,
  `build.zig.zon` and the complete `src` tree (including added/deleted files).
- Setup helper bytes, fixed ReleaseFast configuration and package version.
- Zig 0.17.0 executable and complete Zig library bytes, plus the selected
  macOS SDK tree when applicable. Installed symlinks and their reachable
  contents participate. This deliberately pays a hashing cost on every hit;
  it is not an mtime-only installation memo.
- Native target, host OS release and OS version. Even an OS upgrade can miss;
  portability is conservative, not a promise to share across runner images.

Custom compiler/library overrides such as `CC`, `ZIG_LIB_DIR` and `CPATH` are
rejected. If Python startup or your shell injects such overrides, explicitly
pass `--clean-env` to remove only these overrides for setup and its children;
the helper reports their names, never values, and does not change your shell.
The isolated benchmark uses this option. `SDKROOT`, if provided, selects the SDK whose contents are hashed
and explicitly passed to Zig. The contract is specific to this repository's
current dependency-free build; additional dependencies, build-time environment
inputs or generated sources require extending the identity first. Do not edit
source or installed tool resources while setup is running.

The cache stores only an executable and a JSON identity/checksum manifest.
It does not store compiler artifacts, Zig incremental state or build logs.
Restore first copies into a private staging directory, verifies identity and
SHA-256, then executes the compatibility checks. Missing, malformed, damaged
or incompatible entries cause a fresh source build. Failed source builds fail
setup; there is no stale-key fallback. Installation and cache-file replacement
are atomic. Use distinct installation prefixes for concurrent callers.

All fallback builds use temporary, private Zig local/global caches and a
private prefix; they never write `zig-out/bin/nanocompile`. This helper
transports one native executable between jobs without bootstrapping it again.
Zig remains required even on a hit to validate toolchain identity. Installing
Zig or Rust is not accelerated by this executable cache.

## Cache writers are a security boundary

**A SHA-256 stored alongside an executable detects corruption, not a malicious
writer.** Someone who can replace both can provide arbitrary executable code
with matching checksums and version output. Only restore a cache whose writers
you trust as much as the source/toolchain you are about to execute. Never use
a public bucket or pull-request artifact as a trusted executable source.

The separate [setup-cache workflow](../.github/workflows/setup-cache.yml) is an
executable integration example; it does not change the main correctness CI.
Its rules are enforced on both the restore and save steps:

- Only a **push or manual dispatch on the repository's default branch** may
  read or publish the shared `trusted-nanocompile-<exact-key>` cache.
- Pull requests and non-default branches use disposable local caches only.
  There are no `restore-keys`, prefix matches or cross-OS archives.
- The workflow uses ordinary `pull_request`, never `pull_request_target` or a
  privileged `workflow_run` consuming PR artifacts. GitHub's server-side
  branch/ref cache visibility is also part of the boundary: malicious PR code
  can invoke cache APIs, but its merge-ref caches are not visible to default-
  branch jobs. A name prefix or read-only `GITHUB_TOKEN` alone is **not** a
  cache-writer authorization mechanism.
- Use isolated GitHub-hosted runners as shown. Do not share writable cache
  directories or persistent workspaces between untrusted PRs and trusted jobs
  on a self-hosted runner. Trusted default-branch changes still require your
  normal review/branch protection policy.

Checkout and cache actions are pinned to commit SHAs. Cache restore uses the
key computed by the helper after toolchain installation. Setup recomputes that
identity rather than trusting an action's cache-hit flag. GitHub caches are
immutable: if a shared entry is corrupt, setup locally rebuilds it, but an
existing exact-key remote entry cannot be overwritten by save. Delete the bad
remote entry through normal repository administration before repopulating it.

For integration into `ci.yml`, install Zig as today, calculate the exact key,
use the same gated restore/setup/save steps, then use the helper's installed
absolute path in compiler tests or `RUSTC_WRAPPER` (append `.exe` on Windows).
Keep correctness tests and compiler artifact caches separate from the
executable setup cache. The sample only triggers for its own
helper/tests/workflow changes or manual dispatch; it does not add a second
full compiler suite to every source edit.

## Measurements and reproduction

```sh
# Contract tests only, no compilation:
python3 tests/setup_nanocompile.py

# Real source builds, deleted-output restore, Rust miss/hit, corrupt-cache fallback:
python3 tests/setup_nanocompile.py --benchmark benchmarks/ci-setup.json
```

The benchmark snapshots the build inputs, uses its own temporary installation,
executable cache and Zig caches, and never edits the checkout or ordinary
build output. Cold setup starts with empty executable and Zig caches. Warm
setup deletes the installed executable and restores it byte-identically.
Each run then compiles the same tiny Rust library: the cold run must record a
compiler miss, and the warm run must restore byte-identical artifacts with a
compiler hit after output deletion. A separate corruption test damages the
cached executable, requires rejection, and verifies an actual source rebuild.

The generated local measurement separates setup
wall time, identity hashing, source compilation, fixture compilation and total
end-to-end time. `setup_seconds` in the helper's own JSON includes identity,
restore/build/validation/install; the benchmark's `setup_wall_seconds` also
includes Python process startup. End-to-end includes setup, fixture compilation
and output verification, not merely the compiler's warm-hit latency.

Warm setup still validates complete toolchain/SDK contents; that cost must
not be omitted from a speedup comparison. The benchmark measures a small
fixture, not a representative application speedup. Toolchains must already
be installed, OS file caches are not flushed, and remote cache transfer is
not measured. A hosted job's complete
setup budget must additionally include toolchain acquisition, the separate
`--key-only` pass and the cache action's download/upload time. Do not present
the local warm setup number as the duration of that whole hosted pipeline.
The workflow checks native installation and a second verified local executable
restore on Linux/macOS/Windows. Pull-request runs intentionally do not test
cross-job shared-cache restore/save: those actions remain default-branch-only.
