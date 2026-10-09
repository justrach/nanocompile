# Watched digest prototype: rejected

A persistent Zig worker can avoid repeated file reads while keeping a vnode
watch and checking both the held descriptor and current pathname. This
experiment tested that model as a possible way to reduce warm restore costs.
**It is unsafe for source or artifact validation and is rejected.** No compiler
cache code, installed binary, eligibility gate or default validation changed.

The decisive counterexample keeps a writable mmap open across registration
and digest reuse. It dirties a page before the initial hash, then modifies
that already-dirty page again without flushing or unmapping it. On this local
APFS machine, the second write changes bytes without changing the checked
metadata or producing a new vnode event. The worker reuses the old BLAKE3
digest; a direct full read produces a different digest. No hostile metadata
forgery, privilege or external filesystem is involved.

Both [the three-blob report](../benchmarks/watch-hash-probe.json) and
[the Harness graph report](../benchmarks/watch-hash-harness-graph.json) reproduce
the failure under `mmap_counterexample`: `stale_digest_observed=true`,
`same_metadata=true`, `after_write_reused=true`, and zero invalidations.
The driver asserts that the failure reproduces; its successful exit means
the rejected model was reproduced, not that the worker is safe.

Sixteen ordinary checks succeed: unchanged reuse, canonical empty digest,
preserved-mtime writes, overwrite/restore, flushed mmap changes, atomic
replacement, rename/delete/recreation, hardlink mutation, symlink retargeting,
truncation, attribute changes, descriptor eviction/recycling, invalid file
requests, concurrent initial-read mutation, lost-queue fallback and malformed
frames. Those checks did not cover the live already-dirty mapping until the
counterexample was added. Passing them cannot establish the desired contract.

The [Zig prototype](../benchmarks/experiments/watch_hash.zig) registers
`EVFILT_VNODE` before reading the same descriptor, holds it open, polls before
reuse, checks device/inode/size/mode/link count/flags/generation/mtime/ctime,
and verifies the pathname still names the same state. Unique event tokens
prevent confusion after descriptor reuse. It uses bounded in-memory entries,
bounded JSON batches through private inherited pipes, and fresh full reads
after queue loss or on unsupported filesystems. A
[small SDK shim](../benchmarks/experiments/watch_hash_fs.c) restricts memo
creation to local APFS using the actual `statfs` ABI. There is no disk digest
memo, socket endpoint, production integration or new runtime dependency.

[Apple's kqueue manual](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/kqueue.2.html)
documents vnode write/attribute/rename/delete notifications and event
aggregation. The measured mmap counterexample demonstrates that those events
plus the checked metadata do not establish that every later byte change will
be observed. Merely holding a descriptor or polling more frequently cannot
recover an event that was never delivered.

The unmodified-file timings below are diagnostic only. They use the same
persistent executable, alternate `full` and `watch` batch order for 25 pairs,
and include private pipe transfer in the medians. Full mode reads every byte
serially with canonical Zig BLAKE3 and a 64 KiB buffer. This is **not** the
production restore's four-worker input path, and no project build was run.

| Batch | Bytes | Full-read median | Unsafe watched-reuse median |
| --- | ---: | ---: | ---: |
| Three actual Harness cache blobs | 55,994,888 | 32.007 ms | 0.146 ms |
| 303 unique regular inputs/output blobs from a Harness entry | 33,289,827 | 24.060 ms | 8.492 ms |

The graph contains duplicate recorded dependencies; the driver deduplicates
paths before measurement. Directory membership, native-directory contents,
symlink/negative lookup guards, compiler identities, locks, materialization,
process launch, R2 transport and Cargo scheduling are outside these timings.
The reports omit private paths and arguments, retain every sample, and record
source/executable SHA-256, file sizes and file content SHA-256.

Reproduce on local APFS with stable Zig 0.17.0 and the macOS SDK:

```sh
zig build-exe -O ReleaseFast -lc \
  benchmarks/experiments/watch_hash_fs.c \
  benchmarks/experiments/watch_hash.zig \
  -femit-bin=/tmp/nanocompile-watch-hash
python3 benchmarks/experiments/watch_hash.py /tmp/nanocompile-watch-hash \
  --output /tmp/watch-hash-reproduced.json
```

The command above reproduces ordinary checks and the rejection without any
Harness checkout. Add repeated `--file /absolute/path/to/file` options for
your own unmodified-file timing batch. To inspect an existing compiler entry,
use `--entry /absolute/path/to/cache/entries/KEY`,
`--cache-root /absolute/path/to/cache`, and `--capacity 4096`; the driver reads
regular dependencies and stored output blobs from that local manifest.
This is a measurement utility, not an entry validator or cache transport.
Default descriptor capacity is 256, configurable to at most 4096; memory and
descriptors are released on eviction, reset, queue loss and worker exit.

The next performance work should preserve complete source/blob verification.
The existing ordinary-hit profile separately identifies process launch and
per-invocation work. A shared execution service could amortize that work while
still reading full contents, but it needs an actual implementation, request
isolation, failure tests and a controlled Harness comparison before any
speedup or adoption claim.
