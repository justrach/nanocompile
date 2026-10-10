# Turborepo task artifact demonstration

Implementation `5318857` adds an opaque-artifact interface in the stable Zig
0.17.0 cache and a Python loopback adapter for Turbo's Remote Cache API.
The [two-package example](../examples/turborepo/README.md) uses locked Turbo
2.11.7 and Node 24.10.0 locally: a producer writes JSON and a dependent app
writes HTML. Both tasks declare `dist/**` outputs and a task environment input.
Artifact signatures are enabled and preserved through the Zig store.

The [local raw results](turborepo-example.json) record a single empty-cache
build at 0.630 seconds, output-deleting remote restore at 0.058 seconds, and
snapshot restore at 0.059 seconds. The final local run uses adapter `12f12ec`;
its Zig core is unchanged from `5318857`. These tiny-fixture samples demonstrate
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

The [actual R2 run](https://github.com/justrach/nanocompile/actions/runs/37928602023)
passed on Linux and Mac for `12f12ec`. Each run uploaded the populated Zig store
to the configured R2 bucket, removed its local cache, downloaded into a different
cache directory and restarted the server with a different cwd. Both signed
outputs then restored with zero build-script executions and matching hashes.
Source/dependency/env invalidation, corruption repair, team/token isolation,
HEAD/bulk lookup, GC and clear passed on each machine too.

| Runner | Empty-cache build | Remote restore | Restore after R2 snapshot |
| --- | ---: | ---: | ---: |
| Ubuntu 24.04, Node 22.23.3 | 0.401 s | 0.125 s | 0.124 s |
| macOS 26, Node 24.20.0 | 1.092 s | 0.069 s | 0.145 s |

These are one-sample demonstrations on a tiny fixture. R2 upload/download is
outside the task-build timers; snapshot-restore time measures the Turbo fetch
from the repopulated local server, not S3 network latency. The live server uses
local CAS storage. [Linux raw evidence](turborepo-r2-ubuntu-24.04.json) and
[Mac raw evidence](turborepo-r2-macos-26.json) retain task summaries, execution
counters, output hashes, Node/Turbo versions and executable checksums.
[Compiler and task-cache CI](https://github.com/justrach/nanocompile/actions/runs/37928463419)
also passed on Linux and Mac.

The initial Mac jobs timed out before the server became ready. Python's standard
HTTP server performs a reverse DNS lookup during bind; the loopback adapter now
skips that unnecessary lookup. A regression test starts it with an unavailable
resolver, and both hosted Mac checks passed after this change. The original
failed Mac run is not included as successful evidence.

## Selected-resource revision refresh

[Fresh actual R2 validation](https://github.com/justrach/nanocompile/actions/runs/38010359904) passes on both Ubuntu 24.04 and macOS 26 for source `3fdc90645289254397e51eccf37a21ba9bb1233e`. Both restored tasks record remote hits, zero executions and output hashes matching the cold build. Dependency, site, environment and corruption checks retain the expected execution patterns.

| Runner | Empty-cache build | Remote restore | Restore after R2 snapshot |
| --- | ---: | ---: | ---: |
| Ubuntu 24.04 | 0.454 s | 0.126 s | 0.130 s |
| macOS 26 | 1.178 s | 0.082 s | 0.099 s |

These remain single-sample fixture demonstrations; S3 transfer time is outside task timers. [Linux raw results](turbo-selected-decoder-r2-linux.json) and [Mac raw results](turbo-selected-decoder-r2-macos.json) preserve all samples and versions.
