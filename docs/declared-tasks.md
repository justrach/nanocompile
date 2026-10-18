# Experimental declared-file task runner

`nanocompile task SPEC.json` executes an explicitly ordered task graph with existing-file inputs and individual-file outputs. The [two-package example](../examples/turborepo/nanocompile.tasks.json) runs the same Node scripts as Turbo. Earlier tasks must appear before their dependents. Missing/forward/cyclic dependencies reject before execution. No globs, directory outputs, automatic Cargo build-script discovery, daemon, parallel graph scheduler or Turbo configuration compatibility is provided.

```sh
cd examples/turborepo
/absolute/path/nanocompile task nanocompile.tasks.json
```

This is a caller-owned contract: outputs must be deterministic functions of declared file bytes, commands, installed tool resources, cwd and environment. Declare all scripts/imports/configuration, dependent task output files and additional runtime resources. Tasks observing undeclared files, filesystem metadata, clock, network or other effects are outside this contract. `depends_on` controls order; consumers must also declare the predecessor files they read. Installing a new runtime without changing its executable requires declaring affected libraries/data through `tool_resources` or clearing this experimental cache. Installed tool resources use the same trusted-installation metadata contract as compiler fingerprints; project inputs always receive fresh complete content hashes.

## Per-task keys and validation

Versioned canonical per-task keys include the selected task's name, resolved working directory, ordered command arguments (and selected executable), ordered input paths and complete file content hashes, ordered output paths, ordered `tool_resources` and identities, and ordered `depends_on` edges. Tagged, counted fields prevent ambiguity between adjacent lists. Keys also retain the full environment and host OS/CPU safeguards; they are **not relocatable**. The v2 namespace does not reuse old raw-specification keys.

JSON whitespace, object-field order, the specification's filename and unrelated task edits no longer invalidate eligible tasks. Changes to the selected task's command/argument order, declared input/output/tool-resource order or dependency edges do invalidate it. Dependencies are never inferred: `depends_on` specifies ordering, and consumers must still declare predecessor files they read. An unrelated edit that makes the overall graph invalid rejects the whole invocation before any task executes.

The complete graph is validated before execution. The specification is then compared byte-for-byte with its original snapshot before **each** task, and again after a successful child and after input/tool revalidation. Thus even a formatting-only specification edit during execution suppresses storage, and an edit during an earlier task prevents subsequent tasks from executing a stale parsed graph. These race guards do not become key inputs or stored cache dependencies. As with other caller-owned contracts, changes that are made and reverted between observations are not detected.

Task outputs/diagnostics use the existing CAS and GC/R2 snapshot format. Every listed input receives a fresh complete content hash before lookup, including large files; persistent input digest memoization is not used for declared tasks. After successful execution the complete input hashes and tool identities must still match before storing. Installed tools retain the trusted-installation identity policy described above. Validation finishes before materialization. Failed commands preserve their exit status and store no result. Whole-task caching does not make arbitrary build scripts hermetic.

## Opt-in private JSON reports

Select a **fresh file in an existing directory** with `NANOCOMPILE_TASK_REPORT`:

```sh
NANOCOMPILE_TASK_REPORT=/tmp/task-report-unique.json nanocompile task SPEC.json
```

The report is a separate JSON document, never stdout/stderr. Reporting does not change task keys, child environments, task diagnostics, event names or exit status. Only `NANOCOMPILE_TASK_REPORT` is omitted from an invocation-local environment copy used for both keys and children; the root environment and every other variable are unchanged. With reporting disabled, no report is written.

Report writes are best-effort and exclusive: existing files are **never overwritten**. Choose a unique destination for each invocation or remove an old report yourself. Invalid/unwritable destinations, missing parent directories, and destinations overlapping the specification, declared inputs/outputs/tool resources or selected executables produce no report and do not fail the build. Existing symlink ancestors are resolved for these guards; exclusive creation also refuses existing symlink/hardlink aliases. Parent directories are never created for a report. Reports are intended as local diagnostics, not an automatic telemetry/upload mechanism.

