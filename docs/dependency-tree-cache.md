# Dependency-tree cache (design proposal for #15)

Status: proposal. No implementation yet. This document exists to fix the shape — keys, entry format, restore semantics, gc impact, failure modes — before code, because almost every decision here is hard to reverse.

## Problem

Every checkout pays for its own dependency tree. `git worktree add`, review copies and agent worktrees each produce a byte-identical `node_modules` when the lockfile has not changed. On the machine this was written on, one project's worktrees alone held ~70 GB of `node_modules`/`target`/`.next` across 37 worktree roots, with `node_modules` at ~1.6 GB per copy.

Compiler-cache savings do not help here: the duplicated bytes are dependencies, not compiled artifacts. nanocompile already has the four pieces needed — a single store (`NANOCOMPILE_DIR`), content-addressed blobs, `clonefile` restore with copy fallback (`materialize`), and gc that reconciles references — so this belongs here rather than in another tool.

The point of using `clonefile` rather than an archive is **physical** sharing: on APFS a restored tree costs no additional disk until it is written to. An archive-based restore (extract tar) writes real bytes and re-creates the problem it was meant to solve. `logical bytes` in `stats` counts apparent size, so it will overstate physical usage for trees; that is expected and should be documented rather than "fixed".

## Non-goals

- Not a package-manager replacement: no resolution, no registry access, no lockfile edits.
- Not a store of registry tarballs (`~/.bun/install/cache` style). It caches the installed tree.
- No cross-platform trees: a `darwin-arm64` tree never satisfies a `linux-x64` key.

## Key

`nanocompile-dep-tree-v1` prefix, then the existing `field()` framing so no two components can collide:

| Field | Source | Why |
| --- | --- | --- |
| lockfile digest | `bun.lock`/`bun.lockb`, `package-lock.json`, `pnpm-lock.yaml` | The only thing that changes the tree's contents. |
| `package.json` digest | scoped fields only: `workspaces`, `overrides`/`resolutions`, `packageManager` | These change the tree without touching the lockfile. |
| package manager + exact version | `bun --version`, etc. | Layout differs across majors (hoisting, `.bin` shape). |
| platform / arch | `builtin.os.tag`, `builtin.cpu.arch` | Native addons are platform-bound. |
| runtime version | `node --version` / `bun --version` | ABI-bound native addons. |
| declared env | `NANOCOMPILE_TREE_ENV=a,b` list | `npm_config_*`, `NODE_ENV` that alter install output. |

Anything unknown — a missing lockfile, an unparseable version, an unrecognised package manager — is a **miss**, never a guess. A frozen install is required to store; a non-frozen install may restore but never populates.

## Entry

Schema bumps to 6 with one additive field, so existing entries stay readable (they simply have `tree == null`, and every compiler path already rejects unknown extras the same way it rejects `artifact`):

```zig
pub const TreeInfo = struct {
    manifest: []const u8,  // blob hash of the manifest
    files: u64,            // record count, for a cheap sanity check
    bytes: u64,            // apparent bytes, for reporting
};

pub const Entry = struct {
    artifact: ?ArtifactInfo = null,
    tree: ?TreeInfo = null,     // new
    schema: u32 = entry_schema, // 6
    dependencies: []const Dependency, // the key inputs, as hashes
    outputs: []const Output,
    stdout: []const u8,
    stderr: []const u8,
};
```

Per-file blobs, not one archive — that is what makes restore a clone instead of a copy.

### Manifest format

One NDJSON record per file, sorted by path, stored as its own blob (so the manifest is content-addressed and dedupes across worktrees too):

```
{"k":"f","p":"@types/node/index.d.ts","m":420,"h":"9f86d0..."}
{"k":"l","p":".bin/tsc","t":"../typescript/bin/tsc"}
{"k":"d","p":"@types"}
```

- `k`: `f` file, `l` symlink, `d` directory (only when empty, to preserve empty dirs).
- `p`: POSIX-relative path. Rejected if absolute, containing `..`, or escaping the destination root — the same class of check as `validHash` and the existing symlink validation.
- `m`: mode bits, files only.
- `h`: blob hash; resolved through the existing `blobs/XX/hash` layout.
- `t`: symlink target, stored verbatim (never dereferenced, never resolved).

Excluded at store time: `.git`, `node_modules/.cache`, and anything in `NANOCOMPILE_TREE_EXCLUDE`. Excluding a directory prunes the whole subtree.

