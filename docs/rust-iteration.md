# Rust edit-compile-check loop

This is a caller-owned [declared-file task](declared-tasks.md) graph for closing
the Rust edit loop without treating a fast preview as a rustc result. It exists
so agents and humans can iterate on the Rust crates under
[github.com/justrach](https://github.com/justrach) — including
[harness](https://github.com/justrach/harness),
[codegraff2](https://github.com/justrach/codegraff2) and
[emergentDB](https://github.com/justrach/emergentDB) — while nanocompile
continues to cache eligible `rustc` invocations underneath a task miss.

The ideas come from [Charlie Marsh's 21 October 2026 thread](https://x.com/charliermarsh/status/2112711387285758250)
on agentic Rust forks and alternative compilers. The thread is about tradeoffs:
stateful daemons, language subsets, skipping borrow-checking or type-checking,
and slower runtime code. This document turns those ideas into two layers:

1. **Usable now** — tools and flags that exist today, including a required
   `fast-check` → `validate` task graph.
2. **Experimental watch-list** — rustd, Relax, Lust, Astral's private fork, and
   upstream rustc work. None of these may replace the rustc gate.

A successful fast path is not a commit or release signal. `validate` always
runs real `cargo test` / rustc after `fast-check`.

```sh
zig build -Doptimize=ReleaseFast
./zig-out/bin/nanocompile rust-loop spec --manifest path/to/Cargo.toml \
  --write nanocompile.tasks.json --wrapper "$PWD/zig-out/bin/nanocompile"
./zig-out/bin/nanocompile rust-loop check-spec nanocompile.tasks.json
./zig-out/bin/nanocompile task nanocompile.tasks.json
```

The native `nanocompile rust-loop` driver writes schema 1. It refuses a
specification that omits `validate`, places it before `fast-check`, or invokes
cranelift, rustd, Lust or Relax as the gate.
`python3 tests/rust_loop.py zig-out/bin/nanocompile` exercises that contract
with a real Cargo crate. `tools/rust_loop.py` remains a compatibility fallback.

The [example crate](../examples/rust-loop/README.md) is a no-dependency library
with the same two-task graph. The mid MAP-Elites sample is pinned
[hashbrown 0.15.2](../examples/pinned-hashbrown/PINNED.md). Timing and the
broken-edit gate live in [rust-iteration-bench.md](rust-iteration-bench.md);
the stable entrypoint is `bench/rust_loop_bench`.

## Correctness rule

| Path | What it proves | What it does not prove |
| --- | --- | --- |
| `cargo check` / rust-analyzer / bacon | The crate type-checks and borrow-checks under rustc's check pipeline, or an editor approximation of it | Linked behavior, test results, release codegen |
| Cranelift / mold / a hot-reloader | A faster or more incremental **development** artifact | That LLVM rustc would accept or emit the same code |
| rustd / Relax / Lust | An experimental compiler accepted a subset or skipped a check | That rustc would build it |

`nanocompile rust-loop run --step validate` exits if `CARGO_PROFILE_*_CODEGEN_BACKEND`
is `cranelift` or if the cargo command names an experimental compiler. The
declared-task runner already stops the graph when `fast-check` fails, so a
broken check never writes a validate stamp.

As-shipped, `nanocompile rust-loop run --wrapper` still sets `CARGO_INCREMENTAL=0`.
That remains the documented wrapper protocol. The best config the wrapper now
allows is `NANOCOMPILE_ALLOW_INCREMENTAL=1` (or `CARGO_INCREMENTAL=1`): registry
and git dependencies stay cacheable, including `-C incremental=…` on those
units, and workspace crates pass through so rustc incremental can own the edit
loop. `NANOCOMPILE_CACHE_DEPS_ONLY=1` forces that split even when incremental
is off.

## (a) Steps usable now

Each row is a real command or flag. `nanocompile rust-loop verify-flags`
confirms the rustc `-C` names, `cargo check` / `cargo test`, and a `rust-lld`
binary in the current sysroot.

### 1. `fast-check` — skip codegen

```sh
CARGO_INCREMENTAL=0 RUSTC_WRAPPER=/absolute/path/nanocompile cargo check
```

`cargo check` asks rustc for metadata, not a linked crate. That is the supported
way to skip LLVM codegen while still running rustc's type checker and borrow
checker. It is the first declared task. Tradeoff: it does not run tests or
produce a binary. Entire-crate checking is still the compile unit.

### 2. `validate` — mandatory rustc gate

```sh
CARGO_INCREMENTAL=0 RUSTC_WRAPPER=/absolute/path/nanocompile cargo test
```

This is the second declared task and lists `depends_on: ["fast-check"]`. It uses
the default LLVM backend. A nanocompile wrapper is allowed because a miss still
executes rustc; a hit only restores a previously successful rustc result for
the same inputs. Do not pass `-Zcodegen-backend`, rustd, Lust or Relax here.

For a release binary, run `cargo build --release` or `cargo test --release`
the same way, still after a passing check. Those commands are outside the
cached two-task example because they write many undeclared `target/` files.

### 3. `rust-analyzer` diagnostics

[rust-analyzer](https://rust-analyzer.github.io/) is the editor language
server. It incrementally maintains HIR (and some MIR) and is usually faster
than a fresh `cargo check` for in-editor squiggles. It is not rustc. Keep
`checkOnSave` on if you want rustc's check pipeline in the background, and
still run `validate` before commit.

This is an editor process, not a declared task: the runner has no daemon and
does not infer LSP state.

### 4. `bacon` persistent check watcher

[bacon](https://github.com/Canop/bacon) (`cargo install bacon`, then `bacon` or
`bacon test`) reruns cargo on save. [cargo-watch](https://github.com/watchexec/cargo-watch)
still exists as crate 8.5.x but the repository is archived and its README
recommends bacon or [watchexec](https://github.com/watchexec/watchexec)
instead. Prefer bacon for a Rust-specific loop.

A watcher is a long-running process. Do not put `bacon` itself in the
declared-task graph; point it at `cargo check` and keep `validate` for the
gate. Tradeoff: a daemon uses RAM and can race an in-progress edit.

### 5. `nanocompile-wrapper`

Nanocompile is the local compiler cache. Use it under both tasks so a task
miss can still hit per-crate rustc artifacts. [Layered task/compiler
caches](task-cache-layering.md) describe the same idea for Zig: a whole-task
miss may reuse compiler outputs.

Do not stack nanocompile and [sccache](https://github.com/mozilla/sccache) as
two `RUSTC_WRAPPER` values. If you already use sccache for Rust, pick one
wrapper. sccache remains useful as `CC="sccache cc"` / `CXX="sccache c++"`
for C/C++ that Cargo's `cc` crate builds, including on Linux where the
portable `nanocompile cc` adapter is opt-in.

### 6. `cranelift-dev` for nightly **dev** builds

Verified from the [Cargo build-performance guide](https://doc.rust-lang.org/cargo/guide/build-performance.html)
and [rustc_codegen_cranelift](https://github.com/rust-lang/rustc_codegen_cranelift):

```sh
rustup component add rustc-codegen-cranelift-preview --toolchain nightly
CARGO_PROFILE_DEV_CODEGEN_BACKEND=cranelift cargo +nightly build -Zcodegen-backend
```

Nightly Cargo (1.101 here) still requires `-Zcodegen-backend` or
`[unstable] codegen-backend = true` in `.cargo/config.toml`. Setting only
`CARGO_PROFILE_DEV_CODEGEN_BACKEND=cranelift` fails on both stable Cargo
1.83 and nightly Cargo. The rust-loop harness always passes
`cargo +nightly -Zcodegen-backend` when `dev_backend=cranelift`. Never
hand this to `validate`.

Or in `.cargo/config.toml`:

```toml
[unstable]
codegen-backend = true

[profile.dev]
codegen-backend = "cranelift"
```

Tradeoffs, quoted from those pages: faster debug codegen; nightly plus an
unstable Cargo feature; worse runtime performance; limited targets; incomplete
unwinding and some SIMD/`std::arch` support. Never enable this on `validate`
or `--release`. The [2025h2 production-ready cranelift goal](https://goals.rust-lang.org/2025h2/production-ready-cranelift.html)
is the upstream track for recommending it by default.

### 7. `fast-linker`

`rustc -C help` documents `-C linker=…` and `-C link-arg=…`. Official rustc
sysroots ship `rust-lld`. The Cargo guide shows mold on Linux:

```toml
# .cargo/config.toml — Linux ELF
[target.'cfg(target_os = "linux")']
rustflags = ["-C", "link-arg=-fuse-ld=mold"]
```

`lld` is the portable fallback:

```toml
[target.x86_64-unknown-linux-gnu]
rustflags = ["-C", "link-arg=-fuse-ld=lld"]
```

`mold` is an ELF linker ([rui314/mold](https://github.com/rui314/mold)). macOS
already uses ld64; switching linkers there is usually not the first win.
Tradeoff: C/C++ dependencies and unusual link scripts can fail. This only
helps `cargo build` / `cargo test`, not `cargo check`.

### 8. `sccache` and incremental caches

[sccache](https://github.com/mozilla/sccache) is a ccache-like wrapper with
local or remote storage. It is the closest production stand-in for
"aggressively cache codegen" today: crate-level, not per-function. Use it
when nanocompile is not the rustc wrapper, or for C objects.

Cargo incremental compilation (`CARGO_INCREMENTAL=1`, the `cargo build`
default) caches work inside `target/`. That is rustc's own incremental
store. It conflicts with nanocompile eligibility, so the generated spec
forces `CARGO_INCREMENTAL=0` only when `--wrapper` is set.

### 9. `crate-shape` and `codegen-units`

rustc's compile unit is still a crate. Splitting a workspace — as harness
already does with `harness-adapters` and friends — is the supported way to
"dissolve" work into smaller units. `rustc -C codegen-units=N` parallelizes
codegen inside a crate; the `dev` profile already defaults to 256.

Tradeoff: more crates mean more rustc processes and more rmeta traffic.
Do not split a crate only to chase a microbenchmark.

### 10. `hot-reload`

- [hot-lib-reloader](https://github.com/rksm/hot-lib-reloader-rs) reloads
  functions from a `dylib`. Signatures, type layouts and generics cannot
  change safely. You keep a host binary and rebuild the library.
- Dioxus [subsecond](https://github.com/DioxusLabs/dioxus) hot-patches
  function bodies (`dx serve --hotpatch` in current Dioxus 0.7 docs). It is
  for Dioxus apps, not a general rustc replacement.

Both still need a rustc-built artifact. Run `validate` before shipping.

### 11. `disk-hygiene`

The Cargo guide recommends shrinking debuginfo:

```toml
[profile.dev]
debug = "line-tables-only"

[profile.dev.package."*"]
debug = false
```

`rustc -C help` accepts `line-tables-only`. Also:

- `CARGO_TARGET_DIR` to keep `target/` off a small volume
- `cargo clean` when a tree is abandoned
- `nanocompile gc` (default 10 GiB blob budget) and `nanocompile stats`
- sccache's `SCCACHE_CACHE_SIZE` if that wrapper is in use

`gc` is explicit so the compile path does not scan the store. It is not part
of the two-task graph.

## (b) Experimental watch-list

Charlie's disclaimer still applies: these projects are early, and he had not
gotten them to build Ruff. **None of them is the `validate` command.**

### `rustd` — Jon Kelley (@jkelleyrtp), Dioxus Labs

- Source: [DioxusLabs/rustd](https://github.com/DioxusLabs/rustd)
- Announcement: [10x edit-loop numbers](https://x.com/jkelleyrtp/status/2110433801071689733)
- Charlie: [rust-analyzer HIR/MIR → Cranelift](https://x.com/charliermarsh/status/2112711393421955552)

A user-level daemon keeps rust-analyzer's workspace database and compiles
changed functions with Cranelift or LLVM, then links or splices them.
Claimed directions match the thread: dissolve crates as the compile unit,
cache codegen per function, fine-grained span invalidation.

Tradeoffs, from rustd's own README and Charlie's thread: no borrow checker on
the fast path (`cargo rustd check` is ordinary `cargo check`); generated code
is not rustc's; a long-running daemon; pinned to Rust 1.99.0; prototype,
largely AI-assisted, with known miscompiles. Success does not mean rustc
would accept the crate.

### `relax` — Rik Arends

- Charlie: [separate frontend/backend JIT](https://x.com/charliermarsh/status/2112711399512092895)
- Rik: [~85% rustc test coverage](https://x.com/rikarends/status/2112212283934077190)

Charlie describes a Rust JIT with its own frontend and backend, hot reload,
and a borrow checker. The t.co in that tweet resolves only to Rik's post;
**a public repository URL was not verified** when this was written. Treat it
as a watch-list item, not something `nanocompile task` can invoke.

### `lust` — Theo

- Source: [t3dotgg/lust-lang](https://github.com/t3dotgg/lust-lang)
- Charlie: [subset of Rust → C → TCC, plus a daemon](https://x.com/charliermarsh/status/2112711403828031827)

Lust type-checks and borrow-checks a subset, emits C, and uses TCC. It keeps
a warm daemon. It has no `async`, no `unsafe` in user code, and almost no
proc macros; the ts-rust port rewrote dependencies so Lust could compile
them. Dev binaries are much slower than rustc debug builds. `lust check
--rustc` and `lust build --release` (Cargo) are how it uses rustc as the
oracle — the same split this graph encodes.

Linux x86_64 only in the README we read. Not a general crates.io compiler.

### `astral-fork`

- Charlie: [true fork of rustc, cargo, rustfmt, clippy](https://x.com/charliermarsh/status/2112711411830804544)

Agent-authored patches aimed at development speed **without** dropping
correctness or borrow-checking. Claimed incremental `cargo check` up to
about 30×, about 30–40% on replayed real sessions, plus disk-space work.
**Not open source** as of the thread. Watch only.

### `upstream-perf`

- Goal: [Compiler performance optimizations](https://goals.rust-lang.org/2026/compiler-performance-optimization.html)
- Owner: Nicholas Nethercote; funding contact Hexcat; Charlie notes
  [OpenAI is funding that work](https://x.com/charliermarsh/status/2112711421721293063)

Profile-driven rustc improvements, including the new trait solver and
Polonius. This is the path that keeps rustc as the source of truth. Prefer
it over a divergent frontend whenever an optimization lands upstream.

## What this is not

The helper does not infer Cargo build-script reads, proc-macro file access,
or `target/` membership. Those remain the [declared-task](declared-tasks.md)
limitations. `target/` is a work directory, like Zig's cache in the
[layering check](task-cache-layering.md): it changes work performed, not the
stamp's meaning. Rerun `nanocompile rust-loop spec` after adding a source file
so membership stays in the contract.

This is not a rustc substitute, a bacon replacement, or a claim that the
two-task graph is faster than an incremental `cargo check` on a warm
`target/`. It is a way to write the loop so the fast path cannot silently
become the gate.
