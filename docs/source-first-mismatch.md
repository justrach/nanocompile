# Source-first hashing after a real Harness edit

Source prioritization reduces measured rejection work, but this experiment does **not** establish faster builds. It adds a small observed warm-hit cost, and unrelated work overlaps the edited builds. The candidate remains separate from production. [All samples and verification](../benchmarks/harness-source-first-mismatch-diagnostic.json) are retained.

The [default-off patch](../benchmarks/experiments/source-first-mismatch.patch) extends the earlier mismatch-stop experiment. With both `NANOCOMPILE_HASH_MISMATCH_STOP=1` and `NANOCOMPILE_HASH_SOURCE_FIRST=1`, small `.rs` and `.zig` files are hashed before other inputs in sufficiently large graphs. Both groups preserve their original ordering. A proven content mismatch rejects the entry after running workers join; hits still require all hashes and guards. The maximum remains eight experimental input workers. Producer digest sharing is disabled.

The same binary runs both controls, with early rejection enabled in both and source ordering toggled at zero/one. Each setting has its own original-source prime because the complete environment is part of the key. Nine warm pairs and five real CLI-help edit pairs alternate order. The source edit preserves modification time. Both revert hits and every edited output match their respective fresh reference bytes, modes and direct CLI behavior.

| Isolated diagnostic | Original order median | Source-first median | Mean paired saving |
| --- | ---: | ---: | ---: |
| Rejected lookup: input hashing | 96.616 ms | 5.310 ms | 92.173 ms |
| Complete rejected producer lookup | 104.657 ms | 13.296 ms | 92.116 ms |
| Warm request | 263.043 ms | 263.719 ms | −2.544 ms |
| Edited request, including compilation | 36.898 s | 38.115 s | −0.408 s |

Both rejection phases favor source-first in all five pairs, with descriptive standard errors of 0.987 ms and 1.080 ms. These phases are nested; do not add them. Warm requests favor the candidate in three of nine pairs, with 1.273 ms standard error on mean paired savings. Edited requests favor it in two of five pairs, with 1.257 s standard error. Compiler execution dominates total variation. These are observations from an isolated compiler request, not full Cargo or kache comparisons.

The host observer covers all 37 executions and retains [545 aggregate snapshots](../benchmarks/harness-source-first-host-activity.jsonl). External build tools appear in 301 snapshots and overlap eight of ten edited executions. Most short warm requests fall between snapshots; the few observed warm intervals also show substantial other CPU activity. Zero observations within an interval do not establish an idle host. Every sample remains included, and these timings cannot justify adoption.

Independent verification checks 148 compiler/CLI streams, 2,158 prebuilt inputs, 883 source files, all 95 candidate source files, exact runtime/runner hashes, activation and rejection markers, paired statistics, final output bytes/modes, and source restoration. Initial build, unit and executable-cache fixtures pass, including thin LTO and retained jobs. Codesign and direct CLI checks pass throughout the real request sequence.

Reproduce the runtime source from `d88cdca` by applying the eight-worker, producer-shared-digests, early-hash-mismatch and source-first patches in that order; leave shared digests disabled. The report retains all source/patch hashes and notes two unrelated benchmark-helper differences in the private snapshot. Raw streams and invocation records remain in `/tmp/nano-source-first-mismatch-harness-paired-20261011`; runner, controls, verifier and host observations are in `/tmp/nano-source-first-mismatch-harness-preparation-20261011`.

The next investigation targets the repeated whole-build warm deficit with a matched Nano/kache trace. Source ordering cannot improve an empty-cache lookup and has shown no warm-hit gain here. Keep it experimental until a quiet, independently confirmed full-workload comparison supports its cost.
