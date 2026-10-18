# Unsigned releases

The release workflow prepares five archives, using the version in
`build.zig.zon` (currently `0.1.0`):

| Archive suffix | Zig target | Build runner | Native runtime check |
| --- | --- | --- | --- |
| `macos-aarch64.tar.gz` | `aarch64-macos` | `macos-15` (Apple Silicon) | Same runner family |
| `macos-x86_64.tar.gz` | `x86_64-macos` | `macos-15-intel` | Same runner family |
| `linux-x86_64.tar.gz` | `x86_64-linux-musl` | `ubuntu-24.04` | Same runner family |
| `linux-aarch64.tar.gz` | `aarch64-linux-musl` | `ubuntu-24.04` (cross-build) | `ubuntu-24.04-arm` |
| `windows-x86_64.zip` | `x86_64-windows-gnu` | `windows-2025` | Same runner family; required before publication |

**Windows is under validation, not yet claimed as verified on a native hosted
Windows runner.** The ZIP and Windows build/unit-test/runtime gates are
prepared for the source port; publication requires the actual native job to
pass. Local Wine execution, if successful, is Windows PE runtime evidence,
not a substitute for hosted native Windows verification.

For example: `nanocompile-0.1.0-linux-x86_64.tar.gz`. Linux uses musl to
avoid depending on a runner-specific glibc version. This is not a claim of
compatibility with every Linux distribution or kernel. macOS runtime checks
cover macOS 15, not older deployment versions. The native ARM Linux runner
is available to public repositories; private repositories must have access
to the selected runner labels before using this workflow.

