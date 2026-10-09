# Cargo native compilation through Apple Clang CAS

The [accepted timing capture](cargo-native-critical-path.md) found that ring's
build-script execution takes 1.88 s in each clean warm Harness build. This
experiment keeps the build scripts live and delegates eligible native compile
jobs to Apple Clang's dependency scanner and compilation cache. Normal production
source and the installed Nano executable are unchanged.

The [Zig adapter](../benchmarks/experiments/clang_cas_adapter.zig) is compiled
in two modes from the same source: scanner with cache replay disabled, and
scanner with cache replay enabled. Both invoke the
same explicitly selected Apple Clang and selected macOS SDK. Caller-supplied
sysroot flags win; otherwise SDKROOT or the recorded SDK is passed explicitly.
This matters because cc-rs passes an Apple target to an unfamiliar compiler
pathname, and that invocation otherwise failed to find TargetConditionals.h.
The corrected fixture includes that header and the explicit arm64 Apple target.

Only `-c` invocations receive the cache options. Preprocessing, assembly-output,
dependency-only, version, verbose driver-plan and internal cc1/cc1as requests
pass through. Both adapters use the same cache remark option on compile jobs.
Both modes add inline dependency scanning, a supplied absolute CAS path
and cc1 compile-job caching; the baseline adds `-fcache-disable-replay`. Missing CAS configuration leaves compilation on
the normal path. The compiler owns dependency discovery, keys and replay;
there is no opaque cache of build-script execution or side effects.

The [adapter fixture checks](../benchmarks/clang-cas-adapter-check.json) pass:
C with SDK/local headers and preprocessed assembly report cold misses and warm
hits, with exact replay-disabled/cold/warm object bytes. A same-size header change with
preserved mtime causes a miss and matches fresh replay-disabled output.
An unflushed write through an already-dirty header mmap also causes a miss and
matching changed output, despite unchanged inode/size/mtime/ctime on the second
write. Stdin compilation passes through with matching input and object bytes. Compiler failure
produces no object; version and preprocessing probes pass through. These are
local arm64 Apple Clang checks, not exhaustive native cache validation.

## Controlled Harness replay comparison

The [27-pair report](../benchmarks/harness-clang-cas-paired.json) compares
replay disabled with replay enabled, using identical inline dependency scanning
in both controls. It rotates build order with one stable `CC` adapter path,
one unchanged accepted Rust wrapper, identical environment/target/shared caches,
Rust 1.97.1 and four Cargo jobs. All raw samples remain in the report. The
40 GiB process-tree cap includes the benchmark parent, Cargo and its descendants.
Tracked source contents remain unchanged in the existing dirty Harness checkout.

| Measure | Result |
| --- | ---: |
| Replay-disabled warm median | 2.807630 s |
| Replay-enabled warm median | 1.808241 s |
| Difference of medians | 0.999389 s (35.60%) |
| Candidate wins | 27 / 27 |
| Median paired savings | 991.45 ms |
| Mean paired savings | 994.15 ms |
| Sample standard deviation | 54.92 ms |
| Standard error | 10.57 ms |

Every warm build records 167 Rust hits, eight bypasses and three failed compiler
probes. Every baseline warm build records 24 native replay skips; every candidate
warm build records 24 native hits with no misses or skips. All **193 unmodified
artifacts** match the first prime: 167 Rust libraries/producers plus 24 native
objects and two archives. No debug stripping or artifact normalization is used
in this validation. Build scripts continue to execute normally.

The baseline prime takes 39.950 s. The candidate prime takes 1.843 s and already
has 167 Rust hits and 24 native hits: the replay-disabled baseline populated
the shared compiler cache while executing the compilation jobs. It is not a
candidate cold result. R2 transfer is excluded. This is a substantial gain from
native replay on this local workload, but it is a controlled scanner/replay
comparison, not a refreshed default-Nano/kache comparison. The experimental
adapter is not installed through the normal build or CLI. Further integration
and a new three-way project comparison are needed before updating production
benchmark claims.

The initial passthrough-versus-scanner comparison stopped at an artifact
mismatch before collecting warm performance samples. A [debug fixture](../benchmarks/clang-cas-debug-difference.json)
reproduces the scanner omitting `DW_AT_comp_dir`: normal and scanner objects
differ, while debug-stripped objects match. This finding does not justify
ignoring arbitrary artifact differences. The final comparison uses the same
scanner and debug representation in both modes, and checks complete, unmodified
artifact bytes across every build. It isolates replay rather than comparing
native CAS against unmodified default Clang. The compiler's scanner changes
debug metadata; this experiment does not promise transparent preservation of
normal Clang's debug representation.

Compile jobs capture bounded stdout/stderr identically in both adapters and
forward those bytes to the caller. A private per-process receipt records only
cache hit/miss/skipped booleans, replay mode and exit code. This is necessary
because ring disables cc-rs's Cargo metadata output, suppressing cache remarks
from the Cargo log. Receipts prove actual replay use; they contain no compiler
arguments or environment values. Requests from stdin bypass this experimental
capture/cache path and retain the inherited-input passthrough.

## Reproduction

Use stable Zig 0.17.0. Generate two config modules with the same selected Clang
and SDK, changing only `enabled`:

```sh
python3 - <<'PY'
import json, subprocess
from pathlib import Path
clang = subprocess.check_output(['xcrun', '--find', 'clang'], text=True).strip()
sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
for name, enabled in [('passthrough', False), ('enabled', True)]:
    Path('/tmp/nano-clang-' + name + '-config.zig').write_text(
        'pub const enabled = ' + str(enabled).lower() + ';\n' +
        'pub const clang = ' + json.dumps(clang) + ';\n' +
        'pub const sdk = ' + json.dumps(sdk) + ';\n')
PY
zig build-exe -O ReleaseFast -lc --dep config \
  -Mroot=benchmarks/experiments/clang_cas_adapter.zig \
  -Mconfig=/tmp/nano-clang-passthrough-config.zig \
  -femit-bin=/tmp/nano-clang-passthrough
zig build-exe -O ReleaseFast -lc --dep config \
  -Mroot=benchmarks/experiments/clang_cas_adapter.zig \
  -Mconfig=/tmp/nano-clang-enabled-config.zig \
  -femit-bin=/tmp/nano-clang-cas
python3 benchmarks/experiments/clang_cas_adapter_check.py \
  /tmp/nano-clang-passthrough /tmp/nano-clang-cas \
  --output /tmp/clang-cas-adapter-check.json
python3 benchmarks/experiments/clang_cas_pair.py \
  /tmp/nano-clang-passthrough /tmp/nano-clang-cas /absolute/path/to/harness \
  --rust-wrapper /absolute/path/to/accepted/nanocompile \
  --state /tmp/clang-cas-paired-new --runs 27 \
  --output /tmp/clang-cas-paired-new.json
```

The compiler and SDK are selected when this experimental adapter is built.
This is not a production toolchain-selection protocol or compatibility promise
for arbitrary Clang versions, compilers, SDKs, languages or hosts. The native
CAS remains local; Nano GC and R2 transport do not manage it. The first failed
SDK-selection attempt remains in its private state directory and is not a
performance sample. No incomplete or failed builds enter the final replay comparison report.
