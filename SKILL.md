---
name: bounded-build-caching
description: Measures and configures bounded nanocompile caches for real builds, including Next.js/OpenNext apps and explicit task contracts. Use when reducing build-cache disk usage, comparing retained cache sizes, or checking cache usefulness after eviction.
disable-model-invocation: true
---

# Bounded build caching

## Inspect before changing a project

1. Locate the exact repository and inspect Git status. Preserve existing edits.
   Obtain the user's actual path before crossing checkout boundaries.
2. Read the project's build scripts, lockfile, workspace configuration and agent
   instructions. Identify the package manager, install root and application root.
3. Measure separate categories: shared CAS, local compiler caches, dependencies,
   package downloads, build outputs and source assets. Record logical bytes and
   allocated blocks separately; filesystem clones can share physical storage.
4. Check the selected native CLI's `--help` for `NANOCOMPILE_MAX_SIZE` support.
   Do not assume an older published binary implements local source features.

## Use a bounded cache without weakening correctness

- Build the CLI with the repository's supported Zig toolchain and ReleaseSafe.
- Start with a project-private `NANOCOMPILE_DIR` and 512 MiB or the 1 GiB default:

  ```sh
  export NANOCOMPILE_DIR="$PWD/.cache/nanocompile"
  export NANOCOMPILE_MAX_SIZE=536870912
  nanocompile stats
  ```

- Use the same budget/environment for cooperating builds. `0` means no retained
  entries/blobs, not unlimited. This limits settled CAS blobs plus entry manifests,
  not package downloads, app outputs, native caches or all filesystem allocations.
- Keep sources, ignored environment files, installed dependencies and mutable build
  outputs private. Never delete them merely to obtain a smaller measurement.
- Use frozen dependency installation at the workspace root. The standalone
  `worktree` preparer does not infer monorepo workspace installs; do not copy a
  root lockfile into an app or pretend workspace dependencies are independent.
- Next.js/OpenNext caches are hints: always run the real package build. Share only
  supported compiler directories, never fetch-cache, rendered outputs or deployment
  results. Turbopack snapshots require the exact installed native engine identity.
- Never execute a deploy, migration or live-service operation as a cache benchmark.
  If configuration requires credentials, use documented non-production fixtures
  when valid; otherwise stop and request what is missing without exposing secrets.

## Measure useful savings

1. Capture the initial footprint before installation or cleanup; an initially empty
   cache cannot honestly demonstrate a reduction from its starting state.
2. Run the actual project's build and required checks. Keep logs private and report
   failures accurately rather than changing unrelated app code to force success.
3. Compare the same real compiler snapshots/workload in isolated baseline and
   bounded stores. Label synthetic retention pressure separately from actual builds.
4. At quiescence, check `stats`, the bytes in `entries` plus `blobs`, retained hits,
   output equality and invalidation. Exercise an over-budget entry without allowing
   it to flush useful smaller entries. Never disable input/blob validation.
5. Distinguish retained-cache reduction from smaller individual files or smaller
   application bundles. Report dependency/download/output growth separately.
6. If timing, alternate baseline/candidate order and confirm on a fresh fixture;
   record command wall time, setup and verification boundaries explicitly.

## Report and document

Save sanitized counts/timings/results and reproducible commands. Keep absolute
paths, environment values, credentials, app-derived cache payloads and raw logs
out of shared reports. State what was modified, verified, excluded from the limit,
and whether the change is local or released. Do not push or publish implicitly.

References: [cache policy](docs/cache-limits.md),
[Next.js/OpenNext helpers](docs/worktrees.md),
[Meld2 case study](docs/meld2-cache.md).
