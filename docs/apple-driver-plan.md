# Apple producer tool selection

Experimental Rust macro and executable producer lookups still query the active
Apple tool selection on every invocation. For a recognized Clang diagnostic,
nanocompile obtains the compiler, linker, resource directory and configuration
status from one live `cc -v -### -x c /dev/null -o /dev/null` plan. Clang documents
[`-###`](https://clang.llvm.org/docs/CommandGuide/clang.html#driver-options)
as printing its command plan without executing the compiler/linker jobs.

Three independent xcrun queries remain: `--find clang`, `--find ld`, and
`--sdk macosx --show-sdk-path`. The compiler and linker from the driver plan must
agree with xcrun after canonicalizing their paths. SDK selection, all native
file fingerprints and the selection hash format remain unchanged. Persistent
link inputs and negative lookup guards are still collected and checked by the
existing producer path. Original Rust compilation arguments and environment
remain unchanged.

The parser accepts exactly one quoted `-cc1` command followed by one quoted
link command, with complete known version/target/thread/installation headers
and one resource directory. Quoted spaces, quotes and backslashes are decoded;
unknown escaping, extra commands, incomplete headers, missing/duplicate
resources and other diagnostics use the older six selection queries. Clang
configuration files continue to refuse producer storage. A recognized plan
needs four queries in total. These four independent queries run through a
queue with at most two active queries, including the calling worker. Workers
use independent subprocess allocations; parsing and native file fingerprinting
begin after they join. A single CPU or unavailable concurrency uses the calling
worker alone. No selection is reused across invocations.

When the plan needs fallback, the three independent xcrun results remain live
and the older driver queries run afterward. The fallback still executes seven
commands in total, including the attempted plan. Configuration markers continue
to refuse storage, and compiler/linker agreement with xcrun remains mandatory.

`tests/driver_plan_selection.py` compares the earlier executable and candidate
under the same private environment and cache. The local comparison covers cc
and clang, Command Line Tools and Xcode developer roots, explicit/private SDKs,
SDK metadata edits with preserved mtime, an invalid deployment-target plan
that falls back to the legacy queries, and invalid/unsupported selectors.
Every accepted selection structure and fingerprint must match exactly. The
helper does not change global Xcode selection or installation files.

The existing `tests/native_identity.py`, run by macOS CI, also checks the
invalid-plan fallback, SDK metadata changes, corrupt memos and invalid
selectors. Linux retains its existing producer policy. Parser unit tests and
real macro/executable restore fixtures cover the new path; this does not add
Linux producer support or broader driver/configuration support.

The [two-query-limit comparison](../benchmarks/native-two-selection-comparison.json)
repeats those real selector cases against the accepted sequential live-plan
binary. Every accepted selection and fingerprint matches. The
[isolated 25-pair comparison](../benchmarks/native-two-query-comparison.json)
and [controlled Harness batches](../benchmarks/harness-hill.md#two-active-native-queries-adopted)
record latency and project behavior separately.

A [four-query-limit experiment](../benchmarks/harness-hill.md#four-active-native-queries-rejected)
reduced isolated selection latency but showed no project gain across 27
controlled Harness pairs. It was rejected; production retains two active
queries.
