# Code assessment of restored proc-macro dylibs

`src/code_assessment.zig`

## The problem

On macOS, a Mach-O file is assessed by the system policy service the first time any process registers its code signature for library validation. The service caches the result on that file. A restore always creates new files, since Nano clones blobs into the target directory. So the first rustc to load each restored proc-macro dylib waits for that dylib's assessment inside its frontend.

The assessments are serialized. Usually each one takes about 0.04 s, but in some periods the service takes about 0.3 s per file. A crate that loads 16 freshly restored proc-macro dylibs then gains roughly 4 s of frontend time. Its CPU time, page faults and free jobserver tokens do not change.

On the full Harness CLI shared-parser edit, this stall fell on the critical path:

| Crate | frontend, fast build | frontend, slow build | codegen (both) |
| --- | ---: | ---: | ---: |
| `harness-preview` | 1.9–2.1 s | 5.7–6.0 s | 2.8–4.0 s |
| `harness-adapters` | 4.5–4.6 s | 6.4–6.6 s | 4.3–5.4 s |
| `harness-ui` | 14.0–15.0 s | 17.7–18.1 s | 10.7–11.6 s |

The system log showed the cause. Shortly after `harness-ui` started, it held 16 XProtect scan sessions (requested by the system policy service), about 0.29 s apart in slow builds and 0.04 s apart in fast ones. kache restores by cloning as well and pays the same per-file cost. In its builds, though, those scans happened before 15 s, off the critical path.

## The change

After a proc-macro producer hit (or miss), Nano forks a detached child that, for each restored `.dylib`:

1. opens it and finds its `LC_CODE_SIGNATURE`
2. registers the signature (`F_ADDFILESIGS_RETURN`)
3. runs the library-validation check (`F_CHECK_LV`)

Nothing from the dylib is mapped for execution or run. The child first points standard input, output and error at `/dev/null` and closes every other inherited descriptor, so it never holds Cargo's output pipes or Nano's cache locks. The request returns without waiting for it. When a compiler later loads the dylib, the assessment has already completed.

Measured on one restored dylib:

| | assessment scans at load | load time |
| --- | ---: | ---: |
| first load of a new clone | 1 | 0.07–0.5 s |
| load after the prewarm child | 0 | 0.024–0.05 s |
| signature registration only (no `F_CHECK_LV`) | 1 | 0.08 s |

Signature registration alone is not enough. The library-validation check is what records the result.

`NANOCOMPILE_PREWARM_CODE=0` disables the prewarm. Other platforms are unaffected.

## Result

Full Harness CLI, pinned kache 1.0.0, eight jobs, alternating order, empty Cargo target every build:

| Study | Nano median | kache median | Nano pair wins | mean saving (± s.e.) |
| --- | ---: | ---: | ---: | ---: |
| shared-parser edit, before (3 pairs runs) | 115.5–115.8 s | 113.1–114.2 s | 3/6 each | about −2 s |
| shared-parser edit, with prewarm | **111.4 s** | 113.4 s | **6/6** | 2.30 ± 0.82 s |
| warm, with prewarm | **5.77 s** | 5.98 s | **6/6** | 0.24 ± 0.06 s |

With the prewarm, `harness-ui` compiled in 25.0–25.1 s in every Nano shared-edit build, and `harness-preview` in 5.0–5.4 s, whichever implementation built first. kache's builds in second position now show the stall instead (`harness-preview` 8.8–9.9 s). Warm builds did not regress. All 12 warm builds matched their own cold artifacts, modes, macro dylibs, build-script executables and final executable.

Records: [shared-edit pairs](../benchmarks/harness-shared-edit-pairs-code-assessment.json), [warm pairs](../benchmarks/harness-code-assessment-warm-kache-paired.json).
