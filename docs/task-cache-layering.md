# Whole-task misses with reusable Zig compilation

`python3 tests/task_layering.py zig-out/bin/nanocompile --runs 1 --output bench-results/task-cache-layering.json`

This integration test and benchmark addresses issue #5 using a **real Zig
0.17.0 build**, wrapped in one declared Nano task. It demonstrates existing
layering, not a new compiler-cache backend: Nano restores the complete installed
executable when the task matches; on a miss, ordinary `zig build` runs and can
reuse its own retained intermediates. No recursive Nano compiler wrapping or
relaxation of compiler eligibility guards is involved.

The generated, disposable project has an unchanged Zig object returning `42`
and a small executable that prints a calculation and an embedded version.
`build.zig` links the object into the executable. A source edit changes the
calculation to `43`. A later **command-only** `-Dversion=1.0.0` to
`-Dversion=1.0.1` change leaves all project source files unchanged and changes
the embedded version. Versions remain output-affecting task-key inputs; the
test does not remove them to manufacture hits.

## What is measured and checked

Each trial executes these phases in order, with the installed output directory
removed before **every** invocation:

| Phase | Nano result required | Zig disk caches | Required evidence |
| --- | --- | --- | --- |
| Cold | Miss | Initially empty | Stable object compiled, correct `42` / `1.0.0` |
| Identical warm | Hit | Retained, not consulted | Exact executable bytes/mode restored, correct `42` / `1.0.0` |
| Source edit | Miss | Retained | Zig explicitly reports stable object cached, correct `43` / `1.0.0` |
| Version only | Miss | Retained | Zig explicitly reports stable object cached, correct `43` / `1.0.1` |
| Version warm | Hit | Retained, not consulted | Exact edited executable bytes/mode restored |
| Source edit, fresh control | Miss | Emptied | Stable object not cached; version/mode and behavior match retained-cache build |
| Version only, fresh control | Miss | Emptied | Stable object not cached; version/mode and behavior match retained-cache build |

The fresh controls use the same paths, command arguments and environment as
their retained-cache counterparts. They evict Nano's task entries to force a
miss but preserve its installed-tool identity memos and CAS blobs. Thus the
fresh controls do not also force another cold SDK/tool identity pass. The
initial cold phase starts with both Nano and Zig caches empty. Each trial
starts in a separate directory and executes at most one compilation at a time
(`-j1`).

Nano's append-only events must contain exactly `task_hit` or `task_miss` for
each invocation. Separately, **executed** Zig `--summary all` diagnostics must
explicitly report `compile obj stable ... cached` for both retained-cache
edits and must not report it for fresh builds. On task hits, Zig does not run;
its cached diagnostics are only replayed. The report records compiler reuse
as `null` for these rows, never counting replayed summaries as fresh evidence.
This proves reuse of the independent object, not a count of all compiler hits
or reuse inside the changed executable/build runner.

Runtime checks verify both the exact calculation and embedded version after
every build/restore. Task restores must match the original executable's
SHA-256 and permissions exactly. Fresh compiler controls must match runtime
behavior, embedded version and permissions; their byte equality is measured
separately in `matches_retained_sha256`, not assumed. Independent compiler
outputs may differ byte-for-byte without changing these semantics, so this
fixture is not a reproducible-build certification. Changed source/version
outputs must differ from the previous executable. Merely observing a faster
task miss cannot satisfy these checks.

## Contract and timing boundaries

The task declares `build.zig`, both Zig source files and a generated installed
resource alias map as inputs. The selected Zig executable and **every file
in its library installation** are explicit `tool_resources`. On macOS the
selected SDK is passed with `--sysroot`, and its complete resource tree is
also declared. Enumeration handles SDK aliases/cycles and records alias
targets in the input map. Resources use Nano's trusted installed-tool identity
contract; project inputs receive fresh content hashes. Tool and SDK discovery,
resource enumeration and contract generation are not hidden warmups.