Schema `1` contains `maintenance_lock_ns` and a `tasks` array in execution order. Rows identify tasks only by zero-based `task_index`; no task names, paths, environment values, arguments or raw errors are emitted. Graph/parse failures before task execution do not produce a report. Rows include:

- `outcome`: `hit`, `miss` (child succeeded), `failed`, `bypass`, or `error`; `exit_code` is populated when known.
- `lookup`: `hit`, `entry_absent`, `entry_unusable`, `disabled`, or `not_attempted`. Absence is observed under the task-key lock. `entry_unusable` means an existing/unreadable entry could not be restored; it includes invalid manifests/blobs, validation failures and I/O failures, **not a proven corruption cause**. No retained historical contract exists, so an absent key is not reported as a changed-command/input/environment reason.
- `storage`: `stored`, `not_attempted`, `spec_changed`, `inputs_or_tools_changed`, `revalidation_failed`, or `error`. Change reasons require comparison with this invocation's initial snapshot; a read/validation failure alone is not asserted to be a change.
- `timings`: monotonic awake-clock nanoseconds for `input_hash_ns` (initial input records, including path/stat overhead), `tool_identity_ns` (initial executable/resource fingerprinting, possibly using installed-tool memos), `lock_wait_ns` (task/output lock acquisition and its bookkeeping), `lookup_restore_ns` (lookup, validation, materialization and cached diagnostic replay), `child_ns` (child execution/capture), `revalidation_ns` (post-child raw-spec/input/tool checks and key comparison), and `storage_ns` (CAS/entry publication). Unattempted stages are zero. Maintenance lock acquisition is reported separately at invocation level. These are elapsed stage intervals, not CPU time or pure kernel I/O/lock-wait measurements. Successful-child diagnostic writes and canonical-key construction outside revalidation are not included in these intervals.
- `input_bytes_hashed` and `revalidation_input_bytes_hashed`: sum of regular-file sizes for successfully completed declared-input hash operations in that phase, counting repeated declarations separately. These are complete content-hash bytes, not filesystem/device traffic; failed partial hashes are not counted. Additional input/blob hashing internal to restore, installed-tool memo reads/hashes, specification reads and manifest I/O are not counted.
- `restored_output_bytes` and `stored_output_bytes`: summed declared-output file sizes observed after a successful restore/store, or `null` when not attempted/unavailable. These are logical payload sizes, **not physical bytes copied or newly written to CAS** (blobs may already exist and materialization can clone files).
- `child_stdout_bytes` and `child_stderr_bytes`: captured child stream lengths; zero when no child ran. Cached stream replay is not counted as child output.

Focused standard-library-only checks run with `python3 tests/task_contracts.py /path/to/nanocompile`. They use `sys.executable`, with no Node/Turbo dependency, to cover canonical-key eligibility and ordered-contract misses, input/tool/environment edits, report on/off equivalence and privacy, corrupt-entry fallback, failed commands, graph rejection, specification race guards, and report destination safety.

The [comparison and checks](../benchmarks/turbo-declared-task-comparison.json) alternate real Turbo local-only/no-daemon and Nano restores on the same paths, scripts and fixed environment, deleting declared outputs before every run. Both restore identical files with zero Node executions. The 27-pair local fixture result is about 5.6 ms Nano versus 47.0 ms Turbo. It demonstrates lower overhead for this small ordered pipeline, not a general advantage over Turbo's scheduler or large JS monorepos. The [earlier check batch](../benchmarks/turbo-declared-task-first-check.json) is also retained; it ran during a separate linked-probe qualification and is not the quiet final timing batch.

Source/dependency/site-only/environment edits, direct uncached Node byte equality, corruption repair, invalid graph rejection and failed status are tested. The existing Turbo remote-cache server is still a separate integration: it lets Turbo store signed archives in Nano's CAS and R2 transport without replacing Turbo's scheduler.

The same fixtures also pass [hosted Linux/macOS validation](hosted-three-directions.md); raw results retain all samples and tool versions.
