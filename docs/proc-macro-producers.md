# Proc-macro producer caching: implementation requirements

Producer caching remains unimplemented. This describes the next coverage change
against the actual [linker fixture](../tests/producer_link_probe.py), rather than
enabling `proc-macro` in the existing library parser prematurely.

The fixture changes an unbundled native archive with its size and mtime retained.
The macro source, explicit Rust externs and dep-info stay unchanged, and rustc's
macro metadata lists no external dependencies. The loaded macro nevertheless
expands to a different value. The final linker report includes the native
archive and transitive Rust archives. On Darwin it also records SDK inputs and
unsuccessful lookup candidates. These are necessary inputs to producer caching.

## Miss and discovery

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
