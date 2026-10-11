# Digest and selection memos

Before this change, every Nano cache hit re-read and BLAKE3-hashed every input file and every cached output blob in full. Across a warm Harness build, the same dependency rlibs were hashed again for each downstream crate. The final `harness` link request alone hashed about 1,000 inputs (300–400 ms). kache keeps per-file stat records and re-reads a file only after it changes. Its warm requests spend about 1–2 ms on keys and 1 ms on restore.

## Digest memo (`src/cache.zig`)

`Context.digest` memoizes the content digest of regular files of at least 64 KiB. The memo is keyed by absolute path and records inode, size, mtime, ctime, the digest and the time hashing began. It is stored as a small record under `<cache>/memo/`.

A memo record is used only when all of the following hold:

- The file's current inode, size, mtime and ctime equal the recorded values. On APFS and other POSIX filesystems, ctime advances on every write, rename, chmod and `utimes`. A same-size rewrite that restores mtime therefore still changes ctime. This was checked directly on APFS: clone, rename and mtime-preserving `utimes` all change ctime, with nanosecond precision.
- Both timestamps are strictly older than the moment the recorded hash started (git's racy-index rule). A file changed during or just before hashing is never memoized. A change during hashing also fails the existing before/after `sameFileState` check.

Outputs restored from verified immutable blobs record their known digest after materialization. This is done only when the destination is still the clone's inode, size and mtime, since any intervening write changes mtime. `putFile` memoizes a new blob only when the source's full state is unchanged across the hash-then-clone window.

`NANOCOMPILE_DIGEST_MEMO=0` disables both lookup and recording. The cache key includes the environment, so each setting primes its own entries. `nanocompile clear` removes the memo directory.

### Trust boundary

This replaces the earlier rule that sources and stored outputs never use a metadata shortcut. The new rule matches git, kache and ccache. Modifications made through the filesystem are always detected. Two kinds of change are not detected:

- Media corruption that leaves metadata unchanged, such as a bit flip on disk.
- Writes through a shared mapping whose mtime and ctime have not yet been updated.

Earlier full re-hashing detected silent media corruption on every hit. Delete `<cache>/memo` or set the control to `0` to return to that behaviour.

## Selection memo (`src/native_identity.zig`)

Apple native selection (`apple()`) used to spawn the driver plan query and three `xcrun` queries on every linking request and every native build-script run: about 23 ms × 154 requests per warm Harness build. The memo stores the selection result and its identity hash in `<cache>/selection-memos/`.

The key covers the driver, its resolved path, and every environment variable that xcrun or the driver consults for selection (`PATH`, `HOME`, `SDKROOT`, `DEVELOPER_DIR`, `TOOLCHAINS`, and the `XCODE*`, `XCRUN*`, `CCC_*`, `CLANG*`, `DYLD_*`, `LD_*` and `MACOSX_*` families, among others). The record is valid only while every stamped path keeps its inode, size, mtime and ctime. Stamped paths include:

- the xcode-select link, both developer roots and `/usr/bin/xcrun`
- the driver, clang, the linker and the resource directory
- the selected SDK, its parent, and the default SDK link and its parent
- the identity files that `apple()` already content-hashes

Racy stamps are never recorded. `xcrun --find` for build-script helpers uses the same contract. `NANOCOMPILE_SELECTION_MEMO=0` always queries live.

Measured on this machine, `internal-native-identity` drops from 32.3 ms to 5.5 ms median, including process startup.

## Installed tree memo (`src/identity.zig`)

Explicit build-script contracts fingerprint installed trees such as the macOS SDK `usr/include` (12,368 stamps) on every hit. The previous memo held a multi-megabyte JSON document and took an **exclusive** lock even to read a valid record. Contracted scripts running in parallel queued on it: the traced profile measured `material.sdk_stamps` at 112 ms per hit.

Version 3 keeps the trust rule unchanged: content digests of every file, plus a complete inode/size/mtime/ctime stamp check and link-target check on every use. Three things change:

- The record is a sealed, tab-separated line format whose paths are sliced from the buffer.
- Valid records are read without a lock. Records are atomically renamed into place, and the lock only coordinates recomputation.
- Stamps are validated with four workers.

Measured in isolation, `internal-installed-tree` on the SDK include tree drops from 8.4 ms to 3.7 ms in-process, and parallel callers no longer serialize. A unit test covers preserved-mtime edits, link retargets and corrupt records.

## Tests

- `tests/digest_memo.py` (real rustc, 256 KiB inputs and outputs):
  - same-size, mtime-preserving input edits miss and match direct compilation
  - same-size, mtime-preserving corruption of a large cached blob forces recompilation and repairs the blob
  - an in-place modification of a restored output is rehashed
  - garbage memo records are ignored
  - the disable control writes no records
- `tests/native_identity.py`:
  - the selection memo equals live selection
  - corrupt selection memos are ignored
  - replacing the selected SDK directory at the same path invalidates the memo
- The existing integration, producer, executable, native-metadata, static-native, build-script and clang suites pass unchanged.
