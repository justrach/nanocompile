# Persistent cache-hit workers: first prototype

The [ordinary-hit profile](library-phase-profile.md) separated cache work from
process launch and runtime costs. This private prototype tests whether moving
cache hits into persistent processes improves actual Harness builds while
keeping full source and blob verification. It does not establish a dependable
gain, so production is unchanged. The implementation remains an experiment
for further transport and dispatch work.

Four persistent Zig workers run the existing compilation plan, key construction,
toolchain validation, locks, directory/negative lookup guards, full BLAKE3
input/blob reads and output materialization. Each request gets a fresh arena,
environment map and cache context. No source or blob digest survives a request.
One request executes at a time per worker process; grouped IO tasks and locks
finish before that process changes its cwd for the next request.

A [small private source patch](../benchmarks/experiments/restore-worker-only.patch)
adds a `restore_only` context flag. Unsupported invocations and actual producers
return a fallback status before compiler execution. A cache miss returns that
status after the ordinary restore attempt and lock cleanup. The experimental
C client then `execv`s the accepted wrapper with its original argv, environment,
stdin and inherited Cargo jobserver descriptors. Actual compilation stays in
the caller process. Producers retain the accepted observer executable hash;
no new producer namespace is used in this comparison.

The [Zig worker](../benchmarks/experiments/restore_worker.zig) receives bounded
JSON batches through Unix sockets in a caller-owned mode-0700 directory.
The [C transport shim](../benchmarks/experiments/restore_worker_transport.c)
creates mode-0600 sockets and verifies peer UID. The
[lightweight C client](../benchmarks/experiments/restore_worker_front.c)
uses private per-worker locks to choose an available process, bounds socket
waits, and falls back on service absence or failure. Diagnostics are captured
into unlinked temporary files, then sent as bounded binary streams. The client
buffers the complete reply before forwarding bytes, preventing a truncated
service reply from duplicating diagnostics during fallback. Local output-write
failure returns failure rather than replaying partly written output.

This experiment uses C for startup/transport measurements and Zig for the
cache logic. It is not a production daemon or a change to the project's
language requirements. Request parsing, transport, diagnostic capture,
worker scheduling and extra miss planning all cost time; removing startup
alone does not predict their net effect.

The [27-pair Harness comparison](../benchmarks/harness-restore-worker-paired.json)
uses Rust 1.97.1, four Cargo jobs, rotating order, one stable wrapper path,
identical environment/target/shared cache, and a 40 GiB process-tree memory
cap. The worker pool remains alive for both modes. Memory samples include
the benchmark parent, all workers, Cargo and compiler descendants.

| Measure | Result |
| --- | ---: |
| Accepted warm build median | 2.691545 s |
| Worker prototype warm build median | 2.706421 s |
| Candidate wins | 17 of 27 pairs |
| Median paired savings | 15.08 ms |
| Mean paired savings | 11.76 ms |
| Sample standard deviation | 105.79 ms |
| Standard error | 20.36 ms |

The two build medians and median paired differences are different statistics;
their signs need not agree. Variation is larger than the observed mean paired
savings. This session does not justify adopting the worker or claiming a
project speedup. All samples, including slower outliers, remain in the report.

All 54 warm builds record 167 hits, eight bypasses and three failed compiler
probes. Every candidate warm build actually serves 136 requests in the workers
and returns 42 requests to the accepted wrapper; baseline builds send no worker
requests. All 167 collected artifacts match the first prime, and tracked
Harness sources remain unchanged. The baseline prime is 39.970 s; the candidate
prime reuses its ordinary and producer entries, so 2.777 s is not a cold-cache
candidate result. R2 transfer is excluded. No new kache or cold-build comparison
is claimed by this experiment.

The [real compiler checks](../benchmarks/restore-worker-check.json) exercise
worker-served Rust/Zig hits, exact artifact/diagnostic replay, source mutation,
environment and cwd isolation, corruption repair, concurrent output locks,
unsupported compiler failures, original stdin, malformed requests and dead
service fallback. Full hashing detects the live already-dirty mmap source
change that defeated the preceding watched-digest model. The driver verifies
that warm restores increment actual worker service counters, rather than
merely observing a normal wrapper hit after fallback.

This validates the local prototype's tested paths. It does not prove crash
atomicity, exhaustive descriptor/signal semantics, all compiler workloads,
cross-platform daemon behavior or a performance gain. The private worker and
transport are not shipped through the normal build or CLI.

Reproduce the first prototype from the recorded core revision in a disposable
source export, using stable Zig 0.17.0 on macOS:

```sh
mkdir /tmp/nanocompile-worker-source
git archive 98db859 src | tar -x -C /tmp/nanocompile-worker-source
git -C /tmp/nanocompile-worker-source apply \
  /absolute/path/to/nanocompile/benchmarks/experiments/restore-worker-only.patch
cp benchmarks/experiments/restore_worker.zig \
  /tmp/nanocompile-worker-source/src/restore_worker.zig
zig build-exe -O ReleaseFast -lc \
  benchmarks/experiments/restore_worker_transport.c \
  /tmp/nanocompile-worker-source/src/restore_worker.zig \
  -femit-bin=/tmp/nanocompile-restore-worker
zig cc -O2 -Wall -Wextra benchmarks/experiments/restore_worker_front.c \
  -o /tmp/nanocompile-restore-front
python3 benchmarks/experiments/restore_worker_check.py \
  /tmp/nanocompile-restore-worker /tmp/nanocompile-restore-front \
  /absolute/path/to/accepted/nanocompile --output /tmp/worker-check.json
python3 benchmarks/experiments/restore_worker_pair.py \
  /absolute/path/to/accepted/nanocompile /tmp/nanocompile-restore-front \
  /absolute/path/to/harness --worker /tmp/nanocompile-restore-worker \
  --state /tmp/worker-paired-new --runs 27 --output /tmp/worker-paired-new.json
```

The pair driver creates `/tmp/nanocompile-restore-worker-service` and stops its
four processes on exit; it preserves logs, locks, sockets and the copied
accepted wrapper there as evidence. Use a fresh service directory for a new
session. To select another location, compile the client with
`-DNC_WORKER_DIR='"/absolute/private/service"'` and
`-DNC_FALLBACK='"/absolute/private/service/baseline"'`, then pass that directory
to the pair driver with `--worker-root`. Both modes must retain identical
environment values. The checks driver configures its own private service
location and fallback through environment variables shared by its controls.

The reports retain core revision, script/helper/patch/executable SHA-256,
raw durations, service counts and artifact/source hashes. Compiler environment
values and request payloads are not written into public results. Accepted
installed executable SHA-256 remains
`1f8f2a76a8bd66450fb24065a64556d74b254a946fb207cfbe7e4a83d96f0658`.

The next iteration can remove temporary-file diagnostic capture and decline
known producer/probe requests before IPC. Those are hypotheses to implement
and measure against this first prototype, not established savings.

The subsequent [in-memory diagnostic/dispatch experiment](restore-worker-memory-experiment.md)
implements those changes and records two 27-pair Harness sessions. It preserves
full hashing and remains experimental; its small median improvements are not
a production adoption or a cold-build gain.
