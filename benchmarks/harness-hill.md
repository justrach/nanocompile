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
