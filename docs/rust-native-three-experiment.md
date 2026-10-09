# Three active Rust native selection queries

The accepted Rust producer path runs four live Apple selections with at most
two active queries: the driver plan, xcrun Clang, xcrun linker and macOS SDK.
The candidate raises that cap to three, bounded by the detected CPU count.
Its atomic work queue and caller still process every query if background
scheduling fails. All driver/configuration checks and source/blob hashing
remain unchanged. The installed native Clang adapter is fixed for both modes.

This retests scheduling after native Clang CAS and overlapping Clang/SDK
selection shortened the former native critical path. It does not invalidate
the earlier evidence that two queries improved the Rust-only build profile.
A different build graph can expose different scheduling costs.

The candidate is built from an isolated source copy and passes unit tests and
the real Rust/Zig integration suite. The paired runner copies Rust binaries
to one stable wrapper path and keeps the complete Cargo environment, target,
cache and native compiler adapter fixed. Observer content hashes remain in
producer keys, so both binary modes are primed before warm measurements.
All Rust, producer and native object/archive bytes must match the first prime.
Warm measurements require exactly 167 Rust hits and 24 observed native hits.
Source/manifest hashes must remain unchanged. Four Cargo jobs, a 40 GiB cap
and half-second RSS sampling apply. No R2 traffic is included.

The experiment alternates order for 27 pairs of clean Harness release builds.
The candidate prime can reuse ordinary Rust/native entries while populating
its distinct producer keys, so it is not a separate cold-build measurement.

Candidate patch:
[rust-native-three.patch](../benchmarks/experiments/rust-native-three.patch).
Runner:
[rust_native_three_pair.py](../benchmarks/experiments/rust_native_three_pair.py).

## Result: retain two active queries

Warm medians are **2.051625 s baseline** and **2.035867 s candidate**.
The candidate wins only **13/27 pairs**. Its median paired saving is **−0.064 ms**,
mean paired saving **−22.41 ms**, paired standard deviation **111.05 ms** and
standard error **21.37 ms**. Thus the lower standalone median does not establish
a repeatable paired improvement, and the candidate is slower on average.

Every one of the 54 warm builds records 167 Rust and 24 native hits, with
8 bypasses and 3 failed compiler probes. The primes and all warm builds
match **193 exact artifact hashes**, including 24 native objects and 2 archives.
Tracked source hashes are unchanged. The first prime is 40.627 s; the second
is 4.127 s with 136 Rust hits, 31 producer misses and 24 native hits. It is
not a cold comparison between implementations.

The production source and installed binary remain unchanged at two active
Rust queries. No validation or mutable-input hashing policy is relaxed.
The candidate patch is preserved as a reproducible rejected experiment.
[Raw samples and provenance](../benchmarks/harness-rust-native-three-paired.json);
[candidate build and integration checks](../benchmarks/rust-native-three-check.json).
