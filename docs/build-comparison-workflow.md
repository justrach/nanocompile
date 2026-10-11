# Use full build logs to choose the next variation

The real Harness source-edit runner accepts `--trace-builds --compiler-profile`.
It records complete Cargo consoles, compiler arguments and stdout/stderr,
cache decisions, Cargo timings, Nano compiler phases and kache service events.
Cold, leaf edits, shared edits, reverts and empty-cache correctness references
have separate records. Failed builds and probes retain their output too.

Keep the private state directory with the report. Arguments and compiler output
can contain local paths or private source information; publish derived summaries
and integrity digests after reviewing them.

```sh
python3 tools/build_trace.py verify-logs /path/to/report.json --state /path/to/state
python3 tools/build_trace.py verify-capture /path/to/state/capture/0
python3 tools/build_trace.py analyze /path/to/report.json --output /path/to/timeline
python3 tools/build_trace.py analyze-edits /path/to/report.json \
  --state /path/to/state --output /path/to/variation-brief
```

Verify every capture directory, not just the first. The analysis emits a timeline
and diagnostic summaries; the edit analysis emits `analysis.json` and
`next-experiments.md`. Check coverage explicitly: direct Cargo builds retain
consoles and Cargo timings but do not intercept individual direct compiler
requests. Capture does not trace every syscall or arbitrary subprocess.

For each future variation:

1. Freeze the source snapshot, runtime hashes, toolchain, flags, job count and
   native input contracts. Retain all samples, failures and rejected candidates.
2. Reproduce the largest loss with alternating **untraced** Nano/kache builds.
   Use a separate matched trace to identify the requests and phases involved.
3. Change one measured cause. Preserve full input validation and safe fallback.
4. Require artifact bytes/modes, expected behavior, edits/reverts, corruption,
   failed compilation and concurrent restore checks.
5. Compare the candidate against frozen Nano and kache, then confirm in an
   independent session before adopting it.

Compiler request spans overlap. Nano phase boundaries and kache service fields
also describe different operations, and service events lack a shared request ID.
Do not sum these durations into promised whole-build savings. Trace overhead,
single observations and resumed sessions remain explicit limitations.

The current shared-edit investigation and measured storage observations are in
[producer-shared-digests-investigation.md](producer-shared-digests-investigation.md).
The untraced source-edit results and next-variation brief are in
[full-harness-source-edit-next-variation.md](full-harness-source-edit-next-variation.md).
