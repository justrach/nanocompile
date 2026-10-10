# Experimental declared-file task runner

`nanocompile task SPEC.json` executes an explicitly ordered task graph with existing-file inputs and individual-file outputs. The [two-package example](../examples/turborepo/nanocompile.tasks.json) runs the same Node scripts as Turbo. Earlier tasks must appear before their dependents. Missing/forward/cyclic dependencies reject before execution. No globs, directory outputs, automatic Cargo build-script discovery, daemon, parallel graph scheduler or Turbo configuration compatibility is provided.

```sh
cd examples/turborepo
/absolute/path/nanocompile task nanocompile.tasks.json
```

This is a caller-owned contract: outputs must be deterministic functions of declared file bytes, commands, installed tool resources, cwd and environment. Declare all scripts/imports/configuration, dependent task output files and additional runtime resources. Tasks observing undeclared files, filesystem metadata, clock, network or other effects are outside this contract. `depends_on` controls order; consumers must also declare the predecessor files they read. Installing a new runtime without changing its executable requires declaring affected libraries/data through `tool_resources` or clearing this experimental cache. Installed tool resources use the same trusted-installation metadata contract as compiler fingerprints; project inputs always receive fresh complete content hashes.

Keys include the complete specification, full environment, selected executable identity and optional declared `tool_resources`. This is more conservative than Turbo's selected environment inputs. Task outputs/diagnostics use the existing CAS and GC/R2 snapshot format. Every listed input is hashed before lookup; after a successful execution all input/tool identities must still match before storing. Validation finishes before materialization. Failed commands preserve their exit status and store no result. Whole-task caching does not make arbitrary build scripts hermetic.

The [comparison and checks](../benchmarks/turbo-declared-task-comparison.json) alternate real Turbo local-only/no-daemon and Nano restores on the same paths, scripts and fixed environment, deleting declared outputs before every run. Both restore identical files with zero Node executions. The 27-pair local fixture result is about 5.6 ms Nano versus 47.0 ms Turbo. It demonstrates lower overhead for this small ordered pipeline, not a general advantage over Turbo's scheduler or large JS monorepos. The [earlier check batch](../benchmarks/turbo-declared-task-first-check.json) is also retained; it ran during a separate linked-probe qualification and is not the quiet final timing batch.

Source/dependency/site-only/environment edits, direct uncached Node byte equality, corruption repair, invalid graph rejection and failed status are tested. The existing Turbo remote-cache server is still a separate integration: it lets Turbo store signed archives in Nano's CAS and R2 transport without replacing Turbo's scheduler.

The same fixtures also pass [hosted Linux/macOS validation](hosted-three-directions.md); raw results retain all samples and tool versions.
