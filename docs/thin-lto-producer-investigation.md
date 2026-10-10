# Thin-LTO producer investigation

Thin LTO remains refused by default. The full-app trace identifies this as the largest warm coverage gap: kache restores the application while Nano recompiles it. A native-archive plus Rust-bitcode fixture was used to investigate an opt-in producer extension.

The fixture compiles an explicit Rust helper with embedded bitcode, then a `lto=thin` executable calling both the helper and a native static archive. It compares the final executable and dep-info to direct compilation. The trial stores a producer entry, but direct-vs-producer byte equality fails. Two empty-cache producer builds also differ; direct repeats match. The observed differences are in Mach-O UUID/signing bytes. A private-output path-remapping trial does not restore direct equality. The exact linker cause is unresolved.

[Recorded rejection evidence](../benchmarks/thin-lto-private-output-rejection.json) includes hashes, UUIDs, changed offsets and frozen trial binary hashes. [The retained trial patch](../benchmarks/experiments/thin-lto-private-output-trial.patch) is experimental and was removed from production. The fixture remains available through `tests/executable_cache.py --thin-lto --state <new-directory>` for candidate binaries implementing that trial; current production refuses the configuration, so this investigative mode is expected to fail until support is corrected. Standard producer checks remain unchanged in behavior.

Apple's [classic linker documentation](https://github.com/apple-oss-distributions/ld64/blob/main/doc/man/man1/ld-classic.1) describes content-derived UUIDs. That does not establish the cause in the installed linker or justify rewriting UUIDs/signatures after linking. Inspect compiler-generated object paths, symbols before stripping and the actual linker invocation. Resolve staging determinism while retaining exclusive private ownership, complete external-input hashing and signing validity. Do not weaken byte gates or use deterministic shared staging directories to bypass this failure.

After repairing reproducibility, verify direct/cold/warm execution and modes, real transitive bitcode edits, native edits with preserved mtime, reverts, corrupt entries/blobs, failed compilation, alternate toolchains and unsupported LTO/debug fallback. Then test the actual full Harness executable before claiming coverage or speed.

## Retained controls

[The retained control results](../benchmarks/thin-lto-stable-alias-control.json) narrow the failure in the small fixture: an observer using the unchanged canonical output directory matches direct bytes. A stable symlink spelling pointing to two separately created exclusive physical directories produces byte-identical repeated outputs; those bytes differ from direct. This supports investigating staging-path spelling, not removing the LTO guard. Descriptor child lookup under `/dev/fd` is unavailable on the tested Mac.

Private job retention captures 21 compiler-owned inputs in this trial, plus compiler/linker commands and reports. Manual relinks also showed that the actual Rust child environment matters (`SDKROOT` and `ZERO_AR_DATE`, among other allowlisted fields); a plain shell relink is not an equivalent reproduction. Diagnostic invocation records now retain the selected child environment fields when retention is enabled.

Before a stable-alias implementation can be accepted, require exclusive alias creation and key/output locking, rejection of pre-existing aliases, fresh private canonical ownership, retargeting detection and failure-safe cleanup. Retained jobs must release aliases even when their physical diagnostics remain. Test concurrent unrelated jobs, compiler failure, old alias artifacts and all transitive bitcode/native changes. Preserve full own-cold byte comparisons; explain and validate any difference from direct rather than hiding UUIDs or changing signatures after linking. No full-app LTO cache benefit has been established yet.

## Opt-in stable-alias candidate

`NANOCOMPILE_THIN_LTO_PRODUCERS=1` adds a stable lexical output alias to the opt-in native Apple executable producer path. Thin-LTO proc-macro producers remain refused because this variation has not validated them. It requires the existing producer flag; fat LTO, linker-plugin LTO, relocation overrides, cross targets and debug information still bypass. Physical jobs remain exclusive random directories. Key and output locks are held before alias acquisition; pre-existing aliases force canonical compiler execution and remain untouched. Ownership requires both lexical and canonical private prefixes. The alias is validated after compilation and cleanup releases it even when physical diagnostic jobs are retained. A retargeted foreign alias is not removed.

This changes staging, not LTO compilation flags or generated machine code. The investigative fixture uses an explicit byte-validation profile: its staged cold repeats and warm restore must match completely; direct compilation may differ only in `LC_UUID` and precisely that page's CodeDirectory digest. Both signatures are checked without rewriting either executable. Runtime reads remain live. Ordinary producer tests keep their strict direct-byte equality gate.

Reproduce the investigative check with:

```sh
python3 tests/executable_cache.py zig-out/bin/nanocompile \
  --thin-lto --stable-alias-experiment --retain-jobs \
  --state /tmp/new-thin-lto-fixture --output /tmp/thin-lto-fixture.json
```

Use `tests/project_comparison.py --thin-lto-producers --executable-producers` for a separate full-project candidate comparison. Complete own-cold artifact and mode gates remain mandatory. Full Harness results are recorded separately from the earlier failed random-path trial; no default promotion follows solely from the small fixture.
