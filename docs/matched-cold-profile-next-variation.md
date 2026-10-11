# Matched cold profile: next variation

The separate matched cold diagnostic sequence completed direct, Nano and kache full Harness CLI builds at 177.321s, 190.928s and 192.870s. These single traced observations do not replace the [repeated untraced comparison](full-eight-workers-kache-comparison.md), which found no cold Nano advantage and a warm Nano loss.

[Verified observations](../benchmarks/harness-cold-gap-matched-profile.json) retain complete-console digests, runtime/toolchain identity, capture coverage and all phases for the selected final Harness, UI, engine and adapters requests. Every capture and all 97 snapshot inputs were verified. Raw captures and full analysis remain private under `/tmp/nano-cold-gap-matched-profile-20261011` and `/tmp/nano-cold-gap-matched-profile-analysis-20261011`.

The final Harness request takes 72.285s Nano versus 68.004s kache, a 4.281s Nano loss despite the overall diagnostic build ordering. Nano records compiler execution 68.677s and postcompile work 3.240s, plus input staging 0.238s and linked-input discovery 0.076s. Kache's nearby final miss service event reports compile time 67.825s, key work 0.024s and storage 0.061s. Service and wrapper intervals differ in scope and are not joined by a shared request ID. They identify hypotheses, not an additive prediction of whole-build savings.

The next diagnostic subdivision separates `save.input_revalidation`, `save.source_discovery_guards`, `save.rust_graphs` and `save.artifacts` inside the existing postcompile marker. Require a real captured final Harness request, direct/cold/restore output checks and unchanged sources before using those stages to select an optimization. An isolated request measurement is mechanism evidence; it cannot establish a full-build gain.

Keep compiler flags and generated sources fixed. Optimize the measured postcompile stage without skipping full content checks, directory guards or mutation/failure handling. The earlier digest-sharing prototype reduced isolated storage but failed its full-build clear-gain gate; do not adopt it on this new broad marker alone. After one targeted change passes correctness, compare it with frozen Nano and kache using repeated untraced cold, hit and real edit/revert trials, followed by independent confirmation. Retain every loss and failed check.

## Actual request subdivision completed

The [verified replay](../benchmarks/harness-producer-save-subdivision.json) contains a direct reference, fresh-metadata cold save, restore hit, then a second cold save with reader/toolchain memos retained and entries cleared, followed by another verified hit. All 20 compiler/CLI streams and within-wrapper output bytes/modes passed independent verification. These are isolated mechanism observations, not repeated full-build speed samples.

The second cold save takes 3.217254s in postcompile work: Rust graph collection 2.839571s, input revalidation 0.233484s, artifact storage 0.142900s and source/directory guards 0.001268s. The initial fresh-metadata save spends 18.986118s in graph collection. That initial state differs from the late final request in a full cold Cargo build, whose earlier units populate reader metadata.

The next private experiment traverses independent producer roots with up to four workers. Each root retains independent resolver state and full fresh validation; records are assembled in original order after all workers join. It shares no mutable digests between roots or requests. Build/unit and the real multi-root fixture passed, including equal sealed payloads and output bytes/modes, preserved-mtime shared edits, corruption/failure, revert and four concurrent restores; 58 fixture streams were independently verified. The repeated actual-request and full-build results below determine whether that isolated mechanism improves the workload. Parallel work could increase contention during Cargo builds, so an isolated win alone will not justify promotion.

## Five parallel-graph request pairs completed

The [complete verified comparison](../benchmarks/harness-producer-parallel-graphs-cold-paired.json) records 15 executions: direct, two separate primes, five alternating pairs and two cold confirmations. Every one of the 60 compiler/CLI streams passed digest verification, with matching own-control artifact bytes/modes and CLI behavior. The [initial multi-root correctness evidence](../benchmarks/producer-parallel-graphs-correctness.json) retains all six cases and the 58 verified fixture streams. It has no within-invocation mutation race hook.

Parallel request median is 33.765930s versus 35.379035s sequential, with five of five pair wins. Mean paired savings are 1.266784s with 0.324400s standard error. The smallest win, 0.110372s, is retained alongside the larger wins. Postcompile work median falls from 3.200520s to 1.806533s. Graph collection median falls from 2.825833s to 1.429884s; mean paired graph savings are 1.414526s with 0.012467s standard error. Compiler-execution mean savings are −0.145480s with 0.320374s standard error, so compiler execution did not measurably improve.

