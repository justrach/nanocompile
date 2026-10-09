# Experimental Rust executable compilation caching

The opt-in `NANOCOMPILE_EXECUTABLE_PRODUCERS=1` adds native Apple `bin`
compilation to the existing [producer capture path](proc-macro-producers.md).
This includes compilation of Cargo build-script executables. Their subsequent
execution belongs to Cargo and still runs normally; runtime inputs are not
compiler inputs merely because a compiled program later reads them.

Eligibility requires explicit crate name/output directory, dep-info and link
emission, zero debug information, native host tools, and supported ordinary
codegen/extern arguments. Tests, metadata-only executables, explicit targets,
custom linkers, LTO and broader debug/link configurations still bypass. Linux
producer integration remains unfinished. The flag is independent of macro
producer and reported-input consumer flags. None is enabled by default.

On a miss, rustc compiles into an exclusive private job with a native linker
observer. The actual linker output is selected from the plan rather than
inferred from a dylib suffix. Executables receive no dylib install-name option.
Dep-info and diagnostics are mapped back to the requested output directory,
then outputs and permissions are independently materialized. The producer key
binds original arguments/environment, compiler content and file state, selected
native tools and the observer executable. Source/extern/search/native/linker
inputs must validate before storage. Hits use the existing CAS validation,
corruption repair and diagnostic replay.

[The real fixture](../tests/executable_cache.py) checks equal direct/cold/restored
executable and dep-info bytes, permissions, execution, preserved-mtime archive
edits, source changes, corruption, invalid compilation and default/debug fallback.
It changes a runtime input between cold and restored execution: the same
restored program reads the new value. This does not establish all linker
configurations or all failed-compilation output side effects.

The first [Harness comparison](../benchmarks/harness-hill.md#build-script-executable-compilation)
stores and restores all 21 build-script executables, with matching direct Cargo
bytes and matching downstream library/macro artifacts. This establishes the
compiled-artifact path on that workload, not cached script execution or full
producer coverage.

The implementation and full existing suite passed on hosted Linux and macOS
in [run 37952952464](https://github.com/justrach/nanocompile/actions/runs/37952952464)
at `4fbcf890f47a2858c86bb930a25566a5e4ee3f64`. The Apple executable test runs
on the hosted Mac; unsupported Linux producer invocations retain fallback.
