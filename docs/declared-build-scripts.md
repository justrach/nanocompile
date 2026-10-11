# Declared build-script caching

Cargo reruns every build script after `cargo clean` or in a fresh target directory. Nano previously cached a run only for packages listed in an explicit execution contract (`NANOCOMPILE_BUILD_SCRIPTS_FILE`), which covers 31 of Harness's 138 build-script runs. The other 107 ran live on every warm build. kache 1.0.0 caches all of them by default. In a matched warm profile this was the largest category gap: 4.5 s of summed slot time, about 0.57 s of estimated wall time.

`NANOCOMPILE_BUILD_SCRIPT_CACHE=declared` caches every other script under Cargo's own rerun rule. Packages in an explicit contract keep using their contract.

## Key

A recorded run is reused only when all of these match:

- the script binary's content digest, its argv, cwd and the real `OUT_DIR`
- the **complete** environment (names and values), which is stricter than kache's fixed variable list
- the content of every path the script declared with `cargo:rerun-if-changed` / `cargo::rerun-if-changed`, resolved against the package directory as Cargo does (files by content, directories by membership and contents)
- the package directory itself, if the script declared no `rerun-if-changed` and no `rerun-if-env-changed` (Cargo's default). Only this package scan skips VCS metadata and `CACHEDIR.TAG` target directories; explicitly declared directories are tracked in full
- the `RUSTC` identity, and the selected `cc` driver with its content digest and the Apple driver/SDK selection hash. Cargo and kache do not track these.

## Never cached

- Scripts that print an empty `rerun-if-changed=` (always rerun).
- Scripts that declare an input under `OUT_DIR`.
- Runs whose outputs include subdirectories, more than 50,000 files or more than 1 GiB.
- Runs with more than 20,000 declared input entries, or non-null stdin.
- Runs that start with a non-empty `OUT_DIR`, or that fail.

Declared inputs are only known after a run. A run is recorded only when every declared input's mtime and ctime predate the start of the run, so an input changed while the script read it is never recorded. The script and tool identity is recomputed after the run and must still match.

A hit validates the recorded input snapshot again, restores into a staging directory beside `OUT_DIR`, re-checks the input stat epoch, then atomically renames the staging directory over the empty `OUT_DIR`. It then replays stdout and stderr.

## Limits

These limits are the same as Cargo's own reruns and kache's:

- State a script probes without declaring it, such as `pkg-config` results, system libraries or tools found on `PATH` other than `cc`, is not part of the key.
- Side effects outside `OUT_DIR` are not replayed.

Use the explicit contract for packages that need audited inputs or tools.

## Tests

`tests/build_script_declared.py` uses real Cargo builds to check:

- hits after `cargo clean`
- same-size, mtime-preserving declared input edits
- declared environment changes
- undeclared files staying out of the key
- reverts
- the package default (both file edits and new files invalidate)
- env-only declarations
- always-rerun scripts, inputs under `OUT_DIR` and nested outputs never being cached
- changed script source
- disabled mode

The explicit-contract suite (`tests/build_script_cache.py`) is unchanged and passes.
