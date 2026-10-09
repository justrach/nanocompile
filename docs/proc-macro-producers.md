# Proc-macro producer caching: implementation requirements

Default producer caching remains disabled. An experimental Apple-only path is
now implemented behind `NANOCOMPILE_PROC_MACRO_PRODUCERS=1`. This describes the coverage change
against the actual [linker fixture](../tests/producer_link_probe.py), rather than
enabling `proc-macro` in the existing library parser prematurely.

The fixture changes an unbundled native archive with its size and mtime retained.
The macro source, explicit Rust externs and dep-info stay unchanged, and rustc's
macro metadata lists no external dependencies. The loaded macro nevertheless
expands to a different value. The final linker report includes the native
archive and transitive Rust archives. On Darwin it also records SDK inputs and
unsuccessful lookup candidates. These are necessary inputs to producer caching.

The Zig reader is now implemented in `src/link_dependencies.zig`. It preserves
Darwin input/missing/output records and decodes escaped Make paths, continuations
and phony dependency rules. Unknown opcodes, truncated reports, unsupported Make
expansions and ambiguous multiple link rules are rejected. It does not yet
classify scratch files or enable producer storage.

The CAS now supports optional missing-file dependency records. They contain a
domain-separated path hash and an absence marker. Storage rechecks absence;
restoration checks every marker before replacing any output. Existing paths,
unavailable lookups and malformed marker combinations prevent restoration.
Ordinary entries omit the optional extension, retaining their existing v5
serialization. The filesystem test verifies restoration, new-candidate refusal,
destination preservation, removal/revalidation and malformed-record rejection.

`src/link_observer.zig` implements the private final-link observer through
`nanocompile internal-linker`. Its configuration explicitly selects the driver,
report format and private report/invocation paths. It records the original
driver arguments in a sealed manifest, inherits the existing environment, adds
the native dependency-report option using separate driver arguments, and
delegates stdout/stderr and exit status. The producer fixture exercises it with
spaces and a comma in its private paths. Driver/SDK identity, scratch ownership
and producer eligibility still need integration.

Response-file capture is now implemented in `src/response_files.zig`. It expands
GNU compiler-driver quotes and escapes recursively from the original working
directory, preserves the raw driver arguments, and snapshots response contents
and inode/size/mtime/ctime before delegation. Content and stamps are checked
again afterward. Cycles, malformed quoting, unsupported encodings, oversized
expansions and changed responses invalidate discovery while retaining the
driver's exit status. Captured environments are not recorded. The observer test
loads a real C library linked through nested response files and exercises both
content changes and a write that restores the original contents and mtime.

Completed invocation manifests have an explicit schema and optional capture
identity. Parent discovery requires a matching fresh identity, expected driver
and working directory, a valid BLAKE3 seal, and successful response validation.
It rejects incomplete or stale captures; ordinary user compiler eligibility
remains unchanged.

