# Next.js and OpenNext worktrees (experimental)

`nanocompile worktree` creates an isolated Git checkout, installs its own Node
dependencies using a shared download cache, and carries compatible Next.js
compiler-cache hints between checkouts. **It always executes the real build.**
It does not cache a successful deployment or assume that a Next.js build is
hermetic.

Requires macOS/Linux, Git, Python 3.9+, Node, and an already installed package
manager. The helpers are installed by `zig build`; keep its `share/nanocompile`
directory beside `bin` when distributing the install prefix. The Zig executable
remains the artifact-store backend. Standalone compiler caching does not require
Python. Set `NANOCOMPILE_PYTHON` to select a
different Python executable.

## Create and prepare

Build nanocompile, then point it at your app:

```sh
zig build -Doptimize=ReleaseFast
NANO="$PWD/zig-out/bin/nanocompile"

"$NANO" worktree create ../shop-cart --project /path/to/shop --branch feature/cart
"$NANO" worktree create ../shop-search --project /path/to/shop --branch feature/search
```

Each command creates a **new branch from HEAD** and runs a frozen dependency
install. Use `--ref COMMIT_OR_REF` to choose another starting point. Git copies
committed content, not dirty edits or ignored `.env` files. Supply each tree's
local environment yourself. Existing paths and branches are not overwritten;
if installation fails, the new worktree is retained for diagnosis and retry.
There is no automatic worktree deletion or branch cleanup.

For an existing worktree, or to retry preparation:

```sh
"$NANO" worktree prepare --project ../shop-cart
```

`create` and `prepare` accept `--no-install` when you want to handle dependency
installation yourself. Preparation normally runs the installer every time; it
does not mistake an existing `node_modules` directory for a verified install.

The app must declare `next` in `package.json` and have exactly one supported
lockfile: `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lock`, or
`bun.lockb`. The lockfile and optional `packageManager` declaration must agree.
The helper uses the installed manager; it does not download or activate a
manager version. Only package download stores are shared. Each worktree owns
its `node_modules`, and a symlinked `node_modules` is rejected. Modern Yarn is
configured to use the node-modules linker. Frozen installs can still execute
your project's dependency lifecycle scripts, just as a normal install does.

The first version targets independently installable apps. A nested app can be
mapped to the same relative directory in a new checkout, but monorepo dependency
graphs and workspace-root installs are not inferred. Use the existing
[Turborepo adapter](../examples/turborepo/README.md) for workspace orchestration.

## Build and develop

```sh
"$NANO" worktree build --project ../shop-cart
"$NANO" worktree build --project ../shop-search

# Scripts receive arguments after --. Next 16's default Turbopack build does not
# currently produce the compiler-cache directories supported by this helper.
"$NANO" worktree build --project ../shop-cart -- --webpack

# An existing package.json script can run either OpenNext adapter's build:
"$NANO" worktree build --project ../shop-cart --script build:worker

# Foreground servers, distinct explicit ports, private worktree outputs:
"$NANO" worktree dev --project ../shop-cart --port 3001
"$NANO" worktree dev --project ../shop-search --port 3002
```

For example, `build:worker` can be `opennextjs-cloudflare build` or
`open-next build`. Configure its underlying Next build to use Webpack if you
want Webpack seed sharing. The helper runs your package script without a shell
wrapper of its own and preserves its exit status. It does not invent an adapter
configuration, provision cloud resources, or deploy anything automatically.
Never put deployment in a build script unless you intend to execute deployment
on **every** invocation.

All helper-controlled installs, builds, and dev sessions for one worktree share
a private Git-metadata lock. Different worktrees can run concurrently. A dev
session holds that lock until it exits; finish it before preparing or building
that same tree. Commands launched outside nanocompile do not honor the lock:
do not run them against the same mutable outputs concurrently. Dev requires an
explicit port and checks that it is available before launching the script; the
script must support Next's `--port` argument. The bind check is advisory, not a
port reservation, and custom scripts remain responsible for their behavior.
Dev sessions do not publish compiler seeds.

## What is reused

Only `.next/cache/swc` and `.next/cache/webpack` are archived, through the
existing content-verified `nanocompile artifact` API. They are **incremental
hints** that Next/Webpack must validate against current source, not evidence
that a whole build can be skipped. Source contents are deliberately not part
of the compatibility key so edited branches can try these hints. Framework
validation may discard path-sensitive hints after relocation; a seed restore
is not a promise of a speedup.

Compatibility keys hash the lockfile, `package.json`, top-level Next/OpenNext,
Wrangler, TypeScript, Babel, PostCSS, Tailwind and package-manager configuration,
`.env*` file contents, installed Node and selected manager identity, OS and
architecture, command arguments, and effective environment. `PWD`, `OLDPWD`,
the nanocompile cache location and reporting paths are excluded. Keys contain
only a digest, never plaintext environment values. Changed environment or
configuration conservatively prevents reuse. Arbitrary external configuration
and workspace graphs are not automatically discovered; framework validation
remains essential. `next-env.d.ts` is generated source, not a compatibility key.

The helper never shares `fetch-cache` (which can contain remote data), `.next`
server/static outputs, `.open-next`, or live dependency directories. It never
symlinks the mutable `.next` tree between worktrees. A seed is restored only
when both supported local compiler-cache directories are absent; existing
local caches are left alone. A successful build publishes fresh hints only if
its compatibility inputs are unchanged after execution. Failures are never
published. Corrupt/missing entries or an unavailable artifact backend fall back
to the normal build. `NANOCOMPILE_DISABLE=1` runs builds without seed reuse.

Turbopack persistent caches are not currently shared. A successful build that
produces neither supported compiler directory reports `stored: false`. A custom
Next `distDir` needs the matching `worktree build --dist-dir PATH` option; this
option selects the cache location, not Next's configuration. Destinations must
remain beneath the app without symlinked ancestors.

Each build ends with a JSON summary: `returncode`, `cache` (`restored`, `miss`,
or `disabled`), `stored`, and a compatibility `key` when eligible. `miss` also
covers preserving an already-present local compiler cache. Normal framework
output is streamed before the summary.

## Storage and trust

The default shared location is `NANOCOMPILE_DIR`, otherwise
`$XDG_CACHE_HOME/nanocompile` or `~/.cache/nanocompile`. Override it before the
subcommand:

```sh
"$NANO" worktree --cache /path/to/trusted/cache build --project ../shop-cart
```

Downloads live under `downloads/MANAGER`; compiler seeds use the normal CAS,
GC, and artifact integrity checks. Archives reject links, special files,
traversal, unexpected paths, and oversized expansion. Restoration stages files
before publishing absent directories. These checks prevent accidental archive
escape, **not malicious compiler-cache execution**: share only with trusted
writers in the same trust domain. Content hashes are not authentication. The
helper does not separately copy `.env` files or upload source trees, but compiler
caches can contain transformed source and embedded environment values: treat
them as private build data. The artifact backend is local; dependency installation
still contacts the configured package registry.

## Checks

```sh
zig build -Doptimize=ReleaseFast
python3 tests/worktree_setup.py
python3 tests/nextjs_cache.py
python3 tests/worktree_cli.py zig-out/bin/nanocompile
python3 tests/worktree_integration.py zig-out/bin/nanocompile --opennext
```

The framework check installs pinned fixture dependencies and executes actual
Next.js builds and optional OpenNext packaging in isolated temporary Git
worktrees. It is correctness evidence, not a benchmark or proof of whole-build
portability.
