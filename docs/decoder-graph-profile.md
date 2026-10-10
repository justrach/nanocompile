# Remaining cold graph work after decoder scope adoption

The new diagnostic capture records **264 resolver metadata queries**, versus
2,885 in the earlier capture, a 90.8% reduction in query count. Both captures
have 5,025 inspections, 1,542 memory hits, 939 fresh digests and 1,376
within-collector digest reuses. Disk memo hits rise from 598 to 3,219.
This supports the intended classification-reuse mechanism. The separate
[controlled comparisons](decoder-scope-experiment.md) establish end-to-end
performance; diagnostic elapsed times across sessions are not an A/B result.

| Work | New count / aggregate elapsed time |
| --- | ---: |
| Graph collectors | 169 calls over 147 parent jobs; 9.046805 s |
| Resolver subprocesses | 264 queries; 3.550276 s |
| Installed-toolchain queries | 120 |
| Other artifact queries | 144 |
| Sysroot queries | 169; 2.332079 s |
| Own-artifact root queries | 169; 2.333699 s |
| Fresh resolver digests | 939; 0.536676 s |
| Classification writes | 567; 0.141891 s |
| Directory enumeration | 0.026802 s |

Counts reconcile: 5,025 = 1,542 memory hits + 3,219 disk hits + 264 queries.
The miss/save capture covers all 167 misses with 334 atomic records.
Containing save-graph time totals 9.078646 s; precompile totals 9.809371 s,
compiler execution 67.184735 s, postcompile 11.669242 s, input validation
0.534432 s and storage 0.474553 s. Times overlap across four jobs and cannot
be added to predict build time.

## Final Harness collector and selector boundary

The final Harness collector still takes **1.667204 s**, including
**114 resolver readers taking 1.518778 s**, 0.082888 s fresh hashing and
0.029567 s classification writes. It has 35 disk hits and zero toolchain
queries. Harness proto has 34 readers, including 19 toolchain readers.

Collectors retain **143 full compilation identities** but use **six decoder
identities**. Captured toolchain memos contain 147 records, 144 full hashes
and six decoder hashes. The largest existing-stamp group has 139 records.
The five smaller groups have existing caller selector files for quote,
thiserror, proc-macro2, anyhow and Harness. Global rustup settings are present
in every group. When a diagnostic grouping explicitly excludes those six
selector paths, all remaining existing stamp lists are identical.
The exact excluded paths and input file checksums are recorded in the
[identity analysis](../benchmarks/harness-decoder-graph-identities.json).
This is metadata evidence about the resource lists, not a license to omit
selection or content validation.

The source currently includes existing selector contents in the decoder
fingerprint. Readers are separately pinned to the absolute selected sysroot
before moving into private diagnostic storage. A candidate can investigate
scoping classifications to that actual selected compiler and installed
resources, while retaining every selector guard in the full compilation
identity and memo validation. It must prove reuse when selectors resolve
the same reader, invalidation when actual compiler/resources change, and
unchanged full compilation fingerprints. Adding/removing selectors must
continue to invalidate selection state. Full mutable-input hashes, directory
and competing-library guards must remain. No further production change is
adopted from this diagnostic capture.

## Capture and correctness

The isolated patch applies to `3d4dc68` and changes only compiler phase
instrumentation, resolver counters and graph records. Graph records now
include both complete and decoder identities. Stable Zig 0.17.0 builds
executable SHA-256
`413c2203389ccf9984095585fce7a74673072afb507a99b2dc5df9240ccf9502`.
Unit tests and profiling-enabled real Rust/Zig integration pass, including
stderr replay equivalence. The installed production adapter remains fixed
at SHA-256 `ff22874cb5ac7ced96e67e076f75dc65581b921fa0307cf8f0b5018e8803f521`.

Instrumented cold is 33.337961 s; warm restores are 2.111926, 2.068311 and
2.057036 s. These are diagnostic samples, not another performance gain.
All four builds match 193 Rust/producer/native artifacts. Every warm restore
has 167 Rust hits and 24 native hits. Tracked Rust sources, manifests and
lockfile remain unchanged. The dirty Harness checkout remains at
`32b41cb0bff55e3c9cbfab3012acec2b179ad199`. Builds use Rust 1.97.1,
four Cargo jobs, a 40 GiB sampled RSS cap, locked offline release library
mode, reported macro inputs and explicit Apple producer policies.

```sh
python3 benchmarks/experiments/cargo_timing_capture.py \
  /tmp/nanocompile-decoder-graph-source/zig-out/bin/nanocompile \
  /Users/rachpradhan/harness --native-clang \
  --clang-wrapper zig-out/bin/nanocompile --miss-profile \
  --state /tmp/nanocompile-decoder-graph-capture \
  --output benchmarks/harness-decoder-graph-builds.json --warm-runs 3
```

[Diagnostic patch](../benchmarks/experiments/decoder-graph-profile.patch),
[build report](../benchmarks/harness-decoder-graph-builds.json),
[all cold phases](../benchmarks/harness-decoder-graph-cold-phases.json),
[all graph records](../benchmarks/harness-decoder-graph-profile.json), and
[diagnostic test gates](../benchmarks/decoder-graph-profile-check.json)
retain provenance. Linux CI for the adopted core passed; macOS CI remains
queued at publication. The local diagnostic does not replace that check.
