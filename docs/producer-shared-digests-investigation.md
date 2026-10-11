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
mutation race hook. The subsequent isolated cold result is recorded below;
production adoption is not established.

## Five isolated cold pairs completed

The [verified comparison](../benchmarks/harness-producer-shared-digests-cold-paired.json)
contains 15 executions: direct, separate cold primes, five alternating pairs and
two cold confirmations. All 60 compiler/CLI streams, own-control artifact bytes
and modes, CLI behavior, signatures, runtime identity and source checks passed.
Sharing-on median request time is 33.782539s versus 35.174898s off, with five of
five wins. Mean paired savings are 1.317177s with 0.285275s standard error.

Postcompile storage median falls from 3.223229s to 1.896423s; mean paired storage
savings are 1.302870s with 0.021059s standard error. Compiler execution mean
savings are only 0.015324s with 0.289244s standard error. This supports reducing
postcompile work, not making rustc itself faster. The initial candidate prime's
18.107084s storage cost includes fresh metadata reader work and is excluded from
the paired timing summary. Metadata/toolchain memos are warm in measured pairs.

The matched eight-build **untraced full Harness cold** baseline/candidate
comparison completed with the same experimental runtime, sharing off/on,
eight Cargo jobs, 29 rewritten wrapper guards and unchanged source snapshot.
The [full samples](../benchmarks/harness-producer-shared-digests-full-cold-paired.json)
and [verification](../benchmarks/harness-producer-shared-digests-full-cold-verification.json)
retain all eight verified logs and 1,244 artifact paths/modes per build. All cold
hit counts are zero and all snapshot inputs remain unchanged.

Baseline median is 198.607469s; candidate median is 194.438621s. The three paired
savings are +12.855135s, **−33.876616s**, and +4.168847s. Mean paired savings are
−5.617544s with 14.350310s standard error, despite two of three wins. The lower
candidate median does not establish a repeatable improvement. No sample is
excluded. The isolated storage result remains a scoped mechanism observation;
production adoption is rejected pending stronger full-workload evidence.

The original gated digest-sharing/kache trial did not launch because this result
failed its clear-gain condition. Its terminal state is retained. A separate
16-build untraced study now compares the **pre-sharing eight-worker runtime**
against pinned kache, with three alternating cold pairs and three warm rounds.
It uses runtime SHA-256
`0d38bfa35100b87d0a42abfd8ced2744eb28a91bc86883a663c938e998406499`,
the same source snapshot/toolchain/job count/native contracts, and no digest-sharing
patch. Its private frozen preparation is
`/tmp/nano-full-eight-workers-kache-preparation-20261011`.
This addresses the previous worker experiment directly; it does not relax the
failed storage candidate's adoption gate. Independent confirmation remains
required, and production still uses four hash workers.

## Next hypothesis after the current comparison

The verified revert trace contains two unsuccessful final-request restores
(0.316204s and 0.217236s) before the successful 0.230984s restore. Each failed
attempt performs the large parallel input-hash pass before reporting a content
change. The [retained manifest comparison](../benchmarks/harness-revert-manifest-mismatch-investigation.json)
finds 17 regular paths with different recorded hashes across three historical
manifests, including `main.rs` and changed Harness archives. It retains each
manifest and compiler-stream digest, regular-input counts, current sizes and
job positions. It does not identify current content equality or map manifests
to individual historical slots.

After evaluating the current storage candidate, investigate stopping parallel
hash work when a freshly read hash proves a manifest mismatch. This should only
shorten a miss: a successful hit must still hash every required input. Join all
workers and publish no output when validation fails. Compare an explicit off/on
control; require source/archive edits, preserved-mtime replacements, missing and
corrupt inputs, failures and concurrent restores. Retain complete hash validation
on successful hits and repeat the actual edit/revert sequence before adoption.
No such candidate has run yet, and these overlapping observations do not
establish projected whole-build savings.

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
