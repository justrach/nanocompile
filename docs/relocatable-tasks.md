# Opt-in relocatable declared tasks

The default task contract remains strict: absolute checkout paths and the full
environment distinguish builds. Relocation is a separate, versioned namespace
for caller-audited, path-independent tasks. It is not enabled by CI caching or
by using relative command arguments alone.

A task can explicitly add:

```json
"relocatable": {
  "path_independent": true,
  "resources_complete": true,
  "environment": ["LANG", "SOURCE_DATE_EPOCH", "SYSTEMROOT"]
}
```

Both assertions and the environment list are required. False assertions reject
the graph before any child runs. `path_independent` asserts that **outputs,
stdout and stderr** do not depend on the absolute checkout root. The
`resources_complete` assertion covers every file read by the command, its
scripts, subprocesses and runtime: project files belong in `inputs`; installed
compiler/runtime/SDK files belong in `tool_resources`. The caller must discover
and enumerate them on every invocation. Directory discovery, missing-file
observations, file metadata, network, clock and undeclared external resources
are not supported by this contract.

## Path and environment rules

The workspace root is the directory in which `nanocompile task SPEC.json` is
invoked (not the specification's parent). `cwd` is `.` or a relative subdirectory
of that workspace. Inputs and outputs must be normalized relative file paths
beneath that working directory: no absolute paths, `..`, empty components,
`.` components or symlinked files/ancestors. Physical path checks run before the
graph starts, at task execution and again before storage. Filesystem changes
concurrent with a task remain outside the caller-owned contract.

The selected executable must be an **absolute installed path outside the
workspace**, and each `tool_resources` entry must also be absolute and outside
the workspace. Their installation paths and identities remain key inputs;
toolchain relocation is deliberately not attempted. SDK/compiler resource
content changes invalidate according to the existing trusted-installation
identity policy. Declare mutable generated/project files as freshly hashed
`inputs`, not installed resources. An external mutable project input must be
copied into the workspace and declared, or the task must remain strict.

Only the explicitly listed environment variables are inherited by the child
and hashed. All others are absent from **both** the key and child, not ignored
only for hashing. Present-empty and absent values differ. The name list itself
is keyed; duplicate names and the reserved `NANOCOMPILE_TASK_REPORT` name reject.
There are no implicit `PATH`, `HOME`, `PWD`, locale or compiler overrides. List
what the runtime actually needs (including `SYSTEMROOT` for Windows programs
that require it). Values are not rewritten: declaring a checkout-specific
`PWD`, for example, intentionally prevents cross-root hits.

The outer invocation still uses `NANOCOMPILE_DIR`, reporting and disable
controls. `NANOCOMPILE_DISABLE=1` bypasses caching even when that variable is not
in the child's environment. Reports remain private and excluded as described
in [declared tasks](declared-tasks.md).

## What remains in the key

- Host OS/version, architecture, native CPU model and CPU features. Native CPU
  selection is not made portable; different native hosts cannot be presumed
  equivalent just because they share an architecture.
- The full ordered command and selected executable, installed tool identities,
  SDK/tool-resource identities, declared environment and task/dependency names.
- Workspace-relative cwd, relative input/output names and fresh complete input
  hashes. Source membership changes must change the generated input list.

**No arbitrary command argument is rewritten or removed.** Absolute paths,
version flags, `-mcpu=native`, SDK flags and output-affecting options remain
byte-for-byte key inputs. If absolute checkout paths appear in arguments, those
arguments still prevent cross-root reuse. Compiler debug paths, `__FILE__`,
embedded cwd, absolute diagnostics and hard-coded external reads require an
audit; do not assert path independence merely to improve hit rates. Use the
strict default for path-sensitive builds, or configure and validate the build's
own relative-path/prefix-mapping behavior before opting in.

There is no sandbox or automatic dependency tracing here. Nano cannot detect a
false assertion, such as a script secretly reading `/tmp/config` or embedding
`getcwd()`. Such a task is **ineligible**, not proven portable by this option.
The explicit assertions make this responsibility visible; they do not turn
untrusted arbitrary commands into hermetic builds. A sandbox would require a
separate platform-specific design. Untrusted cache writers are also outside
this feature's trust boundary; content checksums are not authentication.

## Cross-root restoration and checks

Relocatable entries contain logical output names and CAS blobs, not the original
checkout's absolute dependencies or destinations. Every invocation hashes its
current declared input bytes before lookup. After execution, inputs, tools and
the specification are revalidated before publication. Restoration checks the
logical names and all blob/diagnostic hashes before materializing only the
current invocation's declared output paths. This retains the normal CAS/GC/
snapshot format without attempting to access the old checkout.

```sh
zig build -Doptimize=ReleaseFast
python3 tests/task_relocatable.py zig-out/bin/nanocompile
python3 tests/task_contracts.py zig-out/bin/nanocompile
```

The relocation fixture removes the producing checkout and restores byte- and
mode-identical multiple outputs into another root with no child execution. It
also covers nested cwd, declared environment changes/absence, excluded variables
being unavailable to the child, source edits, installed SDK-resource edits,
native-CPU arguments, unchanged absolute arguments, corrupt-blob fallback,
disable behavior, incomplete assertions, external path/symlink rejection and
strict-default path-sensitive builds. The original contract suite checks that
strict-mode canonical keys, reporting, graph validation and race guards remain
intact. These are local correctness checks, not evidence of cross-OS or
cross-toolchain cache equivalence.
