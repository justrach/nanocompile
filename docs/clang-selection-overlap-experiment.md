# Overlapping live Clang and SDK selection

The installed Apple Clang command queries the default compiler and SDK on every
eligible job. This candidate starts the SDK query while the caller queries and
resolves the compiler, then joins the SDK worker before using its output.
It does not memoize either selection or change Clang's dependency discovery,
CAS arguments, artifact restoration, Rust key policy or producer observer.

Overlap applies only to eligible compile jobs using both defaults. Explicit
compiler selection, SDKROOT, caller sysroot flags, unsupported jobs and disabled
caching retain their existing paths. Failure to schedule the worker falls back
to sequential selection. SDK selection failure preserves the original compiler
arguments; tool selection failure preserves failure. Query buffers use a
separate allocator and are released after joining/canceling the worker.

The candidate is built in an isolated source directory. Correctness checks
exercise real C/debug/assembly replay, live selections, preserved-mtime and
already-dirty mmap invalidation, passthrough and compiler failures. A separate
two-way start barrier requires both selectors to start before either completes,
proving concurrency without a wall-time threshold. That check also covers
failed SDK and tool lookup behavior.

The paired runner keeps the accepted Rust wrapper and its producer-observer
identity fixed. It copies native wrapper binaries to one stable CC path and
uses the same complete Cargo environment, target, cache, compiler and SDK,
with native remarks enabled in both modes. Each mode is primed, then clean
Harness release builds alternate order in 27 pairs. Every Rust library,
producer artifact, native object and archive must match the first prime's
exact bytes. Tracked source/manifest hashes must remain unchanged. Native and
Rust warm hits are checked. Four Cargo jobs and a 40 GiB cap apply; sampled RSS
includes the benchmark parent and descendants. No R2 traffic is included.
The second prime reuses the first mode's cache and is not a separate cold run.

Reproducible candidate:
[clang-selection-overlap.patch](../benchmarks/experiments/clang-selection-overlap.patch).
Runner:
[clang_selection_pair.py](../benchmarks/experiments/clang_selection_pair.py).

## Result and adoption

Two independent 27-pair batches confirm a gain:

| Batch | Sequential median | Overlap median | Gain | Candidate wins |
| --- | ---: | ---: | ---: | ---: |
| First | 2.104719 s | 1.985952 s | 5.64% | 26/27 |
| Confirmation | 2.109516 s | 2.001227 s | 5.13% | 25/27 |

Every one of the 108 warm builds recorded 167 Rust hits and 24 native hits,
with 8 bypasses and 3 failed compiler probes. Both primes and all warm builds
matched 193 exact artifacts, including 24 native objects and 2 archives.
Tracked source/manifest hashes remained unchanged in both batches. The first
baseline primes were 39.855 and 38.522 s; the candidate primes reused warm
caches, so this experiment does not show a cold-build gain.

The change is adopted into the installed Clang command. Both selections still
execute live; only their ordering changes. The installed binary is rebuilt and
passes the real Rust/Zig integration suite, Clang regression and selector tests.
The Mac CI workflow now runs the barrier and failure tests too.

Raw samples and exact source/executable provenance:
[first batch](../benchmarks/harness-clang-selection-paired.json),
[confirmation](../benchmarks/harness-clang-selection-paired-confirm.json).
Installed checks:
[Clang regression](../benchmarks/clang-selection-installed-regression.json),
[live selectors](../benchmarks/clang-selection-installed-check.json).
The barrier/failure test is [tests/clang_selection.py](../tests/clang_selection.py).

These paired results use an unchanged accepted Rust wrapper and its observer
identity. They establish the native adapter gain, not a new direct/kache ranking.
A separate installed-binary three-way comparison supplies that comparison.

## Fresh installed-binary comparison

The fresh three-way run uses the rebuilt installed Nano command, the explicit
reported-macro and Apple producer policies, default selected native compilers,
and kache 1.0.0's private daemon. Warm medians from three samples per mode are
**22.584865 s direct, 1.982855 s Nano, and 2.080077 s kache**.

Nano samples are **2.853956, 1.959223 and 1.982855 s**; the first slow sample
is retained. Kache samples are **2.080077, 2.086133 and 2.067754 s**.
Nano has the lower median in this small run, but its mean is higher because of
the slow sample. This does not establish a broad latency advantage over kache.
The two 27-pair batches provide the stronger evidence for the lookup change.

Every warm mode matches its own cold Rust, producer and native artifact bytes.
Nano records 167 Rust and 24 native hits each time; kache records 187 local hits
and 3 passthroughs. Scanner debug differences and kache path remapping preclude
a blanket cross-mode byte-equality claim. Nano cold is **37.463829 s** versus
kache's **26.502405 s**; direct's initial build is 23.399754 s. No cold-build
improvement is established. Tracked source hashes remain unchanged.

[Full three-way samples and checks](../benchmarks/harness-clang-selection-three-way.json).

## Nine-sample repeatability run

The accepted installed executable was unchanged for a new session with nine
warm samples per mode (27 warm builds), the same pinned Rust 1.97.1 and kache
1.0.0, four jobs, native remarks and the previously stated macro/producer policies.
All timings are retained, including the 24.634 s direct sample.

| Mode | Warm median | Warm mean | Observed minimum–maximum |
| --- | ---: | ---: | ---: |
| Direct | 22.644105 s | 22.920641 s | 22.484260–24.634416 s |
| Nano | 2.005335 s | 2.024423 s | 1.955546–2.158802 s |
| Kache | 1.962289 s | 2.004796 s | 1.903651–2.164960 s |

Kache has the lower median by **43.05 ms** in this session, reversing the
shorter run's median ordering. Nano is faster in 3 of the 9 corresponding
rotation rounds. The mean same-round Nano-minus-kache difference is **19.63 ms**,
with descriptive standard error **45.05 ms**. These are measurements from one
local session, not independent-machine evidence or a general latency ranking.
The correct conclusion is that the tools are close on this workload, with
kache's median ahead here; a broad Nano advantage remains unproven.

Nano's first warm sample is 1.990365 s, and its maximum is 2.158802 s. The earlier
2.853956 s sample did not recur in this session. That does not explain its cause
or establish that such delays cannot recur. Both datasets remain public.

All 27 warm builds match their own cold Rust, producer and native artifact
hashes. Every Nano warm build records 167 Rust and 24 native hits; every kache
warm build records 187 local hits. Tracked source hashes are unchanged.
Cold Nano is **37.285164 s** versus kache **26.514397 s**, while the direct prime
is 24.275025 s. No cold-build advantage is demonstrated.

[Full nine-sample timings, artifact checks and descriptive statistics](../benchmarks/harness-clang-selection-nine-samples.json).
The controlled 54-pair evidence for the adopted lookup optimization remains
valid; this longer comparison qualifies the broader kache ranking.
