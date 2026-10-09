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
unchanged. No production source change is adopted in this report.

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
An independent confirmation and warm-restore regression check remain
necessary before adopting the candidate.

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
