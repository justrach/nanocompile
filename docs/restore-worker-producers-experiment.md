# Producer cache-hit workers

This experimental iteration extends the [in-memory worker](restore-worker-memory-experiment.md)
to opt-in cached Rust proc-macro and executable producers. Normal production
code and the installed executable remain unchanged.

The [complete private source patch](../benchmarks/experiments/restore-worker-producers.patch)
is against core revision `80e72e4f959c4458c4f680a93a2b03070514ddf1`.
The [frontend](../benchmarks/experiments/restore_worker_front_producers.c)
sends the absolute accepted fallback executable as the producer observer.
The [worker](../benchmarks/experiments/restore_worker_producers.zig)
fully hashes that observer and uses the existing producer key namespace.
It runs the accepted live Apple toolchain selection queries for every producer
lookup and retains full input/blob hashing, guards, locks, diagnostics and
output materialization. No mutable digest or native-selection result is reused
between requests. A producer restore miss returns to the accepted wrapper before
observer installation or actual compilation. Disabled producer policies still
skip worker IPC. This controlled prototype pins one compatible accepted fallback;
it does not establish compatibility with arbitrary future observer versions.

The [15 general checks](../benchmarks/restore-worker-producers-check.json)
pass, including Rust/Zig artifact and diagnostic replay, trace bytes, source,
environment and cwd changes, blob repair, already-dirty mmap mutation, concurrent
locks, compiler failure, stdin, malformed requests, dead-service fallback and
version/disabled-producer pruning. The [producer regression driver](../benchmarks/experiments/restore_worker_producer_check.py)
runs the existing real macro and executable suites through the service.
[Macro results](../benchmarks/restore-worker-producers-regression-producer_cache.json)
and [executable results](../benchmarks/restore-worker-producers-regression-executable_cache.json)
verify actual macro loading, cold/warm artifact equality, native/source invalidation,
corruption repair, diagnostics, failed compilation and default/debug refusal.
Executable permissions and live runtime reads after restore also pass.
Each suite actually serves two worker hits and declines seven requests;
the [service report](../benchmarks/restore-worker-producers-regression.json)
checks those counters rather than inferring service use from cache events.

## Controlled Harness measurements

Two separate 27-pair sessions use Rust 1.97.1, four Cargo jobs, rotating order,
a stable wrapper path and identical environment/target/shared cache within each
session. Every raw sample is retained. The 40 GiB memory cap includes the
benchmark parent, all live pools, Cargo and compiler descendants. The project
checkout is dirty; all tracked Rust/manifest/lock contents remain unchanged.

| Measure | Accepted vs prototype | Ordinary vs producer dispatch |
| --- | ---: | ---: |
| Baseline warm median | 2.694806 s | 2.680255 s |
| Candidate warm median | 2.660769 s | 2.687345 s |
| Candidate wins | 22 / 27 | 15 / 27 |
| Median paired savings | 24.53 ms | 2.56 ms |
| Mean paired savings | 15.17 ms | 11.84 ms |
| Sample standard deviation | 73.80 ms | 91.04 ms |
| Standard error | 14.20 ms | 17.52 ms |

The [first comparison](../benchmarks/harness-restore-worker-producers-paired.json)
compares the accepted executable with the complete producer-worker prototype.
Its gain includes the earlier ordinary-worker and transport changes, so it
cannot isolate the benefit of producer dispatch.

The [direct dispatch comparison](../benchmarks/harness-restore-worker-producer-dispatch-paired.json)
uses the same producer-capable Zig backend for both policies, through two
independent four-process pools kept alive in both modes. The ordinary frontend
executes the accepted fallback for producers; the producer frontend sends them
to its worker. This isolates dispatch policy with the same backend, rather
than comparing the previous backend binary with the new one. Every warm ordinary
build serves 136 worker hits; every warm producer-enabled build serves 167.
Both decline six requests through IPC, with zero requests to the idle pool.
All warm builds record 167 cache hits, eight bypasses and three failed compiler
probes; all 167 collected artifacts match each session's first prime.

The first session has a lower prototype median, but the direct dispatch session
does not establish an incremental speed gain: its producer-enabled median is
7.09 ms slower, and mean paired savings are smaller than their standard error.
Difference of medians and paired differences are distinct statistics and can
have different signs. Serving 31 additional hits in workers is demonstrated;
a dependable project performance improvement from that change is not.
The prototype remains experimental and is not adopted into production.

Baseline primes are 39.714 s and 40.410 s. Candidate primes reuse their session's
baseline cache, so 2.741 s and 2.784 s are not candidate cold results. These
sessions exclude R2 transfer and do not replace the accepted three-way kache
comparison or demonstrate a cross-platform gain.

## Reproduction

Build in a fresh isolated export using stable Zig 0.17.0 on macOS:

```sh
mkdir /tmp/nanocompile-worker-producers-source
git archive 80e72e4 src | tar -x -C /tmp/nanocompile-worker-producers-source
git -C /tmp/nanocompile-worker-producers-source apply \
  /absolute/path/to/nanocompile/benchmarks/experiments/restore-worker-producers.patch
cp benchmarks/experiments/restore_worker_producers.zig \
  /tmp/nanocompile-worker-producers-source/src/restore_worker_producers.zig
zig build-exe -O ReleaseFast -lc \
  benchmarks/experiments/restore_worker_transport_memory.c \
  /tmp/nanocompile-worker-producers-source/src/restore_worker_producers.zig \
  -femit-bin=/tmp/nanocompile-restore-worker-producers
zig cc -O2 -Wall -Wextra benchmarks/experiments/restore_worker_front_producers.c \
  -o /tmp/nanocompile-restore-front-producers
python3 benchmarks/experiments/restore_worker_check.py \
  /tmp/nanocompile-restore-worker-producers /tmp/nanocompile-restore-front-producers \
  /absolute/path/to/accepted/nanocompile --expect-pruning \
  --output /tmp/worker-producers-check.json
python3 benchmarks/experiments/restore_worker_producer_check.py \
  /tmp/nanocompile-restore-worker-producers /tmp/nanocompile-restore-front-producers \
  /absolute/path/to/accepted/nanocompile \
  --output /tmp/worker-producers-regression.json
```

The regression service root must match the frontend's compiled default:
`/tmp/nanocompile-restore-worker-service-producers`. Some existing producer tests
filter cache environment overrides, so setting only a fallback environment
variable is insufficient. The pool copies the accepted observer there. After
all processes stop, move the preserved directory aside before a new run.
For another service root, compile the corresponding `NC_WORKER_DIR` and
`NC_FALLBACK` overrides and pass the same root to the driver.

The first Harness session uses `restore_worker_pair.py` with the accepted binary,
producer frontend, producer backend and `--worker-root` matching that frontend.
For dispatch isolation, also compile `restore_worker_front_memory.c` and run:

```sh
python3 benchmarks/experiments/restore_worker_producer_pair.py \
  /tmp/nanocompile-restore-front-memory /tmp/nanocompile-restore-front-producers \
  /absolute/path/to/harness --worker /tmp/nanocompile-restore-worker-producers \
  --fallback /absolute/path/to/accepted/nanocompile \
  --state /tmp/worker-producer-dispatch-new --runs 27 \
  --output /tmp/worker-producer-dispatch-new.json
```

Both default service roots must be fresh. Drivers stop their pools on exit and
preserve copied observers and result-only service logs. Reports record core,
helper/source/patch/executable SHA-256, raw durations, service counters and
artifact/source hashes; request payloads and environment values are excluded.
