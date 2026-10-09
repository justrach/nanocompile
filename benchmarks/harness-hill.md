# Harness hill climb against kache

The first coverage change produces a measurable project-level improvement, but
kache remains much faster. Each row is a separate three-way comparison with
three warm samples per implementation, rotated order, four Cargo jobs, and a
clean target directory for every build. Workload, machine, toolchain and
artifact validation are the same as [the original comparison](kache-harness.md).
Compare implementations within a row; the different sessions are not a
controlled before/after A/B experiment.

| Iteration | Direct median | nanocompile median | kache median | Nano warm hits |
| --- | ---: | ---: | ---: | ---: |
| Original | 22.77 s | 22.95 s | 2.01 s | 2–3 |
| Accept Cargo LTO/codegen flags | 23.19 s | 24.19 s | 2.14 s | 2–8 |
| Scope library lookup to the compiled dependency graph; accept lint flags | 25.16 s | **19.31 s** | 2.16 s | 90–91 |
| Explicit compiler-reported proc-macro inputs | 26.66 s | **19.35 s** | 2.31 s | 110–115 |
| Native paths, comment/literal scanner, default macro policy | 22.86 s | **19.18 s** | 2.09 s | 84–88 |
| Native paths and scanner, reported-input macro policy | 22.96 s | **5.30 s** | 2.80 s | 115–123 |

The latest reported-input implementation is 4.33× faster than its concurrent
direct baseline, while kache remains 1.89× faster than nanocompile in that run.
The latest default mode is only 1.19× faster than direct and still 9.16× slower
than kache. Earlier, enabling reported macro inputs without native-path coverage
increased hit counts but left the median around 19 seconds. The improvement
depends on the combined native-path coverage and reported-input policy, not a
blanket safety claim about arbitrary macros.

Cold-cache cost regressed: nanocompile took 48.46 seconds in the scoped run and
51.31 seconds in reported mode, versus 26.88 and 29.04 seconds for kache. Those
are single samples. Metadata queries and repeated graph validation add work;
this cost must be reduced along with expanding eligibility.

All builds succeeded and produced 135 rlibs. All warm artifacts match their
wrapper's cold artifacts by SHA-256; nanocompile also matches the direct build.
These checks validate cached library restoration, not the complete GUI app.
R2 transport is excluded from this local performance comparison.

## What changed

The original parser rejected `linker-plugin-lto`, `prefer-dynamic` and common
Cargo lint arguments. Accepting the codegen flags alone did not improve the
benchmark; the next eligibility gates still dominated.

Previously, every library in a Cargo dependency directory was included, and
any proc-macro DSO caused a bypass. The new implementation reads the completed
crate's metadata on misses and records candidate files and directory membership
for only the crate prefixes in that graph. A transitive library replacement or
new competing candidate still invalidates a hit. Unrelated concurrently built
crates no longer invalidate it.

The default still declines storage for actual proc-macro dependencies. Reported
mode is explicit (`NANOCOMPILE_PROC_MACROS=reported`) and follows the
compiler-reported-input contract: hidden file reads must be declared. The
initial declaration is a JSON array of explicit files, applied to every Rust
consumer through `NANOCOMPILE_EXTRA_INPUTS_FILE`. It supports no glob or directory
expansion. Integration tests exercise a real macro's hidden data file,
preserved-mtime changes, a changed macro binary, macro reexports, and strict-mode
refusal. No extra file declaration was used for the Harness reported-mode run.

The diagnostic query uses `RUSTC_BOOTSTRAP=1 rustc -Zls=root` only to decode an
already compiled artifact. User compilations retain their original environment
and arguments. A failed query or unrecognized format leaves the result uncached.

## Next bottlenecks

A fresh [invocation diagnostic](harness-current-diagnostic.json) on 2026-10-09
used the current compiler core, the dirty local Harness checkout and explicit
reported-input mode. Both clean warm builds recorded 133 hits and 40 bypasses.
Hit invocation durations summed to 2.48 s and 2.30 s, versus 6.53 s and 6.49 s
for bypasses. These sums overlap under four Cargo jobs and include Python
capture/trace overhead; they are **not build wall times** or a forecast of
speedup. The run is diagnostic evidence, not another kache comparison.
All three Cargo builds completed successfully. Each phase also contains three
nonzero rustc exits from build-script feature probes (`proc_macro2`, `anyhow`
and `thiserror`); these are recorded as failed invocations, not failed Cargo
builds. Failed probe results remain uncached.

`serde_derive` took about 0.81 s per warm invocation and `ring` about 0.63 s.
The other slow bypasses are largely proc-macro producers. Ten calls reject
extern arguments without paths, including `--extern proc_macro`; allowing
that spelling alone would still leave proc-macro crate types unsupported.
Producer caching requires validation of its source/dependency graph, implicit
sysroot lookup, linker/SDK inputs and complete dynamic-library outputs before
expanding eligibility. This is separate from the existing opt-in contract for
macro **consumers**. That coverage work is the next target.

The [producer linker fixture](producer-link-probe-macos.json) now demonstrates
why the existing library metadata resolver cannot simply be reused for
producers. A macro links `middle -> leaf -> unbundled native archive` and returns
the native function's value. Changing that archive from 12 to 13 changes the
compiled macro and its executed expansion while the macro's sources, explicit
Rust externs and dep-info remain identical. The archive remains 712 bytes and
its mtime is preserved. `rustc -Zls=root` reports an empty external dependency
list for both macro binaries; the native linker's dependency report includes
the transitive Rust archives, native archive and SDK stubs. On this Mac it also
records failed lookup candidates. Those negative lookups matter: adding a
previously absent library can change resolution.

The fixture is a discovery prototype, not newly enabled caching. It invokes
the compiler through a private linker observer only within the fixture; normal
user compilation is unchanged. Run it on macOS or Linux with:

