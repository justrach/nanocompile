# Live sysroot/root query overlap: not adopted

A fresh [current graph profile](selected-resource-graph-profile.md) shows that two sequential live Rust subprocesses dominate aggregate graph time: selected sysroot/target-libdir discovery and own-artifact root decoding. The candidate overlaps their execution without removing either query.

The toolchain fingerprint retains its validated selected sysroot in memo schema 6 and the compilation context. Root decoding starts with that root pinned in its private diagnostic directory. The original-cwd live selection query runs concurrently using a separate allocator. Both tasks join before metadata is used; a disagreeing live root rejects cache storage. Complete compilation fingerprints and selected-resource decoder identities remain unchanged. Memo schema 5 is rejected and re-fingerprinted by the candidate. All selector/resource stamp checks, mutable hashes and directory/library guards remain.

Stable Zig 0.17.0 unit and real Rust/Zig integration pass. [Scope checks](../benchmarks/root-overlap-scope-check.json) verify byte-identical complete fingerprints against the installed version, selector add/remove transitions, actual Rust 1.97.1/1.98.1 changes and 19 reused toolchain classifications. A [native-proxy disagreement fixture](../benchmarks/root-overlap-selection-check.json) proves that a changed live root leaves successful compiler output available, stores no entry and recompiles on the second clean build. [Build/check provenance](../benchmarks/root-overlap-checks.json) identifies the candidate executable and source hashes.

## Controlled cold comparison

Six builds comprise three alternating pairs, on the same dirty Harness checkout `32b41cb0bff55e3c9cbfab3012acec2b179ad199`. Each build removes both target and entire cache; both Rust executables occupy the same wrapper path, with an identical environment and fixed installed native adapter. Four Cargo jobs and the 40 GiB RSS cap remain. Source revision for the baseline is `a21296b29e8d6da3995d22f234ff8999a726a166` (same production code as `3fdc906`).

| Pair | Serial baseline | Overlap candidate | Baseline minus candidate |
| --- | ---: | ---: | ---: |
| 1 | 30.813831 s | 29.389028 s | +1.424803 s |
| 2 | 28.523041 s | 29.393635 s | −0.870594 s |
| 3 | 29.641243 s | 29.643028 s | −0.001784 s |

The candidate wins **1/3 pairs**. Medians are **29.641243 s baseline and 29.393635 s candidate**, about 0.84% apart. Median paired saving is −0.001784 s, mean saving 0.184142 s and descriptive standard error 0.669113 s. This small mixed batch does not establish a repeatable end-to-end improvement, so the candidate is **not adopted**. A lower median alone is insufficient evidence.

All six builds retain zero Rust/native hits and match all 193 Rust, producer and native artifacts. Tracked sources/manifests/lockfile remain unchanged. This experiment measures the candidate against Nano's predecessor, not kache; it does not establish a new kache comparison.

[All samples](../benchmarks/harness-root-overlap-cold-first.json), [candidate patch](../benchmarks/experiments/root-query-overlap.patch), [cold runner](../benchmarks/experiments/root_overlap_cold_pair.py), [scope fixture](../benchmarks/experiments/root_overlap_scope_check.py) and [disagreement fixture](../benchmarks/experiments/root_overlap_selection_check.py) make the rejected approach inspectable. Production source and installed binary remain unchanged.
