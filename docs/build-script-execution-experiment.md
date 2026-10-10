# Cargo build-script execution cache: first verified restore trial

This is an opt-in, uncommitted runtime prototype, not an accepted production improvement. It now restores ring's flat native output bundle and streams, removing all 24 native requests in warm Harness builds. The three warm pairs favor Nano, but the median difference is small and the three cold pairs favor kache.

| Phase | Nano median | kache median | Nano pair wins |
| --- | ---: | ---: | ---: |
| Empty compiler caches and clean target | 17.965230 s | 17.067632 s | 0/3 |
| Populated compiler caches and clean target | 1.266634 s | 1.277947 s | 3/3 |

Warm median improvement is 0.89%; cold regression is 5.26%. Individual warm Nano/kache pairs are 1.293183/1.637208, 1.266634/1.277947 and 1.128080/1.169828 seconds. This does not establish a durable advantage or a cold-build win. All warm native objects/archives, rlibs, macro dylibs and script launchers match their own implementation's first cold hashes. Cross-tool byte equality is not asserted.

[Every sample and artifact/source hashes](../benchmarks/harness-build-script-execution.json) records the real dirty Harness adapters snapshot, Rust 1.97.1, kache 1.0.0, eight jobs, offline dependency resolution, alternating cold order and rotated warm order. The workload is the adapters library, not the complete GUI. OS filesystem caches are unflushed. Fetching dependencies and starting/stopping the private kache daemon are outside timing. R2 is excluded. Every Nano cold build records 167 Rust and 24 native misses plus one script execution miss. Every warm build records 167 Rust hits and one script execution hit, with zero native requests.

## Mechanism and current contract

`NANOCOMPILE_BUILD_SCRIPTS_FILE` selects an explicit per-package JSON contract. Mutable input files and directory membership are fully hashed, including absent paths. Installed trees use the existing trusted-installation stamp policy after their initial full content fingerprint; they now follow directory links, record link selection and resolved contents, and validate link and target state before reuse. Caller environment, script binary, contract bytes and selected compiler/resources enter identity. Output restoration reuses ordinary verified content blobs and replays complete stdout/stderr.

A first attempt bypassed linked SDK directories. A later attempt marked membership dependencies as regular files, which rejected ring's large graph in parallel hashing. Both are corrected in this measured prototype. The real Cargo regression fixture covers a graph above the parallel threshold, preserved-mtime source edits/reverts, installed target edits, link retargeting, directory membership, environment changes, stdin, exit codes, jobserver descriptors, nested outputs and corrupt receipts/blobs.

This contract requires deterministic script behavior from declared file contents, environment and declared tools, writes limited to OUT_DIR and streams, and no outstanding background writers. Clock, random, network, metadata-dependent behavior or executable-basename-dependent behavior is outside this experiment. Arbitrary stdin is not cached. Mutable symlinks and non-regular inputs are refused. Outputs must be flat regular files, below the file-count/size bounds, and OUT_DIR must start empty. Unsupported cases execute rather than partially restoring a tree.

The diagnostic ring contract tracks package bytes, local headers and selected Apple compiler/SDK resources. It does **not yet enumerate all archiver/helper executables**. The observations apply to this unchanged machine/tool installation; before promotion, declare and verify the exact archive/helper selection and its dependencies. Do not use this contract as a general toolchain-change correctness guarantee.

## Reproduce the prototype

The measured runtime binary SHA-256 is `1fece4e81207a7da99c70c7c6eee41de77f4b17246b2dfbc384a6b366ec983ce`. The patch is against accepted revision `a4868dbe4c871c32d30c6230b7e1303454fd9a5c`. Apply the [tracked prototype patch](../benchmarks/experiments/build_script_execution/prototype.patch) in a disposable checkout and copy [build_script.zig](../benchmarks/experiments/build_script_execution/build_script.zig) to `src/build_script.zig`. Build with stable Zig 0.17.0. Run [the real Cargo fixture](../benchmarks/experiments/build_script_execution/fixture.py) with the binary and `--output /tmp/script-fixture-results.json`; [local fixture evidence](../benchmarks/experiments/build_script_execution/fixture-results.json) retains its tested binary and script hashes.

The [diagnostic ring contract](../benchmarks/experiments/build_script_execution/harness-contract.json) and `tests/project_comparison.py --build-script-contract` reproduce the benchmark configuration. Use fresh dedicated state and the same source snapshot. Raw logs remain private at `/tmp/nano-ring-linked-verified-20261010`.

## Next variation

1. Finish the helper/archiver contract, output-restore failure handling and additional mutation checks before adopting the runtime feature.
2. Validate real Harness leaf/shared edits and reverts against each state’s fresh cold artifacts and linked behavior.
3. Measure installed-tree fingerprint phases. The cold trial creates about 3,600 additional per-file memo records for SDK inputs on top of its whole-tree memo. Investigate a single whole-tree content record that retains every link/file/directory stamp; removing duplicate persistent records must preserve full initial content hashing and post-hash validation.
4. Repeat alternating untraced cold and warm comparisons against frozen production and kache. Keep initial fingerprint cost, restore cost, compiler time and overlapping Cargo intervals separate. Reject cold regressions unless the explicit workload tradeoff justifies them; do not claim general superiority from this narrow warm result.