The verified installer supports Linux x86_64, both macOS architectures and
Windows x86_64, but not Linux ARM64. Therefore the ARM Linux executable is cross-built with
the same verified Zig 0.17.0 on an x86_64 host. Its separate native smoke job
needs Rust, but does not need to install Zig. macOS builds use native runners
and their SDKs rather than assuming a Linux host can supply Apple's SDK.
Windows uses Git Bash explicitly for workflow commands and native Windows
Python (`python`, not an assumed Unix `python3` alias). Its installer normalizes
`AMD64` to `x86_64`, checks the official Zig 0.17.0 ZIP checksum, extracts the
ZIP with Python and executes `zig.exe`. The checksum comes from
[Zig's official release metadata](https://ziglang.org/download/index.json).
Windows unit tests use the explicit GNU target, and the runtime fixture uses
Rust 1.97.1's `x86_64-pc-windows-gnu` toolchain.

## Verify and install

Download the archive for your operating system and architecture and its
`.tar.gz.sha256` (or `.zip.sha256`) file from the same GitHub release. In the download directory:

```sh
# Linux; on macOS use: shasum -a 256 -c nanocompile-0.1.0-linux-x86_64.tar.gz.sha256
sha256sum -c nanocompile-0.1.0-linux-x86_64.tar.gz.sha256
tar -xzf nanocompile-0.1.0-linux-x86_64.tar.gz
./nanocompile-0.1.0-linux-x86_64/nanocompile --version
install -m 755 nanocompile-0.1.0-linux-x86_64/nanocompile "$HOME/.local/bin/nanocompile"
```

Create `$HOME/.local/bin` first if necessary, and ensure it is on `PATH`.
Substitute your actual archive name on macOS or ARM64. `SHA256SUMS` checks all
five archives when all five have been downloaded. Checksums detect corruption;
they are not independent signatures or proof of publisher identity.

For the Windows candidate, once its native checks have passed, verify and
extract it in PowerShell:

```powershell
$archive = "nanocompile-0.1.0-windows-x86_64.zip"
$expected = ((Get-Content "$archive.sha256").Trim() -split '\s+')[0]
if ((Get-FileHash $archive -Algorithm SHA256).Hash -ne $expected) { throw "Checksum mismatch" }
Expand-Archive $archive -DestinationPath .
.\nanocompile-0.1.0-windows-x86_64\nanocompile.exe --version
```

Keep `nanocompile.exe` in a directory on your Windows `PATH`, or supply its
absolute path as `RUSTC_WRAPPER` for a Windows Cargo project. The executable
is not Authenticode signed; local security policy or SmartScreen may require
explicit approval. Do not disable system-wide security checks to install it.

Each archive has a single versioned directory containing `nanocompile`
(`nanocompile.exe` on Windows),
`LICENSE`, `NOTICE`, `README.md` and this guide. The package tool uses an
explicit file list, normalized tar ownership/timestamps/modes and a zero-time
gzip header. ZIP entries use a fixed 1980 timestamp, explicit permissions and
stored bytes (no compressor-dependent output). Checksum text uses LF on every
host. Identical executable and documentation bytes produce identical
archives, independent of local file metadata. This does **not** claim that
independent compiler builds are byte-for-byte reproducible. No cache, build
log, environment dump or local machine metadata is included.

The executable does not bundle a compiler. Install the Rust, Zig or native
compiler your project needs and follow the README's eligibility and wrapper
instructions. macOS binaries are not Developer ID signed or notarized;
Gatekeeper may require an explicit user approval under local security policy.

## Windows and WSL2

The in-progress native Windows target is **x86_64 GNU**, not Windows ARM64 or
an MSVC-targeted nanocompile build. The native release gate tests the CLI,
real Rust library cold compilation, byte-identical cache restoration, an edited
input miss, single-flight concurrent compilation, opaque artifact roundtrips,
competing artifact writers, copy isolation, GC and clear. The Windows-specific
Rust fixture uses absolute source/output paths with spaces, `--extern` and
`-L` dependency paths, and compares cold and restored outputs byte for byte
with direct rustc. Both a changed dependency and a same-size source edit with
its original modification time restored must miss. Extensionless compiler
selection through Windows `PATH`/`PATHEXT` is checked separately from the
explicit compiler-path comparisons.

Windows currently bypasses specialized producer/proc-macro, build-script and
portable C caching rather than claiming those cache paths work. Persistent
toolchain and input-digest metadata memos are disabled on Windows: inputs are
revalidated without those persistent shortcuts, preserving strong validation
at the cost of slower cache hits. The runtime scope
under test is Rust libraries and opaque artifacts, not complete feature parity;
native Windows Zig targets and linker-observer paths have not been runtime
validated by this suite. Xcode and Apple-native Clang features remain
macOS-only. These added tests do not establish a successful Wine or hosted
native Windows run.

WSL2 remains a separate Linux environment: use the matching Linux release,
a Linux compiler, Linux Cargo and a Linux project/build environment. Do not
set Windows Cargo's `RUSTC_WRAPPER` to the Linux executable, or WSL Cargo's
wrapper to the Windows executable.

## Maintainer verification and publishing

The existing [compile and benchmark CI](../.github/workflows/ci.yml) also has
a bounded `windows-runtime` job on push, pull request and manual dispatch. It
uses `windows-2025`, the verified Zig installer, explicit Windows GNU build
and unit tests, Rust 1.97.1 GNU, and both runtime smoke scripts. It does not run
the Unix-specific integration/benchmark suite on Windows or suppress Windows
unit-test failures. **This hosted native Windows CI verification is pending;
adding the job is not evidence that it has passed.**

A manual **Unsigned releases** workflow dispatch builds, runs native unit
tests, packages all targets, checks each extracted executable's version and
help, and exercises a real Rust compilation followed by a byte-identical cache
restore, edited-input miss and concurrent single-flight compilation on all five
native platform/architecture combinations. Windows additionally runs opaque
artifact/locking checks. The smoke job checks the archive checksum and exact
member allowlist before running the extracted executable. It then requires the
exact five archives and matching per-archive checksums and uploads a `verified-release`
workflow artifact with aggregate `SHA256SUMS`. **Manual dispatch never creates
a GitHub release**, even when dispatched on a tag. It has no publication tag
input.

A pushed `v<version>` tag triggers the same pipeline. Tag validation requires
an exact match to `build.zig.zon`; the native smoke also requires the executable's
`--version` to match it. Before a future release, maintainers must keep the
package version and the version strings in `src/main.zig` synchronized. Only
a successful complete build/smoke/checksum pipeline enables the publish job.
That job uses `gh release create --verify-tag` to attach the verified files to
a GitHub release for the already-existing tag. It will fail rather than
silently overwrite an existing release. A failed run can still leave diagnostic
workflow artifacts; these are not a published release. Normal CI remains the
broader correctness suite and should pass before a release tag is created.

No keys need to be sent in chat. An unsigned GitHub release needs only GitHub's
automatic, job-scoped `GITHUB_TOKEN`: other jobs have `contents: read`, and only
the gated tag-publication job has `contents: write`. This change does not push
commits, create tags or publish anything by itself.

Optional future signing/notarization is separate work. Store necessary Apple
Developer ID certificates, notarization credentials, Windows Authenticode
certificates or other signing material
in protected CI secrets/environments or a supported identity service, never
in chat or the repository. No such credentials are needed for this unsigned
workflow, and it does not implement signing.

Local packaging-only checks (Python 3.9+, no Zig compilation):

```sh
python3 tests/release_packaging.py
python3 tools/package_release.py version
# With an already-built native release executable and rustc on PATH:
python3 tests/release_packaging.py --smoke zig-out/bin/nanocompile
# Windows, with Windows rustc.exe on PATH or selected by NANOCOMPILE_RUSTC:
python tests/release_packaging.py --smoke zig-out/bin/nanocompile.exe
python tests/windows_cache.py zig-out/bin/nanocompile.exe
# A single downloaded platform archive and checksum in dist/:
python tests/release_packaging.py --smoke-archive dist
```

Before the Windows port, local verification covered all four macOS/Linux
target builds, macOS ARM64 native unit tests and real compiler integration,
Rosetta execution of the macOS x86_64 version command, and Linux x86_64/ARM64
Docker artifact/version/maintenance smoke. The Docker and Rosetta checks were
not full native cross-platform compiler integration. Those results describe
the pre-port macOS/Linux binaries, not completion of Windows support. The
hosted five-platform native matrix has not yet been run locally or on GitHub.

The packaging tests check tar and ZIP allowlists, file bytes, executable mode,
normalized metadata, deterministic output, complete target set and corruption
rejection. Workflow execution on GitHub is still needed to verify hosted runner
availability, downloads, permissions and the publication path; local checks
never call GitHub's release API.
