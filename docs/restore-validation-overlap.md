# Input/output verification overlap

Large restores start one private-arena worker to hash immutable output blobs while the caller validates every dependency. The existing input-hash pool remains bounded to four workers; total verification concurrency is at most five per compiler invocation. The overlap threshold is at least 32 dependency records and 1 MiB of output blobs. Smaller restores retain the serial path.

The worker shares no mutable allocator or hash map. Every early rejection cancels/joins its group; successful restoration joins before any materialization. Output destination checks, input content hashes, directory/negative/symlink guards, diagnostic hashes and all output blob hashes remain. Entry/key schemas are unchanged. The enlarged unit fixture exercises input changes, corrupt large output blobs and missing inputs while verifying that existing destinations remain untouched.

| Workload | Baseline median | Candidate median | Wins |
| --- | ---: | ---: | ---: |
| Metadata-heavy Rust fixture, 27 pairs | 48.320 ms | 42.715 ms | See raw samples |
| Complete Harness, first 27 pairs | 2.077061 s | 2.034227 s | 21/27 |
| Complete Harness, independent 27 pairs | 2.078197 s | 2.035141 s | 23/27 |

Both Harness batches reduce medians by about 2.1%, with 44/54 pair wins. Mean paired savings are 50.65 ms and 43.68 ms; descriptive standard errors are 18.00 ms and 24.63 ms. These local dependent samples do not establish a universal gain. Each warm build records 167 Rust and 24 native hits; all 193 artifacts match, and tracked sources remain unchanged. This is a warm optimization; lower candidate prime times are retained as observations, not claimed cold gains.

[Fixture samples](../benchmarks/restore-validation-overlap-first.json), [Harness first batch](../benchmarks/harness-restore-overlap-first.json), [Harness confirmation](../benchmarks/harness-restore-overlap-confirm.json), [fixture runner](../benchmarks/experiments/restore_overlap_pair.py) and [Harness runner](../benchmarks/experiments/restore_overlap_harness_pair.py) retain provenance. The experiment used the same accepted native adapter, fixed wrapper/cache/target paths, separately primed binary-specific producer caches, alternating order, four Cargo jobs and a 40 GiB RSS cap. Production adopts the measured verification algorithm; additional portable/task dispatch and stats do not remove any checks.
