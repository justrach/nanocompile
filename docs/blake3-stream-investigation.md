# Streaming BLAKE3 backend investigation

The [ordinary-hit profile](library-phase-profile.md) identifies full input and
output hashing as a substantial part of large library restores. This private
[streaming comparison](../benchmarks/blake3-stream-comparison.json) tests the
accepted Zig `Context.digest` against the
[official BLAKE3 C implementation](https://github.com/BLAKE3-team/BLAKE3/blob/1.8.7/c/README.md).
The upstream release is pinned to **1.8.7**, commit
`f3149ec5bb5449af877ba20377a11008ff499fa2`, and the report records every compiled
source/header checksum. Both implementations are built with Zig 0.17.0 in
ReleaseFast. The C backend reports ARM NEON SIMD degree four.

Both modes use the same executable, open/stat/close checks, 64 KiB streaming
reader and hex digest allocation. There is no mapping, hash memo or additional
hashing thread. Both are primed before 25 rotating process runs per file.
The internal timer includes file opening, reading, hashing, closing and result
allocation. Complete process timings are retained separately.

All **35 official unkeyed test vectors** pass for both modes, including block
and chunk boundaries, empty input and input lengths through 102,400 bytes.
Every real-file digest also agrees, and SHA-256 plus inode/size/mtime/ctime
checks verify that inputs remain unchanged.

| Real cached Harness blob | Zig median | Upstream median |
| --- | ---: | ---: |
| 32,551,120 bytes | 17.839 ms | 15.724 ms |
| 13,162,816 bytes | 7.190 ms | 6.339 ms |
| 10,280,952 bytes | 5.616 ms | 4.951 ms |

These are roughly 12% lower file-digest times on this local ARM machine.
They do not establish a project gain, cold-build improvement, or behavior on
other architectures. Production still uses the existing Zig digest and keeps
all full-content verification. Integrating a candidate requires real compiler
regressions, a controlled Harness comparison and platform validation before
adoption.

The subsequent [private cache prototype](upstream-file-digest-experiment.md)
showed no reliable project gain across 27 controlled Harness pairs and was
rejected. Production still uses the existing Zig digest.

The [Zig probe](../benchmarks/experiments/blake3_stream.zig) and
[vector/comparison driver](../benchmarks/experiments/blake3_stream.py) are
retained. Upstream source and generated bindings remain outside the project;
there is no new production dependency. The following commands reproduce the
probe on native AArch64. Run them from the nanocompile repository:

```sh
git clone --depth 1 --branch 1.8.7 https://github.com/BLAKE3-team/BLAKE3.git \
  /tmp/nanocompile-blake3-1.8.7
# Verify HEAD is f3149ec5bb5449af877ba20377a11008ff499fa2.
git -C /tmp/nanocompile-blake3-1.8.7 rev-parse HEAD
zig translate-c -lc /tmp/nanocompile-blake3-1.8.7/c/blake3.h \
  > /tmp/nanocompile-blake3-bindings.zig
zig build-exe -O ReleaseFast -lc \
  /tmp/nanocompile-blake3-1.8.7/c/blake3.c \
  /tmp/nanocompile-blake3-1.8.7/c/blake3_dispatch.c \
  /tmp/nanocompile-blake3-1.8.7/c/blake3_portable.c \
  /tmp/nanocompile-blake3-1.8.7/c/blake3_neon.c \
  --dep cache --dep blake3 -Mroot=benchmarks/experiments/blake3_stream.zig \
  -O ReleaseFast -Mcache=src/cache.zig \
  -O ReleaseFast -Mblake3=/tmp/nanocompile-blake3-bindings.zig \
  -femit-bin=/tmp/nanocompile-blake3-stream
python3 benchmarks/experiments/blake3_stream.py \
  /tmp/nanocompile-blake3-stream /tmp/nanocompile-blake3-1.8.7 \
  --file /absolute/path/to/a/large/cached/blob --runs 25 \
  --output /tmp/blake3-stream-new.json
```
