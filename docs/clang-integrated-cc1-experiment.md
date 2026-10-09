# Integrated Clang cc1 experiment

The first 27-pair batch reduces median warm-build time from
**1.988609 to 1.886351 seconds (5.14%)**, with the candidate winning
**25/27 pairs**. Mean paired saving is **87.862 ms**, paired median saving
**97.462 ms**, and descriptive standard error **10.276 ms**. The two losing
pairs and all slower samples remain in the dataset.

A fresh 27-pair confirmation reduces median time from **2.024719 to
1.911030 seconds (5.62%)**, winning **26/27 pairs**. Mean paired saving is
**118.917 ms**, paired median saving **102.088 ms**, with descriptive
standard error **19.036 ms**. All 56 confirmation builds match their first prime across
193 artifacts, with unchanged tracked sources and 167 Rust/24 native warm
hits. Across the two batches the candidate wins **51/54 pairs**. The
confirmation uses a separate target/cache state, the same binaries and
protocol, and no phase instrumentation. This supports adopting the flag
for eligible native-CAS commands. Caller policy, live selection and input
validation remain intact.

All 56 builds, including both primes and 54 warm runs, match **193 exact
artifacts**: Rust/producer artifacts plus 24 native objects and two archives.
Each warm run records 167 Rust hits, 24 native hits, eight bypasses and three
failed compiler probes. Tracked sources remain unchanged. The baseline
prime takes 39.504294 seconds; the candidate prime reuses the shared cache
and takes 1.970103 seconds. These primes do not establish a cold speedup.

The native phase profile attributes most measured adapter time to the Clang
process. The captured driver `-###` command reports separate cc1 execution
by default and `(in-process)` when explicitly passed `-fintegrated-cc1`.
The candidate adds only that flag to eligible native CAS commands, before
caller arguments. It leaves unsupported jobs and passthrough commands alone.
Caller arguments can override the execution policy.

The isolated source is an archive of `354a3de` plus
[this patch](../benchmarks/experiments/clang-integrated-cc1.patch), built with
stable Zig 0.17.0. The candidate is distinct from the diagnostic binary and
contains no phase instrumentation. All native regression checks pass,
including preserved-mtime and dirty mmap input invalidation, inherited-I/O
mode, opaque compiler passthrough, cache clearing and compiler failure.

The paired protocol keeps the accepted Rust wrapper fixed. Two native
binaries are copied to one stable CC path, with the cc-rs known-wrapper
setting. Complete Cargo environment, target path and shared cache remain
fixed, including producer observer identity. Both modes keep live default
compiler and SDK lookups, inline Clang CAS and native hit remarks. No mutable
input or artifact content hashing is weakened.

Each pair reverses its order relative to the previous pair. Builds use
Harness `harness-adapters`, Rust 1.97.1, four Cargo jobs, locked offline
release library mode, disabled incremental compilation, and explicit
reported macro input and producer policies. A 40 GiB sampled RSS cap and
one-hour timeout apply. All outputs are checked against the first prime,
including Rust libraries, macro dylibs, producer executables, native objects
and archives. Tracked Rust/manifest/lockfile hashes are checked before and
after the run. The second prime can reuse the shared CAS and is not an
independent cold-build comparison.

```sh
python3 benchmarks/experiments/clang_integrated_pair.py \
  zig-out/bin/nanocompile \
  /tmp/nanocompile-clang-integrated-source/zig-out/bin/nanocompile \
  /Users/rachpradhan/harness --rust-wrapper zig-out/bin/nanocompile \
  --state /tmp/nanocompile-clang-integrated-paired \
  --output benchmarks/harness-clang-integrated-paired.json \
  --runs 27 --jobs 4
```

[Paired runner](../benchmarks/experiments/clang_integrated_pair.py),
[source/binary provenance and native checks](../benchmarks/clang-integrated-check.json),
and [raw paired builds](../benchmarks/harness-clang-integrated-paired.json)
retain the evidence. [Full confirmation data](../benchmarks/harness-clang-integrated-confirm.json)
records the separate batch. This is a local paired evaluation. A subsequent
[nine-sample complete comparison](clang-integrated-nine-samples.md) measures
the adopted version against direct Cargo and kache separately; these local
results do not establish a cross-machine advantage.

Installed source matches the tested candidate exactly.
[Installed build/check provenance](../benchmarks/clang-integrated-installed-check.json),
[native replay/invalidation checks](../benchmarks/clang-integrated-installed-regression.json),
and [live-selection overlap/failure checks](../benchmarks/clang-integrated-installed-selection.json)
record the adopted executable. Unit tests and real Rust/Zig integration also pass.
