# Upstream file digest prototype: rejected

The [streaming microbenchmark](blake3-stream-investigation.md) suggested about
12% lower digest time on large cached blobs. A private cache prototype replaces
only `Context.digest` with that pinned upstream implementation. It preserves
regular-file checks, the 64 KiB reader, complete file reads, canonical Blake3
hex output and allocation lifetime. Key and entry hashing remain the existing
Zig implementation; all input/blob verification, locks, worker counts, schema
and eligibility checks remain intact.

The [27-pair Harness comparison](../benchmarks/harness-upstream-digest-paired.json)
does not establish a reliable project gain:

| Measure | Result |
| --- | ---: |
| Accepted warm median | 2.683367 s |
| Prototype warm median | 2.681208 s |
| Candidate wins | 17 of 27 |
| Median paired savings | 8.27 ms |
| Mean paired savings | 12.09 ms |
| Sample standard deviation | 44.68 ms |
| Standard error | 8.60 ms |

The median build difference is about 0.08%. The uncertainty and modest win
frequency do not justify adding this backend. Production retains the accepted
Zig digest; the isolated file result is not advertised as a project speedup.
This experiment does not validate a production backend on other architectures
or establish a cold-build gain.

The benchmark uses one stable wrapper path, identical environment/target and
a shared cache after priming both binaries, with rotating measurement order.
All 54 warm builds have 167 hits, eight bypasses and three failed compiler
probes. All 167 collected artifacts match the first prime. Tracked source
contents match the preceding accepted workload and remain unchanged. The
second prime reuses ordinary entries, so prime times are not cold-cache A/B
measurements. No samples are removed. R2 transfer is excluded.

Accepted executable SHA-256 is
`1f8f2a76a8bd66450fb24065a64556d74b254a946fb207cfbe7e4a83d96f0658`;
prototype SHA-256 is
`795c169664c2ed3563ae0a80210f30e4f42a38ef0607efa1dfee25b81e716c0d`.
The prototype was compiled directly with the Zig CLI from a private source
export at `360eadd`, with the upstream C sources and generated bindings. The
accepted executable uses the normal ReleaseFast build. All normal production
source and the installed executable remain unchanged.

The prototype passes all 20 unit tests and real Rust/Zig integration, including
restore, content invalidation, corruption, output isolation, escaped paths,
failure handling and single-flight behavior. Final-binary records cover
[native identity and SDK changes](../benchmarks/upstream-digest-identity-regression.json),
[native metadata restores and static refusal](../benchmarks/upstream-digest-native-regression.json),
[macro loading and Cargo flags](../benchmarks/upstream-digest-producer-regression.json),
and [executable restore, live execution and invalidation](../benchmarks/upstream-digest-executable-regression.json).
The upstream implementation also matched all 35 official unkeyed vectors in
the preceding streaming probe. These checks validate the local prototype;
they do not supply evidence of a performance gain.

To reproduce the prototype, first follow the upstream checkout and
`zig translate-c` instructions in the streaming investigation. Verify upstream
commit `f3149ec5bb5449af877ba20377a11008ff499fa2`, then export the accepted source
and apply the [private patch](../benchmarks/experiments/upstream-file-digest.patch):

```sh
mkdir /tmp/nanocompile-upstream-digest-360eadd
git archive 360eadd src | tar -x -C /tmp/nanocompile-upstream-digest-360eadd
git -C /tmp/nanocompile-upstream-digest-360eadd apply \
  /absolute/path/to/nanocompile/benchmarks/experiments/upstream-file-digest.patch
zig build-exe -O ReleaseFast -lc \
  /tmp/nanocompile-blake3-1.8.7/c/blake3.c \
  /tmp/nanocompile-blake3-1.8.7/c/blake3_dispatch.c \
  /tmp/nanocompile-blake3-1.8.7/c/blake3_portable.c \
  /tmp/nanocompile-blake3-1.8.7/c/blake3_neon.c \
  --dep blake3 -Mroot=/tmp/nanocompile-upstream-digest-360eadd/src/main.zig \
  -O ReleaseFast -Mblake3=/tmp/nanocompile-blake3-bindings.zig \
  -femit-bin=/tmp/nanocompile-upstream-digest-candidate
python3 tests/project_pair_comparison.py /absolute/path/to/accepted/nanocompile \
  /tmp/nanocompile-upstream-digest-candidate /absolute/path/to/harness \
  --state /tmp/nanocompile-upstream-digest-paired-new --runs 27 \
  --output /tmp/upstream-digest-paired-new.json
```

These commands target native AArch64 and use no new production dependency.
The upstream source checksums and provenance are retained in the streaming
report; the source delta is retained as an experiment patch.
