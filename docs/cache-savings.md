# Local cache-savings measurements

`tools/cache_savings.py` is a Python 3.9+ standard-library-only recorder and
aggregator for `nanocompile task SPEC`. It never sends network requests and has
no hosted backend. Measurements and summaries are local by default. Executing a
build or preparation command is **not** sandboxed: those caller-owned commands
can themselves access the network or modify files.

## Record and summarize

Run from the same working directory you normally use for the declared task:

```sh
python3 tools/cache_savings.py record \
  --binary /path/to/nanocompile --spec tasks.json \
  --target x86_64 --output first.json

# Repeat builds with the intended output/cache state; choose a fresh file each time.
python3 tools/cache_savings.py record \
  --binary /path/to/nanocompile --spec tasks.json \
  --target x86_64 --output second.json

python3 tools/cache_savings.py summary first.json second.json --output summary.json
```

`record` uses a fresh temporary `NANOCOMPILE_TASK_REPORT` path, invokes the binary
with `task SPEC`, reads the native report, and removes the temporary report. The
process-wall measurement includes process startup, task processing, and native
report writing. The recorder's own Python startup, JSON parsing, and output write
are outside that measurement. Child stdout/stderr are discarded, not embedded or
echoed into the resulting JSON. Use the native command separately if you need
local build diagnostics.

Optional external costs must be **observed**, not guessed:

```sh
python3 tools/cache_savings.py record \
  --binary /path/to/nanocompile --spec tasks.json \
  --setup-report setup-report.json --transfer-seconds 0.28 \
  --output observed.json
```

Alternatively use `--setup-seconds NUMBER`. These setup options are mutually
exclusive. The setup report is a local JSON object; **only `setup_seconds` is
read as a metric**. Keys, checksums, paths and all other fields are ignored, never
forwarded. Malformed JSON, duplicate keys, or invalid setup seconds reject the
operation before the build runs. Transfer time represents a separately observed
external artifact/cache transfer, not the native materialization timer. Do not
supply overlapping costs. Explicit zero means you observed no such cost; omitting
either option leaves that cost `null`. If setup/transfer is shared across several
builds, attribute it once or use a documented caller-owned allocation; repeating
one setup measurement on every build would overcount it.

Every JSON record contains only a fixed schema, coarse platform and target,
status, numeric timing/byte metrics and task counts. No input filename, task
name/index, command, environment, native key/hash, log, timestamp, session or
machine identifier is retained. `--target` is a caller-selected coarse
architecture category (`x86_64`, `aarch64`, `wasm`, `other`, `unknown`), not a full
target triple or project target name. Host platform is one of `linux`, `macos`,
`windows`, `other`. Summary aggregates all explicitly selected records, including
records from multiple targets; anonymous export additionally provides adequately
sized platform/target breakdowns. No workload identity or automatic workload
matching is inferred.

### Timing and size definitions

Native schema `1` is additive. Older reports missing newer fields remain usable,
but missing observations stay `null`, never zero.

| Metric | Meaning |
| --- | --- |
| `process_seconds` | Measured entire native subprocess wall time. |
| `external_setup_seconds` | Explicit observed external setup, or unknown. Separate from native setup. |
| `external_transfer_seconds` | Explicit observed external transfer, or unknown. |
| `native_setup_seconds` | Native `setup_ns`, including maintenance lock acquisition. |
| `native_total_seconds` | Native total, including setup, tasks and unattributed work, but excluding report writing/process startup. |
| `maintenance_lock_seconds` | Native maintenance-lock interval; already included in native setup. |
| `task_input_hash_seconds`, `task_tool_identity_seconds` | Initial declared-input hashing and installed-tool identity work. |
| `task_lookup_seconds` | Manifest, dependency and blob validation. |
| `task_restore_seconds` | Materialization, including time spent on failed restore attempts. |
| `task_diagnostic_replay_seconds` | Cached diagnostic replay. |
| `task_lookup_restore_seconds` | Inclusive lookup/restore/replay interval, **not an additional cost**. |
| `task_child_seconds` | Task-command elapsed time. It may include scripts, wrappers, linking and compiler caches; it is **not necessarily pure compilation time**. |
| `task_lock_wait_seconds`, `task_revalidation_seconds`, `task_storage_seconds` | Other native stage intervals. |
| `task_total_seconds` | Sum of reported whole-task elapsed intervals. |
| `process_overhead_seconds` | Process wall minus observed task-command time, checked nonnegative; includes hashing, native setup, lookup, restore and process/report overhead. Not the sum of overlapping stage timers. |
| `artifact_bytes` | Sum of nullable native `output_bytes` observations for hit/miss/bypass. Logical output bytes, not compressed/network/device traffic; repeated outputs may be counted repeatedly. |
| `input_bytes_hashed`, `revalidation_input_bytes_hashed` | Native counts of observed complete declared-input hashing in each phase. |
| `observed_total_seconds` | Process wall plus whichever external costs were actually observed. A lower/incomplete accounting total when external observations are missing. |
| `complete_total_seconds` | Same sum, but only when both external costs were supplied; otherwise `null`. |

