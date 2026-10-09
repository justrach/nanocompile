# Cache-hit workers with in-memory diagnostics

The [first persistent-worker prototype](restore-worker-experiment.md) did not
establish a gain. This iteration removes temporary-file diagnostic capture and
avoids worker IPC for obvious compiler probes and actual Rust producers.
It retains the same full-content verification and produces small median
improvements in two controlled Harness sessions. It remains experimental;
production is not changed.

The [private source patch](../benchmarks/experiments/restore-worker-memory.patch)
keeps the first prototype's `restore_only` gate and adds optional, request-local
stdout/stderr buffers to `cache.Context`. Ordinary restores append their already
verified diagnostics directly into the request arena; trace messages use the
same stderr buffer. Streams are bounded to 64 MiB each. The
[worker](../benchmarks/experiments/restore_worker_memory.zig) sends them before
releasing that arena through the
[memory transport](../benchmarks/experiments/restore_worker_transport_memory.c).
No `tmpfile`, stdout/stderr `dup2`, file rewind or diagnostic-file reread is
needed. The client still buffers a complete response before forwarding bytes,
so incomplete service responses can fall back without partial replay.

The [client](../benchmarks/experiments/restore_worker_front_memory.c) recognizes
disabled caching, known management commands, Rust version/print probes, and
exact binary/proc-macro crate-type flags. It immediately executes the accepted
wrapper for those requests. This is a dispatch optimization; it changes no
eligibility, source/blob validation, key, native selection, locking or producer
policy. Other unsupported requests are still declined by the worker and
returned to the accepted wrapper. The CLI environment and inherited descriptors
are preserved.

The [15 real compiler and failure checks](../benchmarks/restore-worker-memory-check.json)
cover exact artifact/diagnostic/trace replay, source/environment/cwd changes,
corruption repair, the already-dirty writable mmap counterexample, concurrent
restores, compiler failure status, original stdin, stable Zig 0.17.0 restores,
malformed requests and dead-worker fallback. They explicitly prove that a
version probe and a binary producer skip IPC while ordinary warm restores
increment worker service counters.

Two 27-pair actual Harness sessions use the same accepted, client and worker
executables: [first session](../benchmarks/harness-restore-worker-memory-paired.json)
and [confirmation](../benchmarks/harness-restore-worker-memory-paired-confirm.json).
Each rotates order, uses a stable wrapper path within its session, keeps
environment/target/cache identical between its two modes, and uses Rust 1.97.1
with four Cargo jobs. The worker pool remains alive for both modes. The memory
cap and RSS observations include the benchmark parent, workers, Cargo and its
compiler descendants. Every raw sample is retained.

| Measure | First session | Confirmation |
| --- | ---: | ---: |
| Accepted warm median | 2.685267 s | 2.697642 s |
| Prototype warm median | 2.649694 s | 2.677427 s |
| Difference of build medians | 35.57 ms (1.32%) | 20.22 ms (0.75%) |
| Candidate wins | 19 / 27 | 18 / 27 |
| Median paired savings | 12.62 ms | 13.77 ms |
| Mean paired savings | 16.27 ms | 37.38 ms |
| Sample standard deviation | 50.66 ms | 133.95 ms |
| Standard error | 9.75 ms | 25.78 ms |

Across all 54 pairs, candidate wins 37, median paired savings are 13.19 ms,
mean paired savings 26.83 ms, sample standard deviation 100.86 ms and standard
error 13.73 ms. These are modest gains with substantial variation; they do not
justify a large speedup claim or adopting a production service by themselves.
The experiment bundles capture and dispatch changes, so it cannot attribute
the gain to either change alone. Its comparison is against the accepted wrapper,
not a controlled first-prototype-versus-second-prototype benchmark.

Every one of the 108 warm builds records 167 hits, eight bypasses and three
failed compiler probes. Every candidate warm build serves 136 worker hits
and declines six requests through IPC; the other producers/probes use the
direct fallback route. The first prototype had 42 IPC declines. All 167
collected artifacts match each session's first prime. Tracked Harness sources
remain unchanged. Service logs contain result codes, not request payloads or
environment values.

Baseline primes take 40.326 and 38.520 s. Candidate primes take 2.741 and
2.700 s because they reuse the baseline cache; those are not candidate cold
results. R2 transport is excluded. The accepted three-way kache comparison is
unchanged, and this experiment claims no cold-build or cross-platform gain.

Reproduce from an isolated export with stable Zig 0.17.0 on macOS:

```sh
mkdir /tmp/nanocompile-worker-memory-source
git archive d7c3c02 src | tar -x -C /tmp/nanocompile-worker-memory-source
git -C /tmp/nanocompile-worker-memory-source apply \
  /absolute/path/to/nanocompile/benchmarks/experiments/restore-worker-memory.patch
cp benchmarks/experiments/restore_worker_memory.zig \
  /tmp/nanocompile-worker-memory-source/src/restore_worker_memory.zig
zig build-exe -O ReleaseFast -lc \
  benchmarks/experiments/restore_worker_transport_memory.c \
  /tmp/nanocompile-worker-memory-source/src/restore_worker_memory.zig \
  -femit-bin=/tmp/nanocompile-restore-worker-memory
zig cc -O2 -Wall -Wextra benchmarks/experiments/restore_worker_front_memory.c \
  -o /tmp/nanocompile-restore-front-memory
python3 benchmarks/experiments/restore_worker_check.py \
  /tmp/nanocompile-restore-worker-memory /tmp/nanocompile-restore-front-memory \
  /absolute/path/to/accepted/nanocompile --expect-pruning \
  --output /tmp/worker-memory-check.json
python3 benchmarks/experiments/restore_worker_pair.py \
  /absolute/path/to/accepted/nanocompile /tmp/nanocompile-restore-front-memory \
  /absolute/path/to/harness --worker /tmp/nanocompile-restore-worker-memory \
  --worker-root /tmp/nanocompile-restore-worker-service-memory \
  --state /tmp/worker-memory-paired-new --runs 27 \
  --output /tmp/worker-memory-paired-new.json
```

The pair driver starts four workers and stops them on exit. It requires a fresh
service directory and preserves the copied accepted executable and service
logs there. The confirmation used the exact same binaries and service pathname;
after the first processes stopped, its directory was moved aside to preserve
evidence, and the driver created a fresh one. For another pathname, use the
`NC_WORKER_DIR`/`NC_FALLBACK` compile-time overrides documented with the first
prototype, and pass that same root to the driver. Do not change only one side's
environment to select a different service.

Reports include core revision, helper/source/patch/executable SHA-256, service
counts, durations, and artifact/source hashes. The original first-prototype
sources and measurements remain available. Normal production code, CLI and
installed executable are unchanged. The next worker iteration can investigate
the producer hits still executing in the normal wrapper, while retaining its
observer identity, live native selection, complete validation and miss fallback.
