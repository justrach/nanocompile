# Native Clang diagnostic capture comparison

The installed `nanocompile clang` command normally inherits the compiler's
output descriptors. `NANOCOMPILE_CLANG_REMARKS=1` adds native cache remarks and
captures output before forwarding it, so benchmark hit counts are observable.
This experiment measures the combined cost of those two changes on actual
Harness builds. It does not isolate the cost of capture from the cost of remarks.

The runner uses one unchanged installed binary and one stable shell launcher.
Cargo's complete environment, Rust wrapper, cache and target paths remain fixed.
The launcher reads a mode control file and sets the remarks option only for the
native compiler child. Both modes use Apple's inline dependency scanner and
compiler-owned CAS. They are primed before 27 pairs of clean release builds,
with order alternating in each pair, four Cargo jobs and a 40 GiB memory cap.
The shell launcher and this run's paths differ from the earlier direct/kache
comparison; these absolute durations do not establish a new kache ranking.

Every Rust library, macro dylib, build-script executable, native object and native
archive must match the first prime's bytes. Tracked Rust sources, manifests and
lockfiles must remain unchanged. Warm Rust hits and native invocation counts
are checked in both modes. Remarks mode additionally requires observed native
hits. Streaming mode deliberately does not report or assert unobserved hit counts.
No R2 traffic is included. The second prime reuses the first mode's shared caches
and is not a separate cold-build measurement.

Runner: [`clang_remarks_pair.py`](../benchmarks/experiments/clang_remarks_pair.py).

## Result

Remarks/capture median: **2.239760 s**. Streaming median: **2.258781 s**.
Streaming won **12 of 27** pairs. Its median paired saving was **−8.64 ms**,
mean **−5.82 ms**, paired standard deviation **65.14 ms**, and standard error
**12.54 ms**. This run does not demonstrate a repeatable warm-build gain from
removing remarks/capture. No production change is adopted from this experiment.
Normal streaming remains the default because it preserves inherited output
descriptors; remarks remain opt-in for observed cache outcomes.

All 54 warm builds recorded 167 Rust hits, 24 native compiler invocations,
8 bypasses and 3 failed compiler probes. All 27 remarks builds recorded 24
native cache hits. The two primes and all warm builds matched **193 unchanged
artifact bytes**, including 24 native objects and 2 archives. Tracked source
hashes remained unchanged. The first prime was 40.263 s; the second reused
caches and took 2.356 s. These are local Apple M3 Ultra / Apple Clang 21 /
Rust 1.97.1 results with the explicit reported-input and producer policies.

Raw samples, artifact hashes, source and executable provenance:
[`harness-clang-remarks-paired.json`](../benchmarks/harness-clang-remarks-paired.json).

The next candidate is overlapping the live default Clang and SDK selection
queries. The queries must still execute on each eligible job; this result
provides no reason to weaken input hashing or memoize mutable project inputs.
