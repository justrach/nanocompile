# Selected compiler resources for Rust classification reuse

This isolated candidate retains the complete compilation fingerprint and
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
remains, isolated by the changed decoder hash. The candidate is not adopted.

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
remain necessary before adoption.

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