Records store native stages under `metrics`. Summaries derive overhead and totals,
then report each metric's `observed_samples`, `total` and `mean`. A partially
observed metric's total is over observed samples only; no missing durations are
imputed. Counts and observed totals are shown even when no savings claim is
possible. `incomplete_external_cost_samples` states how many builds lack external
setup or transfer observations.

Hit rate is `hit / lookup_attempts`, where attempts are native `hit`,
`entry_absent`, and `entry_unusable` lookups. Disabled/not-attempted lookups do not
inflate that denominator. Task outcome counts retain failures and bypasses.
Failed subprocesses retain their measured process wall and status; CLI returns
nonzero. A missing/malformed native report yields an incomplete record and
nonzero CLI status even if the task command returned zero. Invalid native metrics
are not used. Nonfinite/negative measurements and booleans masquerading as
numbers are rejected. Savings themselves may legitimately be negative.

## Estimates are not measured speedups

The default summary produces **no savings estimate and no speedup**. In
particular, a cold miss followed by a cache hit does not establish a controlled
comparison: compiler caches, OS caches, outputs and system activity may differ.

To request an explicitly historical, caller-selected estimate:

```sh
# Record an intentionally uncached baseline build (set the environment using
# your shell/platform's normal syntax).
NANOCOMPILE_DISABLE=1 python3 tools/cache_savings.py record \
  --binary /path/to/nanocompile --spec tasks.json --output baseline.json

python3 tools/cache_savings.py summary first.json second.json \
  --baseline baseline.json --attest-comparable --output estimate.json
```

The caller attests that the selected baseline files describe the **same
comparable workload**, not merely the same platform. The selected files must
form one platform/target cohort. Baselines must contain **either all successful
bypass tasks or all successful misses**, not a mixture; evaluated records must
also be successful. A caller may explicitly select earlier miss records in
place of `baseline.json` above, but an ordinary summary never does this silently.

The estimate is `baseline mean process wall × evaluated build count − evaluated
process wall sum`. It retains `baseline_kind`, baseline/evaluation sample counts,
`compiler_cache_condition: historical_uncontrolled`, `controlled_measurement:
false`, and fixed provenance `caller_selected_comparable_historical_bypass` or
`caller_selected_comparable_historical_miss`. A miss-based estimate answers the
hypothetical cost of repeating those historical misses, **not** the benefit over
a warm compiler cache. Misses include lookup/hashing/storage overhead and their
compiler-cache state may differ. Neither baseline supports a measured speedup
claim. External setup/transfer costs are explicitly excluded from this
process-wall estimate; their observed totals remain available separately.
Negative estimates are preserved.

## Controlled paired comparison

```sh
python3 tools/cache_savings.py compare \
  --binary /path/to/nanocompile --spec tasks.json \
  --prepare-json '["python3", "prepare.py"]' \
  --snapshot source.c --snapshot compile.py --snapshot prepare.py \
  --artifact output.o \
  --pairs 5 --compiler-cache-condition warm --attest-comparable \
  --output comparison.json
```

This is an actual execution harness, not an API that accepts claimed speedup
numbers. Each pair executes enabled and `NANOCOMPILE_DISABLE=1` builds; pair
order alternates `enabled,bypass` then `bypass,enabled`. The identical mandatory
prepare argv runs **before every individual build**, outside timed process wall.
Its actual elapsed cost is retained separately in `preparation.enabled_seconds`
and `preparation.bypass_seconds`, with sample counts and an explicit exclusion
from the process-speedup scope. This is measurement-harness preparation, not
unobserved/free CI setup. No shell interpretation is applied to this JSON argv array. Enabled runs remove
an inherited disable override; bypass reports must actually confirm bypass,
and enabled reports must not contain bypass tasks. You can prime the whole-task
cache before comparison if you want all enabled runs to be hits; otherwise the
measured enabled cohort may include legitimate misses, which remain visible.

`--compiler-cache-condition fresh|warm` and `--attest-comparable` are mandatory
caller assertions, **not automatic discoveries**:

- `fresh`: preparation must remove outputs and reset all relevant native/compiler
  caches before each run. Keep the intended whole-task cache state distinct.
- `warm`: preparation must reproduce the same warm native/compiler-cache state
  (for example, compile the exact same source with the exact compiler command),
  then remove the declared outputs before **each** timed run. Merely deleting
  output files or running one warmup before the entire comparison is insufficient.
- List every relevant immutable project source, configuration and preparation
  script using repeatable `--snapshot` options. Small installed tool-resource
  files can also be included; larger trusted installations must be kept stable
  externally throughout the comparison. The specification
  itself is always included. Files must be regular, non-symlink files. Snapshot
  lists are caller-attested complete; this is not automatic dependency discovery
  or a filesystem sandbox. Tool installations/environment and concurrent system
  activity must remain comparable. Account for compiler caches outside the
  checkout explicitly.
- List all final outputs via repeatable `--artifact` options. The harness checks
  exact bytes and permission bits in memory, never retaining artifact hashes,
  paths or contents in reports. Input/spec bytes and permissions must match the
  initial snapshot before/after each preparation and build. Changes reverted
  between observations cannot be detected. Memory usage scales with explicitly
  listed file sizes; use a focused fixture, not an entire tool installation tree.

