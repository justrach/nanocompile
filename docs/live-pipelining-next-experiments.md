# Instructions for the next variation

compile_time_ms on cache hits can describe the stored original compilation; stage summaries exclude hit/dup compile_time_ms. Per-unit medians are scheduling-sensitive, unpaired diagnostic observations. Request durations overlap. Missing counterparts are unknown, not zero. No optimization or overall speed win is established by this capture.

Reproduce the captured configuration and freeze its exact binary as the experiment baseline. Also compare against the accepted production binary. Change one measured cause at a time. Preserve full content hashing, loader selection, native include discovery and artifact validation. Never optimize by skipping an unverified input.

Investigate these observed Nano-minus-kache interval gaps; a long overlapping interval does not establish critical-path savings:

- cold / cargo / todo / pin-project-lite 0.2.17  features=: 0.410000s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / rustls: 0.408761s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / cfg_if: 0.404146s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / stable_deref_trait: 0.400188s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / cfg-if 1.0.4  features=: 0.400000s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / rustls 0.23.45  features=ring,std,tls12: 0.400000s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / pin_project_lite: 0.395403s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / stable_deref_trait 1.2.1  features=: 0.390000s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / unicode-ident 1.0.24  features=: 0.390000s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / unicode_ident: 0.389356s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / smallvec 1.15.2  features=const_generics,const_new: 0.380000s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / smallvec: 0.379185s median interval gap; samples Nano=1, kache=1.

Kache service stage measurements (sums overlap and do not predict wall savings):

{"build": 2, "phase": "cold", "results": {"dup": 1, "miss": 210, "passthrough": 13}, "stages": {"compile_time_ms": {"median_ms": 136, "samples": 223, "sum_ms": 78290}, "daemon_store_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 198}, "dep_info_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 0}, "elapsed_ms": {"median_ms": 182.5, "samples": 224, "sum_ms": 85442}, "flight_wait_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 0}, "key_ms": {"median_ms": 1.0, "samples": 224, "sum_ms": 949}, "lookup_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 0}, "permit_wait_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 158}, "restore_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 0}, "startup_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 92}, "store_ms": {"median_ms": 6.5, "samples": 224, "sum_ms": 2143}}}
{"build": 5, "phase": "warm", "results": {"local_hit": 187, "passthrough": 4}, "stages": {"compile_time_ms": {"median_ms": 0.0, "samples": 4, "sum_ms": 0}, "daemon_store_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "dep_info_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "elapsed_ms": {"median_ms": 6, "samples": 191, "sum_ms": 2567}, "flight_wait_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "key_ms": {"median_ms": 2, "samples": 191, "sum_ms": 1108}, "lookup_ms": {"median_ms": 0, "samples": 191, "sum_ms": 13}, "permit_wait_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "restore_ms": {"median_ms": 1, "samples": 191, "sum_ms": 714}, "startup_ms": {"median_ms": 0, "samples": 191, "sum_ms": 219}, "store_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}}}
{"build": 7, "phase": "warm", "results": {"local_hit": 187, "passthrough": 4}, "stages": {"compile_time_ms": {"median_ms": 0.0, "samples": 4, "sum_ms": 0}, "daemon_store_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "dep_info_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "elapsed_ms": {"median_ms": 6, "samples": 191, "sum_ms": 1873}, "flight_wait_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "key_ms": {"median_ms": 2, "samples": 191, "sum_ms": 1107}, "lookup_ms": {"median_ms": 0, "samples": 191, "sum_ms": 1}, "permit_wait_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "restore_ms": {"median_ms": 1, "samples": 191, "sum_ms": 211}, "startup_ms": {"median_ms": 0, "samples": 191, "sum_ms": 66}, "store_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}}}

Inspect the private compiler records and build-script logs for each candidate. Use kache service breakdowns to distinguish key, lookup, compile and restore costs; do not infer Nano stage costs from kache events. Add Nano phase instrumentation if that distinction is missing.

Require repeated alternating untraced cold and warm pairs, actual source edits and reverts, zero cold hits, expected warm coverage, unchanged source hashes, and matching own-cold artifact bytes. Report rejected variations and uncertainty. Promote only repeatable improvements without correctness regressions.
