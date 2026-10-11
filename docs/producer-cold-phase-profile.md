# Cold producer phase diagnostics

Enable `NANOCOMPILE_TRACE=1` and `NANOCOMPILE_COMPILER_PROFILE=1`, or use
`--compiler-profile` with the whole-build comparison runner and trace capture.
Profiling stays off by default. New cold executable/proc-macro producer markers
separate input snapshots and staging, actual compiler execution, publication and
stream forwarding, linked-input discovery, identity rechecks, postcompile storage
and cleanup. Existing prefix, restore and total markers remain available.

Successful postcompile saves additionally emit `save.input_revalidation`,
`save.source_discovery_guards`, `save.rust_graphs` and `save.artifacts`.
These subdivide the containing postcompile stage for ordinary and producer
requests. Graph collection includes linker-record assembly for producers;
artifact storage includes variant manifest construction and publication.
Markers after an early failure can be absent. Profile-off behavior and input
validation are unchanged.

The whole-build analyzer accepts these stages without a fixed stage allowlist.
Use its owned request streams and Cargo timeline to attribute work. A marker can
be absent on an early fallback or failure; absence is not zero cost. Total spans
include nested stages, so do not add them together. Compiler execution still
includes the linker and any compiler children; these markers do not split LLVM
passes automatically.

The production four-worker runtime passed build/unit checks and actual executable
profile-on, default-off and thin-LTO stable-alias fixtures. They check restored
bytes, modes, live behavior, edits, corruption, failure and fallback behavior.
The initial experimental thin-LTO validation command omitted required
`--retain-jobs` and was rejected by argument parsing before compilation; its log
is retained alongside the corrected successful run.

This adds measurement, not a speed improvement. Next capture the actual full
Harness shared-edit request with the same recorded source/toolchain/native
contracts. Its latest single Nano observation is 7.810s slower than kache.
Measure compiler execution and postcompile work before assigning that difference
to hashing or caching, then test one change in repeated untraced comparisons.