```sh
python3 tests/producer_link_probe.py --state /tmp/nano-producer-probe-new \
  --output /tmp/nano-producer-probe.json
```

Apple's [dependency report format](https://github.com/apple-oss-distributions/ld64/blob/main/src/ld/Options.h)
includes inputs, missing candidates and outputs. The Linux probe uses the
linker's Make-format dependency report. The
[Rust linkage documentation](https://doc.rust-lang.org/rustc/command-line-arguments.html#linking-modifiers-bundle)
explains why an unbundled native archive is only searched during final linking.

A [buffer-size probe](harness-digest-buffer-probe.json) checked identical
BLAKE3 digests over the twelve largest rlibs in the preceding local target
(114 MB total). Five rotated samples measured about 0.103 s with the current
64 KiB reader/block setup and 0.098–0.102 s with other buffer configurations.
The result does not justify changing the production hash loop. Reproduce the
individual-file probe with `zig build-exe tests/digest_probe.zig -O ReleaseFast
-lc -femit-bin=/tmp/nano-digest-probe`, then run it with a file path and block
size; an optional third argument allocates a matching reader buffer.

The diagnostic can be captured and summarized without publishing compiler
arguments or environments:

```sh
python3 tests/rust_diagnostic.py zig-out/bin/nanocompile /path/to/harness \
  --state /tmp/nano-diagnostic-new --warm-runs 2
python3 tests/summarize_rust_diagnostic.py /tmp/nano-diagnostic-new \
  --output /tmp/nano-diagnostic-summary.json
```

The earlier reported-mode diagnostic found 21 unsupported crate types, 10 extern
arguments without explicit file paths, 7 native search paths, 5 possible native
link declarations, one native `-l` argument and one directory change during
compilation. These are calls, not unique crate counts. At that point the native
TLS chain, reqwest, Harness's top package and false positives from ordinary
Rust methods/documentation remained uncached. The native-path iteration below
closes much of that gap in reported mode. Direct native links, build-script
and proc-macro producer compilation remain uncached. Extra cache hits must be
judged by build time, not just counts.

## Reproduce and inspect

```sh
zig build -Doptimize=ReleaseFast
python3 tests/project_comparison.py zig-out/bin/nanocompile /path/to/harness \
  --kache /path/to/kache --state /tmp/nano-scoped-new \
  --runs 3 --jobs 4 --output bench-results/scoped.json

# Explicit reported-input macro policy
python3 tests/project_comparison.py zig-out/bin/nanocompile /path/to/harness \
  --kache /path/to/kache --state /tmp/nano-reported-new \
  --proc-macros reported --runs 3 --jobs 4 \
  --output bench-results/reported.json
```

Raw data retains every sample, artifact hash, cache counter, compiler version and
measured executable checksum:
[LTO gate](harness-hill-lto.json), [scoped graph](harness-hill-scoped.json),
[reported macro inputs](harness-hill-reported.json).

## Native-path iteration

The scan-reuse-only comparison measured 18.902 s nanocompile versus 22.787 s
direct and 2.050 s kache, with 84–87 warm hits. It is a separate session, not
a controlled A/B against the scoped-graph run; it does not establish a useful
performance gain from scan reuse alone.
[Raw scan-reuse results](harness-hill-scan-reuse.json) retain all samples.

The next candidate accepts explicit `-L native=…` on Rust consumers. It records
every immediate file's content, symlink targets and all directory names before
and after compilation and on hits. Additions and preserved-mtime edits
invalidate it. Thin archives remain uncached because their member objects may
live elsewhere. Direct `-l` options and possible native link declarations
remain unsupported until their resolution inputs can be fully tracked.
Rust can pack a static native library into an rlib; tracking the Rust provider's
content and native inputs matters for downstream consumers.
[Rust's native bundle semantics](https://doc.rust-lang.org/rustc/command-line-arguments.html#linking-modifiers-bundle)
describe this behavior. A new integration case compiles a real C archive,
builds a Rust provider/consumer, restores the consumer, links/runs it, then
changes the C implementation and verifies the new executable result.

The source scanner now ignores comments and literals and recognizes function
declarations and member/qualified calls. It still refuses actual link
attributes, `cfg_attr` forms, macro arguments and ambiguous bare `link(…)`
calls. Raw strings and character literals containing comment markers cannot
hide a subsequent native declaration.

The reported-input native-path prototype measured 6.615 s nanocompile versus
22.797 s direct and 2.007 s kache. Its warm samples were 9.385, 6.615 and 5.972
seconds with 114–123 hits; cache coverage was still filling after the first
build. Every artifact matched direct and its own cold reference. These are
prototype measurements before the additional overlapping-output guard, not
the final binary's performance result.
[Raw prototype measurements](harness-hill-native-prototype.json) record the
measured executable checksum and all samples. Cold cache still took 52.727 s.

The final implementation uses entry schema 5 and key namespace v7. The project
benchmark now enforces a sampled 40 GiB process-tree RSS guard, records tracked
Rust/manifests' hashes, and checks they stayed unchanged during a comparison.

The final binary was then measured separately in both policies, three warm
samples per pipeline, rotated order, four jobs, clean targets, the same dirty
local Harness revision and Rust 1.97.1. Both comparisons record the same
nanocompile executable checksum and all 881 tracked Rust/manifest hashes stayed
unchanged. All 24 builds produced 135 rlibs; all warm libraries match their own
cold references, and nanocompile matches direct. Peak sampled process-tree RSS
was 1.21 GiB, below the 40 GiB guard.

Default warm samples were 19.150, 19.505 and 19.180 seconds (median 19.180,
84–88 hits), versus 22.863 direct and 2.095 kache medians. Default cold cache
took 48.844 seconds. This is not a meaningful improvement over the earlier
default-mode sessions.

Reported-input warm samples were 8.837, 5.300 and 5.170 seconds (median 5.300,
115–123 hits), versus 22.962 direct and 2.798 kache medians. Kache samples were
2.074, 4.191 and 2.798 seconds; the variation limits precise relative claims.
Reported cold cache took 52.952 seconds versus kache's 26.042 seconds. The first
warm sample still populated additional entries, so the median does not imply
uniform five-second latency immediately after a cold build. No extra macro
input declaration was used for these Harness runs; the reported-input contract
and its limitations still apply.

[Final default results](harness-hill-native-default.json) and
[final reported-input results](harness-hill-native-reported.json) record all
samples, artifact/source hashes, tool versions, counters and the measured
binary. [Linux/Mac CI](https://github.com/justrach/nanocompile/actions/runs/37918600207)
passed the native invalidation, real C-link/run, Rust/Zig and R2 transport tests.

The manual `Harness comparison against kache` workflow compares all three
pipelines on Ubuntu 24.04 and macOS 26, with pinned Rust 1.97.1, Zig 0.17.0 and
checksum-verified kache 1.0.0. It uses public Harness revision
`20c4019201e4b1eee5e04cfbb8dc7bda941b11b9`, since the local checkout's revision
is unavailable on GitHub. Hosted results are a separate workload and must be
compared within their own runner/revision; they are not an A/B against the
dirty local checkout. R2 credentials and transport are excluded from this
three-way performance workflow.


## Hosted three-way comparison

The [hosted run](https://github.com/justrach/nanocompile/actions/runs/37919336094)
completed successfully on both runners with implementation `6f6094c` and public
Harness `20c4019201e4b1eee5e04cfbb8dc7bda941b11b9`. Reported-input macro mode,
Rust 1.97.1, Zig 0.17.0, kache 1.0.0, four jobs and three warm samples were used.
Every build starts with a removed Cargo target directory; local artifact caches
remain populated. Dependencies are fetched outside timing. No R2 transport is
timed. Rows are independent workloads and machines.

| Runner | Direct warm median | nanocompile | kache |
| --- | ---: | ---: | ---: |
| Ubuntu 24.04, x86_64 | 52.97 s | 14.39 s | 1.44 s |
| macOS 26, arm64 | 81.68 s | 15.15 s | 2.60 s |

All 24 builds succeeded. Warm library hashes match their own cold builds, and
nanocompile matches direct. The Linux workload produced 131 rlibs and the Mac
workload 135. Tracked Rust sources and manifests stayed unchanged. These checks
cover library builds, not GUI execution. Kache still wins both comparisons.
Nanocompile warm samples were 24.019/14.393/14.227 seconds on Linux and
23.785/15.152/14.584 on Mac, so the first warm build still fills missing entries.
The Mac direct samples varied from 70.175 to 88.409 seconds; exact speed ratios
should not be generalized beyond these runs.

[Linux raw results](harness-hosted-ubuntu-24.04.json) and
[Mac raw results](harness-hosted-macos-26.json) include every sample, artifact
hash, source hash, tool version and executable checksum.


## Full-prefix candidate

Per-crate traces of the native-path implementation found seven directory-change
refusals in the second warm build. A hashed crate prefix such as `syn-…` was
reduced to `syn`, so other build profiles and crates such as `proc_macro2` could
change broad prefix membership while an unrelated consumer compiled.

The candidate follows rustc's two-phase resolver: first try the dependency's
full extra-filename prefix, then fall back to broad lookup only when no matching
metadata is found. See the [Rust 1.97.1 metadata loader](https://github.com/rust-lang/rust/blob/1.97.1/compiler/rustc_metadata/src/locator.rs).
A narrow guard requires a matching root name, crate hash, target and macro kind.
Fallback guards all library candidates because arbitrary suffixes and renamed
files prevent safely inferring the semantic crate name from the display name.
Every candidate in the selected phase is content-hashed; new competing primary
candidates still invalidate. Classification memos are content-addressed and
compiler-scoped, while standard-library metadata uses the already validated
complete toolchain identity. They save readers, not dependency validation.

Readers prefer `.rmeta` because distributed standard-library `.rlib` files can
contain link-only metadata. Diagnostic subprocesses use a private cache cwd and
the originally selected toolchain; actual compilation environments are unchanged.
Key namespace v8 isolates these semantics from old entries. `clear` removes the
new classification memos and diagnostic files. These memos are not transported
through R2; restored entries validate their recorded inputs directly.

The real-compiler tests cover alternate suffixes, competing primary candidates,
renamed fallback libraries, a primary filename with the wrong crate metadata,
and preserved-mtime fallback corruption, checking direct/wrapped exit statuses.
The existing source, transitive, proc-macro, native C-link/run, output corruption,
concurrency and Zig tests also pass. `tests/rust_diagnostic.py` can collect private
per-crate traces; its capture wrapper adds instrumentation overhead and its timing
must not be used as a performance comparison.


The candidate's local comparison uses implementation `636a9e6`, the same M3
Ultra, dirty local Harness revision `32b41cb`, Rust 1.97.1 and four Cargo jobs.
The two policy comparisons record the same measured executable checksum. Each
has three rotated warm samples per pipeline and removes the Cargo target before
every build. These sessions are independent of the earlier v7 measurements.

| Macro policy | Direct warm median | nanocompile | kache | nanocompile warm hits |
| --- | ---: | ---: | ---: | ---: |
| Default | 22.964 s | 17.363 s | 2.183 s | 97 each build |
| Reported inputs | 23.249 s | 4.775 s | 2.053 s | 132 each build |

Reported-input warm samples were 4.775/4.884/4.728 seconds, with no warm cache
fill ramp in this run. Default samples were 17.336/17.363/17.670 seconds. Kache
still leads in both modes. Default kache samples were 2.183/2.101/4.720 seconds,
so one outlier also limits precision. These observations do not establish a
controlled A/B speedup against prior sessions, although eligible-library
coverage is more consistent.

Cold nanocompile builds took 53.904 seconds in default mode and 64.194 seconds
in reported mode, versus kache's 25.206 and 26.866 seconds. Each cold timing is
one sample. Classification readers add cold work; reducing this cost remains
necessary. No extra macro file declaration was used, and reported mode retains
its compiler-reported-input limitation for arbitrary macros.

All 24 builds succeeded and produced 135 rlibs. Every warm artifact matches its
own cold reference; nanocompile also matches direct. All 881 tracked Rust and
manifest hashes stayed unchanged. Peak sampled process-tree RSS was 1.20 GiB.
R2 is excluded. [Default raw measurements](harness-hill-full-prefix-default.json)
and [reported-input raw measurements](harness-hill-full-prefix-reported.json)
record every sample, source/artifact hash and executable checksum.
[Linux/Mac CI](https://github.com/justrach/nanocompile/actions/runs/37922949650)
passed for this implementation. Its separate
[hosted Harness comparison](https://github.com/justrach/nanocompile/actions/runs/37923282236)
completed successfully; the results are recorded below.


## Hosted full-prefix results

[Run 37923282236](https://github.com/justrach/nanocompile/actions/runs/37923282236)
passed on both runners for `636a9e6`, public Harness `20c4019`, reported-input
macro policy, Rust 1.97.1 and four jobs. Each pipeline has three warm samples,
with target directories removed before every build. This is the full-prefix
implementation before the shared toolchain-digest optimization below.

| Runner | Direct warm median | nanocompile | kache | nanocompile warm hits |
| --- | ---: | ---: | ---: | ---: |
| Ubuntu 24.04, x86_64 | 36.312 s | 6.957 s | 1.089 s | 130 each build |
| macOS 26, arm64 | 87.052 s | 14.254 s | 3.880 s | 132 each build |

All 24 builds succeeded. Restored library hashes match each wrapper's cold
reference, nanocompile matches direct, and tracked sources/manifests stayed
unchanged. Linux produced 131 rlibs and Mac 135. These are library artifact
checks, not GUI execution. Kache remains faster. Runner variation prevents a
controlled A/B claim against the preceding hosted run: even Linux's direct
median changed from 52.965 to 36.312 seconds. Full-prefix hit counts stayed
constant across the warm builds, without a cache-fill ramp.

Cold nanocompile took 49.151 seconds on Linux and 142.870 on Mac, versus kache's
39.230 and 93.420 seconds. Cold timings are single samples. The raw data is in
[Linux](harness-hosted-full-prefix-ubuntu-24.04.json) and
[Mac](harness-hosted-full-prefix-macos-26.json).

## Shared Rust toolchain file digests

Cargo callers in different directories have distinct toolchain-selection
memos so adding or changing an ancestor override invalidates them. Previously,
each fresh selection memo hashed the same installed Rust resources again.
Implementation `fa45544` shares those file digests under the existing trusted
local-toolchain inode/size/mtime/ctime contract. Sealed atomic records and
per-file locks let concurrent first-use selection memos reuse a validated
content hash. Complete toolchain directory checks and selection checks remain;
source dependencies and project artifacts are still content-hashed on every
invocation. Zig fingerprinting is unchanged. This preserves the existing key
and fingerprint bytes; no cache namespace change is needed.

A controlled comparison compiled the same tiny Rust crate in six fixed caller
directories, with a fresh private cache for each sample, three samples per
implementation, alternating order. It compared the frozen `636a9e6` executable
against `fa45544` on Rust 1.97.1. All 36 compilations produced identical artifacts
across the implementations. Six selection memos remained in each sample;
the candidate shared 362 file digests between them. Total wrapper time medians
were **5.205 seconds baseline versus 1.370 candidate**. The candidate's first
caller still took 0.925–0.943 seconds, while subsequent first-use callers took
0.086–0.090. This measures repeated toolchain initialization, not a large
project speed prediction. [Controlled raw data](toolchain-shared-digests.json)
records every invocation and both executable checksums.

```sh
python3 tests/toolchain_comparison.py /path/to/frozen-baseline /path/to/candidate \
  --state /tmp/toolchain-comparison-new --runs 3 --directories 6 \
  --output bench-results/toolchain.json
```

The full local Harness comparison with `fa45544` then measured a **39.760-second
cold build**, versus kache's 26.985 seconds. The preceding full-prefix session
observed 64.194 seconds; these project cold timings are single samples from
separate sessions, not the controlled test above. Warm medians were **4.808
seconds nanocompile**, 22.952 direct and 2.007 kache. Nanocompile warm samples
were 4.808/4.830/4.783 seconds with 132 hits each. Warm time is effectively
unchanged from the preceding session; this iteration reduces cold work rather
than claiming a warm improvement.

All 12 project builds succeeded and produced 135 rlibs. Warm artifacts match
own cold references, nanocompile matches direct, and all 881 tracked source and
manifest hashes stayed unchanged. Peak sampled process-tree RSS was 1.31 GiB.
Reported-input macro policy was explicit, with no extra file declaration; its
hidden-input limitations remain. R2 transport is excluded. The default-policy
project measurements above are from `636a9e6`, not a new default-policy run of
this binary. [Project raw results](harness-hill-shared-toolchain-reported.json)
record the exact measured executable and all samples.

A new filesystem test changes toolchain resource bytes while preserving size
and mtime, verifies the shared digest changes, then corrupts a memo and verifies
it is repaired. The existing real Rust/Zig restore, source and transitive
invalidation, macro/native C-link/run, concurrency, corruption and R2 tests also
passed on [Linux/Mac CI](https://github.com/justrach/nanocompile/actions/runs/37924515217).
`clear` retains validated toolchain-file memos alongside selection memos; they
are not shipped in R2 snapshots and are outside the artifact GC quota.
[Hosted project run 37925078346](https://github.com/justrach/nanocompile/actions/runs/37925078346)
completed successfully; the results are recorded below.


The shared-digest implementation's hosted run passed all artifact and unchanged
source checks on both runners (public Harness `20c4019`, Rust 1.97.1, reported
macros, four jobs, three warm samples, removed targets each build).

| Runner | Direct warm median | nanocompile | kache | Cold nanocompile / kache |
| --- | ---: | ---: | ---: | ---: |
| Ubuntu 24.04, x86_64 | 58.609 s | 11.721 s | 1.509 s | 82.686 / 65.697 s |
| macOS 26, arm64 | 85.085 s | 18.730 s | 5.103 s | 74.441 / 73.781 s |

Warm hit counts stayed at 130 on Linux and 132 on Mac. All 24 builds succeeded;
Linux produced 131 rlibs and Mac 135. Nanocompile artifacts match direct and own
cold references. These are separate hosted workloads: Linux's direct median
changed substantially from the preceding run, and Mac kache warm samples ranged
from 3.143 to 6.949 seconds. Do not claim a controlled project A/B from these
sessions. Kache remains faster warm; the cold gap is small on this Mac run and
still substantial on Linux. The controlled initialization experiment above is
the stronger evidence for the intended shared-digest mechanism.
[Linux raw results](harness-hosted-shared-toolchain-ubuntu-24.04.json) and
[Mac raw results](harness-hosted-shared-toolchain-macos-26.json) preserve every
sample, artifact/source hash and executable checksum.

## Experimental Apple proc-macro producers

The first full comparison of producer caching used binary `8449f3f8738abff8d35d8f19ebbdf1e37f7428ef7b82390f9cc5d5c00a270c56`
(the exact checksum is recorded in the raw JSON), stable Zig 0.17.0 and Rust
1.97.1. [Raw results](harness-hill-producer-reported.json) retain twelve clean
builds, rotating three warm measurement orders with four Cargo jobs. The
existing reported-input macro policy and experimental producer flag were enabled;
R2 was excluded. Harness was the same local dirty checkout at `32b41cb`; all
tracked Rust and manifest hashes remained unchanged during the run.

| Implementation | Warm median | Cold build |
| --- | ---: | ---: |
| Direct Cargo | 22.796 s | 24.556 s prime |
| nanocompile | 4.752 s | 40.621 s |
| kache daemon | 2.018 s | 26.561 s |

All 135 library and ten macro dylib hashes matched direct Cargo for nanocompile
and remained stable across warm builds. Kache matched its own cold outputs.
Nanocompile still recorded 132 hits and three misses per warm build; producer
storage contributed no new entries. The trace confirms all ten Harness macros pass `-C prefer-dynamic` and
`-C strip=symbols`, so all ten take the unsupported-configuration fallback.
The three misses are not producer compilations. This run verifies the
fallback and unchanged library cache, but **does not exercise producer restore
on Harness or establish a producer performance improvement**. Supporting these
actual Cargo flags is the next coverage step.

Reproduce with `tests/project_comparison.py --proc-macros reported
--proc-macro-producers`, retaining the same isolated-state and runs/jobs options
shown above.

## Cargo macro flag coverage

The next iteration admits Apple's native, zero-debug producers with Cargo's
`prefer-dynamic` and `strip=symbols` flags. The real macro fixture verifies
direct/cold/restored bytes, executable macro behavior, source and native-input
invalidation, corruption repair and default/debug fallback with these flags.
[Fixture results](producer-cache-cargo-flags-macos.json) record the measured binary.

[Harness results](harness-hill-producer-cargo-flags.json) use the same twelve-build
comparison protocol, Rust 1.97.1, four jobs, reported-input consumer policy and
local checkout as the preceding run. All ten producers were stored. Every warm
build recorded 142 hits, up from 132. All 135 library and ten macro dylib hashes
matched direct Cargo and each wrapper's cold artifacts. Tracked source files
remained unchanged.

| Implementation | Warm median | Cold build |
| --- | ---: | ---: |
| Direct Cargo | 22.857 s | 25.343 s prime |
| nanocompile | 4.231 s | 40.536 s |
| kache daemon | 2.009 s | 26.822 s |

The observed nanocompile median is 11.0% below the previous 4.752 s run.
This is a comparison across separate runs, not a randomized producer-on/off
experiment. It establishes real producer coverage and successful restore on
this workload; kache remains roughly twice as fast for warm builds. Linux
producer integration and broader debug/link configurations remain unfinished.

## Explicit bundled static libraries

The next warm diagnostic found `ring` as the largest remaining compiler bypass
(0.62 s with tracing and the Python capture shim). Its command uses two plain
`-l static=NAME` archives in an explicit native directory. The wrapper now
requires a regular `libNAME.a` candidate in the provided native directories,
then uses the existing complete native-directory membership/content snapshots
before/after compilation and on restore. Native names with modifiers/renaming,
dynamic libraries, explicit target overrides and absent candidates still bypass.
Source `link(...)` declarations retain the conservative refusal.

Rust's [bundled static-library semantics](https://doc.rust-lang.org/rustc/command-line-arguments.html#linking-modifiers-bundle)
embed archive members in the rlib. [The real fixture](../tests/static_native_cache.py)
checks equal direct/cold/restored artifacts and executes a consumer. It changes
archive bytes while preserving mtime, introduces a preferred archive in an
earlier directory, and checks missing, thin and unsupported-form fallback.
[Local fixture evidence](static-native-cache-macos.json) records the exact binary.

[Raw Harness results](harness-hill-static-native.json) retain twelve clean
four-job builds under the same reported-input and producer policies. `ring` was
stored, each warm run had 144 hits and two misses, and all library and macro
dylib hashes matched direct Cargo. Tracked source files remained unchanged.

| Implementation | Warm median | Cold build |
| --- | ---: | ---: |
| Direct Cargo | 23.126 s | 23.641 s prime |
| nanocompile | 3.433 s | 40.636 s |
| kache daemon | 2.172 s | 27.749 s |

The observed nanocompile median is 18.9% below the previous 4.231 s macro-flag
run. These are separate comparisons rather than a randomized static-library
on/off experiment. Kache still leads. Native compilation by build scripts,
source link declarations, executable producers and Linux proc-macro producers
remain coverage gaps; the cold-cache cost remains larger too.

## Build-script executable compilation

The experimental `NANOCOMPILE_EXECUTABLE_PRODUCERS=1` flag enables native
Apple executable compilation using the same private capture and verified CAS
path. The plan names executable link outputs explicitly; dylib install-name
arguments apply only to macro producers. Cargo still executes restored build
scripts, including their current runtime inputs. The
[executable fixture](../tests/executable_cache.py) verifies direct/cold/restored
bytes, executable permissions, diagnostic replay and live runtime reads, plus
source/native-input invalidation, corruption, failure and default/debug fallback.
[Fixture evidence](executable-cache-macos.json) records binary and test checksums.

The expanded [Harness comparison](harness-hill-executable.json) records twelve
clean builds with the same four jobs and consumer/macro policies. It additionally
checks all 21 build-script executable hashes. Every nanocompile library, macro
and build-script executable matches direct Cargo and its own cold artifact.
Kache matches its own cold artifact set. All 21 build-script executables are
stored and warm builds record 165 hits, with two misses and eight bypasses.
Tracked sources are unchanged.

| Implementation | Warm median | Cold build |
| --- | ---: | ---: |
| Direct Cargo | 22.817 s | 24.837 s prime |
| nanocompile | 3.264 s | 41.458 s |
| kache daemon | 2.077 s | 27.013 s |

The observed median is 4.9% below the preceding 3.433 s static-library run;
these are separate measurements rather than an isolated producer-on/off test.
Kache still leads, and cold-cache cost increased. Tool selection/validation
latency, remaining source-native declarations and native compilation performed
by running scripts remain costs to investigate. Linux producer integration
and broader debug/link coverage remain unfinished.

Reproduce with the previous comparison arguments plus `--executable-producers`.

## Parallel native-selection experiment

A [candidate patch](experiments/native-query-parallel.patch) ran all six
independent Apple selection queries concurrently in a Zig I/O group. Each
worker owned subprocess allocations; results were joined before parsing and
native fingerprinting, and synchronous execution handled unavailable concurrency.
The commands, environment, validation and identity fields were unchanged.

A [controlled isolated comparison](native-query-parallel-macos.json) rotated
25 calls per binary against the same environment/cache after priming both. Every
identity field and fingerprint matched. Median full-process selection latency
fell from **39.054 ms to 13.588 ms**. Private SDK edits, corrupt memos and invalid
selectors also passed with the candidate.

The [full Harness candidate comparison](harness-hill-parallel-native.json)
retained all artifact checks and 165 hits per warm sample. Its warm medians were
22.887 s direct, **3.267 s nanocompile** and 2.155 s kache; the preceding
sequential implementation measured 3.264 s. Candidate samples were 3.267, 3.283
and 3.099 s. Cold nanocompile took 41.218 s. There is no demonstrated project
median improvement, so this candidate was **not adopted**. The source patch
and exact binary checksums remain available for reproduction. The production
implementation and the latest accepted result remain the executable-cache
iteration above. Lower isolated latency alone does not establish a build win.

A [fresh accepted-binary trace](harness-executable-diagnostic.json) with both
producer flags confirms 31 macro/executable producer hits. Its slowest warm
compiler miss is `libc` (0.222 s, source-native-link refusal); the slowest
library restores are `harness_adapters` (0.203 s) and `reqwest` (0.123 s).
These include Python shim and trace overhead. They identify the next
validation/coverage work rather than measuring project speed.

## Bounded parallel dependency hashing

[Manifest inspection](harness-restore-inputs.json) found that `harness_adapters`
validates 322 unique dependency files totaling 252 MB, and `reqwest` 231 files
totaling 170 MB. Directory enumeration was already shared within a restore;
the content hashes still dominated these large graphs.

The cache now hashes large dependency sets with up to four workers (bounded
by available CPUs). A set qualifies only with at least 32 unique files and
8 MiB of content. Workers own allocation arenas and claim independent files
from an atomic index. File hashes are copied into the existing per-restore map
after the group joins. Small sets retain serial hashing. Every file still gets
a full BLAKE3 hash, and directory, negative/symlink, output-blob and diagnostic
validation finish before materialization. There is no cross-invocation source
metadata shortcut, key change or new entry format.

A real large-set unit fixture compares restore against serial reference hashes,
includes duplicate dependencies, and verifies changed/missing input and corrupt
output blob refusal without changing existing output. Existing compiler tests
and the producer/static-native fixtures also exercise the normal cache paths.

[Full Harness results](harness-hill-parallel-hashes.json) retain all twelve clean
builds and artifact checks under the same four jobs and opt-in producer/reported
consumer policies. All 135 libraries, ten macro dylibs and 21 build-script
executables match direct Cargo; each warm sample records 165 hits. Tracked
source files remained unchanged, and the final release binary checksum matches
the measured binary after the regression checks.

| Implementation | Warm median | Cold build |
| --- | ---: | ---: |
| Direct Cargo | 23.291 s | 24.836 s prime |
| nanocompile | 2.961 s | 41.646 s |
| kache daemon | 2.153 s | 26.930 s |

The observed warm median is 9.3% below the last accepted 3.264 s run, across
separate comparisons. Samples are 2.999, 2.932 and 2.961 s. This iteration is
adopted; kache still leads and the cold-cache overhead remains substantial.
The performance evidence is local macOS, not a Linux speedup claim.

## Metadata priority for ordinary Rust libraries

The [Rust 1.97.1 loader](https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/compiler/rustc_metadata/src/locator.rs#L500)
reads rmeta first and can skip the companion rlib flavor when compiling a
library. The cache now omits an archive from transitive content validation
only when its exact same-stem rmeta matches the dependency's name, crate hash,
target and ordinary-crate kind. It still hashes the entire metadata file and
guards directory membership. Explicit extern archives, unmatched candidates,
broad fallback, proc macros and producer collection retain their full checks.

The [real three-crate probe](../tests/rmeta_priority_probe.py) verifies identical
direct and restored artifacts after corrupting an unused companion archive,
including a preserved-mtime mutation. Missing, corrupt and mismatched metadata
force archive fallback. A metadata byte change with an unchanged root identity
still causes a miss; competing candidate changes and explicit archive mutation
also invalidate entries. A final executable rejects the corrupt archive.
[Probe results](rmeta-priority-probe.json) record the compiler and binary checksums.
The fixture runs in both Linux and macOS CI.

[Manifest inspection](harness-rmeta-restore-inputs.json) shows `harness_adapters`
now validates 202 unique files totaling 122 MB, versus the earlier 322 files
and 252 MB. Reqwest validates 143 files and 85 MB, versus 231 files and 170 MB.
These are fewer unused inputs, not partial hashes of consumed inputs.

[Full Harness results](harness-hill-rmeta-priority.json) retain twelve clean
builds with four jobs and the same reported consumer and experimental Apple
producer policies. All 135 libraries, ten macro dylibs and 21 build-script
executables match direct Cargo. Each warm Nano build records 165 hits and the
tracked Rust source/manifests remain unchanged. R2 is excluded.

| Implementation | Warm median | Cold build |
| --- | ---: | ---: |
| Direct Cargo | 22.710 s | 25.240 s prime |
| nanocompile | 2.822 s | 38.115 s |
| kache daemon | 2.095 s | 26.684 s |

Nano samples are 2.822, 2.817 and 2.873 s. The warm median is 4.7% below the
preceding accepted 2.961 s measurement, across separate comparisons; the
direct and kache medians also changed, so this is not a controlled A/B
attribution. This iteration is adopted for the proven reduction in validation
work and the observed project result. Kache remains faster, cold overhead is
still substantial, and these timings establish only local macOS performance.

## Reuse checked hashes after compilation

Cold entry construction previously hashed explicit inputs once for the required
after-compilation comparison, again for dependency records, and again for Rust
metadata classification. Those steps now share fresh full-content hashes within
the successful compilation's save operation. Before-compilation and
after-compilation snapshots remain separate. No digest survives into another
compiler invocation, and cache-hit validation is unchanged.

Reusable hashes carry the inode, size, kind, mtime and ctime observed around the
full read. A changing file refuses reuse. Metadata readers check that state
again before querying or using a classification, preventing a changed artifact
from receiving a classification under an earlier byte hash. The unit fixture
changes bytes while preserving mtime and verifies refusal for both cached and
unclassified metadata roots.

The [controlled comparison](postcompile-hash-comparison.json) rotates the
preceding accepted binary and the candidate through nine cold-entry builds
each, with identical arguments, environment and paths. Toolchain and metadata
reader memos are primed. Eight explicit metadata files total 260 MB. Every
output and complete entry manifest matches, and both binaries restore the same
entry. Median complete wrapper time is **0.772 s versus 0.477 s**, a 38.2%
reduction in this metadata-heavy cold-entry fixture. This is not a general
Rust compilation speedup or a warm-cache improvement.

Reproduce with [the comparison script](../tests/postcompile_hash_benchmark.py):

```sh
python3 tests/postcompile_hash_benchmark.py /path/to/previous/nanocompile \
  /path/to/candidate/nanocompile --runs 9 \
  --output bench-results/postcompile-hashes.json
```

The [final-binary Harness comparison](harness-hill-postcompile-hashes.json)
uses the same twelve-build protocol, four jobs, reported macro consumers and
both experimental Apple producer policies. All 135 libraries, ten macro
dylibs and 21 build-script executables match direct Cargo, with 165 hits in
each warm Nano build. Tracked source/manifests remain unchanged; R2 is excluded.

| Implementation | Warm median | Cold build |
| --- | ---: | ---: |
| Direct Cargo | 22.797 s | 23.377 s prime |
| nanocompile | 2.825 s | 37.753 s |
| kache daemon | 1.958 s | 26.696 s |

Warm samples are 2.888, 2.790 and 2.825 s. Warm performance is essentially
unchanged from the preceding 2.822 s result, as expected for an optimization
to entry construction. The cold measurement is only slightly below the
preceding 38.115 s run, across separate comparisons; it does not establish a
large Harness build gain. The controlled fixture establishes the benefit for
large repeated input validation, so the change is adopted with that limited
claim. Kache still leads in both project phases.

Unit and real Rust/Zig integration checks pass. Final-binary fixture results
cover [metadata priority and full-byte invalidation](postcompile-rmeta-regression.json),
[macro producer restore and loading](postcompile-producer-regression.json),
[executable restore and runtime behavior](postcompile-executable-regression.json),
and [bundled static archive invalidation](postcompile-static-regression.json).
Their executable checksums match the measured final binary.

## Eight-worker restore candidate: not adopted

A [two-line candidate patch](experiments/restore-eight-workers.patch) increased
the maximum full-content hashing workers from four to eight, still capped by
available CPUs. Eligibility thresholds and all dependency/blob guards stayed
the same. Unit tests passed.

The [isolated rotating comparison](restore-workers-comparison.json) restored
the same real Rust entry through both binaries 25 times each, checking output
bytes, modes and unchanged manifest after every hit. Its 32 explicit metadata
files total 130 MB. On this 28-CPU Mac, median wrapper time fell from
**44.45 ms to 26.57 ms**, a 40.2% fixture improvement.

The [twelve-build project comparison](harness-hill-eight-workers.json) measured
22.968 s direct, 2.939 s Nano and 2.086 s kache warm medians, with 38.354 s Nano
cold. All artifacts matched and warm hits stayed at 165. That separate session
did not establish an improvement over the accepted 2.825 s project result.

A [paired project comparison](harness-eight-workers-paired.json) then copied
each binary to one stable wrapper path between completed builds, preserving
the same environment, target path and shared cache. Each binary was primed;
producer identities still use their distinct binary hashes. Nine warm pairs
rotated order. Every build restored 165 entries and all 167 collected library,
dylib and build-script artifacts matched the first prime. Tracked sources
remained unchanged. This comparison does not measure separate cold-cache
performance: the second prime shares ordinary library entries with the first.

The four-worker median was 2.888 s and eight-worker median 2.858 s. The mean
paired saving was only 7.25 ms, with 51.93 ms sample standard deviation and
17.31 ms standard error. Six of nine pairs favored eight workers. These samples
do not establish a reliable project gain, so the production maximum remains
**four workers** and the latest accepted performance result remains the
post-compilation hash-reuse iteration above. Faster isolated hashing alone is
insufficient to double the per-invocation concurrency limit.

Both helpers are reusable for subsequent candidates:

```sh
python3 tests/restore_worker_comparison.py /path/to/baseline/nanocompile \
  /path/to/candidate/nanocompile --runs 25 \
  --output bench-results/restore-workers.json
python3 tests/project_pair_comparison.py /path/to/baseline/nanocompile \
  /path/to/candidate/nanocompile /path/to/harness \
  --state /tmp/nano-project-pair-new --runs 9 --jobs 4 \
  --output bench-results/project-pair.json
```

The paired helper deliberately enables reported consumers and both experimental
producer policies and requires at least 165 warm hits for this Harness workload.
R2 is excluded from all these measurements.

## Completed native metadata: adopted for the pinned compiler

Source-level native link attributes no longer force refusal when the completed
ordinary library metadata records only default/dynamic/framework libraries, or
no native libraries. The [Zig reader and real restore checks](../docs/native-metadata-investigation.md)
accept exactly Rust 1.97.1 on Darwin and GNU/musl Linux. Active static links,
including macro-generated ones, unsupported fields, other compiler versions,
link-only outputs and all producer paths retain their prior policy. Existing
source/native/extern content checks remain intact. A separate Rust eligibility
key tag prevents old binaries from reusing newly eligible entries.

The [nine-pair project comparison](harness-native-metadata-paired.json) uses
one stable wrapper path and identical environment and target path, rotating
order after both binaries are primed. The baseline is the accepted executable
`bf9ed504a41b66eab0fdcf040707f5efea880c79ef0ef89c6a3e5b2e638e8bf7`;
the candidate is
`33100a369757582d2d880f85f2de0f823ab408cf4f2b1e25c75f4928608a33ad`.
Ordinary entry keys differ, while toolchain/classification storage is shared;
prime timings are not an independent cold-cache comparison.

Median time fell from **2.872 s to 2.813 s**, about 2.0%. Eight of nine pairs
favored the candidate. Mean paired savings were 48.05 ms, with 51.72 ms sample
standard deviation and 17.24 ms standard error. All 167 collected libraries,
macro dylibs and build-script executables matched the first prime. Baseline
warm builds recorded 165 hits and two misses; candidate warm builds recorded
**167 hits and zero misses**, with the same eight bypasses and three failed
compiler probes. Tracked Rust files and manifests remained unchanged.

The [separate twelve-build three-way comparison](harness-hill-native-metadata.json)
measures the final executable against direct Cargo and kache with its daemon:

| Implementation | Warm median | Cold sample |
| --- | ---: | ---: |
| Direct Cargo | 22.866 s | 23.499 s prime |
| nanocompile | **2.770 s** | 37.887 s |
| kache daemon | 2.071 s | 26.954 s |

Nano's complete warm samples are **2.770, 2.735 and 3.731 s**. The slower third
sample is retained; the median alone does not describe that variation. This
separate run supports the coverage change and records current performance;
the controlled paired run supplies the before/after evidence. Kache remains
faster, and there is no demonstrated cold-build improvement. All 135 rlibs,
10 macro dylibs and 21 build-script executables match direct builds and their
own cold outputs. Tracked sources remain unchanged; R2 transport is excluded.

Final-binary local checks include unit tests and the real Rust/Zig integration
suite, [native metadata restores and downstream execution](native-metadata-cache.json),
[metadata priority/corruption/invalidation](native-metadata-rmeta-regression.json),
[bundled static archive changes](native-metadata-static-regression.json),
[macro producers with Cargo flags](native-metadata-producer-regression.json),
and [executable producers](native-metadata-executable-regression.json).
Linux and macOS CI run the new real metadata and restoration fixtures too.

A [fresh diagnostic capture](native-metadata-diagnostic.json) after this change
runs one cold and two warm Cargo builds through the existing Python capture
wrapper. It confirms 136 ordinary library hits, 21 executable-producer hits
and 10 macro-producer hits in both warm phases. The three remaining compiling
invocations are failing compiler probes, not successful library misses.

Ordinary library hit medians in the capture are about 9 ms; macro/executable
producer hit medians are about 61–66 ms. Capture overhead and concurrency are
included, and invocation times overlap, so these are diagnostic observations,
not a new project benchmark. Producers currently run native tool-selection
queries before every cache lookup. This makes verified selection reuse a
candidate to investigate next; no such reuse or selection guard relaxation has
been implemented here. The earlier parallel-query experiment remains rejected.