## Store

1. Require a frozen install and an unchanged lockfile afterwards; otherwise refuse to store.
2. Walk the staging tree (never the live tree — the installer must run into a sibling directory).
3. `putFile` each regular file, `putBytes` the manifest, `seal` the entry.
4. Cap: refuse a tree above `NANOCOMPILE_TREE_MAX_FILES` (default 200k) or `NANOCOMPILE_TREE_MAX_BYTES` (default 8 GiB) with a trace line, so a pathological checkout cannot fill the store in one step.

## Restore

1. Read and unseal the entry; require `schema == 6`, `artifact == null`, `tree != null`, and a manifest hash that validates.
2. Verify the manifest's own hash (small: single blob), then each record's blob **size**. Content verification is deliberately different from compiler outputs: a 30k-file, 1.6 GB tree cannot be re-hashed on every restore without turning a sub-second clone into a multi-second read, which is the entire benefit. `nanocompile tree verify` re-hashes on demand, and `NANOCOMPILE_TREE_VERIFY=1` forces it during restore.
3. Materialize into a sibling temp directory (`<dest>.nano-<pid>`), then rename into place, so a failed restore never leaves a half-tree. `materialize` already does the per-file temp+rename dance; this wraps it one level up.
4. Missing or size-mismatched blob: treat as a miss, remove the temp directory, and let the caller run the real installer. Never a partial tree under the destination.

## gc

Tree entries must expose their file hashes, or the first gc pass will delete the entire tree's blobs as unreferenced. When collecting references, if `entry.tree != null`, read the manifest blob and add each `h` (and the manifest hash itself). This is the single most dangerous part of the change: a missed reference list still parses, still validates, and silently destroys restore-ability. It needs a test that stores a tree, runs gc to a budget that forces eviction of everything else, and asserts the tree still restores.

## CLI

```sh
nanocompile tree key                    # print the key for the current directory
nanocompile tree store DIR [--frozen]    # store a staged tree
nanocompile tree restore DIR             # restore into DIR (atomic)
nanocompile tree verify [DIR]            # re-hash blobs against the manifest
nanocompile install [--pm bun|npm|pnpm] [--frozen] -- [installer args]
```

`install` keys the tree; on a hit it restores and exits without network; on a miss it runs the real installer into a staging directory, stores what came out, then clones it into place. Worktree hooks get the cheap path:

```sh
# .git/hooks/post-checkout, or the worktree-creation helper
nanocompile install --frozen || bun install --frozen-lockfile
```

## Out-of-the-box artifact

```sh
$ nanocompile install
key 8f3c19e0… (bun 1.2.21, darwin-arm64, node 24.14.1, bun.lock)
hit: 14,982 files, 1.6 GB apparent, restored in 0.31s, ~0 bytes added
$ nanocompile stats | grep logical
logical bytes: 1733369856    # one copy, shared by every worktree
```

## Failure modes

| Case | Behaviour |
| --- | --- |
| Store and destination on different volumes | `clonefile` fails → copy fallback (already in `materialize`); trace it. Space is no longer shared. |
| Tree mutated in place after restore | CoW copies the changed files (correct). Detected at the next store by manifest mismatch; not re-stored automatically. |
| Lockfile changed during install | Refuse to store. |
| pnpm | Its `node_modules` is a symlink graph into a global store. Restoring it must preserve symlinks verbatim, and the global store must exist; v1 supports `bun`/`npm` and treats `pnpm` as a miss until tested. |
| postinstall scripts | Not run on restore (they already ran when the tree was stored). Documented, with `NANOCOMPILE_TREE_POSTINSTALL=rerun` as an explicit opt-in. |

## Slices

1. **Tree entries + store/restore + gc references + tests.** No package manager involvement; `tree store/restore/verify` only. This is the part that must be right.
2. **`install` wrapper** for bun and npm, frozen-only population.
3. **Worktree hook docs** and a measured before/after on a real repo with several worktrees.

## Open questions

- Content verification default (see Restore §2): off with `tree verify` on demand, or on with an opt-out?
- Should `install` also handle `target/` and `.next/`, or stay dependency-only? The same mechanism applies; the key would be the crate graph and the build inputs respectively.
- Does the manifest format need a version prefix so a future change can coexist, or is the entry `schema` bump sufficient? (Current code has a single `entry_schema`; a future tree-v2 would need a discriminator.)
