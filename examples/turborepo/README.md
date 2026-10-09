# Turborepo task cache example

This workspace has two tasks: `@nano/message` builds JSON from `greeting.txt`,
and `@nano/site` builds HTML from that JSON. Turbo owns dependency ordering,
task hashes, declared outputs, logs and artifact signatures. A Python loopback
API adapter sends opaque task archives to nanocompile's **Zig 0.17.0** store.
The same sealed entries, shared BLAKE3 blobs, integrity checks, GC and R2 snapshot
transport used by the compiler cache preserve the task artifacts.

## Run it

From the nanocompile repository root, with Node 20+ and npm:

```sh
zig build -Doptimize=ReleaseFast
npm ci --prefix examples/turborepo --ignore-scripts --no-audit --no-fund

# Generate private credentials in this terminal, then retain them in terminal 2.
export NANOCOMPILE_TURBO_TOKEN="$(openssl rand -hex 32)"
export TURBO_TOKEN="$NANOCOMPILE_TURBO_TOKEN"
export TURBO_REMOTE_CACHE_SIGNATURE_KEY="$(openssl rand -hex 32)"
export TURBO_API=http://127.0.0.1:9080
export TURBO_TEAM=nanocompile-example

python3 tools/turbo_cache.py --nanocompile zig-out/bin/nanocompile \
  --cache /tmp/nanocompile-turbo-cache --port 9080
```

In another terminal with the same `TURBO_*` values, from the repository root:

```sh
cd examples/turborepo
npm run build -- --cache=remote:rw
rm -rf packages/message/dist apps/site/dist .turbo/cache
npm run build -- --cache=remote:rw
cat apps/site/dist/index.html
```

The second invocation restores both declared outputs. The `remote:rw` flag
excludes Turbo's client-local cache, so hits come from the adapter's store.
Changing `packages/message/greeting.txt` rebuilds both tasks; changing only
`apps/site/build.mjs` rebuilds the app. `EXAMPLE_LABEL` is declared as a task input,
so changing it also changes task keys. Signature verification is enabled.
Keep the signature key stable for clients that share artifacts.

The automated demonstration generates its own temporary tokens, workspace and
cache. It records executed build scripts, Turbo's remote-hit summaries and output
SHA-256 hashes, then tests source/dependency/environment invalidation, preserved
mtime, corrupt-blob rebuilding, team/token isolation, quota GC and clear:

```sh
python3 tests/turbo_integration.py zig-out/bin/nanocompile \
  --output bench-results/turborepo.json
```

The default snapshot test uses an in-memory S3 test double. For **actual R2**, use
the existing private `R2_ENDPOINT`, `R2_BUCKET`, `R2_ACCESS_KEY_ID` and
`R2_SECRET_ACCESS_KEY` environment variables, install boto3, then run:

```sh
python3 tests/turbo_integration.py zig-out/bin/nanocompile \
  --r2-snapshot turbo-example-unique-run --output bench-results/turborepo-r2.json
```

That uploads the populated store, deletes the isolated local server cache,
downloads the snapshot and proves Turbo restores outputs without executing tasks.
The [manual R2 workflow](https://github.com/justrach/nanocompile/actions/runs/37928602023)
passed this check on Linux and Mac with GitHub's encrypted R2 secrets.
[Recorded evidence](../../benchmarks/turborepo.md) includes all task/output hashes. The live server serves local CAS data; R2 is a
snapshot backend, not an S3 request for every task fetch.

## Other task runners and native builds

The Zig opaque-artifact interface is build-tool independent:

```sh
nanocompile artifact put my-project my-task-key artifact.tar '{"duration":120}'
nanocompile artifact head my-project my-task-key
nanocompile artifact get my-project my-task-key restored.tar
```

`get`/`head` return JSON and exit 3 on a miss, 0 on a verified hit. Task keys are
scoped by namespace, independent of server cwd/host. The caller must discover
inputs, choose the key and interpret the archive. Compiler entries remain
separate; a task archive cannot be treated as a compiler entry. Use the current
nanocompile GC with a store containing task entries.

For Rust/Zig tasks inside Turbo, invoke nanocompile from the task script
(`RUSTC_WRAPPER=/absolute/path/nanocompile cargo build`, or
`nanocompile zig build-lib ...`). A Turbo hit skips the whole task; on a miss,
the compiler cache can reuse individual compilations. Include external source
inputs, root Cargo/Zig manifests, toolchain versions, target, CPU/SDK and relevant
environment values in Turbo's task keys before sharing native outputs between
machines. The portable JSON/HTML example avoids native-output assumptions.

This is a single-team development adapter with bounded uploads and bearer auth,
bound to loopback. A hosted service needs a TLS proxy, operational limits and
credential management. It supports the artifact/status/bulk/events endpoints,
including `/v8` paths, and preserves signature/duration/commit headers. It does
not extract archives or infer undeclared task inputs. Side effects and
nondeterministic tasks should use Turbo's `cache: false` configuration.

See [Turbo caching](https://turborepo.dev/docs/crafting-your-repository/caching)
and the [remote-cache API](https://turborepo.dev/docs/openapi).
