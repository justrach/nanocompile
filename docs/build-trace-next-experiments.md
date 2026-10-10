# Instructions for the next variation

compile_time_ms on cache hits can describe the stored original compilation; stage summaries exclude hit/dup compile_time_ms. Per-unit medians are scheduling-sensitive, unpaired diagnostic observations. Request durations overlap. Missing counterparts are unknown, not zero. No optimization or overall speed win is established by this capture.

Use the installed production binary as baseline. Change one measured cause at a time. Preserve full content hashing, loader selection, native include discovery and artifact validation. Never optimize by skipping an unverified input.

Investigate these observed Nano-minus-kache interval gaps; a long overlapping interval does not establish critical-path savings:

- warm / cargo / run-custom-build / ring 0.17.14  build-script (run) features=alloc,default,dev_urandom_fallback: 1.230000s median interval gap; samples Nano=2, kache=2.
- cold / cargo / todo / quote 1.0.47  build-script features=default,proc-macro: 0.930000s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / cfg-if 1.0.4  features=: 0.930000s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / cfg_if: 0.927392s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / stable_deref_trait: 0.927375s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / proc-macro2 1.0.107  build-script features=default,proc-macro: 0.920000s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / stable_deref_trait 1.2.1  features=: 0.920000s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / unicode-ident 1.0.24  features=: 0.920000s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / pin_project_lite: 0.918966s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / unicode_ident: 0.916357s median interval gap; samples Nano=1, kache=1.
- cold / request / rust / smallvec: 0.910761s median interval gap; samples Nano=1, kache=1.
- cold / cargo / todo / smallvec 1.15.2  features=const_generics,const_new: 0.910000s median interval gap; samples Nano=1, kache=1.

Kache service stage measurements (sums overlap and do not predict wall savings):

{"build": 2, "phase": "cold", "results": {"dup": 1, "miss": 210, "passthrough": 13}, "stages": {"compile_time_ms": {"median_ms": 113, "samples": 223, "sum_ms": 72022}, "daemon_store_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 141}, "dep_info_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 0}, "elapsed_ms": {"median_ms": 138.0, "samples": 224, "sum_ms": 78471}, "flight_wait_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 0}, "key_ms": {"median_ms": 1.0, "samples": 224, "sum_ms": 959}, "lookup_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 0}, "permit_wait_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 129}, "restore_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 0}, "startup_ms": {"median_ms": 0.0, "samples": 224, "sum_ms": 227}, "store_ms": {"median_ms": 5.0, "samples": 224, "sum_ms": 1742}}}
{"build": 5, "phase": "warm", "results": {"local_hit": 187, "passthrough": 4}, "stages": {"compile_time_ms": {"median_ms": 0.0, "samples": 4, "sum_ms": 0}, "daemon_store_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "dep_info_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "elapsed_ms": {"median_ms": 5, "samples": 191, "sum_ms": 2167}, "flight_wait_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "key_ms": {"median_ms": 2, "samples": 191, "sum_ms": 1062}, "lookup_ms": {"median_ms": 0, "samples": 191, "sum_ms": 8}, "permit_wait_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "restore_ms": {"median_ms": 1, "samples": 191, "sum_ms": 560}, "startup_ms": {"median_ms": 0, "samples": 191, "sum_ms": 59}, "store_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}}}
{"build": 7, "phase": "warm", "results": {"local_hit": 187, "passthrough": 4}, "stages": {"compile_time_ms": {"median_ms": 0.0, "samples": 4, "sum_ms": 0}, "daemon_store_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "dep_info_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "elapsed_ms": {"median_ms": 5, "samples": 191, "sum_ms": 1719}, "flight_wait_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "key_ms": {"median_ms": 2, "samples": 191, "sum_ms": 1044}, "lookup_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "permit_wait_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}, "restore_ms": {"median_ms": 1, "samples": 191, "sum_ms": 159}, "startup_ms": {"median_ms": 0, "samples": 191, "sum_ms": 48}, "store_ms": {"median_ms": 0, "samples": 191, "sum_ms": 0}}}

Inspect the private compiler records and build-script logs for each candidate. Use kache service breakdowns to distinguish key, lookup, compile and restore costs; do not infer Nano stage costs from kache events. Add Nano phase instrumentation if that distinction is missing.

Require repeated alternating untraced cold and warm pairs, actual source edits and reverts, zero cold hits, expected warm coverage, unchanged source hashes, and matching own-cold artifact bytes. Report rejected variations and uncertainty. Promote only repeatable improvements without correctness regressions.

## Build-script execution candidate

Warm Nano issues [24, 24] native requests per round; kache issues [0, 0]. Inspect per-package build_script_run events, build-script intervals and own-cold native artifact checks. Investigate build-script execution reuse after verifying the exact mechanism and input contract. Native bundle audit fields alone do not prove execution reuse. Require an ablation before estimating whole-build impact. Require C/header/assembly include edits, toolchain/loader changes, environment changes and output tampering to invalidate correctly. Missing native requests alone do not prove the mechanism or a speed win.