Any failed preparation/build, unavailable report, snapshot change, unconfirmed
bypass, output byte/permission mismatch or zero process duration rejects the
comparison without writing a speedup result. Output equality is checked within
each pair. These checks are stronger than comparing unrelated historical runs,
but comparability still depends on truthful, complete caller assertions.

The comparison reports both cohorts' observed metrics/counts and a
`measured_speedup` object: pair count, compiler-cache condition, fixed provenance,
`ratio_bypass_over_enabled = summed bypass wall / summed enabled wall`, and
`saved_seconds = summed bypass wall − summed enabled wall`. Ratios below one and
negative savings are retained. This measures **process wall only**, not
preparation/external setup/transfer, and is not a universal performance claim or
statistical confidence interval.

## Explicit anonymous aggregate export

```sh
python3 tools/cache_savings.py export run1.json run2.json run3.json run4.json run5.json \
  --opt-in-anonymous-export --output anonymous-summary.json
```

Export requires the explicit opt-in flag and at least **five recorded build
samples**. It recomputes a strict allowlist from records, never forwarding unknown
fields or arbitrary precomputed summaries. Only aggregate metrics/counts and
coarse platform/target categories are written. There are no per-run records,
paths, names, arguments, environment values, cache keys, hashes, logs or stable
machine/session IDs. Historical estimates and controlled comparison documents
are deliberately not accepted as export input.

Every platform/target breakdown requires five samples; smaller groups are omitted
entirely. Each exposed optional metric also needs five actual observations;
otherwise its aggregate is `null`. An observed failure/status count is part of
the overall aggregate, not a per-failure record. These thresholds are small-cohort
suppression, **not differential privacy**. Do not create repeated overlapping
exports to reconstruct small groups, and do not count copies of one build record
as independent samples. Without persistent identifiers the tool cannot prove
sample independence. Timing and size values may still characterize a workload;
review the final file before sharing.

**There is no network sender.** `--output` is an ordinary local filesystem path;
stdout is the default for all commands. A user may separately choose to upload
the exported file. A GitHub Actions artifact remains attached to its repository,
workflow run and account: restricting its **file contents** to anonymous
aggregates does not make hosted artifact metadata anonymous or unlinkable.
No upload should include raw records, specifications or child logs. Any optional
CI publishing step must be separately and explicitly opted into, default off.

## Checks and integration

```sh
python3 tests/cache_savings.py
python3 -m py_compile tools/cache_savings.py tests/cache_savings.py
```

Unit tests cover missing costs, inclusive timer handling, numeric validation,
historical miss/bypass provenance and baseline rejection, negative savings,
failed commands, explicit export consent, five-sample suppression,
unknown-field/privacy attacks, paired ordering, measured preparation costs,
preparation failure, source changes and output byte/permission mismatches.

The real Zig object-build fixture records a miss and five deleted-output hits,
then executes five alternating pairs against freshly primed **warm Zig compiler
caches**. It verifies output bytes/permissions, separate native stage timings,
artifact size, estimate/measured labels, measured preparation, privacy canaries,
export consent and insufficient-cohort rejection:

```sh
python3 tests/cache_savings_integration.py zig-out/bin/nanocompile \
  --summary local-fixture-summary.json
# Optional: include an actually measured external setup report; attribute it once.
# Add --setup-report setup-report.json
# Optional LOCAL export, not an upload:
# Add --anonymous-output anonymous-fixture-summary.json
```

Without a setup report the initial external setup cost remains unknown. Later
builds have zero additional external setup; no external cache transfer occurs.
The fixture reports command/process timing, not pure compiler CPU time, and
makes no production speedup guarantee. Its installed Zig resources are fully
declared in the task, and their trusted installation must remain stable. Native
Linux/macOS/Windows validation requires executing the fixture on each host.

The [manual CI example](../.github/workflows/cache-savings.yml) coordinates with
[#6's setup helper](ci-setup.md). It measures verified Zig download/installation
and revision-pinned executable setup, adds their observed wall cost once to the
repeated-build series, and records native lookup/restore/build timings. It does
not use remote executable/artifact-cache transport, so the fixture's external
cache-transfer cost is explicitly zero. Git checkout, runner provisioning/queue
time, observer Python startup and artifact upload are outside these build/setup
measurements. Adapt those boundaries and record transfer costs before claiming
a complete CI-job speedup.

The workflow runs only on manual dispatch. `publish_summary` defaults to **false**;
no measurement artifact is uploaded in that mode. Setting it to true explicitly
creates and uploads only the allowlisted aggregate file, with a seven-day
retention setting. Raw records, specs, setup reports (which can contain keys and
hashes), and command logs are never selected for upload. The shared payload
contains no estimated or measured speedup claims; those require reviewing the
local baseline/comparison context. GitHub artifact metadata still identifies
its repository/run/account, as explained above. To disable publication leave the
input false; locally, omit `export`/`--anonymous-output`. No persistent opt-in
setting is stored.

All outputs must use fresh filenames: writes are exclusive, not append/overwrite.
