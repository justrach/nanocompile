# Instructions for the next variation

compile_time_ms on cache hits can describe the stored original compilation; stage summaries exclude hit/dup compile_time_ms. Per-unit medians are scheduling-sensitive, unpaired diagnostic observations. Request durations overlap. Missing counterparts are unknown, not zero. No optimization or overall speed win is established by this capture.

Reproduce the captured configuration and freeze its exact binary as the experiment baseline. Also compare against the accepted production binary. Change one measured cause at a time. Preserve full content hashing, loader selection, native include discovery and artifact validation. Never optimize by skipping an unverified input.

Investigate these observed Nano-minus-kache interval gaps; a long overlapping interval does not establish critical-path savings:

- cold / cargo / todo / proc-macro2 1.0.107  build-script features=default,proc-macro: 0.370000s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / cfg-if 1.0.4  features=: 0.370000s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / quote 1.0.47  build-script features=default,proc-macro: 0.370000s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / stable_deref_trait 1.2.1  features=: 0.370000s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / unicode_ident: 0.367494s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / stable_deref_trait: 0.365965s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / pin_project_lite: 0.364782s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / cfg_if: 0.363485s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / pin-project-lite 0.2.17  features=: 0.360000s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / unicode-ident 1.0.24  features=: 0.360000s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / libc 0.2.189  build-script features=default,std: 0.350000s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / smallvec: 0.343850s median interval gap; samples Nano=1, kache=1.

Kache service stage measurements (sums overlap and do not predict wall savings):

{"build": 2, "phase": "cold", "results": {"dup": 1, "miss": 210, "passthrough": 13}, "stages": {"compile_time_ms": {"median_ms": 112, "samples": 223, "sum_ms": 69759}, "daemon_store_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 219}, "dep_info_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 0}, "elapsed_ms": {"median_ms": 139.5, "samples": 224, "sum_ms": 76087}, "flight_wait_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 0}, "key_ms": {"median_ms": 1.0, "samples": 224, "sum_ms": 937}, "lookup_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 0}, "permit_wait_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 164}, "restore_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 0}, "startup_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 233}, "store_ms": {"median_ms": 5.0, "samples": 224, "sum_ms": 1707}}}
{"build": 5, "phase": "warm", "results": {"local_hit": 187, "passthrough": 4}, "stages": {"compile_time_ms": {"median_ms": 0.0, "samples": 4, "sum_ms": 0}, "daemon_store_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "dep_info_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "elapsed_ms": {"median_ms": 6, "samples": 191, "sum_ms": 2219}, "flight_wait_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "key_ms": {"median_ms": 2, "samples": 191, "sum_ms": 1051}, "lookup_ms": {"median_ms": 0, "samples": 191, "sum_ms": 4}, "permit_wait_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "restore_ms": {"median_ms": 1, "samples": 191, "sum_ms": 593}, "startup_ms": {"median_ms": 0, "samples": 191, "sum_ms": 78}, "store_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}}}
{"build": 7, "phase": "warm", "results": {"local_hit": 187, "passthrough": 4}, "stages": {"compile_time_ms": {"median_ms": 0.0, "samples": 4, "sum_ms": 0}, "daemon_store_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "dep_info_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "elapsed_ms": {"median_ms": 5, "samples": 191, "sum_ms": 1795}, "flight_wait_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "key_ms": {"median_ms": 2, "samples": 191, "sum_ms": 1105}, "lookup_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "permit_wait_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "restore_ms": {"median_ms": 1, "samples": 191, "sum_ms": 156}, "startup_ms": {"median_ms": 0, "samples": 191, "sum_ms": 60}, "store_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}}}

Inspect the private compiler records and build-script logs for each candidate. Use kache service breakdowns to distinguish key, lookup, compile and restore costs; do not infer Nano stage costs from kache events. Add Nano phase instrumentation if that distinction is missing.

Require repeated alternating untraced cold and warm pairs, actual source edits and reverts, zero cold hits, expected warm coverage, unchanged source hashes, and matching own-cold artifact bytes. Report rejected variations and uncertainty. Promote only repeatable improvements without correctness regressions.


## Remaining warm script cost

The same capture reports ring's warm run-custom-build interval at Nano 0.150s versus kache 0.045s over two samples. The automatic top-twelve ranking is dominated by cold startup gaps; retain this warm lead for a separate experiment. Instrument mutable-input snapshot hashing, live xcrun/helper selection, installed SDK stamp validation, entry/blob verification, staging/publication and stream replay separately. Freeze this candidate and compare one variation against it, accepted production and kache using untraced alternating pairs. Preserve all declared mutable contents, negative lookups, installed links, tool/loader selection and output checks. Do not replace mutable content hashing with a persistent metadata shortcut. Verify permission failures, corruption, real edits/reverts and fresh-cache reference outputs before claiming a gain.
