# Full-content positional reads

The [producer-worker comparison](restore-worker-producers-experiment.md) did not
establish an incremental project gain. This experiment returns to the accepted
full-content digest path and changes only file reads. Production is unchanged.

The [probe](../benchmarks/experiments/digest_read.zig) compares the accepted
64 KiB buffered reader with direct positional reads into 4 KiB, 64 KiB,
256 KiB and 1 MiB buffers. Every mode opens and checks a regular file, reads
through EOF, hashes every byte with the same Zig BLAKE3 and allocates the same
canonical hex result. There is no mapping, digest memo, extra hashing worker or
change to cache keys. Positional offsets advance by the bytes actually returned,
so short reads are consumed completely. A zero-byte positional read marks EOF.

The [file report](../benchmarks/digest-read-comparison.json) records 25 runs per
mode and file, rotating order after all modes are primed. All 35 official
unkeyed BLAKE3 vectors match in every mode. All real-file digests agree;
SHA-256 and inode/size/mtime/ctime checks show inputs remain unchanged.
Internal timers include open/stat/read/hash/close/result allocation; complete
process durations are retained separately.

| File size | Accepted | Positional 64 KiB | Positional 256 KiB | Positional 1 MiB |
| --- | ---: | ---: | ---: | ---: |
| 32,551,120 bytes | 18.028 ms | 17.668 ms | 17.364 ms | 17.322 ms |
| 13,162,816 bytes | 7.277 ms | 7.124 ms | 7.027 ms | 7.019 ms |
| 10,280,952 bytes | 5.682 ms | 5.568 ms | 5.482 ms | 5.495 ms |

The 4 KiB mode is slower on each file. The 256 KiB mode reduces these large-file
medians by about 3–4%, while 1 MiB provides little additional improvement.
These are file-level measurements, not a project speedup.

A [private source patch](../benchmarks/experiments/digest-read-positional.patch)
against `6191692` replaces only `Context.digest` with the 256 KiB positional
loop. It retains regular-file refusal, all full-content checks, native selection,
locks, guards, eligibility, worker limits and output materialization. Real Rust
and Zig integration passes restore, invalidation, corruption, output isolation,
compiler failure, environment changes, escaped paths, single-flight and bypass.

The [first 27-pair Harness run](../benchmarks/harness-digest-read-paired.json)
records 2.699154 s accepted and 2.691375 s candidate medians, with 19 candidate
wins. Median paired savings are 19.83 ms, mean paired savings 29.51 ms, sample
standard deviation 106.38 ms and standard error 20.47 ms. This is a small,
uncertain result; the confirmation below supplies a separate check.

Both binaries are primed, then clean builds alternate order with one stable
wrapper path, the same environment/target/shared cache, Rust 1.97.1 and four
Cargo jobs. All 54 warm builds record 167 hits, eight bypasses and three failed
compiler probes. Every one of the 167 collected artifacts matches the first
prime; tracked source contents remain unchanged. All raw samples are retained.
The accepted prime is 39.978 s; the candidate prime is 4.325 s and reuses ordinary
entries while priming its distinct producer observer identity. These are not
cold-cache A/B results. R2 transfer is excluded. Production remains unchanged.

The [confirmation](../benchmarks/harness-digest-read-paired-confirm.json) uses
the exact same accepted and candidate binaries. It records 2.710470 s accepted
versus 2.702229 s candidate medians, with 17 wins. Median paired savings are
3.54 ms, mean paired savings 7.48 ms, sample standard deviation 43.71 ms and
standard error 8.41 ms. All 54 warm builds again have 167 hits, eight bypasses,
three failed probes and matching artifacts; tracked sources remain unchanged.
Its primes are 39.302 s and 4.447 s, with the same shared-cache qualification.

Across both sessions, candidate wins 36 of 54 pairs. Median paired savings are
5.86 ms, mean savings 18.49 ms, sample standard deviation 81.32 ms and standard
error 11.07 ms. Each session's difference of medians is about 0.3%; the combined
paired estimate remains uncertain. These results do not justify adopting the
read strategy or advertising a dependable project gain. The file-level gains
are retained as diagnostic evidence. Production keeps the accepted buffered
reader. No cold-build or cross-platform improvement is established.

The [regression/provenance record](../benchmarks/digest-read-regression.json)
identifies the exact candidate, accepted binary, probe, patch and test sources.
The 40 GiB benchmark memory cap includes the benchmark parent, Cargo and compiler
descendants. Only one project comparison ran at a time.

Reproduce the probe with stable Zig 0.17.0:

```sh
zig build-exe -O ReleaseFast -lc --dep cache \
  -Mroot=benchmarks/experiments/digest_read.zig \
  -O ReleaseFast -Mcache=src/cache.zig \
  -femit-bin=/tmp/nanocompile-digest-read
python3 benchmarks/experiments/digest_read.py /tmp/nanocompile-digest-read \
  /absolute/path/to/pinned/blake3-1.8.7 --file /absolute/path/to/blob \
  --runs 25 --output /tmp/digest-read-new.json
```

The pinned upstream checkout supplies official test vectors only; no C backend
is linked. Its commit and vector checksum are recorded in the report.
Build the private compiler candidate in a fresh isolated export:

```sh
mkdir /tmp/nanocompile-digest-read-source
git archive 6191692 src | tar -x -C /tmp/nanocompile-digest-read-source
git -C /tmp/nanocompile-digest-read-source apply \
  /absolute/path/to/nanocompile/benchmarks/experiments/digest-read-positional.patch
zig build-exe -O ReleaseFast -lc \
  /tmp/nanocompile-digest-read-source/src/main.zig \
  -femit-bin=/tmp/nanocompile-digest-read-candidate
env RUSTUP_TOOLCHAIN=1.97.1 python3 tests/integration.py \
  /tmp/nanocompile-digest-read-candidate
python3 tests/project_pair_comparison.py /absolute/path/to/accepted/nanocompile \
  /tmp/nanocompile-digest-read-candidate /absolute/path/to/harness \
  --state /tmp/digest-read-paired-new --runs 27 \
  --output /tmp/digest-read-paired-new.json
```

The subsequent [accepted Cargo timing capture](cargo-native-critical-path.md)
identifies ring's native build-script execution as a larger late-build target.
Its 1.88 s execution persists despite Rust wrapper hits; fixture probes establish
local Apple Clang CAS feasibility for the next native adapter experiment.
