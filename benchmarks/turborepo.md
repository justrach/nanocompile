# Turborepo task artifact demonstration

Implementation `5318857` adds an opaque-artifact interface in the stable Zig
0.17.0 cache and a Python loopback adapter for Turbo's Remote Cache API.
The [two-package example](../examples/turborepo/README.md) uses locked Turbo
2.11.7 and Node 24.10.0 locally: a producer writes JSON and a dependent app
writes HTML. Both tasks declare `dist/**` outputs and a task environment input.
Artifact signatures are enabled and preserved through the Zig store.

The [local raw results](turborepo-example.json) record a single empty-cache
build at 0.302 seconds, output-deleting remote restore at 0.059 seconds, and
snapshot restore at 0.060 seconds. These tiny-fixture samples demonstrate
functionality, not general project performance or superiority to Turbo's own
local cache. Node/npm installation is outside timing. No S3 network transfer is
included in these timings; the local snapshot uses an in-memory S3 test double.

The test explicitly disables Turbo's client-local cache, deletes outputs before
restores and inspects native Turbo summaries: both task hits are `REMOTE`.
Execution counters prove neither build script ran, and restored JSON/HTML hashes
match the cold build. Snapshot restoration moves the server cache to a new path
and restarts it under a different working directory. The same task keys still
restore signed artifacts.

Changing the producer input with its mtime preserved rebuilds producer and
app. Changing only the app source runs only that task. Changing a declared env
value changes both task hashes. Corrupting a stored archive causes a remote miss
and rebuild of only its producer; its correctly cached dependent output remains
valid. Token/team mismatch, bulk lookup, HEAD, GC quota and clear are exercised.
The real Rust/Zig integration suite also passes with the new entry metadata.

The backend does not discover task inputs or extract archives: Turbo owns those
operations, following its [caching contract](https://turborepo.dev/docs/crafting-your-repository/caching)
and [remote API](https://turborepo.dev/docs/openapi). Task entries share compiler
CAS blobs and GC/R2 transport, with an explicit entry marker and separate key
namespace preventing compiler/task confusion. The loopback service is a
single-team development adapter, not a published production cache endpoint.

The actual-R2 `Turborepo task cache and R2` workflow is running for this revision
on Linux and Mac. Its result must be recorded separately from the in-memory
local transport demonstration.