LLD writes its output path verbatim in a Make report even when it contains
spaces. The strict reader binds that raw header to the caller's known output
destination instead of guessing how multiple target tokens should be combined.
Unbound parsing stays strict. The Linux path-with-spaces fixture failed before
this change, then the full Linux/macOS workflow passed in
[run 37933977961](https://github.com/justrach/nanocompile/actions/runs/37933977961)
at `f8eebf0ec0c2dd9b08f9bef4ecc1227bbd333949`.

The [new local fixture](../benchmarks/producer-link-observer-macos.json) covers
three loaded macro results: 12, 13 after a preserved-mtime archive edit, and 14
after a higher-priority archive appears while the fallback archive stays
unchanged. Sources, explicit Rust externs and producer dep-info stay identical.
Darwin reports the preferred candidate as missing before it appears; the cache
must also guard native search-directory membership on platforms whose reports
omit negative lookups.

Inspect a report with the standalone diagnostic tool:

```sh
zig build-exe -O ReleaseFast -lc --dep link_dependencies \
  -Mroot=tools/link_report.zig -Mlink_dependencies=src/link_dependencies.zig \
  -femit-bin=/tmp/nano-link-report
/tmp/nano-link-report darwin /path/to/linker.deps
# ELF linker reports use `make` instead of `darwin`.
```

Pass `--decoder /tmp/nano-link-report` to the producer fixture to validate the
reader against actual linker output. That check compares Darwin's complete
input/missing record lists with an independent Python decoder, checks the
output destination, and requires the transitive Rust and native archives on
both platforms. Parser unit tests run with `zig build test`.

The preceding observer fixture passed on hosted
[Linux](../benchmarks/producer-link-probe-ubuntu-24.04.json) and
[macOS](../benchmarks/producer-link-probe-macos-15.json) in
[run 37931112697](https://github.com/justrach/nanocompile/actions/runs/37931112697).
Those files predate the Zig reader. The
[local Zig reader check](../benchmarks/producer-link-probe-zig-macos.json) also
passed; hosted decoder verification runs in the regular CI workflow.
The real-linker decoder step passed on both Linux and macOS in
[run 37931953779](https://github.com/justrach/nanocompile/actions/runs/37931953779)
at source `e2712a605fb005fcd216bb76703d685b433d70df`. This confirms the report
reader on both platforms; producer eligibility remains gated and the complete
CI suite has its own independent status.

## Miss and discovery

`src/native_identity.zig` now queries Apple's default dispatch driver, checks
that its ld selection agrees with xcrun, and records the resolved Clang, linker,
SDK and Clang resource directory. Its fingerprint includes the dispatch shim,
xcrun, selected Clang/ld, libLTO and SDKSettings.json. Installed file digests use
sealed per-file memos with inode/size/mtime/ctime validation and a separate
native-resource namespace; existing Rust file identities and library keys stay
unchanged. All files are checked again after fingerprinting. Project/native
library contents cannot use this API's trusted-installation shortcut.

The private `internal-native-identity /usr/bin/cc` diagnostic and
`tests/native_identity.py` verify the actual selected installation, stable warm
identity, a private SDKROOT selection, preserved-mtime SDK metadata edits,
corrupt memos and invalid developer/SDK selections. Tests never edit the real
tool installation. This initial selection helper supports Apple's default
dispatch shims; it does not yet cover Linux, alternate driver overrides,
driver configuration/resource coverage, or the complete producer key. Actual
link-input contents, missing candidates, source validation and before/after
selection validation remain separate requirements. Producer caching is still
disabled by default.

`src/producer_job.zig` now provides exclusive, randomized mode-0700 job and
output directories. The output starts empty; observer configuration and records
belong beside it, not inside it. Its input classifier requires a live regular
file beneath both the lexical and resolved output-directory paths. Foreign
objects, sibling-prefix paths, symlinks into or out of the directory, missing
files and directories cannot be treated as owned compiler inputs. Tests verify
independent job identities, an initially empty output, and these boundaries.
Future callers must hold the maintenance lock and reserve this directory for
the compiler job. The experimental Apple producer path now uses this helper;
default eligibility remains unchanged.

Private jobs can now install a native observer symlink named
`nanocompile-internal-linker` beside `observer.json`. That argv[0] dispatches
directly to the observer with all linker arguments preserved. The real macro
placement fixture uses this entry point instead of a Python linker shim.
It does not introduce a shell or helper environment variables. The installer
rejects relative/non-executable targets, and the native-entry test preserves
the driver's stdout, stderr, status and argument list.

The observer now accepts an explicit private output boundary and captures the
complete raw linker report plus each input's lexical path, resolved path and
ownership while scratch files still live. Parent parsing binds the captured
output boundary and output spelling, report input order and ownership flags to
the fresh sealed invocation. It does not require temporary files to survive
rustc returning. Persistent inputs retain both path spellings for subsequent
content and symlink-resolution checks. The observer removes old reports before
delegation; missing or invalid discovery retains the native exit code and
invalidates capture. Real C linking exercises generated objects and foreign
symlinks; the placement fixture now captures real proc-macro scratch inputs
for all twelve builds and loads every macro. Driver/SDK identity, complete
persistent dependency validation and broader producer compilation integration
remain requirements; the experimental Apple path below integrates the initial subset.

Hosted live ownership capture passed on Mac in
[run 37939634123](https://github.com/justrach/nanocompile/actions/runs/37939634123),
but the Linux real C-link check failed with `FileNotFound` during reported-input
classification after the driver returned success. The follow-up
[run 37940933136](https://github.com/justrach/nanocompile/actions/runs/37940933136)
identified `/tmp/nano` as the failing input: the Make lexer split a filename
containing spaces. GNU ld's [dependency writer](https://github.com/RTEMS/sourceware-mirror-binutils-gdb/blob/master/ld/ldmain.c)
writes raw filenames on individually indented lines and repeats them as phony
rules; LLD escapes prerequisite names. The reader now binds GNU's exact layout
to the expected output and requires every matching raw phony rule, preserving
spaces, dollars, colons and backslashes without guessing token combinations.
Truncated or mismatched layouts are rejected. Missing actual inputs still
invalidate discovery. Local parser tests verified the strict layout before
hosted verification.

The GNU decoder and complete existing suite subsequently passed on Linux and
Mac in [run 37941809114](https://github.com/justrach/nanocompile/actions/runs/37941809114)
at `d046d71f72d81f790d5b3f2f1562e429294ace16`. The native observer entry also
passed both platforms in [run 37942262790](https://github.com/justrach/nanocompile/actions/runs/37942262790)
at `3f38c8e6e2526857aa54ee87b406605ecb03b6b9`.

`src/producer_dependencies.zig` now converts a bound, sealed linker capture into
content-hashed dependencies, excluding only captured owned scratch inputs.
Persistent files must predate compilation, retain their recorded resolution,
and pass content plus inode/size/mtime/ctime checks around hashing. Both lexical
and resolved file paths are retained. Symbolic links along lexical paths carry
explicit target guards; these also must predate compilation and remain stable.
Darwin's missing lookups become the existing negative dependency records.

The optional `symlink_target` CAS extension is omitted for ordinary entries.
Its path/target marker is domain-separated and validated at storage and before
restoration writes. Retargeting an alias, even to identical bytes, refuses an
old restore without touching the destination. Malformed marker combinations
and checksums are rejected. The real C-link test converts a capture after its
owned object has been deleted and refuses a subsequent foreign-alias change;
all twelve local macro builds also exercise conversion after rustc returns.

This converter is not a complete producer plan: source/extern before-and-after
snapshots, lookup-directory guards, macro-consumer input policy, tool/SDK
selection and output/diagnostic handling still require compiler integration.
Default producer eligibility remains disabled.

The dependency-conversion stage and full existing suite passed on both platforms
in [run 37943855759](https://github.com/justrach/nanocompile/actions/runs/37943855759)
at `791328fe4de276f5bd34bf4ee36b2dcca6c4cbda`, before experimental storage
was added.

## Experimental storage and restore

The compiler wrapper now has an opt-in producer path for Apple's default driver,
native host builds, zero debug information and supported ordinary codegen flags.
It uses a distinct producer key containing the ordinary Rust key, selected
native-tool fingerprint, installed Rust file-state signature and full observer executable digest. Existing library
keys are unchanged. Cargo `prefer-dynamic` and `strip=symbols` are covered by
real direct/cold/restored artifact equality and macro execution tests. Cross
targets, custom linker flags, LTO, relocation overrides and unusual escaped
output paths still pass through.
Linux integration remains unfinished.

On a miss it snapshots known source/extern/native inputs, compiles into the
private job output, preserves the original dylib install name, maps dep-info
and diagnostic output prefixes back to the requested directory and independently
materializes outputs. The actual compilation environment remains unchanged.
It collects the sealed live linker dependencies, checks tool selection again,
verifies known inputs and source dep-info, and stores through the existing CAS.
Explicit Rust library metadata is checked under the existing default/reported
macro-consumer policy rather than trusting the producer's empty macro metadata.
Thin reported archives and changed tool/observer files prevent storage.

On a hit the normal CAS validates all dependencies and outputs before restoring
and replaying diagnostics. The real test compares direct/cold/restored dylib and
dep-info bytes, loads and executes every macro, tests preserved-mtime native
archive edits, source changes, corrupt blobs/manifests and a failed compilation.
This experiment does not establish full producer coverage, all failure-output
side effects, complete native driver configuration coverage, or a project
speedup. Broader gates and the Harness/kache comparison remain required before
changing default behavior.

Output placement is now probed by `tests/producer_placement.py` with absolute
and relative directories, default and optimized codegen, and full debug info.
Every resulting macro is loaded by rustc and its expansion executed. On the
local Mac, default and optimized dylibs are byte-identical after preserving
the original `LC_ID_DYLIB` install name with separate `-Xlinker` arguments;
full debug-info dylibs differ. The original install name must retain its
relative or absolute spelling. Dep-info targets need output-path mapping;
rustc writes literal spaces in these target names. CI records each mode on
Linux and macOS. These results support further private-output investigation,
not producer eligibility or a performance claim. The preceding placement probe
passed on both platforms in [run 37938338649](https://github.com/justrach/nanocompile/actions/runs/37938338649)
at `2c5be6a78b9a2e9d8fb1dca16a1110fd35d22e14`; that revision predates live
ownership capture. Debug output equivalence, production scratch integration,
diagnostic mapping and driver/SDK identity remain unresolved.

1. Keep the user's compiler selection, compilation environment and original
   arguments as key inputs. A producer-specific implementation/version domain
   and validated linker-driver/toolchain/SDK selection must also enter its key.
   Ordinary library keys should not change just to add this coverage.
2. Resolve the actual default linker driver and linker. A private observer may
   add a supported dependency-report option, but must preserve rustc's driver
   selection and search behavior. User linker overrides and unsupported report
   formats must pass through until their behavior can be captured correctly.
3. Capture final-link inputs during the actual compilation. On Darwin, parse
   ld's version/input/missing/output records; on ELF, parse the linker's escaped
   Make-format dependency report. Do not infer a producer graph from its empty
   `-Zls=root` external-dependency section.
4. Record source dep-info, explicit externs, actual transitive Rust archives,
   native archives and SDK/system link inputs. Retain full search-directory
   membership where the report does not expose negative lookups. Decode driver
   response files before assuming the observed argument list is complete.
5. Distinguish this compilation's generated scratch objects from persistent
   inputs using observed ownership and paths, not an `.o` suffix heuristic.
   Persistent objects and linker scripts must remain dependencies. Unrecognized
   or missing persistent inputs decline storage.
6. Apply before/after content validation to known inputs. Newly discovered
   persistent inputs must predate compilation and remain readable/stable while
   hashed. Verify reported negative lookups remain absent before saving. Track
   the complete dynamic-library, dep-info and any supported metadata outputs;
   unsupported debug/link sidecars decline eligibility.

## Hit

Use the existing sealed CAS, per-key/output locks, full artifact hash validation
and independent output restoration. Project sources, Rust archives and native
libraries must retain full content validation, including preserved-mtime edits.
Only installed compiler/linker/SDK resources may use a separately documented
trusted-installation identity contract comparable to current toolchain memos.
Negative lookup guards must detect newly appearing competing inputs. A default
linker or SDK selection change must invalidate the producer key.

Caching the macro producer does not execute its macro code. If it uses another
macro during its own compilation, the existing default/reported consumer-input
policy still applies. Producing a macro does not justify silently opting every
consumer into the reported-input contract.

## Verification and comparison

The linked fixture must cover restoration after output removal, source and
explicit-extern changes, a transitive Rust input replacement, the existing
preserved-mtime unbundled archive change, newly appearing search candidates,
linker/SDK selection changes, corrupt reports/blobs and compiler/linker failure.
Load each restored producer with rustc and execute its expansion; dylib hashes
alone do not verify usability. Exercise both macOS and Linux in CI.

After those gates pass, repeat the complete Harness comparison against direct
builds and kache with a fresh dedicated state, rotated warm samples, artifact
verification and the same reported/default policy disclosure. Diagnostic sums
are not a performance comparison. Keep the existing Rust, Zig, Xcode and Turbo
checks passing while adding producer coverage.

The experimental implementation and existing suite passed on Linux and macOS in
[run 37949239666](https://github.com/justrach/nanocompile/actions/runs/37949239666)
at `69b52a0ffb381c993872671f00bb224e2d5ec0d0`. The Apple producer round trip runs
on macOS; unsupported Linux producer compilation retains direct fallback.
The first [Harness comparison](../benchmarks/harness-hill.md#experimental-apple-proc-macro-producers)
passes all library and macro dylib artifact checks but adds no producer hits: all
ten Cargo macro invocations use unsupported `prefer-dynamic` and `strip=symbols`
flags and therefore run directly. It verifies fallback, not producer restore on Harness.

The subsequent [Cargo flag iteration](../benchmarks/harness-hill.md#cargo-macro-flag-coverage)
supports those two flags, stores all ten Harness producers, and records 142 hits
per warm build with matching library and macro dylib hashes. Default behavior
and the remaining platform/debug/linker gates are unchanged.

Cargo macro flag coverage and the full suite passed on both platforms in
[run 37950601653](https://github.com/justrach/nanocompile/actions/runs/37950601653)
at `3bc48d7ebf6b77c9e7040235cbcb27d9eb60ef4b`. Linux continues to bypass
producer compilation; the Apple producer fixture executes on the hosted Mac.
