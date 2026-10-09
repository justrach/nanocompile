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

The default scoped implementation is 1.30× faster than its concurrent direct
baseline, while kache is still 8.94× faster than nanocompile. Adding reported
macro inputs increases hit coverage but does not materially improve the measured
median. Its warm samples range from 17.74 to 22.09 seconds; avoid attributing
small differences between these sessions to the macro policy.

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

The reported-mode diagnostic found 21 unsupported crate types, 10 extern
arguments without explicit file paths, 7 native search paths, 5 possible native
link declarations, one native `-l` argument and one directory change during
compilation. These are calls, not unique crate counts. The remaining uncached
libraries include the native TLS chain, reqwest, Harness's top package and some
false positives from ordinary Rust functions named `link`. Build-script and
proc-macro producer compilation also remain uncached. Extra cache hits must be
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

The manual `Harness comparison against kache` workflow compares all three
pipelines on Ubuntu 24.04 and macOS 26, with pinned Rust 1.97.1, Zig 0.17.0 and
checksum-verified kache 1.0.0. It uses public Harness revision
`20c4019201e4b1eee5e04cfbb8dc7bda941b11b9`, since the local checkout's revision
is unavailable on GitHub. Hosted results are a separate workload and must be
compared within their own runner/revision; they are not an A/B against the
dirty local checkout. R2 credentials and transport are excluded from this
three-way performance workflow.
