# File-granular opaque artifacts

The local native CLI adds `artifact put-files`, `get-files` and `head-files`.
They keep a complete file set in one sealed entry while sharing identical
content-addressed blobs with other entries. This is not a whole-build cache or
an incremental remote-transfer protocol. Check `nanocompile --help` for
`put-files`; the feature is not yet in a new downloadable release.

## Inventory and commands

Create an inventory while the producer's files are quiescent:

```json
{
  "schema": 1,
  "directories": ["compiler", "compiler/empty"],
  "files": [
    {"path": "compiler/hint", "source": "/absolute/private/compiler/hint"}
  ]
}
```

All parent directories must be declared, including empty directories. `source`
may be absolute or relative to the command's working directory; it is read but
not recorded in the stored entry. Logical `path` names are persisted and should
not contain sensitive information. The caller owns the namespace/key contract.

```sh
export NANOCOMPILE_DIR="$PWD/.cache/nanocompile"
export NANOCOMPILE_MAX_SIZE=402653184
nanocompile artifact put-files example compatible-inputs inventory.json '{"schema":1}'
nanocompile artifact head-files example compatible-inputs
nanocompile artifact get-files example compatible-inputs private-stage
```

`private-stage` must not already exist and its parent must be caller-owned and
trusted. A successful get restores independent copies/clones, never hardlinks to
CAS blobs. Validate framework-specific layout and metadata in this private stage
before publishing into the live project. The API does not merge or replace live
directories and is not an atomic live-tree publication operation.

Put reports `stored`, payload `bytes`, file and directory counts. Get/head report
`hit`, the same counts and the caller's metadata as a JSON string. Misses return
exit code 3 and `{"hit":false}`. Other errors are nonzero. Native automatic
maintenance can immediately evict an over-budget put, so use `head-files` to
confirm retention rather than interpreting `stored:true` as a retention promise.

## Bounds and validation

- At most 100,000 file/directory members and 1 GiB of summed file payload.
- Logical names are portable ASCII, at most 4,096 bytes; absolute paths,
  traversal, case aliases, duplicate names, missing parents, file/directory
  conflicts, Windows reserved names and nonportable characters are rejected.
  Source filesystem paths can contain non-ASCII characters.
- Sources must be regular, non-symlink files. The Next helper additionally rejects
  hardlinks and all non-owned/special nodes. The native API normalizes file modes
  to `0644`; it is not an executable-tree or permission-preservation API.
- Caller metadata must be valid JSON, at most 8 KiB. The sealed entry is limited
  to 64 MiB. Empty directory-only snapshots are supported.
- Put rechecks source state and freshly hashes the exact stored blobs before
  publishing the complete manifest. Get/head verify its seal, schema, identities,
  names and every referenced blob by content. They do not trust persisted stat
  memos. Get creates no destination until this verification passes, and cleans
  its newly owned stage if subsequent placement fails.

The caller must still provide a coherent source snapshot, prevent concurrent
producer mutation and enforce its semantic compatibility key. The cache is
private trusted storage; a manifest checksum is not an authentication boundary.

## Storage and compatibility

Each file is an ordinary `outputs[]` reference in the existing schema-5 entry.
Empty directories and caller metadata are carried in the artifact metadata
wrapper. There is no hidden list of untracked blobs: normal native budget/GC
traversal sees every reference and counts shared content once. A complete seed
still has to fit its budget; deduplication does not make a single oversized seed
retainable. The quota excludes local compiler outputs and temporary peak writes.

The new commands have a separate identity domain. Existing single-file
`artifact put|get|head` entries remain unchanged, even for the same namespace/key.
Older CLIs cannot consume the new commands. Existing generic Next/worktree builds
continue to use archives; Meld2 explicitly opts into file snapshots when its CLI
and adjacent Python helpers support both new APIs. Its archive fallback remains
available. See [the real Meld2 study](meld2-file-snapshots.md).

Verified locally with ReleaseSafe on macOS/aarch64. This is not a Linux/Windows
runtime or hosted remote-transfer benchmark.
