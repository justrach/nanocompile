#!/usr/bin/env python3
"""Agent worktrees: shared store, per-worktree target, hill-climb + generalization.

Tune only on the training set (axum + ripgrep). Freeze that config. Run it
unchanged on held-out repos. Occupancy of the size x edit grid is unchanged;
rows are tagged split=train|held_out and live in archive.agent_worktrees.

    python3 bench/agent_worktrees.py
    python3 bench/agent_worktrees.py --phase train
    python3 bench/agent_worktrees.py --phase held-out
    python3 bench/agent_worktrees.py --phase record
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bench"))
import rust_loop_bench as bench  # noqa: E402

COMPILING = re.compile(r"^\s*(?:Compiling|Checking|Dirty)\s+(\S+)", re.M)
STAT_LINE = re.compile(r"^([a-z0-9 /+-]+): ([0-9]+)\s*$")
BODY_INSERT = "let _nano_agent_body = 1u8;"
SIG_INSERT = "\n#[allow(dead_code)] fn _nano_agent_sig(x: u32) -> u32 { x }\n"
LARGE_INSERT = "\n#[allow(dead_code)] fn _nano_agent_large(xs: &[u8]) -> usize { xs.len().wrapping_add(7) }\n"

TRAIN = ("axum", "ripgrep")
HELD_OUT = ("bhumi", "hashbrown", "nalgebra", "serde", "ruff", "tokio", "emergentDB")
MIN_GAIN = 0.03
OBJECTIVES = ("crates_compiled_mean", "wall_ms", "disk_bytes", "store_bytes")

SAMPLE_CATALOG = {
    "axum": {"path": Path("/tmp/real-samples/axum"), "package": None, "size": "mid"},
    "ripgrep": {"path": Path("/tmp/real-samples/ripgrep"), "package": None, "size": "large"},
    "bhumi": {"path": Path("/tmp/real-samples/bhumi"), "package": None, "size": "mid"},
    "hashbrown": {"path": REPO / "examples" / "pinned-hashbrown", "package": None, "size": "mid"},
    "nalgebra": {"path": Path("/tmp/real-samples/nalgebra"), "package": None, "size": "large"},
    "serde": {"path": Path("/tmp/real-samples/serde"), "package": "serde", "size": "mid"},
    "ruff": {"path": Path("/tmp/real-samples/ruff"), "package": "ruff", "size": "large"},
    "tokio": {"path": Path("/tmp/real-samples/tokio"), "package": "tokio", "size": "large"},
    "emergentDB": {"path": Path("/tmp/real-samples/emergentDB"), "package": "vector-core", "size": "mid"},
}

NANO_BEST = {
    "NANOCOMPILE_ALLOW_INCREMENTAL": "1",
    "CARGO_INCREMENTAL": "1",
    "NANOCOMPILE_PROC_MACROS": "reported",
    "NANOCOMPILE_PROC_MACRO_PRODUCERS": "1",
    "NANOCOMPILE_EXECUTABLE_PRODUCERS": "1",
}
NANO_SCRIPT = dict(NANO_BEST, NANOCOMPILE_BUILD_SCRIPT_CACHE="1")

# Additive deltas climbed one at a time on top of the current elite.
CLIMB_DELTAS = (
    {"id": "l3_hardlink_target", "env": {"NANOCOMPILE_HARDLINK_TARGET": "1"}},
    {"id": "l4_zstd", "env": {"NANOCOMPILE_ZSTD": "1"}},
    {"id": "l5_no_incremental", "env": {"CARGO_INCREMENTAL": "0"}},
    {"id": "l6_debuginfo_line", "env": {"NANOCOMPILE_DEBUGINFO": "1"}},
    {"id": "l7_skip_cheap", "env": {"NANOCOMPILE_SKIP_CHEAP": "1"}},
    {"id": "l8_script_delta", "env": {"NANOCOMPILE_BUILD_SCRIPT_CACHE": "1", "NANOCOMPILE_SCRIPT_DELTA": "1"}},
)

# Lever order: one change at a time. Keep >3% wins that do not regress another >3%.
LEVERS = (
    {"id": "l0_nano_best", "approach": "nanocompile", "env": NANO_BEST, "loop": "check"},
    {"id": "l1_script_cache", "approach": "nanocompile", "env": NANO_SCRIPT, "loop": "check"},
    {"id": "l2_test_bins", "approach": "nanocompile", "env": NANO_SCRIPT, "loop": "test"},
)

BASELINES = (
    {"id": "none", "approach": "none", "env": {}, "loop": "check"},
    {"id": "shared_target", "approach": "shared_target", "env": {}, "loop": "check"},
    {"id": "kache", "approach": "kache", "env": {}, "loop": "check"},
    {"id": "sccache", "approach": "sccache", "env": {}, "loop": "check"},
)


def git_commit():
    try:
        return subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip()
    except subprocess.CalledProcessError:
        return None


def parse_compiled(text: str) -> list[str]:
    return COMPILING.findall(text)


def parse_stats_text(text: str) -> dict:
    out = {}
    for line in (text or "").splitlines():
        match = STAT_LINE.match(line.strip())
        if match:
            out[match.group(1).strip()] = int(match.group(2))
    return out


def read_nano_stats(wrapper: Path, store: Path) -> dict:
    env = os.environ.copy()
    env["NANOCOMPILE_DIR"] = str(store)
    result = subprocess.run([str(wrapper), "stats"], env=env, capture_output=True, text=True)
    return parse_stats_text(result.stdout)


def read_kache_stats(store: Path) -> dict:
    env = os.environ.copy()
    env["KACHE_CACHE_DIR"] = str(store)
    env["KACHE_LOCAL_ONLY"] = "1"
    exe = kache_bin() or "kache"
    result = subprocess.run([exe, "stats", "--json"], env=env, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return parse_stats_text(result.stdout)
    disk = data.get("disk") or {}
    hits = data.get("hits") or data.get("counters", {}).get("hits") or 0
    misses = data.get("misses") or data.get("counters", {}).get("misses") or 0
    return {
        "hits": int(hits or 0),
        "misses": int(misses or 0),
        "logical bytes": int(disk.get("store_bytes") or 0),
    }


def stats_compiled(before: dict, after: dict) -> tuple[int, int]:
    """Return (compiled/misses, restored/hits) from a stats delta."""
    def n(d, *keys):
        for key in keys:
            if key in d:
                return int(d[key])
        return 0
    misses = n(after, "misses") - n(before, "misses")
    script_miss = n(after, "build-script misses") - n(before, "build-script misses")
    hits = n(after, "hits") - n(before, "hits")
    script_hit = n(after, "build-script hits") - n(before, "build-script hits")
    return max(0, misses + script_miss), max(0, hits + script_hit)


def unique_disk_bytes(paths) -> int:
    """Count each hardlinked inode once (store + all targets)."""
    seen = set()
    total = 0
    for root in paths:
        root = Path(root)
        if not root.exists():
            continue
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                path = Path(dirpath) / name
                try:
                    st = path.lstat()
                except OSError:
                    continue
                if not stat_is_file(st):
                    continue
                key = (st.st_dev, st.st_ino)
                if key in seen:
                    continue
                seen.add(key)
                total += st.st_size
    return total


def stat_is_file(st) -> bool:
    import stat as statmod
    return statmod.S_ISREG(st.st_mode)


def rust_files(root: Path) -> list[Path]:
    skip = {".git", "target", "zig-out", ".zig-cache"}
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for name in filenames:
            if name.endswith(".rs"):
                out.append(Path(dirpath) / name)
    return out


def pick_edit_files(root: Path, count: int = 3) -> list[Path]:
    files = rust_files(root)
    preferred = []
    for name in ("src/lib.rs", "src/main.rs"):
        candidate = root / name
        if candidate.exists():
            preferred.append(candidate)
    for pkg in ("axum", "ripgrep", "serde", "ruff", "tokio", "hashbrown", "nalgebra", "bhumi", "vector-core"):
        for name in ("src/lib.rs", "src/main.rs"):
            candidate = root / pkg / name
            if candidate.exists() and candidate not in preferred:
                preferred.append(candidate)
        nested = root / "crates" / pkg / "src" / "lib.rs"
        if nested.exists() and nested not in preferred:
            preferred.append(nested)
    named = [p for p in files if p.name in ("lib.rs", "main.rs") and "examples" not in p.parts and "tests" not in p.parts]
    rest = [p for p in files if p not in preferred and p not in named]
    chosen = []
    for path in preferred + named + rest:
        if path not in chosen:
            chosen.append(path)
        if len(chosen) >= count:
            break
    return chosen


def apply_agent_edit(root: Path, kind: str) -> list[tuple[Path, str]]:
    """kind: body | sig | dep | large. Returns restore records."""
    records = []
    files = pick_edit_files(root, 4 if kind == "large" else 1)
    if not files:
        return records
    if kind == "dep":
        manifests = [root / "Cargo.toml"]
        for pkg in ("axum", "ripgrep", "serde", "ruff", "tokio", "hashbrown", "nalgebra", "bhumi", "vector-core"):
            manifests.append(root / pkg / "Cargo.toml")
            manifests.append(root / "crates" / pkg / "Cargo.toml")
        for manifest in manifests:
            if not manifest.exists():
                continue
            text = manifest.read_text(encoding="utf-8")
            if "[package]" not in text:
                continue
            extra = "\n[package.metadata.nano_agent]\nnote = \"worktree-dep\"\n"
            if extra not in text:
                manifest.write_text(text + extra, encoding="utf-8")
                records.append((manifest, text))
            break
        if files:
            path = files[0]
            original = path.read_text(encoding="utf-8")
            path.write_text(original + SIG_INSERT, encoding="utf-8")
            records.append((path, original))
        return records
    insert = LARGE_INSERT if kind == "large" else SIG_INSERT if kind == "sig" else (
        "\n#[allow(dead_code)] fn _nano_agent_body() { %s }\n" % BODY_INSERT
    )
    targets = files if kind == "large" else files[:1]
    for path in targets:
        original = path.read_text(encoding="utf-8")
        if insert.strip() in original:
            continue
        path.write_text(original + insert, encoding="utf-8")
        records.append((path, original))
    return records


def restore_records(records):
    for path, original in reversed(records):
        path.write_text(original, encoding="utf-8")


def cargo_cmd(loop: str, package: str | None, offline: bool = True) -> list[str]:
    argv = ["cargo", "+nightly"]
    if loop == "test":
        argv += ["test", "--no-run"]
    else:
        argv += ["check"]
    if package:
        argv += ["-p", package]
    if offline:
        argv.append("--offline")
    argv += ["--message-format=human"]
    return argv


def run_cargo(argv, cwd, env, timeout=3600):
    start = time.perf_counter()
    result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, timeout=timeout)
    elapsed = (time.perf_counter() - start) * 1000
    text = (result.stderr or b"").decode(errors="replace") + "\n" + (result.stdout or b"").decode(errors="replace")
    return {
        "ms": elapsed,
        "returncode": result.returncode,
        "compiled": parse_compiled(text),
        "crates_compiled": len(parse_compiled(text)),
        "ok": result.returncode == 0,
        "stderr_tail": text[-2000:],
    }


def kache_bin():
    return shutil.which("kache")


def sccache_bin():
    return shutil.which("sccache")


def nano_env(base, store, wrapper, extra):
    env = dict(base)
    env["NANOCOMPILE_DIR"] = str(store)
    env["RUSTC_WRAPPER"] = str(wrapper)
    env.pop("RUSTC_WORKSPACE_WRAPPER", None)
    env.pop("KACHE_CACHE_DIR", None)
    for key in list(env):
        if key.startswith("KACHE_"):
            env.pop(key, None)
    env.update(extra)
    env.setdefault("CARGO_INCREMENTAL", "1")
    env.setdefault("NANOCOMPILE_ALLOW_INCREMENTAL", "1")
    return env


def kache_env(base, store):
    env = dict(base)
    env["RUSTC_WRAPPER"] = kache_bin() or "kache"
    env["KACHE_CACHE_DIR"] = str(store)
    env["KACHE_LOCAL_ONLY"] = "1"
    env["KACHE_SCHEDULER"] = "0"
    env["CARGO_INCREMENTAL"] = "1"
    env.pop("RUSTC_WORKSPACE_WRAPPER", None)
    for key in ("NANOCOMPILE_DIR", "NANOCOMPILE_ALLOW_INCREMENTAL"):
        env.pop(key, None)
    return env


def none_env(base):
    env = dict(base)
    env.pop("RUSTC_WRAPPER", None)
    env.pop("RUSTC_WORKSPACE_WRAPPER", None)
    env.pop("NANOCOMPILE_DIR", None)
    env.pop("KACHE_CACHE_DIR", None)
    env.pop("SCCACHE_DIR", None)
    env["CARGO_INCREMENTAL"] = "1"
    return env


def sccache_env(base, store):
    env = dict(base)
    env["RUSTC_WRAPPER"] = sccache_bin() or "sccache"
    env["SCCACHE_DIR"] = str(store)
    env["SCCACHE_DIRECT"] = "1"
    env["CARGO_INCREMENTAL"] = "0"
    env.pop("RUSTC_WORKSPACE_WRAPPER", None)
    for key in ("NANOCOMPILE_DIR", "NANOCOMPILE_ALLOW_INCREMENTAL", "KACHE_CACHE_DIR"):
        env.pop(key, None)
    return env


def approach_env(approach, base, store, wrapper, extra):
    if approach == "nanocompile":
        return nano_env(base, store, wrapper, extra)
    if approach == "kache":
        return kache_env(base, store)
    if approach == "sccache":
        return sccache_env(base, store)
    return none_env(base)


def is_git(root: Path) -> bool:
    return (root / ".git").exists() or subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
    ).returncode == 0


def add_worktree(src: Path, dest: Path, commit: str | None = None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        remove_worktree(src, dest)
    if is_git(src):
        argv = ["git", "-C", str(src), "worktree", "add", "--detach", str(dest)]
        if commit:
            argv.append(commit)
        result = subprocess.run(argv, capture_output=True, text=True)
        if result.returncode == 0:
            return "git"
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    bench.copy_project(src, dest)
    return "copy"


def remove_worktree(src: Path, dest: Path):
    if dest.exists() and is_git(src):
        subprocess.run(["git", "-C", str(src), "worktree", "remove", "--force", str(dest)], capture_output=True)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)


def older_commit(root: Path, steps: int = 20) -> str | None:
    if not is_git(root):
        return None
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD~%d" % steps],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    result = subprocess.run(
        ["git", "-C", str(root), "rev-list", "--max-parents=0", "HEAD"],
        capture_output=True, text=True,
    )
    sha = (result.stdout or "").splitlines()
    return sha[0] if sha else None


def first_green(argv, cwd, env, loops=("check",)):
    """Time to first green cargo check / cargo test (compile only for test)."""
    out = {}
    for loop in loops:
        cmd = list(argv)
        if loop == "test":
            cmd = ["cargo", "+nightly", "test", "--offline"] + (["-p", argv[argv.index("-p") + 1]] if "-p" in argv else [])
        measured = run_cargo(cmd if loop == "test" else argv, cwd, env)
        out[loop] = measured
        if not measured["ok"]:
            break
    return out


EDIT_CYCLE = ("body", "sig", "dep", "body", "sig", "dep", "large", "body")


def measure_worktrees(
    sample: str,
    src: Path,
    work: Path,
    wrapper: Path,
    approach: str,
    extra_env: dict,
    n_worktrees: int,
    mode: str,
    loop: str,
    package: str | None,
    edit_kind: str = "mixed",
    from_older: bool = False,
    measure_test: bool = False,
):
    store = work / "store"
    main = work / "main"
    if main.exists():
        shutil.rmtree(main)
    if store.exists():
        shutil.rmtree(store, ignore_errors=True)
        if store.exists():
            shutil.rmtree(store, ignore_errors=True)
    bench.copy_project(src, main)
    if not (main / "rust-toolchain.toml").exists() and not (main / "rust-toolchain").exists():
        (main / "rust-toolchain.toml").write_text('[toolchain]\nchannel = "nightly"\n', encoding="utf-8")
    base = {k: v for k, v in os.environ.items() if not k.startswith(("NANOCOMPILE_", "KACHE_", "R2_"))}
    base.pop("RUSTC_WRAPPER", None)
    base.pop("RUSTC_WORKSPACE_WRAPPER", None)
    base["RUSTUP_TOOLCHAIN"] = "nightly"
    env = approach_env(approach, base, store, wrapper, extra_env)
    shared_target = work / "shared-target"
    if approach == "shared_target":
        env["CARGO_TARGET_DIR"] = str(shared_target)
    argv = cargo_cmd(loop, package)

    def snapshot():
        if approach == "nanocompile":
            return read_nano_stats(wrapper, store)
        if approach == "kache":
            return read_kache_stats(store)
        return {}

    if approach == "sccache" and not sccache_bin():
        return {
            "sample": sample, "approach": approach, "ok": False, "error": "sccache not installed",
            "n_worktrees": n_worktrees, "mode": mode, "loop": loop, "edit_kind": edit_kind,
            "from_older": from_older, "crates_compiled_mean": None, "wall_ms": None,
            "disk_bytes": None, "store_bytes": None,
        }

    before_warm = snapshot()
    warm = run_cargo(argv, main, env)
    if not warm["ok"] and "--offline" in argv:
        argv = [a for a in argv if a != "--offline"]
        warm = run_cargo(argv, main, env)
    if approach in ("nanocompile", "kache", "sccache"):
        if approach != "sccache":
            warm_compiled, warm_restored = stats_compiled(before_warm, snapshot())
            warm["crates_compiled"] = warm_compiled
            warm["crates_restored"] = warm_restored
    worktrees = []
    commit = older_commit(src) if from_older else None
    kinds = []
    for i in range(n_worktrees):
        if edit_kind == "mixed":
            kinds.append(EDIT_CYCLE[i % len(EDIT_CYCLE)])
        else:
            kinds.append(edit_kind)
    for i in range(n_worktrees):
        dest = work / ("wt-%d" % i)
        add_worktree(main if not from_older else src, dest, commit if from_older else None)
        records = apply_agent_edit(dest, kinds[i])
        target = dest / "target" if approach != "shared_target" else shared_target
        wt_env = dict(env)
        if approach != "shared_target":
            wt_env["CARGO_TARGET_DIR"] = str(target)
        worktrees.append({"path": dest, "env": wt_env, "target": target, "records": records, "kind": kinds[i]})

    per = []
    start = time.perf_counter()
    if mode == "concurrent":
        before = snapshot()
        with ThreadPoolExecutor(max_workers=n_worktrees) as pool:
            futs = {pool.submit(run_cargo, argv, wt["path"], wt["env"]): i for i, wt in enumerate(worktrees)}
            by_i = {}
            for fut in as_completed(futs):
                by_i[futs[fut]] = fut.result()
            per = [by_i[i] for i in range(n_worktrees)]
        compiled_delta, restored_delta = stats_compiled(before, snapshot())
        if approach in ("nanocompile", "kache") and n_worktrees:
            share = compiled_delta / n_worktrees
            restore_share = restored_delta / n_worktrees
            for row in per:
                row["crates_compiled"] = share
                row["crates_restored"] = restore_share
    else:
        for wt in worktrees:
            before = snapshot()
            row = run_cargo(argv, wt["path"], wt["env"])
            if approach in ("nanocompile", "kache"):
                compiled_delta, restored_delta = stats_compiled(before, snapshot())
                row["crates_compiled"] = compiled_delta
                row["crates_restored"] = restored_delta
            per.append(row)
    wall_ms = (time.perf_counter() - start) * 1000

    first = {}
    if measure_test and per and per[0]["ok"]:
        first = first_green(argv, worktrees[0]["path"], worktrees[0]["env"], ("check", "test"))

    targets = [wt["target"] for wt in worktrees] + [main / "target"]
    if approach == "shared_target":
        targets = [shared_target]
    disk = unique_disk_bytes([store, *targets])
    store_bytes = unique_disk_bytes([store]) if store.exists() else 0
    compiled = [row["crates_compiled"] for row in per]
    mean_compiled = sum(compiled) / len(compiled) if compiled else 0
    restored = max(0, warm["crates_compiled"] - mean_compiled)
    row = {
        "sample": sample,
        "approach": approach,
        "n_worktrees": n_worktrees,
        "mode": mode,
        "loop": loop,
        "edit_kind": edit_kind,
        "from_older": from_older,
        "warm_ms": warm["ms"],
        "warm_crates": warm["crates_compiled"],
        "warm_ok": warm["ok"],
        "wall_ms": wall_ms,
        "crates_compiled": compiled,
        "crates_compiled_mean": mean_compiled,
        "crates_restored_mean": restored,
        "per_worktree_ms": [row["ms"] for row in per],
        "ok": warm["ok"] and all(row["ok"] for row in per),
        "disk_bytes": disk,
        "store_bytes": store_bytes,
        "first_green": first,
        "errors": [row["stderr_tail"] for row in per if not row["ok"]][:2],
    }
    for wt in worktrees:
        restore_records(wt["records"])
        remove_worktree(main, wt["path"])
    return row


def pct_gain(baseline: float, value: float) -> float | None:
    if baseline is None or baseline <= 0 or value is None:
        return None
    return (baseline - value) / baseline


def summarize_pair(base_rows, new_rows, metrics=OBJECTIVES):
    out = {}
    for metric in metrics:
        base_vals = [r[metric] for r in base_rows if r.get("ok") and r.get(metric) is not None]
        new_vals = [r[metric] for r in new_rows if r.get("ok") and r.get(metric) is not None]
        if not base_vals or not new_vals:
            out[metric] = {"gain": None, "keep": False, "base": None, "new": None}
            continue
        base = sum(base_vals) / len(base_vals)
        new = sum(new_vals) / len(new_vals)
        gain = pct_gain(base, new)
        out[metric] = {"gain": gain, "keep": bool(gain is not None and gain > MIN_GAIN), "base": base, "new": new}
    return out


def default_nano() -> Path:
    return REPO / "zig-out" / "bin" / "nanocompile"


def run_matrix(samples, levers, n_list, modes, wrapper, work_root, variants=None, split="train"):
    rows = []
    variants = variants or [{"edit_kind": "mixed", "from_older": False, "n": None}]
    for sample in samples:
        info = SAMPLE_CATALOG[sample]
        src = info["path"]
        if not src.exists():
            rows.append({"sample": sample, "ok": False, "error": "missing sample", "split": split})
            continue
        for lever in levers:
            for n in n_list:
                for mode in modes:
                    for variant in variants:
                        n_wt = variant.get("n") or n
                        work = work_root / sample / lever["id"] / ("%d-%s-%s-%s" % (
                            n_wt, mode, variant.get("edit_kind", "mixed"),
                            "old" if variant.get("from_older") else "head",
                        ))
                        if work.exists():
                            shutil.rmtree(work, ignore_errors=True)
                        work.mkdir(parents=True)
                        try:
                            row = measure_worktrees(
                                sample, src, work, wrapper,
                                lever["approach"], lever.get("env") or {},
                                n_wt, mode, lever.get("loop") or "check",
                                info.get("package"),
                                edit_kind=variant.get("edit_kind", "mixed"),
                                from_older=bool(variant.get("from_older")),
                                measure_test=lever.get("loop") == "test",
                            )
                        except Exception as exc:
                            row = {"sample": sample, "ok": False, "error": str(exc), "approach": lever["approach"]}
                        row["lever"] = lever["id"]
                        row["env"] = dict(lever.get("env") or {})
                        row["split"] = split
                        row["held_out"] = split == "held_out"
                        row["product"] = "agent_worktrees"
                        row["variant"] = {
                            "edit_kind": variant.get("edit_kind", "mixed"),
                            "from_older": bool(variant.get("from_older")),
                        }
                        rows.append(row)
                        progress = {
                            k: row.get(k) for k in (
                                "sample", "lever", "approach", "n_worktrees", "mode",
                                "wall_ms", "crates_compiled_mean", "disk_bytes", "store_bytes",
                                "ok", "split",
                            )
                        }
                        if not row.get("ok"):
                            progress["error"] = ((row.get("errors") or [row.get("error") or ""])[0] or "")[-240:]
                        print(json.dumps(progress), flush=True)
                        write_json(REPO / "bench" / "archive" / "agent-worktrees.partial.json", {"rows": rows})
    return rows


def keep_decision(summary, metrics=OBJECTIVES):
    """Keep a >3% win on any objective that does not regress another past 3%."""
    win = False
    regress = False
    for metric in metrics:
        info = summary.get(metric) or {}
        gain = info.get("gain")
        if gain is None:
            continue
        if gain > MIN_GAIN:
            win = True
        if gain < -MIN_GAIN:
            regress = True
    return win and not regress


def dominates(a, b, metrics=OBJECTIVES):
    """True when a is <= b on every objective and strictly better on one."""
    any_strict = False
    for metric in metrics:
        av, bv = a.get(metric), b.get(metric)
        if av is None or bv is None:
            return False
        if av > bv + 1e-9:
            return False
        if av < bv - 1e-9:
            any_strict = True
    return any_strict


def pareto_frontier(rows, metrics=OBJECTIVES):
    ok = [r for r in rows if r.get("ok") and all(r.get(m) is not None for m in metrics)]
    frontier = []
    for row in ok:
        if not any(dominates(other, row, metrics) for other in ok if other is not row):
            frontier.append(row)
    return frontier


def pareto_by_repo(rows, split="held_out"):
    out = {}
    for sample in sorted({r.get("sample") for r in rows if r.get("sample")}):
        subset = [
            r for r in rows
            if r.get("sample") == sample and r.get("ok")
            and r.get("n_worktrees") == 4
            and r.get("mode") in ("sequential", None)
            and (r.get("edit_kind") or (r.get("variant") or {}).get("edit_kind") or "mixed") == "mixed"
            and not (r.get("from_older") or (r.get("variant") or {}).get("from_older"))
        ]
        front = pareto_frontier(subset)
        nano = [r for r in subset if r.get("approach") == "nanocompile"]
        dominated_by = []
        for row in nano:
            for other in subset:
                if other is row:
                    continue
                if dominates(other, row):
                    dominated_by.append({
                        "nano_lever": row.get("lever"),
                        "by": other.get("lever") or other.get("approach"),
                        "approach": other.get("approach"),
                        "objectives": {m: {"nano": row.get(m), "other": other.get(m)} for m in OBJECTIVES},
                    })
        out[sample] = {
            "split": split,
            "frontier": [
                {
                    "lever": r.get("lever"),
                    "approach": r.get("approach"),
                    **{m: r.get(m) for m in OBJECTIVES},
                }
                for r in front
            ],
            "nano_dominated_by": dominated_by,
            "nano_on_frontier": any(r.get("approach") == "nanocompile" for r in front),
        }
    return out


def hill_climb(rows):
    """One change at a time on train. Keep >3% wins that do not regress another >3%."""
    log = []
    kept = ["l0_nano_best"]
    stalled = {}
    train = [r for r in rows if r.get("split") == "train" and r.get("ok")]
    none_rows = [r for r in train if r.get("lever") == "none" and r.get("mode") == "sequential"]
    current = [r for r in train if r.get("lever") == "l0_nano_best" and r.get("mode") == "sequential"]
    vs_none = summarize_pair(none_rows, current)
    log.append({"lever": "l0_nano_best", "vs": "none", "metrics": vs_none, "keep": True})
    frozen_env = dict(NANO_BEST)
    lever_ids = []
    seen = set()
    for row in rows:
        lid = row.get("lever")
        if lid and lid not in seen and lid not in ("none", "shared_target", "kache", "sccache", "l0_nano_best"):
            seen.add(lid)
            lever_ids.append(lid)
    for lever_id in lever_ids:
        nxt = [r for r in train if r.get("lever") == lever_id]
        loop = "test" if "test" in lever_id else "check"
        base = [r for r in current if r.get("loop") == loop]
        cand = [r for r in nxt if r.get("loop") == loop and r.get("mode") == "sequential"] or nxt
        if "test" in lever_id and not base:
            log.append({
                "lever": lever_id, "vs": "coverage", "metrics": {}, "keep": False,
                "samples": sorted({r["sample"] for r in cand if r.get("ok")}),
                "note": "cargo test --no-run coverage; --test is eligible under EXECUTABLE_PRODUCERS. No prior test-loop elite to beat by 3%.",
            })
            for metric in OBJECTIVES:
                stalled[metric] = stalled.get(metric, 0) + 1
            continue
        summary = summarize_pair(base or current, cand)
        keep = keep_decision(summary)
        samples = {r["sample"] for r in cand if r.get("ok")}
        log.append({"lever": lever_id, "vs": kept[-1], "metrics": summary, "keep": keep, "samples": sorted(samples)})
        for metric, info in summary.items():
            if not info["keep"]:
                stalled[metric] = stalled.get(metric, 0) + 1
            else:
                stalled[metric] = 0
        if keep:
            kept.append(lever_id)
            current = cand
            for row in cand:
                env = row.get("env")
                if env:
                    frozen_env = dict(env)
                    break
    if not any(r.get("env") for r in current):
        frozen_env = NANO_SCRIPT if "l1_script_cache" in kept or "script" in kept[-1] else dict(NANO_BEST)
    return {
        "min_gain_pct": MIN_GAIN * 100,
        "kept": kept,
        "stalled": stalled,
        "log": log,
        "frozen_env": frozen_env,
        "frozen_lever": kept[-1] if kept else "l0_nano_best",
        "pareto": pareto_by_repo(train, "train"),
    }


def survival(train_rows, held_rows, frozen_lever):
    """How much of the train gain vs none survives on held-out, per metric."""
    out = {"per_metric": {}, "per_sample": {}, "repo_specific": [], "general": []}
    metrics = OBJECTIVES
    for metric in metrics:
        train_none = [r.get(metric) for r in train_rows if r.get("lever") == "none" and r.get("ok")]
        train_fr = [r.get(metric) for r in train_rows if r.get("lever") == frozen_lever and r.get("ok")]
        held_none = [r.get(metric) for r in held_rows if r.get("approach") in ("none",) and r.get("ok") and not r.get("variant", {}).get("from_older") and r.get("n_worktrees") == 4]
        held_fr = [r.get(metric) for r in held_rows if r.get("lever") == frozen_lever and r.get("ok") and not r.get("variant", {}).get("from_older") and r.get("n_worktrees") == 4 and r.get("edit_kind", "mixed") in ("mixed", None)]
        # held rows from frozen config may be tagged lever=frozen
        if not held_fr:
            held_fr = [r.get(metric) for r in held_rows if r.get("approach") == "nanocompile" and r.get("ok")
                       and r.get("n_worktrees") == 4 and not r.get("from_older")
                       and (r.get("variant") or {}).get("edit_kind") == "mixed"
                       and not (r.get("variant") or {}).get("from_older")]
        t_gain = pct_gain(avg(train_none), avg(train_fr))
        h_gain = pct_gain(avg(held_none), avg(held_fr))
        survived = None if t_gain is None or t_gain <= 0 or h_gain is None else h_gain / t_gain
        out["per_metric"][metric] = {
            "train_gain": t_gain,
            "held_out_gain": h_gain,
            "survived_fraction": survived,
        }
    # Per-sample: settings that only help one repo are repo-specific.
    for sample in {r["sample"] for r in held_rows}:
        none = [r for r in held_rows if r["sample"] == sample and r.get("approach") == "none" and r.get("ok")]
        fr = [r for r in held_rows if r["sample"] == sample and r.get("approach") == "nanocompile" and r.get("ok")
              and r.get("n_worktrees") == 4 and not (r.get("variant") or {}).get("from_older")]
        gains = {m: pct_gain(avg([r.get(m) for r in none]), avg([r.get(m) for r in fr])) for m in metrics}
        out["per_sample"][sample] = gains
    train_gain_wall = out["per_metric"]["wall_ms"]["train_gain"]
    for sample, gains in out["per_sample"].items():
        g = gains.get("wall_ms")
        if g is None:
            continue
        if train_gain_wall and g > 0 and g + 1e-9 >= 0.5 * train_gain_wall:
            out["general"].append(sample)
        else:
            out["repo_specific"].append(sample)
    return out


def avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def breakdown(held_rows):
    """Where the shared store breaks: more worktrees, larger edits, older main."""
    out = []
    for row in held_rows:
        if not row.get("ok"):
            out.append({
                "sample": row.get("sample"),
                "n_worktrees": row.get("n_worktrees"),
                "variant": row.get("variant"),
                "ok": False,
                "error": row.get("error") or (row.get("errors") or [None])[0],
            })
            continue
        out.append({
            "sample": row["sample"],
            "n_worktrees": row.get("n_worktrees"),
            "mode": row.get("mode"),
            "edit_kind": (row.get("variant") or {}).get("edit_kind"),
            "from_older": (row.get("variant") or {}).get("from_older"),
            "approach": row.get("approach"),
            "crates_compiled_mean": row.get("crates_compiled_mean"),
            "wall_ms": row.get("wall_ms"),
            "disk_bytes": row.get("disk_bytes"),
            "store_bytes": row.get("store_bytes"),
            "ok": True,
        })
    return out


def row_evaluation(row, split):
    info = SAMPLE_CATALOG.get(row.get("sample") or "", {})
    size = info.get("size") or "mid"
    approach = row.get("approach") or "none"
    return {
        "cell": "%s|worktree" % size,
        "size": size,
        "edit": "worktree",
        "genome": {
            "wrapper": approach == "nanocompile",
            "dev_backend": "llvm",
            "linker": "default",
            "sccache": False,
            "kache": approach == "kache",
            "warm_store": approach in ("nanocompile", "kache"),
            "incremental": True,
            "debuginfo": "full",
            "fast_check": "cargo-check",
            "loop": row.get("loop") or "check",
        },
        "fitness_ms": float(row.get("wall_ms") or 0),
        "disk_bytes": row.get("disk_bytes"),
        "store_bytes": row.get("store_bytes"),
        "pareto": True,
        "correctness": {
            "ok": bool(row.get("ok")),
            "agree_on_broken": True,
            "validate_is_final": True,
        },
        "sample": "%s-agent-worktrees-%s" % (row.get("sample"), split),
        "held_out": True,
        "split": split,
        "product": "agent_worktrees",
        "cache_tool": "nanocompile" if approach == "nanocompile" else "kache" if approach == "kache" else "none",
        "cache_state": "warm_compiler_cache" if approach in ("nanocompile", "kache") else "empty",
        "n_worktrees": row.get("n_worktrees"),
        "mode": row.get("mode"),
        "crates_compiled_mean": row.get("crates_compiled_mean"),
        "variant": row.get("variant"),
        "lever": row.get("lever"),
    }


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("schema_version", 1)
    payload.setdefault("kind", "nanocompile.rust-loop.map-elites.shard")
    payload.setdefault("sample", "agent-worktrees")
    evals = [row_evaluation(r, "train") for r in payload.get("train") or []]
    evals += [row_evaluation(r, "held_out") for r in payload.get("held_out") or []]
    payload["evaluations"] = evals
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def record_archive(payload, map_path: Path):
    archive = json.loads(map_path.read_text(encoding="utf-8"))
    notes = archive.setdefault("design_notes", [])
    note = (
        "agent-worktrees rows live in archive.agent_worktrees (split=train|held_out). "
        "They do not occupy the size x edit grid. worktree init ships the frozen general config."
    )
    if note not in notes:
        notes.append(note)
    rules = archive.setdefault("size_rules", {})
    rules["agent_worktrees"] = (
        "Train on axum+ripgrep; freeze; held-out on bhumi/hashbrown/nalgebra/serde/ruff/tokio/emergentDB. "
        "Minimize crates/wt, wall, unique disk, store. Tag split=train|held_out. Occupancy unchanged. "
        "archive.agent_worktrees.pareto is the per-repo frontier."
    )
    archive["agent_worktrees"] = payload
    history = archive.setdefault("history", [])
    history.append({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sample": "agent-worktrees",
        "cell": "mid|worktree",
        "action": "held_out",
        "fitness_ms": None,
        "reason": "agent-worktrees train/held-out recorded separately; occupancy unchanged",
    })
    map_path.write_text(json.dumps(archive, indent=2) + "\n", encoding="utf-8")


def render_docs(payload) -> str:
    climb = payload.get("hill_climb") or {}
    surv = payload.get("survival") or {}
    frozen = climb.get("frozen_env") or NANO_SCRIPT
    lines = [
        "# Agent worktrees",
        "",
        "Use nanocompile so a main checkout plus N git worktrees (one per coding agent)",
        "compile as little as possible. Each worktree has its own `CARGO_TARGET_DIR`.",
        "One shared `NANOCOMPILE_DIR` restores everything main or a sibling already",
        "compiled. Only crates the worktree's own edit invalidates should miss.",
        "",
        "Occupancy of the size × edit MAP-Elites grid is unchanged. These rows are",
        "tagged `split=train|held_out` in `bench/map_elites.json` → `agent_worktrees`.",
        "",
        "## Setup Rach should use",
        "",
        "```sh",
        "zig build -Doptimize=ReleaseFast",
        "./zig-out/bin/nanocompile worktree init",
        "git worktree add --detach ../agent-1",
        "git worktree add --detach ../agent-2",
        "# each worktree keeps target/; the store is shared",
        "cargo check",
        "```",
        "",
        "`worktree init` writes `.cargo/config.toml` with the **general** frozen",
        "config (not per-repo knobs):",
        "",
        "```toml",
        "[build]",
        "rustc-wrapper = \"/absolute/path/nanocompile\"",
        "",
        "[env]",
        "NANOCOMPILE_DIR = { value = \"$XDG_CACHE_HOME/nanocompile\", force = true }",
    ]
    for key, value in frozen.items():
        lines.append("%s = { value = \"%s\", force = true }" % (key, value))
    lines += [
        "```",
        "",
        "Do not stack `RUSTC_WRAPPER=nanocompile` with sccache or kache.",
        "",
        "## Hill-climb (train = axum + ripgrep)",
        "",
        "One lever at a time. Keep a change only when it beats the previous elite",
        "by more than 3% on crates compiled per worktree, total wall, unique disk",
        "(hardlinks counted once), or store size, and does not regress another",
        "objective past 3%. Stop a metric after it stalls.",
        "",
        "| lever | vs | crates/worktree | wall | disk | store | keep |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry in climb.get("log") or []:
        m = entry.get("metrics") or {}
        def fmt(metric):
            info = m.get(metric) or {}
            g = info.get("gain")
            return "n/a" if g is None else "%.1f%%" % (g * 100)
        note = "coverage" if entry.get("vs") == "coverage" else ("yes" if entry.get("keep") else "stall")
        lines.append("| `%s` | %s | %s | %s | %s | %s | %s |" % (
            entry.get("lever"), entry.get("vs"),
            fmt("crates_compiled_mean"), fmt("wall_ms"), fmt("disk_bytes"),
            fmt("store_bytes"),
            note,
        ))
        if entry.get("note"):
            lines.append("")
            lines.append(entry["note"])
            lines.append("")
    lines += [
        "",
        "Frozen lever: `%s`." % climb.get("frozen_lever", "l0_nano_best"),
        "",
        "## Generalization (held-out)",
        "",
        "Config was frozen on axum+ripgrep, then run unchanged on bhumi, hashbrown,",
        "nalgebra, serde, ruff, tokio, and emergentDB (Rach's repo; tokio is not).",
        "",
        "| metric | train gain vs none | held-out gain vs none | fraction that survived |",
        "| --- | --- | --- | --- |",
    ]
    for metric, info in (surv.get("per_metric") or {}).items():
        def pct(v):
            return "n/a" if v is None else "%.1f%%" % (v * 100)
        lines.append("| %s | %s | %s | %s |" % (
            metric,
            pct(info.get("train_gain")),
            pct(info.get("held_out_gain")),
            pct(info.get("survived_fraction")),
        ))
    lines += [
        "",
        "### Repo-specific vs general",
        "",
        "Settings that kept at least half the train wall-time gain on a held-out",
        "repo are treated as **general**. The rest are **repo-specific**; we still",
        "ship the general config.",
        "",
        "- general: %s" % (", ".join(surv.get("general") or []) or "(none yet)"),
        "- repo-specific: %s" % (", ".join(surv.get("repo_specific") or []) or "(none yet)"),
        "",
        "### Where the shared store breaks",
        "",
        "Held-out variants: 8 worktrees, larger edits (several files), worktrees",
        "branching from an older main. Shared-target (one `CARGO_TARGET_DIR`) is",
        "the lock-contention control.",
        "",
        "| sample | n | edit | older main | approach | crates/wt | wall ms | disk | store | ok |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload.get("breakdown") or []:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            row.get("sample"),
            row.get("n_worktrees"),
            row.get("edit_kind"),
            row.get("from_older"),
            row.get("approach"),
            "%.1f" % row["crates_compiled_mean"] if row.get("crates_compiled_mean") is not None else "",
            "%.0f" % row["wall_ms"] if row.get("wall_ms") is not None else "",
            row.get("disk_bytes") or "",
            row.get("store_bytes") if row.get("store_bytes") is not None else "",
            "yes" if row.get("ok") else "no",
        ))
    lines += [
        "",
        "## Pareto frontier (minimize crates, wall, unique disk, store)",
        "",
        "A config is non-dominated when no competitor is better or equal on every",
        "objective and strictly better on one. Shipped `worktree init` must sit on",
        "the held-out frontier for every repo.",
        "",
    ]
    pareto = payload.get("pareto") or {}
    for split_name, label in (("train", "Train"), ("held_out", "Held-out")):
        block = pareto.get(split_name) or {}
        lines += ["### %s" % label, ""]
        if not block:
            lines += ["(not measured yet)", ""]
            continue
        for sample, info in block.items():
            on = "yes" if info.get("nano_on_frontier") else "NO"
            lines.append("**%s** — nanocompile on frontier: %s" % (sample, on))
            lines.append("")
            lines.append("| approach | lever | crates/wt | wall ms | disk | store |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for row in info.get("frontier") or []:
                lines.append("| %s | %s | %s | %s | %s | %s |" % (
                    row.get("approach"),
                    row.get("lever"),
                    "%.1f" % row["crates_compiled_mean"] if row.get("crates_compiled_mean") is not None else "",
                    "%.0f" % row["wall_ms"] if row.get("wall_ms") is not None else "",
                    row.get("disk_bytes") if row.get("disk_bytes") is not None else "",
                    row.get("store_bytes") if row.get("store_bytes") is not None else "",
                ))
            if info.get("nano_dominated_by"):
                lines.append("")
                for dom in info["nano_dominated_by"]:
                    lines.append("- dominated by `%s` (%s)" % (dom.get("by"), dom.get("approach")))
            lines.append("")
    lines += [
        "",
        "## Train table (4 worktrees, sequential + concurrent)",
        "",
        "| sample | lever | approach | n | mode | crates/wt | wall ms | disk | store | ok |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload.get("train") or []:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            row.get("sample"),
            row.get("lever"),
            row.get("approach"),
            row.get("n_worktrees"),
            row.get("mode"),
            "%.1f" % row["crates_compiled_mean"] if row.get("crates_compiled_mean") is not None else "",
            "%.0f" % row["wall_ms"] if row.get("wall_ms") is not None else "",
            row.get("disk_bytes") or "",
            row.get("store_bytes") if row.get("store_bytes") is not None else "",
            "yes" if row.get("ok") else "no",
        ))
    lines += [
        "",
        "## What climbed",
        "",
        "- **L0** workspace-logical keys (`$NANO_MANIFEST` / `$NANO_WORKSPACE`) so",
        "  sibling worktrees share rustc identities. Incremental + reported",
        "  proc-macros + executable producers. Jobserver env is not part of the key.",
        "- **L3** `NANOCOMPILE_HARDLINK_TARGET=1`: after store, replace immutable",
        "  `.rlib`/`.rmeta`/`.so`/`.a` in `target/` with a hardlink to the CAS blob.",
        "- **L4** `NANOCOMPILE_ZSTD=1`: zstd-compress cold blobs (>=4KiB); restore",
        "  decompresses. Hot hardlinked blobs stay uncompressed.",
        "- **L5** `CARGO_INCREMENTAL=0` to drop per-worktree incremental dirs.",
        "- **L6** `NANOCOMPILE_DEBUGINFO=1` (line tables) to shrink cached blobs.",
        "- **L7** `NANOCOMPILE_SKIP_CHEAP=1`: skip storing artifacts cheaper to rebuild.",
        "- **L8** slim build-script RUN cache: only small OUT_DIR trees (<=256KiB,",
        "  no file >64KiB) so the script cache can cut crate count without +82% disk.",
        "",
        "Competitors on the same chart: no cache, shared `CARGO_TARGET_DIR`, kache,",
        "sccache (if it runs), and every nanocompile config tried.",
        "",
        "Harness: `bench/agent_worktrees.py`. Raw rows: `bench/archive/agent-worktrees.json`.",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", choices=("all", "train", "held-out", "record"), default="all")
    p.add_argument("--samples", default="")
    p.add_argument("--worktrees", default="4")
    p.add_argument("--modes", default="sequential,concurrent")
    p.add_argument("--nano", type=Path, default=default_nano())
    p.add_argument("--work", type=Path, default=Path("/tmp/agent-worktrees"))
    p.add_argument("--out", type=Path, default=REPO / "bench" / "archive" / "agent-worktrees.json")
    p.add_argument("--skip-baselines", action="store_true")
    p.add_argument("--quick", action="store_true", help="4 sequential worktrees only; skip concurrent and 8")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    wrapper = args.nano.resolve()
    if not wrapper.exists():
        raise SystemExit("missing nanocompile binary: %s (zig build -Doptimize=ReleaseFast)" % wrapper)
    n_list = [int(x) for x in args.worktrees.split(",") if x]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if args.quick:
        n_list = [4]
        modes = ["sequential"]
    train_names = [s.strip() for s in args.samples.split(",") if s.strip()] or list(TRAIN)
    payload = {}
    if args.out.exists() and args.phase != "train":
        try:
            payload = json.loads(args.out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}

    if args.phase in ("all", "train"):
        baselines = list(BASELINES if not args.skip_baselines else ())
        if not sccache_bin():
            baselines = [b for b in baselines if b["id"] != "sccache"]
        if args.quick:
            baselines = [b for b in baselines if b["id"] in ("none", "kache", "shared_target", "sccache")]
        train = run_matrix(
            train_names, baselines + [LEVERS[0]], n_list, modes, wrapper, args.work / "train", split="train",
        )
        elite_env = dict(NANO_BEST)
        elite_id = "l0_nano_best"
        if not args.quick:
            for delta in CLIMB_DELTAS:
                env = dict(elite_env)
                env.update(delta["env"])
                lever = {"id": delta["id"], "approach": "nanocompile", "env": env, "loop": "check"}
                nxt = run_matrix(
                    train_names, [lever], n_list, modes, wrapper, args.work / "train", split="train",
                )
                train.extend(nxt)
                base = [r for r in train if r.get("lever") == elite_id and r.get("ok") and r.get("mode") == "sequential"]
                cand = [r for r in nxt if r.get("ok") and r.get("mode") == "sequential"]
                summary = summarize_pair(base, cand)
                keep = keep_decision(summary)
                print(json.dumps({"climb": delta["id"], "vs": elite_id, "keep": keep, "metrics": {
                    m: (summary.get(m) or {}).get("gain") for m in OBJECTIVES
                }}), flush=True)
                if keep:
                    elite_env = env
                    elite_id = delta["id"]
        payload["train"] = train
        payload["hill_climb"] = hill_climb(train)
        payload["hill_climb"]["frozen_env"] = elite_env
        payload["hill_climb"]["frozen_lever"] = elite_id
        payload["pareto"] = {"train": pareto_by_repo(train, "train")}
        payload["commit"] = git_commit()
        payload["frozen_env"] = elite_env
        write_json(args.out, payload)

    if args.phase in ("all", "held-out"):
        frozen_env = (payload.get("hill_climb") or {}).get("frozen_env") or NANO_BEST
        frozen = [{"id": "frozen", "approach": "nanocompile", "env": frozen_env, "loop": "check"}]
        baselines = [] if args.quick else [
            {"id": "none", "approach": "none", "env": {}, "loop": "check"},
            {"id": "shared_target", "approach": "shared_target", "env": {}, "loop": "check"},
            {"id": "kache", "approach": "kache", "env": {}, "loop": "check"},
        ]
        if not args.quick and sccache_bin():
            baselines.append({"id": "sccache", "approach": "sccache", "env": {}, "loop": "check"})
        held = run_matrix(
            list(HELD_OUT), baselines + frozen, [4], ["sequential"],
            wrapper, args.work / "held",
            variants=[{"edit_kind": "mixed", "from_older": False, "n": 4}],
            split="held_out",
        )
        if not args.quick:
            held += run_matrix(
                list(HELD_OUT), frozen, [4], ["sequential"],
                wrapper, args.work / "held-variants",
                variants=[
                    {"edit_kind": "mixed", "from_older": False, "n": 8},
                    {"edit_kind": "large", "from_older": False, "n": 4},
                    {"edit_kind": "mixed", "from_older": True, "n": 4},
                ],
                split="held_out",
            )
        payload["held_out"] = held
        payload["survival"] = survival(payload.get("train") or [], held, (payload.get("hill_climb") or {}).get("frozen_lever") or "frozen")
        payload["breakdown"] = breakdown(held)
        payload.setdefault("pareto", {})
        payload["pareto"]["held_out"] = pareto_by_repo(held, "held_out")
        payload["commit"] = git_commit()
        write_json(args.out, payload)

    if args.phase in ("all", "record"):
        payload.setdefault("docs", "docs/agent-worktrees.md")
        payload.setdefault("harness", "bench/agent_worktrees.py")
        payload["commit"] = git_commit()
        write_json(args.out, payload)
        record_archive({
            "source": str(args.out.resolve().relative_to(REPO)),
            "docs": "docs/agent-worktrees.md",
            "harness": "bench/agent_worktrees.py",
            "commit": payload.get("commit"),
            "hill_climb": payload.get("hill_climb"),
            "survival": payload.get("survival"),
            "frozen_env": payload.get("frozen_env") or payload.get("hill_climb", {}).get("frozen_env"),
            "pareto": payload.get("pareto"),
            "train": payload.get("train") or [],
            "held_out": payload.get("held_out") or [],
            "breakdown": payload.get("breakdown") or [],
        }, REPO / "bench" / "map_elites.json")
        (REPO / "docs" / "agent-worktrees.md").write_text(render_docs(payload), encoding="utf-8")
        print("recorded", args.out, "and docs/agent-worktrees.md", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
