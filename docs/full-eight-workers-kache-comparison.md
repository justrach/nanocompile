# Full Harness comparison against kache

The completed untraced study favors kache on warm builds and does not establish a Nano cold advantage. All 16 builds passed independent verification of saved console digests, source inputs, each implementation's output hashes against its own first reference, final executable modes and explicit CLI behavior.

| Phase | Nano median | kache median | Nano pair wins |
| --- | ---: | ---: | ---: |
| Cold | 189.747857s | 186.548740s | 1/3 |
| Warm | 7.771689s | 6.528966s | 0/3 |

Cold paired savings (kache minus Nano) are −6.246000s, −6.098554s and +7.626777s. Their mean is −1.572592s with 4.599882s standard error. Warm paired savings are −1.292852s, −0.852362s and −1.358590s; mean −1.167935s with 0.158924s standard error. Preserve every sample. Neither a lower previous single cold sample nor an isolated optimization result overrides this comparison.

[Every sample and artifact/source hash](../benchmarks/harness-full-eight-workers-kache-paired.json), [independent verification and paired statistics](../benchmarks/harness-full-eight-workers-kache-verification.json). The report records the relative path, size and SHA-256 of each full console. Raw consoles remain private in `/tmp/nano-full-eight-workers-kache-paired-20261011`; the preparation, frozen runner, controls and verifier are in `/tmp/nano-full-eight-workers-kache-preparation-20261011`. This study has complete build consoles but no compiler-phase traces; matched diagnostic profiles are a separate follow-up.

## Controls and limits

The workload builds the full Harness CLI release binary, not the GUI, from the recorded dirty snapshot at commit `32b41cb0bff55e3c9cbfab3012acec2b179ad199`. Rust 1.97.1, pinned kache 1.0.0, eight Cargo jobs, fixed SOURCE_DATE_EPOCH and recorded native/producer policies are used. Nano's experimental eight-worker runtime has SHA-256 `0d38bfa35100b87d0a42abfd8ced2744eb28a91bc86883a663c938e998406499`. The digest-sharing patch is absent. Production retains four hash workers.

Cargo target is removed before every build. Both compiler caches are emptied and the private kache daemon restarted outside timing before each cold pair; wrapper order alternates. Warm rounds rotate direct/Nano/kache order. All cold hit counts are zero. All 97 snapshot inputs and the tracked source/manifest hashes were independently rechecked. Warm builds serve actual cache hits.

Output comparisons are within each implementation, since output representation differs between wrappers. Final executable modes are recorded; permission modes for every library/native artifact are not recorded by this runner. Failed compiler feature probes can be expected while the complete Cargo build succeeds. OS filesystem caches are unflushed. Dependency downloads, daemon startup and R2 are excluded. Three rounds on one machine are not a cross-machine result or independent confirmation.

## Instructions for the next variation

1. Preserve these runtimes, source hashes, flags, native contracts, logs and results. Do not enable the digest-sharing candidate based on its isolated storage win: its full-build adoption gate failed.
2. Capture a separate matched Nano/kache cold profile with the same runtime and workload. Verify complete capture manifests and source/output gates before analyzing it. Profile timings are diagnostic and must not be pooled with these speed trials.
3. Identify the actual requests and phases behind the gap. Distinguish compiler execution, input validation, output materialization and postcompile storage. Nested/overlapping spans cannot be summed into a promised project saving.
4. Change one evidenced cause. Validate correct cache hits, real edits, reverts, preserved-mtime replacements, corruption/failure and concurrent restores. Early mismatch termination is a hypothesis for rejected entries after edits/reverts; it cannot improve an empty-cache cold lookup or skip validation on a hit.
5. Compare the candidate with frozen Nano and kache in alternating repeated untraced cold/warm/source-edit trials, then independently confirm the result. Retain regressions and failures. Production adoption requires correctness and a repeatable workload gain.
