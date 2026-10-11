# Producer postcompile digest-sharing investigation

The [initial full-Harness cold profile](../benchmarks/harness-full-app-source-edit-initial-cold-profile.json)
verified 4,997 captured files, 1,145 compiler requests and 1,237 Cargo units.
The final executable producer spends 66.419639s executing the compiler,
3.184994s in postcompile storage, 0.230052s staging input snapshots and
0.068585s collecting linked inputs. Its total is 69.946907s. These nested
observations cannot be added to project time or turned into a promised saving.
The full traced source-edit sequence completed all 18 builds, including its
fresh-output and revert gates. Independent verification checked 18 consoles,
72,418 captured files and 36 probe streams, with all four source checks passing.
The [analysis](../benchmarks/harness-full-app-source-edit-phase-analysis.json)
retains every observation. The shared-edit diagnostic gap is 6.433536s against
Nano. This resumed session is not an untraced performance comparison.

`compiler.save` collects each direct Rust dependency root separately. Every call
creates a fresh metadata resolver seeded with the directly validated inputs;
additional transitive digests discovered in one root walk are discarded before
the next. This is a candidate source of repeated work, not a measured attribution
of all 3.184994s.

A private prototype shares only those fresh digest/file-state maps across root
walks within the same successful entry construction. Each reuse still validates
file state, each root retains its own metadata classification and directory
guards, and the maps are discarded after that entry. It is default-off and
built for initial validation; production is unchanged. Build, unit and executable
smoke checks run before the multi-root fixture and isolated cold pairs. That
validation alone will not justify adoption.

Initial validation and the actual multi-root fixture have now passed. The
[verified correctness summary](../benchmarks/producer-shared-digests-correctness.json)
records equal sealed dependency payloads and output bytes/modes with sharing off
and on, a shared-transitive edit with preserved mtime, corrupt input failure,
revert behavior and four concurrent restores. All 58 fixture streams and five
smoke logs passed digest verification. The fixture has no within-invocation
mutation race hook. Isolated cold pairs are running; no speed improvement or
production adoption is established.

The [exact experimental patch](../benchmarks/experiments/producer-shared-digests.patch)
has SHA-256 `ccba043908e86662c5902fae984078d61e3585db264bb9ac3f9f99ec1e8ee161`.
It was applied to the frozen eight-worker producer-profile source, not adopted in
production. The [portable isolated runner](../benchmarks/experiments/harness_producer_shared_digests_cold_pair.py)
uses the same candidate binary for both controls, toggling only
`NANOCOMPILE_PRODUCER_SHARED_DIGESTS`. It requires a completed source-edit report
and existing captured request/dependencies. Empty entry namespaces force actual
compilation; reader/toolchain memos remain warm in measured pairs. Fresh primes
and final cold confirmations are retained separately. The executed private runner
has its own recorded hash; the portable copy changes only import paths.

Require an actual multi-root shared-transitive-input fixture, mutation/revert and
preserved-mtime replacement checks, failures/corruption/concurrency gates, and an
isolated replay of the captured final request. Compare both controls using the
same binary and flags with the experimental setting toggled, ensuring real
postcompile misses and identical dependency/output manifests. Then run repeated
alternating full-Harness comparisons against frozen Nano and kache, followed by
independent confirmation. Reject unknown coverage, changed outputs or repeatable
regressions. The shared-edit loss still has no established cause.

## Matching shared-edit observations

The [verified partial source-edit observations](../benchmarks/harness-full-app-source-edit-nano-phase-observations.json)
now include Nano's own fresh leaf/shared reference checks and kache's matching
shared-edit capture. Nano's final `harness` request takes 71.657s and kache's
68.525s. Nano records compiler execution 67.621s, postcompile storage 3.187s and
previous-entry validation 0.485s. Kache's nearby `harness` miss service event
records compiler time 67.961s, key work 0.494s and storage 0.058s. These categories
have different scopes and are not joined by request IDs. The storage difference
is a useful hypothesis; it does not establish a whole-build causal saving.

`harness_ui` request time is 30.886s Nano versus 26.874s kache; Nano's execution
and stream forwarding stage is 29.642s, while kache's compiler service reports
26.624s. Inspect scheduling and competing work before attributing that compiler
variation to a wrapper feature. Request spans overlap.

Kache reports reflinked outputs with zero copied bytes for both requests. Nano
already attempts macOS `clonefile` in `cache.materialize`; this observation does
not establish a missing clone operation or a copy bottleneck in Nano. Split graph
collection from output storage if the digest-sharing trial cannot explain the
measured cost. The private two-root shared-transitive fixture is prepared and
queued, with exact payload/output comparisons, preserved-mtime replacement,
corruption/failure, revert and concurrent restore cases; it has not run yet.

The traced project observations are 127.506s Nano and 121.072s kache. They are
single diagnostic samples, not repeated untraced speed benchmarks. Kache's own
fresh shared reference, direct shared reference, reverts and final source
restoration checks remain pending in this sequence.

## Storage checkpoint recovery

The [storage-recovery record](../benchmarks/harness-source-edit-profile-storage-recovery.json)
preserves the storage-guard failure before build 13: 6.82GiB free against an 8GiB
minimum. All 12 completed consoles/captures, probe streams and original source
hashes were verified before resuming. Kache's fresh shared reference passed its
own artifact/mode checks. An older completed native-script session's six captures
and logs were verified and its final CLI/signature preserved before reclaiming
its target and object caches. Its logs, entries, receipts and captured streams
remain available.

A private checkpoint runner is executing the six remaining builds at the same
source, target, cache and capture paths. It validates the recorded runtime,
toolchain, flags, native contract, bindgen selection and source hashes; rehydrates
artifact references from completed rows; and skips only the verified prefix.
The original failed report, console and stopped dependent queue states are
retained. The resume runner hash is recorded separately. Inherited environment
equality across the pause is not established, so the combined observations remain
diagnostic. Revert and final source-restoration checks subsequently passed.
