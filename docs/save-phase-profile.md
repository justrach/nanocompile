# Cold Rust dependency-graph costs

The [isolated phase session](../benchmarks/harness-save-phase-session.json) splits successful ordinary compiler saves into preexisting input checks, discovered source/directory handling, Rust graph collection and storage. It uses the accepted four-worker default, unchanged dirty Harness adapters snapshot, eight Cargo jobs, Rust 1.97.1 and the same explicit macro/producer and ring execution options as previous local comparisons. This is the adapters library workload.

[All phase records](../benchmarks/harness-save-phase-profile.json) contain 136 cold ordinary calls, 136 successful saves and 136 ordinary restores. Save intervals subdivide their containing miss interval; they must not be added to it. Concurrent calls overlap. Producers, native calls, script execution, failures and bypasses are excluded.

| Successful save phase | Median | Maximum |
| --- | ---: | ---: |
| Preexisting input revalidation | 0.466ms | 24.256ms |
| Source discovery and directory guards | 0.596ms | 26.063ms |
| Rust dependency-graph collection | 3.944ms | 247.536ms |
| Artifact storage | 2.131ms | 69.095ms |

The largest graph intervals are `futures_core` at 247.536ms, `harness_adapters` at 122.544ms and `futures_sink` at 106.437ms. Graph collection, rather than ordinary storage, accounts for the previously observed large save outliers. This does not prove that each graph interval is on the build's critical path. The [retained instrumentation](../benchmarks/experiments/save-phase-profile.patch) and [exact provenance](../benchmarks/experiments/save-phase-provenance.json) reproduce the diagnosis. Diagnostic timing and logging overhead exclude this session from production speed claims. All repeated warm artifacts match their own cold references and sources remain unchanged.

## Candidate under test

The [installed-root decoder variation](../benchmarks/experiments/direct-builtin-root.patch) reuses the existing exact-version `.rmeta` decoder for installed root classifications before attempting the existing compiler-query fallback. Only installed metadata takes this shortcut. Unknown versions, unsupported structures and non-`.rmeta` files keep the query fallback. The same compiler-scoped classification memo, complete installed-resource identity and before/after file-state checks remain mandatory. No persistent source-content shortcut is introduced.

[All 27 installed host metadata files](../benchmarks/direct-builtin-oracle.json) decode to complete roots and dependency graphs equal to actual rustc `-Zls=root`. Local unit tests and real Rust/Zig integration pass. [Selector and compiler-switch checks](../benchmarks/direct-builtin-scope.json) pass for Rust 1.97.1 and 1.98.1; the latter uses the version fallback. These checks establish candidate correctness on these fixtures, not a speedup. Repeated untraced Harness A/B comparisons are running before any promotion. Production remains the accepted query-based default.

## First untraced comparison

[Five alternating cold pairs](../benchmarks/harness-direct-builtin-cold-ab.json) give medians 16.092977s accepted baseline and 15.920009s candidate, approximately 1.1% lower, with 4/5 candidate wins. Mean paired saving is only 69ms; one candidate sample loses by 683ms. All observations are retained. Every cold build has 167 Rust misses and one script miss with zero hits. All 194 artifact sets match each binary's own prime; the sole cross-binary difference is the copied Nano ring launcher, while actual compiled scripts and other collected artifacts are equal. Sources remain unchanged.

[An explicit named-crate activation check](../benchmarks/direct-builtin-activation.json) records 19 direct installed-root decisions. An earlier fixture without a crate name bypassed and supplied no evidence; the corrected check uses a real eligible Rust call. The candidate binary SHA-256 is `eb23be7f672976fdb0da49fe158ad9f7f0ae0fdfbf6234c6683f1ec6339c2353`. A separate five-pair confirmation is running. This result is promising but insufficient for promotion; the accepted runtime stays unchanged.

## Confirmation: not promoted

[Five separate confirmation pairs](../benchmarks/harness-direct-builtin-cold-confirm.json) give medians 16.189019s baseline and 16.123392s candidate, with 4/5 candidate wins. The mean paired saving is negative 30ms; median paired saving is only 15ms. The large losing sample remains in the report. Together with the first batch, the mean improvement is about 20ms across ten pairs, too small and variable to establish a dependable additional whole-build gain. All 194 artifacts match own references; the sole cross-binary difference remains the copied ring launcher. Sources are unchanged.

The decoder remains experimental and is not promoted. The accepted default stays query-based. Broader full-application performance measurement now takes priority over further small adapters-only changes.
