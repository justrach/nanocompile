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
needs four queries in total; fallback includes the attempted plan and then the
older queries. No selection is reused across invocations.

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
