# Complete logs and source-edit experiment instructions

The source-edit runner saves each complete Cargo console, including failed builds,
with its byte count and SHA-256. Linked behavior probes retain their command and
stdout/stderr separately. Keep these private captures alongside the benchmark
report; a public summary does not replace them.

Generate an integrity-checked comparison and a brief for the next variation:

```sh
python3 tools/build_trace.py analyze-edits /path/to/report.json \
  --state /path/to/private-build-state --output /path/to/analysis
```

`analysis.json` retains every observed sample, console digest, cache counts,
artifact/behavior check flags, tool identities and report hash.
`next-experiments.md` separates cold, leaf edit, shared edit and revert timings.
Fresh-cache correctness references are retained separately. Incomplete sessions
are marked provisional; failed or missing comparisons have no timing gap.
Duplicate samples are rejected instead of silently replacing observations.

Use `build_trace.py capture` and `analyze` for full compiler/Cargo timelines and
request-level attribution. Console logs alone cannot explain a timing gap.
Keep traced diagnostic runs separate from untraced speed trials, and preserve
failed captures. Compiler phase profiling is opt-in and adds overhead.

Request comparisons and timeline labels retain the source-edit scenario and
fresh-reference status. Leaf/shared edits and reverts are never pooled solely
because they share an `edit` phase. Fresh references remain visible but do not
generate performance-optimization priorities. Missing same-scenario counterparts
have no timing gap.

The completed Harness capture was reanalyzed with these guards: 11,688 distinct
comparison groups and no excluded builds. The
[selected request observations](../benchmarks/harness-full-app-source-edit-request-observations.json)
retain every scenario/reference comparison for the final executable, UI, engine
and adapters, plus their execution/storage/total profiles and stream hashes.
The highest shared-edit request gaps remain UI (4.012s) and final Harness
(3.131s). Their intervals overlap and are diagnostic; do not add them into
projected build savings. The full private timeline and filterable HTML are at
`/tmp/nano-full-harness-source-edit-phase-timeline-20261011`.

The actual source-edit runner also accepts `--trace-builds --compiler-profile`.
Add both flags to the recorded `tests/harness_full_source_edits.py` invocation
to retain complete compiler arguments, stdout/stderr and Cargo timelines across
the full cold/leaf/shared/revert sequence and fresh-output checks. Update explicit
native-contract `RUSTC_WRAPPER` guards to the resolved state path
`capture/nanocompile/nanocompile`; the capture frontend transparently invokes the
selected frozen runtime. Verify coverage rather than assuming those guards still
match. The full traced integration session completed all 18 builds. Independent
verification covered 18 consoles, 72,418 captured files and 36 linked-probe
streams; all four source-preservation/restoration checks passed. See the
[analysis](../benchmarks/harness-full-app-source-edit-phase-analysis.json) and
[verification ledger](../benchmarks/harness-full-app-source-edit-phase-verification.json).
The run resumed after a storage preflight failure; inherited environment equality
across that pause is unproven. Its timings remain diagnostic.

Future variations should reproduce the largest observed loss, identify its
actual request/stage, change one cause, and pass artifact, source-edit, revert,
failure, corruption and concurrency gates. Require alternating comparisons
against the frozen Nano baseline and kache plus independent confirmation.
A single sequence cannot establish repeatable performance or justify adoption.
