# Sharing Rust decoder classifications across callers

This isolated candidate keeps the full compilation fingerprint, including
absent selector paths, and adds a separate decoder fingerprint for Rust
artifact classification. The decoder fingerprint includes version output
and every existing compiler, selector and installed-resource stamp and
content digest. Toolchain memo reads and writes still validate all original
stamps, including absent paths. Mutable artifacts still receive full content
hashes; dependency snapshots retain directory and competing-library guards.

The classification memo namespace moves to version 2 and toolchain memos to
schema 4. Old toolchain memos are re-fingerprinted. Existing selector files
remain part of both identities. The full compilation hash computation is
unchanged. The candidate is now adopted after the independent confirmation and correctness gates below.

The patch applies to `c21b5b4`. Stable Zig 0.17.0 builds candidate SHA-256
`314613d94792178dc9947953cdd2432f4787592d73435e4eb3378c478dfc85d4`.
The accepted baseline and fixed native Clang adapter have SHA-256
`f03c9570446371873565886f4e6ba980629547f99284437240c13a2003200be1`.
Candidate unit tests and real Rust/Zig integration pass.

The scope fixture uses real Rust 1.97.1 in two caller directories with one
shared cache. It checks that full compilation identities remain distinct,
that identical present toolchain state shares a decoder identity, and that
19 installed-toolchain classifications are reused without rewriting.
Adding a caller selector changes both identities.
The same-caller baseline comparison also verifies byte-for-byte equality
of the full compilation fingerprint before and after the candidate.

## Cold comparison

Six alternating pairs build the actual dirty Harness checkout at
`32b41cb0bff55e3c9cbfab3012acec2b179ad199`, with four Cargo jobs,
Rust 1.97.1, locked offline release library mode, and a 40 GiB sampled RSS
cap. Before every build both the complete cache and Cargo target are removed.
Rust wrappers use one stable path and the native Clang adapter stays fixed.
Explicit reported macro and executable producer policies stay identical.
Each wrapper's content hash remains part of producer observer keys.

The candidate wins **6/6 pairs**. Baseline median is **40.728340 s** and
candidate median is **31.935735 s**, a **21.59%** reduction between
medians. Mean paired saving is 9.173137 s, median paired saving 9.332384 s,
with paired sample SD 3.276452 s and descriptive SE 1.337606 s. All twelve
builds have 167 Rust misses, 24 native misses and zero hits in both caches;
all 193 artifacts match the first cold build. Tracked Rust sources,
manifests and lockfile are unchanged. Baseline samples span 39.151926–44.953159 s;
candidate samples span 30.192480–35.056726 s. No samples are discarded.

The raw report's `artifacts_match_first_prime` field means matching the
first **cold build**; this runner has no priming or warm phase.
Results measure this host and checkout, not cross-machine performance.
Independent cold confirmation, a 27-pair warm check and adoption gates are recorded below.

```sh
python3 benchmarks/experiments/decoder_cold_pair.py \
  zig-out/bin/nanocompile \
  /tmp/nanocompile-decoder-scope-source/zig-out/bin/nanocompile \
  /Users/rachpradhan/harness --clang-wrapper zig-out/bin/nanocompile \
  --state /tmp/nanocompile-decoder-cold-paired \
  --output benchmarks/harness-decoder-cold-paired.json --runs 6 --jobs 4
```

See [candidate patch](../benchmarks/experiments/decoder-scope.patch),
[raw build report](../benchmarks/harness-decoder-cold-paired.json), and
[scope regression report](../benchmarks/decoder-scope-check.json).

## Independent cold confirmation

Three new alternating pairs, using a new empty state directory and the same
runner, produce baseline median **41.487079 s** and candidate median
**32.063746 s** (22.71% lower). The candidate wins 3/3 pairs, or 9/9
across both batches. Mean paired saving is 11.549460 s with sample SD
3.989338 s and descriptive SE 2.303245 s. All six builds match 193
artifacts and record 167 Rust misses, 24 native misses and no hits.
Tracked sources remain unchanged. The 52.692516-second baseline outlier
is retained, as is its 36.540995-second candidate counterpart.
This confirms a local cold-build gain against the accepted implementation;
it does not establish a comparison against kache or across machines.
[Confirmation raw report](../benchmarks/harness-decoder-cold-confirm.json).

The warm comparison primes independent caches for each binary. Before each
build it moves that mode's cache to the same active path, then moves it back
after validation. This keeps all environment and target/cache paths fixed
and prevents schema 3 and schema 4 toolchain memos from overwriting one
another. Observer binary digests remain in producer keys. The warm runner
requires 167 Rust hits and 24 native hits, and compares all 193 artifacts.

## Warm regression check and adoption

The 27-pair warm batch measures baseline median **2.396014 s** and candidate
median **2.301408 s**. Candidate wins 17/27 pairs. Mean paired saving is
63.746 ms, median 47.376 ms, sample SD 274.846 ms and descriptive SE
52.894 ms. This variable batch does not establish a reliable warm speedup;
it shows no convincing warm regression. All 54 warm builds have 167 Rust
hits and 24 native hits. Those builds and both primes match the batch's
193 reference artifacts; tracked sources are unchanged.
[All warm samples](../benchmarks/harness-decoder-warm-paired.json).

The source patch is adopted, without the diagnostic profiling patches.
The locally rebuilt executable has SHA-256
`ff22874cb5ac7ced96e67e076f75dc65581b921fa0307cf8f0b5018e8803f521`;
it is built in the workspace from source identical to the measured isolated
candidate, with a different executable checksum. Unit tests, real Rust/Zig integration, native identity, native
metadata, static-native inputs, Cargo-flag macro producers, executable
producers and the extended scope fixture all pass on this binary.
The fixture also checks selector removal and unchanged full compilation
fingerprints against the accepted baseline. CI runs the scope fixture on
Linux and macOS. Toolchain schema 4 and classification namespace v2
rebuild old memos; compilation keys retain the original full fingerprint.
[Adoption correctness gates](../benchmarks/decoder-adoption-checks.json).