The fixture has no network/package downloads, external runtime libraries or
project dependencies. Python orchestrates the benchmark but is not the cached
task's command; that command is the resolved Zig executable. Output-affecting
arguments, the native target, paths and the environment remain in the task
key. The Zig local/global caches are intentionally **not task inputs or
outputs**: their presence changes work performed, not the executable's intended
meaning. Normal compiler-cache validity checks remain Zig's responsibility.

Per-row `total_seconds` includes:

- setup: source changes, deleting installed outputs, applicable cache resets,
  enumerating complete tool resources and writing the task specification;
- the whole Nano process: startup, complete declared-input hashing, tool
  identity checks, lookup/restore, any compiler execution, post-build
  revalidation and storage;
- verification: reading Nano events, checking Zig evidence, executing the
  resulting program and hashing/checking its permissions.

The cold row also includes tool/SDK discovery and initial fixture creation.
`task_process_seconds` is the entire process wall time, **not pure compilation
time**. Setup/process/verification durations are reported separately but none
is subtracted from totals. `session_elapsed_seconds` additionally includes
outer harness and final temporary-directory cleanup. Installing Zig/SDK and
building the prerequisite Nano binary are outside this benchmark; they are
not described as free CI setup. The OS filesystem cache is not flushed.

## Running locally and in CI

Use an already-built native Nano binary and the repository's supported Zig
0.17.0 installation. A single trial is a meaningful correctness gate:

```sh
python3 tests/task_layering.py zig-out/bin/nanocompile \
  --runs 1 --output bench-results/task-cache-layering.json
```

On Windows, use `zig-out/bin/nanocompile.exe`. Native Linux uses the bundled
musl target; macOS uses the native SDK; Windows uses the bundled GNU target.
No cross-compiled executable is run. The fixture uses ReleaseFast with explicit
`strip = true` on both modules to avoid Windows PDB/debug sidecars. It also
asserts that the installed directory contains only the declared executable;
undeclared installed sidecars fail the check rather than silently escaping
the task contract.

For repeated local measurements, use `--runs 3` (the default). `--zig PATH`
selects the compiler. Compiler/library overrides such as `CC`, `ZIG_LIB_DIR`
and `CPATH` are rejected; unset them or explicitly use `--clean-env` to remove
only these overrides from child environments. Existing ambient Nano/cache
transport configuration is removed for this isolated local-cache test. None
of these changes modifies the caller's shell or installation.

The report contains an allowlisted set of timings, fixture checks, artifact
hashes and compiler target/version. Temporary paths, usernames, environment
values, task specifications, SDK alias maps and raw compiler diagnostics are
not copied into it. Temporary working state is removed automatically. The
test does not edit the repository's source/build files or user caches.

## Results and limits

Run the command above to obtain local per-phase measurements and explicit
compiler-reuse evidence for the current checkout. Reports are not uploaded by
the correctness workflow. Both edited task misses must report stable-object
reuse; both fresh controls must lack that reuse. Task restores must be
byte-identical. One sample per phase is **not a statistical performance result**.

This is a small fixture with one reusable object. Full installed-resource coverage can
make enumeration and identity checks dominate this tiny workload, including
on a Nano hit. There is no speedup threshold or claim about nanocompile's
full self-build, large monorepos or general scheduler performance.

The fixed sequential phase order, host contention and warmed filesystem pages
can bias elapsed comparisons. Fresh controls empty compiler disk caches, not
the machine's memory caches. Running more trials reduces some noise but does
not eliminate these confounders. The explicit Zig summary, independently
verified fresh controls and executable behavior establish reuse/correctness;
the timings illustrate its cost in this particular fixture.

This work does not add cache transport, relocatable task keys, per-compiler
hit telemetry or compiler eligibility for unsupported link modes. This small
fixture does not prove which intermediates a larger build reuses. The CI
command runs on native Linux/macOS/Windows; only passing results for the
specific revision establish that platform's runtime coverage.