The [default-off patch](../benchmarks/experiments/producer-parallel-graphs.patch) applies to public core revision `77823b8` and enables up to four producer graph workers only with `NANOCOMPILE_PRODUCER_GRAPH_WORKERS=4`. The [portable request runner](../benchmarks/experiments/harness_producer_parallel_graphs_cold_pair.py) compares the same binary with that setting at zero/four. The measured runtime also uses the existing experimental eight-worker input-hash patch; its SHA-256 is `e54426c75a7b4edbbb78b1be82d124d1946ea3ed00e79b9b104e68b9c2119207`. Production source is unchanged by the experimental patch and retains four input-hash workers.

The isolated mean saving exceeded the predeclared two-standard-error gate, opening a twelve-build full Harness cold A/B trial: two excluded primes and five alternating pairs, eight Cargo jobs, fixed source/toolchain/epoch and 29 native wrapper guards rewritten to the stable wrapper path. Measured builds are untraced; only the excluded candidate prime traces actual graph-worker activation. Both controls use the same experimental runtime, with entries and Cargo target cleared before every build. Preparation is retained at `/tmp/nano-producer-parallel-graphs-full-pair-preparation-20261011`. The completed full-build trial is reported below. Real edit/revert validation, kache comparison and independent confirmation remain unproven; do not adopt the candidate from its isolated result.

## Full cold trial completed: no clear gain

The [twelve-build result](../benchmarks/harness-producer-parallel-graphs-full-cold-paired.json) fails the predeclared full-build gain gate. Parallel graph traversal remains experimental and is not adopted. The conditional kache comparison was not launched.

| Pair | Sequential seconds | Parallel seconds | Savings (sequential − parallel) |
| --- | ---: | ---: | ---: |
| 1 | 188.602612 | 181.867201 | +6.735412 |
| 2 | 183.273458 | 186.547354 | −3.273896 |
| 3 | 189.702739 | 179.140069 | +10.562670 |
| 4 | 190.980312 | 210.379030 | −19.398718 |
| 5 | 192.141324 | 190.437315 | +1.704009 |

Parallel wins three of five pairs. Its median is lower (186.547354s versus 189.702739s), but mean paired savings are **−0.734105s**, with **5.216194s** standard error. The 19.4-second loss is retained. The isolated graph-collection gain did not establish a repeatable whole-build improvement; neither the median nor the win count overrides this result. Sampled peak process-tree RSS stays between 5.34 and 5.65 GiB across all twelve builds, so these samples do not identify memory growth as the cause of that loss.

[Independent evidence verification](../benchmarks/harness-producer-parallel-graphs-full-cold-verification.json) checks all twelve complete log sizes/hashes, 883 snapshot files, 881 tracked Rust/manifest files, frozen runner/runtime/contract hashes, each mode's repeated artifact bytes/modes and CLI behavior against its own prime, and all 1,244 final artifacts on disk. Cold builds have zero cache hits. The candidate prime contains the actual graph-worker activation marker; measured builds have no activation/profile markers. This independently verifies the recorded evidence, not performance in a second session.

The frozen raw report inherited an incorrect `producer_shared_digests` label and a statement about distinct executable identities. Its executed code toggled `NANOCOMPILE_PRODUCER_GRAPH_WORKERS=0/4` in the same runtime, with no digest-sharing patch. The published report explicitly records that correction and the raw report SHA-256; no timing or artifact data was changed. Raw report, full consoles and verifier remain in the private preparation/state directories above. Future trials can use the [explicit runtime-control runner](runtime-toggle-comparisons.md) rather than copy these labels.

The next performance investigation should target an observed remaining gap rather than promote this cold candidate: the repeated kache study still shows a warm deficit, and the validated early-mismatch prototype still needs actual edited-Harness measurements. It cannot improve empty-cache cold lookups or avoid complete validation on hits. Keep cold, warm and edit conclusions separate, preserve all samples and correctness gates, and require a repeatable workload improvement before changing defaults.
