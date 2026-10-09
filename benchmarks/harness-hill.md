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
