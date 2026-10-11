# Earlier rejection after a real Harness source edit

The prototype reduces the measured cache-rejection stage, but this trial does **not** establish faster builds or beating kache. Other Rust compilations ran concurrently on the host. Every timing, including large losses, remains in the [verified diagnostic report](../benchmarks/harness-early-mismatch-source-edit-diagnostic.json). Production is unchanged.

The experimental `NANOCOMPILE_HASH_MISMATCH_STOP=1` compares each freshly computed input digest with its expected value. A mismatch stops assigning further hash jobs; all running workers join before the entry is rejected, and no cached output is published. Hits still require all content hashes and existing guards. Both controls use the same experimental eight-worker runtime; its earlier producer digest-sharing code is disabled.

The [early-rejection patch](../benchmarks/experiments/early-hash-mismatch.patch) applies after the existing eight-worker and producer digest-sharing patches to public revision `d88cdca`. That patch chain reproduces every runtime/build source file and the executable fixture exactly. Two unrelated benchmark helpers differ from the private 95-file snapshot; the report records those paths and every source/patch hash. The earlier sharing switch remains unset in this experiment. The snapshot predates the later save-stage subdivisions, so applying these patches to a newer revision does not reproduce the exact measured source.

The workload replays the actual final Harness compiler request with its 2,158 verified prebuilt dependency artifacts and metadata files. A separate source snapshot changes the real CLI help description while preserving the file's original modification time. Both original-source environment-specific keys are primed, then that exact entry set is restored before each measured compilation. Five pairs alternate order. A direct edited build and an empty-entry edited build provide behavior and byte/mode references. Original-source hits and subsequent reverts exercise both settings.

| Diagnostic phase | Baseline median | Candidate median | Mean paired saving |
| --- | ---: | ---: | ---: |
| Input hash work during rejected lookup | 207.820 ms | 109.511 ms | 95.444 ms |
| Complete rejected producer lookup | 216.527 ms | 123.092 ms | 94.161 ms |

Both stages favor the candidate in all five pairs. Descriptive standard errors are 9.701 ms and 9.797 ms respectively. The phases are nested and must not be added. Their measurements support avoiding unnecessary hashing after a proven mismatch; they do not predict whole-project savings.

Total request medians are 38.682327s baseline and 38.549831s candidate. Only two of five wall-time pairs favor the candidate; mean paired savings are −3.036436s with 10.345837s standard error. Compiler execution accounts for most of that variation, including individual executions exceeding 60 seconds. A point-in-time ancestry check identified unrelated Cargo/Rust compilation, and the later aggregate host observer found external build tools in all 29 observations over its approximately 32-second final window. That observer cannot identify the start of contention or explain earlier samples. A quieter independently observed session is required for an end-to-end speed comparison.

Independent verification checks all 19 executions, 76 saved compiler/CLI streams, source restoration, the prebuilt inputs, final output bytes/modes, matching direct CLI behavior, activation and rejection markers, runtime/runner hashes, and recomputed paired statistics. Every source-edit pair matches the fresh edited artifacts. Both revert hits match the original artifacts. Codesign checks pass. This is an isolated compiler-request diagnostic, not a full Cargo, shared-crate, kache or second-session performance comparison.

The first setup attempt stopped before any edited pair: it incorrectly expected the second setting to reuse the first setting's compilation key. Nanocompile keys the complete environment. The corrected run primes both settings separately and preserves the failed attempt's report and runner hashes. No cache-key check was weakened. The shared runner now also rejects a traced activation prime for a warm comparison because that prime would populate a different key.

Private streams, source snapshot and capture records remain under `/tmp/nano-harness-early-mismatch-edit-paired-20261011-2`; the runner, verifier, prebuilt-input manifest, recovery record and host observations are under `/tmp/nano-harness-early-mismatch-edit-preparation-20261011-2`. Raw arguments and environment values are not published.

The [source-first follow-up](source-first-mismatch.md) now verifies that hypothesis on 37 actual request executions with host observation throughout. It further reduces rejected-lookup work, but shows no warm-hit gain and no clear total-request improvement. Both experiments remain separate from production. A matched warm Nano/kache trace is the next investigation; full Harness edit/revert and independently confirmed performance comparisons remain required before adoption.
