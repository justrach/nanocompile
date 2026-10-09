# Cold graph discovery: metadata reader launches

The detailed capture attributes **83.821477 aggregate seconds** to
**2,885 metadata reader launches** inside dependency classification.
Another 169 sysroot queries and 169 own-root metadata queries take
4.999803 and 4.927202 aggregate seconds respectively. Resolver fresh
content hashing takes 0.842309 s; directory enumeration takes 0.068624 s.
Reducing content validation is therefore the wrong target for this capture.

| Measured work | Aggregate elapsed time |
| --- | ---: |
| Complete graph collectors | 97.350723 s |
| Resolver metadata subprocesses | 83.821477 s |
| Sysroot subprocesses | 4.999803 s |
| Own-artifact metadata subprocesses | 4.927202 s |
| Fresh resolver content digests | 0.842309 s |
| Classification memo writes | 2.301846 s |
| Directory enumeration | 0.068624 s |

The 169 collector calls belong to 147 successful compiler jobs. Producer
jobs can collect more than one dependency artifact; other successful jobs
need no collector. The separate miss/save profile still covers **all 167
cold misses**. Resolver counters reconcile exactly:

- 5,025 inspections = 1,542 memory hits + 598 disk memo hits + 2,885 queries.
- 1,989 queries read installed toolchain libraries; 896 read other artifacts.
- 939 fresh digests and 1,376 within-collector digest reuses.
- 3,188 classification memo writes, including own-artifact classifications.

All timings are per-job elapsed durations overlapping across four Cargo
jobs. They are cost attribution, not additive build time or promised savings.
Remaining collector time includes matching, guards, metadata parsing, memo
reads and other uninstrumented work. The containing save graph phase totals
97.436128 s; its small difference includes collector call overhead and
diagnostic persistence.

The final Harness collector spends 1.783655 s total, including 1.623644 s
in 114 resolver subprocesses, 0.086616 s in fresh content digests, and
0.000327 s enumerating directories. It records 35 disk memo hits. Several
registry dependency collectors record zero disk memo hits despite reading
previously compiled dependencies; tower-http launches 77 readers, reqwest
115, and hyper-rustls 75.

## Identity scope observation

Collectors observe **143 complete compiler identities**. Inspection of the
captured toolchain memo directory finds 147 memos containing 144 distinct
hashes. **139 memos have identical existing stamp lists but 139 different
identity hashes**. The other eight memos form five existing-stamp groups.
Across all memos there are 297 distinct absent paths: 146 named
`rust-toolchain.toml` and 151 named `rust-toolchain`.

The source explains a plausible reuse barrier: `identity.fingerprint`
includes selector paths in its stamp list and hashes each path even when
absent. Those paths vary with Cargo's caller directory.
`rust_metadata.Resolver.location` then scopes classification memos by that
complete compiler identity. Different directory selection guards can
therefore partition the same artifact classification into different memo
namespaces. This inference is supported by the counters and memo contents;
stamp equivalence alone does not establish that every decoder is interchangeable.

The next candidate should retain the complete compilation identity and
negative selector guards, while deriving a separate, validated decoder
identity for content-addressed classification memos. It must preserve
compiler/resource content checks, tool changes and existing selector-file
changes, full mutable-artifact hashing, and competing-library/directory
guards. No key normalization, memo scope change, or production optimization
is adopted in this diagnostic turn.

## Capture and correctness

The isolated patch applies to `6af7702` and changes only
`src/compiler.zig`, `src/rust_dependencies.zig`, and `src/rust_metadata.zig`.
It retains the production query arguments, memo namespaces and guards.
Stable Zig 0.17.0 builds diagnostic executable SHA-256
`7a1090c0e2ce37b71dcb40d87c6bbcdd060b8590b7053dbd53125625a39fb98b`.
Unit tests and profiling-enabled real Rust/Zig integration pass, including
stderr replay equivalence. Phase records use atomic files behind the
explicit `NANOCOMPILE_MISS_PROFILE=1` switch.

The instrumented prime takes **68.672640 s**; three warm restores take
**2.277612, 2.329089, and 2.246521 s**. A distinct executable/observer,
instrumentation, environment switch, new state and Cargo `--timings` mean
these are diagnostic samples. They neither replace the uninstrumented
comparison nor establish a throughput regression or improvement.
All four builds match 193 artifacts; each warm build records 167 Rust hits
and 24 native hits. Tracked Rust sources, manifests and lockfile stay
unchanged. The installed integrated-cc1 adapter remains the fixed native
Clang wrapper. Builds use Rust 1.97.1, four jobs, a 40 GiB sampled RSS cap,
locked offline release library mode and reported producer policies.

```sh
python3 benchmarks/experiments/cargo_timing_capture.py \
  /tmp/nanocompile-graph-detail-source/zig-out/bin/nanocompile \
  /Users/rachpradhan/harness --native-clang \
  --clang-wrapper zig-out/bin/nanocompile --miss-profile \
  --state /tmp/nanocompile-graph-detail-capture \
  --output benchmarks/harness-graph-detail-builds.json --warm-runs 3
```

[Diagnostic patch](../benchmarks/experiments/graph-detail-profile.patch),
[all graph records](../benchmarks/harness-graph-detail-profile.json),
[all miss/save phases](../benchmarks/harness-graph-detail-cold-phases.json),
[identity memo observations](../benchmarks/harness-graph-detail-identities.json),
[build/source/artifact evidence](../benchmarks/harness-graph-detail-builds.json), and
[build/check provenance](../benchmarks/graph-detail-profile-check.json)
retain the complete result. Summary scripts and individual record file
digests are included with the datasets.
