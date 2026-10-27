# Small shared cache, useful retained work

The native CLI defaults to a **1 GiB logical-byte budget for shared CAS blobs
plus sealed entry manifests**. This covers Rust/Zig/portable-C cached outputs,
declared task outputs, and opaque artifacts such as shared Next.js/OpenNext
compiler snapshots. Shared blobs count once regardless of how many retained
entries reference them. It is not a hard quota on the entire cache directory
or on temporary space while a build is running.

```sh
# Smaller shared store: 512 MiB. Set consistently for users of the same cache.
export NANOCOMPILE_MAX_SIZE=536870912
nanocompile stats

# Decimal bytes; zero means no persistent entry/blob retention, not unlimited.
NANOCOMPILE_MAX_SIZE=0 nanocompile task tasks.json

# Explicit orphan collection and blob-budget eviction remain available.
nanocompile gc
nanocompile gc 268435456
```

The default is `1073741824` bytes. Invalid or overflowing values are rejected
before executing the requested command. As with other environment values,
changing this setting can change a compiler/task compatibility key; it is not
removed from a task's real environment merely to manufacture cache hits.
`stats` reports the configured automatic budget and current managed logical
bytes separately from its existing blob-only byte count. Those are file
lengths, not allocated filesystem blocks or physical disk usage; copy-on-write
and filesystem metadata can make physical use differ.

## Retention without throwing away the wins

Successful artifact reads and output restores explicitly refresh the entry's
modification timestamp. Eviction uses that recency, rather than relying on
filesystem access-time policies. Old entries go first. An immutable blob is
deleted only after its final retained reference is gone; orphan blobs are
removed when over-budget collection runs. Entries whose complete retained
payload cannot fit are discarded before evicting useful smaller entries, not
permanently exempted or allowed to flush the working set. Existing user outputs
remain usable after their cache entry is evicted.

A warm hit normally performs small control-file checks, not a whole-store
scan. After stores, pending maintenance or a changed limit, the CLI tries to
acquire **exclusive maintenance without waiting**. At a safe quiescent point
it counts the managed store, evicts only if necessary, and removes obsolete
zero-byte key-lock files. It never unlinks the permanent maintenance lock.
Reference reconciliation and deletion cannot race a cooperating restore,
compiler, task or artifact writer holding shared maintenance.

Nested commands matter: a declared task can invoke the artifact CLI while its
parent holds shared maintenance. Blocking for exclusive maintenance in that
child would deadlock. Instead maintenance is deferred. A marker written
before storage survives crashes and contention; the next quiescent cache
operation reconciles it. Concurrent operations can temporarily exceed the
budget, and one oversized write can require temporary space above it. This is
settled retention, not a reservation system or an in-flight disk-space quota.
Maintenance errors warn without changing the real build's exit status.

The local event history resets after exceeding **1 MiB**, under exclusive
maintenance. `stats` event counters therefore describe a recent window, not
an unlimited lifetime history. Long individual graphs can temporarily exceed
that window before a safe maintenance point. Explicit `gc` keeps its existing
blob-byte accounting/report interface; automatic retention additionally counts
entry manifests. Both share the same content/refcount validation and eviction.

## What this does not delete or cap

- Project source files, restored outputs, Git worktrees and private
  `node_modules`/`.next`/`.open-next` directories.
- Shared package-manager downloads under `downloads/`; installers and package
  managers have separate ownership and pruning policies.
- Apple's native Xcode/Clang CAS, toolchain identity/resource memos, metadata
  queries, retained producer diagnostics and other non-CAS auxiliary state.
- Remote R2 object storage or remote snapshots.

Do not interpret a 1 GiB shared-store limit as 1 GiB total disk use. Use a
separate `NANOCOMPILE_DIR` for workloads that should not evict one another.
Arbitrary manual changes and older writers cannot maintain the pending marker;
after external imports, run `nanocompile gc` and inspect `stats`. The bundled R2
pull helper marks imports pending so the next native cache operation reconciles
them; download/staging and remote retention limits remain separate. All writers
sharing a store should use the updated CLI and compatible settings.

A smaller budget trades historical branch/version coverage for disk space.
Start with the default or 512 MiB, then inspect actual hits and managed bytes;
no universal hit-rate or whole-build speedup is promised. Cache keys, complete
input/blob hashes, failure handling, output isolation and trust boundaries are
unchanged by retention.

## Warm-hit cost

[Paired local measurements](../benchmarks/cache-budget.json) compare against the
immutable ReleaseSafe binary from the preceding task hill-climb. Initial
small-asset task wall time was essentially unchanged. Explicit recency updates
are not free: a 16-task graph with the retained single-syscall POSIX timestamp
update measured 19.979 versus 20.752 ms initially and 20.048 versus 19.815 ms
on fresh confirmation. Separate unreported graph medians increased by about
0.32 and 0.84 ms. Raw observations, including the earlier open/set/close
prototype, are retained rather than turning these mixed results into a speedup
claim. Maintenance only scans at storage/pending/configuration boundaries, not
every ordinary warm hit. These local warm-cache probes do not establish a
whole-project build saving or universal overhead bound.

## Verification

`python3 tests/cache_budget.py /path/to/nanocompile` uses disposable caches and
real native artifact/task commands. It covers default and zero limits,
manifest overhead, LRU refresh, shared-blob survival, replacement orphans,
oversized artifacts, invalid configuration, concurrent readers/writers,
nested-task deadlock avoidance, bounded event history and protected
source/output/dependency/download files. It does not alter user caches or
contact a service. All **14** budget checks passed, along with the native
ReleaseSafe build/unit tests and real Rust/Zig integration covering restore,
invalidation, corruption, copy isolation, failures, environment, escaped paths,
single-flight and bypass. Declared-task, focused-input, relocatable-task,
Next.js cache, worktree CLI, offline R2 transport and release-packaging checks
also passed. The platform-specific retention paths cross-built for Linux musl
and Windows GNU; this is not a native-runtime claim for those platforms.

These changes are local development work, not part of the published `v0.1.0`
binaries until a subsequent verified release is published.
