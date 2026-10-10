# Selected compiler resources for Rust classification reuse

The adopted change retains the complete compilation fingerprint and
validates every original selector/resource stamp. It changes only the
classification decoder fingerprint: Rust selector paths are excluded after
selection, while the native compiler/proxy executable, version output and
all selected installed resources remain included by path and content hash.
Zig's resource membership stays unchanged. Existing and absent selectors
remain in full compilation hashes and all memo validation. Mutable source
and artifact hashing, directory guards and competing-library checks remain.

The patch applies to `b565468`. Toolchain memos move from schema 4 to 5;
old memos are re-fingerprinted. The decoder hash domain becomes
`metadata-decoder-selected-resources-v2`. Classification namespace v2
remains, isolated by the changed decoder hash. The change is adopted after the confirmation and correctness gates below.

Stable Zig 0.17.0 builds candidate SHA-256
`79f99506ec623089647d8bbdf623be56215ec6bc0e9b5413217bc4361de2fe65`.
Baseline/fixed native adapter SHA-256 is
`ff22874cb5ac7ced96e67e076f75dc65581b921fa0307cf8f0b5018e8803f521`.
Unit tests and real Rust/Zig integration pass. The extended real-compiler
fixture verifies:

- Distinct caller full compilation identities with one resource decoder.
- Full compilation fingerprint equality against the accepted baseline.
- Reuse of 19 toolchain classifications without rewriting.
- Selector addition/removal affects full identity while unchanged selected
  resources preserve decoder reuse.
- Switching actual Rust 1.97.1 to installed 1.98.1 changes decoder identity.
- With no environment override, a caller selector that switches compilers
  changes both full and decoder identities.
- Returning to the original compiler reuses its unchanged identities.

The scope fixture uses an isolated temporary source/cache and never changes
installed compiler files or user toolchain settings. The switched compiler
is Rust 1.98.1, commit `48a229ceaefd4985c50990b14116b6d856af0985`.
[Scope report](../benchmarks/selected-decoder-scope-check.json) and
[correctness gates](../benchmarks/selected-decoder-checks.json) retain evidence.

## Cold measurement

Six alternating cold pairs use the actual dirty Harness checkout at
`32b41cb0bff55e3c9cbfab3012acec2b179ad199`. Both complete cache and target
are removed before every build; Rust wrappers use one stable path and the
accepted native adapter remains fixed. Full environment and paths are
constant, with Rust 1.97.1, four Cargo jobs, a 40 GiB sampled RSS cap,
locked offline release library mode and explicit reported macro and Apple
producer policies. Observer binary content hashes remain part of producer
keys. Every build must have 167 Rust misses, 24 native misses and zero hits,
and match all 193 artifacts against the first cold build.
The six-pair result has baseline median **31.150235 s** and candidate
median **29.524911 s**, a **5.22%** reduction between medians. Candidate
wins **5/6 pairs**. Mean paired saving is 1.777745 s, median paired saving
1.804536 s, sample SD 1.665248 s and descriptive SE 0.679835 s. All twelve
builds match 193 artifacts and retain the required cold miss counts.
Tracked Rust sources, manifests and lockfile are unchanged. Baseline spans
31.046563–33.719442 s; candidate spans 29.143813–31.527080 s. The final
candidate is 0.480517 s slower than its paired baseline; it is retained.
This first batch favors the candidate but requires independent confirmation.

The raw field `artifacts_match_first_prime` refers to that first cold build;
this runner does not have a warm or priming phase.

```sh
python3 benchmarks/experiments/selected_decoder_cold_pair.py \
  zig-out/bin/nanocompile \
  /tmp/nanocompile-selected-decoder-source/zig-out/bin/nanocompile \
  /Users/rachpradhan/harness --clang-wrapper zig-out/bin/nanocompile \
  --state /tmp/nanocompile-selected-decoder-cold-paired \
  --output benchmarks/harness-selected-decoder-cold-paired.json --runs 6 --jobs 4
```

[Candidate source patch](../benchmarks/experiments/selected-decoder.patch)
and [all cold builds](../benchmarks/harness-selected-decoder-cold-paired.json)
retain provenance. This batch compares against the accepted Nano version,
not kache; it cannot establish a cross-machine advantage. Independent
confirmation, a controlled warm comparison and broader producer/native gates
are recorded below.

## Candidate warm correctness check

A fresh diagnostic Cargo-timing capture primes this binary and then deletes
target outputs for three restores. All four builds match 193 artifacts;
all warm builds have 167 Rust hits and 24 native hits, with unchanged
tracked sources. The prime takes 31.628282 s and restores take 2.202465,
2.159381 and 2.159109 s. Different wrapper/state paths and Cargo `--timings`
make these correctness/diagnostic samples, not a before/after speedup.
[Warm correctness report](../benchmarks/harness-selected-decoder-warm-check.json).

The accepted schema-4 decoder version, source `bb55f97`, now passes both
[Linux and macOS CI](https://github.com/justrach/nanocompile/actions/runs/38007374944).
Both hosted scope fixtures reuse 19 classifications and verify selector
invalidation under that version's contract. This validates the accepted
version, not the isolated schema-5 candidate.
[Hosted CI evidence](../benchmarks/decoder-ci-validation.json).

## Independent cold confirmation

Three new alternating cold pairs produce baseline median **32.316619 s** and
candidate median **29.180211 s** (9.71% lower). Candidate wins 3/3
pairs, or 8/9 across both batches. Mean paired saving is 2.751199 s, median
3.136408 s, sample SD 0.845434 s and descriptive SE 0.488112 s. All six builds
match 193 artifacts, have 167 Rust and 24 native misses with no hits, and
retain unchanged tracked source hashes.
[Independent raw samples](../benchmarks/harness-selected-decoder-cold-confirm.json).

The warm A/B runner separately primes each schema's cache, moving it to the
same active cache path before its turn. This preserves paths/environment
while avoiding incompatible toolchain schemas overwriting each other.
The native adapter stays fixed and producer observer binary digests remain
part of keys. It requires 167 Rust hits, 24 native hits and matching artifacts.

## Controlled warm comparison

The 27-pair warm batch produces medians **2.060624 s baseline** and
**2.058241 s candidate**, with 16/27 candidate wins. Mean paired saving is
6.911 ms, median 4.376 ms, sample SD 35.342 ms and descriptive SE 6.802 ms.
There is no reliable warm speedup claim; the batch shows no convincing
regression. All 54 warm builds have 167 Rust hits and 24 native hits. Those
builds and both primes match 193 artifacts, and tracked sources are unchanged.
[All warm samples](../benchmarks/harness-selected-decoder-warm-paired.json).

## Adoption and correctness gates

The selected-resource source is adopted after both cold batches and the warm
comparison. The rebuilt workspace executable has SHA-256
`ce7204f1e4bd5968d5e40d7dd3c9496c2a4b77b4344f718718108911b4e57a3c`.
Its identity source matches the measured isolated candidate byte-for-byte.
Unit tests, real Rust/Zig integration, native identity, native metadata,
static-native inputs, Cargo-flag macro producers, executable producers and
selected-resource scope checks all pass on the rebuilt binary.
[Adoption gate results](../benchmarks/selected-decoder-adoption-checks.json).

The scope fixture also passes without a baseline binary, matching the new
CI invocation. CI installs Rust 1.97.1 and 1.98.1, retaining 1.97.1 as default,
and runs active-selector/compiler-switch tests on Linux and macOS. The
previous schema-4 accepted version's green CI remains separate; the new
source still needs its own hosted result.
[Local CI-mode fixture check](../benchmarks/selected-decoder-ci-mode-check.json).
