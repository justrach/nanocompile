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

Future variations should reproduce the largest observed loss, identify its
actual request/stage, change one cause, and pass artifact, source-edit, revert,
failure, corruption and concurrency gates. Require alternating comparisons
against the frozen Nano baseline and kache plus independent confirmation.
A single sequence cannot establish repeatable performance or justify adoption.
