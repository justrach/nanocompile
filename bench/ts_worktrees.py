#!/usr/bin/env python3
"""MAP-Elites hill-climb for TypeScript agent worktrees.

Cells: checker (tsc / tsgo / tsrs / bun) × scenario
  (cold | leaf | shared | tsconfig | concurrent).

Each cell keeps a Pareto set over wall_ms, files_rechecked, store_bytes,
disk_bytes, rss_kb. Injected type errors are a hard gate.

Real `git worktree add` off a warm main. node_modules is a symlink to
main's install (counted once). `nanocompile worktree init` writes the TS
shims used for nanocompile rows.

Tune on condensation-site when present, else the 126-file public stand-in.
Freeze one shipped config, then verify held-out (ajv, prettier).

    python3 bench/ts_worktrees.py
    python3 bench/ts_worktrees.py --repo /path/to/any-ts-app
    python3 bench/ts_worktrees.py --phase record
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bench"))
import agent_worktrees as aw  # noqa: E402

OBJECTIVES = ("wall_ms", "files_rechecked", "store_bytes", "disk_bytes", "rss_kb")
SCENARIOS = ("cold", "leaf", "shared", "tsconfig", "concurrent")
STALL_ROUNDS = 2
MIN_GAIN = 0.03
N_WORKTREES = 4

CHECKERS = (
    {"id": "tsc", "bin_env": "NANOCOMPILE_TSC", "default": "tsc"},
    {"id": "tsgo", "bin_env": "NANOCOMPILE_TSGO", "default": "tsgo"},
    {"id": "tsrs", "bin_env": "NANOCOMPILE_TSRS", "default": "tsrs"},
    {"id": "bun", "bin_env": "NANOCOMPILE_BUN", "default": "bun"},
)

NANO_TS_FRONTIER = {
    "NANOCOMPILE_TS_INCREMENTAL": "1",
    "NANOCOMPILE_TS_SEED": "1",
    "NANOCOMPILE_TSRS_CHECKERS": "4",
}

CLIMB_DELTAS = (
    {"id": "l0_result_cache", "env": {"NANOCOMPILE_TS_INCREMENTAL": "0", "NANOCOMPILE_TS_SEED": "0"}},
    {"id": "l1_incremental", "env": {"NANOCOMPILE_TS_INCREMENTAL": "1", "NANOCOMPILE_TS_SEED": "0"}},
    {"id": "l2_seed_buildinfo", "env": {"NANOCOMPILE_TS_INCREMENTAL": "1", "NANOCOMPILE_TS_SEED": "1"}},
)

RSS_LINE = re.compile(r"Maximum resident set size \(kbytes\):\s+(\d+)")


def _condensation_path() -> Path:
    real = Path("/tmp/real-samples/condensation-site")
    if (real / "tsconfig.json").exists():
        return real
    return Path("/tmp/real-samples/condensation-standin")


SAMPLE_CATALOG = {
    "condensation-site": {"path": _condensation_path(), "size": "mid", "args": ["--noEmit"], "split": "train"},
    "ajv": {"path": Path("/tmp/real-samples/ajv"), "size": "mid", "args": ["--noEmit", "--pretty", "false"], "split": "held_out"},
    "prettier": {"path": Path("/tmp/real-samples/prettier"), "size": "large", "args": ["--noEmit", "--pretty", "false"], "split": "held_out"},
}


def which(name: str):
    return shutil.which(name)


def resolve_checker(spec) -> str | None:
    env_path = os.environ.get(spec["bin_env"])
    if env_path and Path(env_path).exists():
        return env_path
    for candidate in (
        REPO / "node_modules" / ".bin" / spec["default"],
        Path("/tmp/ts-tools/node_modules/.bin") / spec["default"],
        Path.home() / ".bun" / "bin" / spec["default"],
    ):
        if candidate.exists():
            return str(candidate)
    return which(spec["default"])


def available_checkers():
    out = []
    for spec in CHECKERS:
        exe = resolve_checker(spec)
        if exe:
            out.append({**spec, "exe": exe})
    return out


def is_git(root: Path) -> bool:
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
    ).returncode == 0


def ensure_git(root: Path):
    if is_git(root):
        return
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=nano@local", "-c", "user.name=nano", "commit", "-qm", "nano ts fixture"],
        cwd=root, check=True, capture_output=True,
    )


def clone_main(src: Path, dest: Path):
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    ensure_git(src)
    subprocess.run(["git", "clone", "--quiet", str(src), str(dest)], check=True, capture_output=True)
    link_node_modules(src, dest)


def add_git_worktree(main: Path, dest: Path):
    if dest.exists():
        subprocess.run(["git", "-C", str(main), "worktree", "remove", "--force", str(dest)], capture_output=True)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "--detach", str(dest)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("git worktree add failed: %s" % result.stderr)
    link_node_modules(main, dest)


def prune_worktrees(main: Path, dests):
    for dest in dests:
        subprocess.run(["git", "-C", str(main), "worktree", "remove", "--force", str(dest)], capture_output=True)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
    subprocess.run(["git", "-C", str(main), "worktree", "prune"], capture_output=True)


def link_node_modules(src: Path, dest: Path):
    target = dest / "node_modules"
    if target.exists() or target.is_symlink():
        return
    for candidate in (src / "node_modules", src.resolve() / "node_modules"):
        if candidate.exists():
            target.symlink_to(candidate.resolve())
            return


def compat_tsconfig_for_checker(root: Path, checker_id: str):
    """TS 7 / bun reject `moduleResolution=node10` from extended configs.
    Force bundler on the repo tsconfig so none / incremental / nano are
    measured on a checkable program (same rewrite for every approach)."""
    if checker_id not in {"tsgo", "tsrs", "bun"}:
        return
    path = root / "tsconfig.json"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    if "NodeNext" in text or "nodenext" in text:
        return
    if '"moduleResolution"' in text:
        for old in ('"node10"', '"node"', '"node16"', '"nodenext"'):
            text = text.replace(old, '"bundler"')
    elif '"compilerOptions"' in text:
        text = text.replace('"compilerOptions": {', '"compilerOptions": { "moduleResolution": "bundler",', 1)
        text = text.replace('"compilerOptions":{', '"compilerOptions":{ "moduleResolution": "bundler",', 1)
    path.write_text(text, encoding="utf-8")


def worktree_init(wrapper: Path, dest: Path, store: Path):
    subprocess.run(
        [str(wrapper), "worktree", "init", "--store", str(store), str(dest)],
        check=False, capture_output=True, text=True,
    )


CLASSIFY_SKIP = {
    "node_modules", ".git", ".next", "dist", "out", "coverage", ".turbo",
    "tests", "test", "__tests__", "website", "docs", "scripts", "fixtures",
    "examples", "playground", "templates", "vendors", "benchmarks", "bin",
}


def classify_sources(root: Path) -> dict:
    files = []
    for p in root.rglob("*"):
        if p.suffix not in {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}:
            continue
        if p.name.endswith(".d.ts"):
            continue
        rel_parts = p.relative_to(root).parts
        if any(part in CLASSIFY_SKIP or part.startswith(".") for part in rel_parts[:-1]):
            continue
        files.append(p)
    counts = {p: 0 for p in files}
    names = {p: p.stem for p in files}
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        for q, stem in names.items():
            if q == p:
                continue
            if stem and stem in text:
                counts[q] += 1
    shared = max(files, key=lambda p: (counts[p], -len(p.parts))) if files else None
    leaf = min(files, key=lambda p: (counts[p], -len(p.parts), str(p))) if files else None
    if shared is not None and leaf is not None and shared == leaf and len(files) > 1:
        leaf = min((p for p in files if p != shared), key=lambda p: (counts[p], -len(p.parts), str(p)))
    tsconfig = root / "tsconfig.json"
    return {
        "leaf": leaf,
        "shared": shared,
        "tsconfig": tsconfig if tsconfig.exists() else None,
        "n_sources": len(files),
        "import_counts": {str(p.relative_to(root)): c for p, c in counts.items()},
    }


def edit_file(path: Path, kind: str) -> dict:
    original = path.read_text(encoding="utf-8")
    if kind == "tsconfig":
        text = original
        if '"forceConsistentCasingInFileNames"' not in text:
            text = text.replace("{", '{ "forceConsistentCasingInFileNames": true,', 1)
        else:
            text = text.replace("true", "true ", 1) if "true" in text else text + "\n"
        path.write_text(text, encoding="utf-8")
    elif kind == "error":
        if path.suffix in {".js", ".jsx", ".mjs", ".cjs"}:
            path.write_text(
                original + "\n/** @type {never} */\nconst _nano_ts_error = true;\n_nano_undefined_ident;\n",
                encoding="utf-8",
            )
        else:
            path.write_text(original + "\nconst _nano_ts_error: never = true;\n_nano_undefined_ident;\n", encoding="utf-8")
    else:
        path.write_text(original + "\nvoid 0;\n", encoding="utf-8")
    return {"path": path, "text": original}


def restore_edit(rec):
    rec["path"].write_text(rec["text"], encoding="utf-8")


def nano_stats(wrapper: Path, store: Path) -> dict:
    return aw.read_nano_stats(wrapper, store)


def run_check(cwd: Path, checker: dict, approach: str, store: Path, wrapper: Path, extra_env=None, args=None):
    env = os.environ.copy()
    env["NANOCOMPILE_DIR"] = str(store)
    env[checker["bin_env"]] = checker["exe"]
    if extra_env:
        env.update(extra_env)
    args = list(args or ["--noEmit"])
    bin_dir = cwd / ".nanocompile" / "bin"
    if approach.startswith("nano") or approach in {d["id"] for d in CLIMB_DELTAS} or approach == "frozen":
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        if checker["id"] == "bun":
            cmd = [str(bin_dir / "bun") if (bin_dir / "bun").exists() else str(wrapper), "check"]
            if (bin_dir / "bun").exists():
                cmd = [str(bin_dir / "bun"), "check"]
            else:
                cmd = [str(wrapper), "bun", "check"]
        else:
            shim = bin_dir / checker["id"]
            cmd = [str(shim), *args] if shim.exists() else [str(wrapper), checker["id"], *args]
    elif approach == "incremental_local" and checker["id"] != "bun":
        info = cwd / (".%s.tsbuildinfo" % checker["id"])
        cmd = [checker["exe"], *args, "--incremental", "--tsBuildInfoFile", str(info)]
    else:
        cmd = [checker["exe"], "check"] if checker["id"] == "bun" else [checker["exe"], *args]
    time_bin = Path("/usr/bin/time") if Path("/usr/bin/time").exists() else None
    time_log = None
    run_cmd = list(cmd)
    if time_bin:
        fd, name = tempfile.mkstemp(prefix="nano-ts-time-")
        os.close(fd)
        time_log = Path(name)
        run_cmd = [str(time_bin), "-v", "-o", str(time_log), *cmd]
    before = nano_stats(wrapper, store)
    start = time.perf_counter()
    proc = subprocess.run(run_cmd, cwd=cwd, env=env, capture_output=True, text=True)
    wall_ms = (time.perf_counter() - start) * 1000
    after = nano_stats(wrapper, store)
    rss = 0
    if time_log:
        try:
            match = RSS_LINE.search(time_log.read_text(encoding="utf-8", errors="replace"))
            if match:
                rss = int(match.group(1))
        except OSError:
            rss = 0
        time_log.unlink(missing_ok=True)
    hits = int(after.get("typescript hits") or after.get("hits") or 0) - int(before.get("typescript hits") or before.get("hits") or 0)
    misses = int(after.get("typescript misses") or after.get("misses") or 0) - int(before.get("typescript misses") or before.get("misses") or 0)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "wall_ms": wall_ms,
        "rss_kb": rss,
        "hits": max(0, hits),
        "misses": max(0, misses),
        "stdout": (proc.stdout or "")[-2000:],
        "stderr": (proc.stderr or "")[-2000:],
        "error_seen": any(
            token in ((proc.stdout or "") + (proc.stderr or ""))
            for token in ("_nano_ts_error", "_nano_undefined_ident", "TS2304", "TS2322")
        ),
    }


def files_for(result, n_sources, approach):
    """none/incremental re-walk the program. A nano hit rechecks 0 files; a
    miss is one project-level recheck (the cache grain), not n_sources."""
    if approach.startswith("nano") or approach in {d["id"] for d in CLIMB_DELTAS} or approach == "frozen":
        if result["hits"] and not result["misses"]:
            return 0
        return 1
    return n_sources


def unique_disk(paths):
    return aw.unique_disk_bytes(paths)


def measure_setup(sample: str, src: Path, checker: dict, approach: str, wrapper: Path, work: Path, extra_env, args, n=N_WORKTREES):
    root = work / sample / checker["id"] / approach
    if root.exists():
        shutil.rmtree(root)
    main = root / "main"
    store = root / "store"
    store.mkdir(parents=True)
    clone_main(src, main)
    worktree_init(wrapper, main, store)
    compat_tsconfig_for_checker(main, checker["id"])
    kinds = classify_sources(main)
    n_sources = kinds["n_sources"] or 1
    env = dict(extra_env or {})
    warm = run_check(main, checker, approach, store, wrapper, env, args)
    trees = []
    for i in range(n):
        dest = root / ("wt-%d" % i)
        add_git_worktree(main, dest)
        worktree_init(wrapper, dest, store)
        compat_tsconfig_for_checker(dest, checker["id"])
        trees.append(dest)
    return {
        "root": root, "main": main, "store": store, "trees": trees,
        "kinds": kinds, "n_sources": n_sources, "warm": warm, "env": env,
    }


def scenario_rows(sample, checker, approach, lever, split, setup, wrapper, args):
    store, trees, kinds, n_sources, env = setup["store"], setup["trees"], setup["kinds"], setup["n_sources"], setup["env"]
    rows = []

    def pack(scenario, results, extra=None):
        walls = [r["wall_ms"] for r in results if r.get("wall_ms") is not None]
        rss = [r.get("rss_kb") or 0 for r in results]
        files = [files_for(r, n_sources, approach) for r in results]
        disk_roots = [store, setup["main"], *trees]
        nm = setup["main"] / "node_modules"
        if nm.exists() and not nm.is_symlink():
            disk_roots.append(nm.resolve())
        elif nm.is_symlink():
            disk_roots.append(nm.resolve())
        rec = {
            "sample": sample,
            "checker": checker["id"],
            "scenario": scenario,
            "cell": "%s|%s" % (checker["id"], scenario),
            "approach": "nanocompile" if approach not in ("none", "incremental_local") else approach,
            "lever": lever,
            "split": split,
            "check_ok": all(r.get("ok") for r in results) and setup["warm"]["ok"],
            "ok": True,
            "wall_ms": sum(walls) / len(walls) if walls else None,
            "files_rechecked": sum(files) / len(files) if files else None,
            "rss_kb": max(rss) if rss else 0,
            "store_bytes": unique_disk([store]),
            "disk_bytes": unique_disk(disk_roots),
            "n_worktrees": len(trees),
            "n_sources": n_sources,
            "warm_wall_ms": setup["warm"]["wall_ms"],
            "node_modules": "symlink-to-main",
        }
        if extra:
            rec.update(extra)
        return rec

    # cold: first check off warm main, sequential
    colds = [run_check(wt, checker, approach, store, wrapper, env, args) for wt in trees]
    rows.append(pack("cold", colds, {"per_worktree_wall_ms": [r["wall_ms"] for r in colds]}))

    # leaf / shared / tsconfig: edit then recheck that worktree
    mapping = [("leaf", 0, kinds["leaf"]), ("shared", 1, kinds["shared"]), ("tsconfig", 2, kinds["tsconfig"])]
    for scenario, idx, path in mapping:
        if path is None or idx >= len(trees):
            rows.append(pack(scenario, [{"ok": False, "wall_ms": None, "rss_kb": 0, "hits": 0, "misses": 1}]))
            continue
        rel = path.relative_to(setup["main"]) if path.is_relative_to(setup["main"]) else path.name
        target = trees[idx] / rel
        if not target.exists():
            # worktree has the same relative layout
            target = trees[idx] / path.name if scenario == "tsconfig" else trees[idx] / Path(*rel.parts)
        rec = edit_file(target, scenario)
        edited = run_check(trees[idx], checker, approach, store, wrapper, env, args)
        restore_edit(rec)
        rows.append(pack(scenario, [edited], {"edit_path": str(rel)}))

    # concurrent: all worktrees check at once (mixed leftover state is clean)
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(trees)) as pool:
        futs = [pool.submit(run_check, wt, checker, approach, store, wrapper, env, args) for wt in trees]
        conc = [f.result() for f in futs]
    span = (time.perf_counter() - start) * 1000
    packed = pack("concurrent", conc, {"concurrent_span_ms": span, "wall_ms": span})
    rows.append(packed)

    # correctness gate: inject error in last worktree; siblings must still hit clean
    error_ok = True
    false_hit = False
    inject = kinds["shared"] or kinds["leaf"]
    if inject is not None and trees:
        rel = inject.relative_to(setup["main"])
        victim = trees[-1] / rel
        rec = edit_file(victim, "error")
        bad = run_check(trees[-1], checker, approach, store, wrapper, env, args)
        restore_edit(rec)
        blob = (bad.get("stderr") or "") + (bad.get("stdout") or "")
        error_ok = (not bad["ok"]) and (
            bad.get("error_seen")
            or "_nano_ts_error" in blob or "_nano_undefined_ident" in blob
            or "TS2304" in blob or "TS2322" in blob
        )
        clean = run_check(trees[0], checker, approach, store, wrapper, env, args)
        # A sibling failure is only a false hit when the project was clean
        # before inject. Checkers that cannot typecheck the repo already fail.
        if setup["warm"]["ok"] and not clean["ok"]:
            false_hit = True
    for row in rows:
        row["error_reported"] = error_ok
        row["false_hit"] = false_hit
        row["correctness_ok"] = error_ok and not false_hit
        if not row["correctness_ok"]:
            row["ok"] = False
    return rows


def dominates(a, b, objectives=OBJECTIVES):
    le = all((a.get(o) or 0) <= (b.get(o) or 0) for o in objectives)
    lt = any((a.get(o) or 0) < (b.get(o) or 0) for o in objectives)
    return le and lt


def pareto_set(rows, objectives=OBJECTIVES):
    ok = [r for r in rows if r.get("correctness_ok", True) and r.get("wall_ms") is not None]
    front = []
    for a in ok:
        if not any(dominates(b, a, objectives) for b in ok if b is not a):
            front.append(a)
    return front


def cell_summary(rows):
    front = pareto_set(rows)
    nano = [r for r in rows if r.get("approach") == "nanocompile" and r.get("ok")]
    front_ids = {(r.get("approach"), r.get("lever")) for r in front}
    nano_on = any((r.get("approach"), r.get("lever")) in front_ids for r in nano)
    dominated_by = []
    for n in nano:
        for b in rows:
            if b is n or not b.get("ok"):
                continue
            if dominates(b, n):
                dominated_by.append({"by": b.get("approach"), "lever": b.get("lever")})
    return {
        "frontier": [
            {k: r.get(k) for k in ("approach", "lever", *OBJECTIVES)}
            for r in front
        ],
        "nano_on_frontier": nano_on,
        "nano_dominated_by": dominated_by,
    }


def survival(train_rows, held_rows, frozen_lever):
    out = {"per_metric": {}, "per_cell": {}}
    for obj in OBJECTIVES:
        def gain(rows, sample_checker_scenario=None):
            none = [r for r in rows if r.get("approach") == "none" and r.get("correctness_ok") and r.get(obj) is not None]
            nano = [r for r in rows if r.get("approach") == "nanocompile" and r.get("correctness_ok") and r.get(obj) is not None
                    and (r.get("lever") == frozen_lever or r.get("lever") == "frozen")]
            if sample_checker_scenario:
                none = [r for r in none if (r.get("sample"), r.get("cell")) == sample_checker_scenario]
                nano = [r for r in nano if (r.get("sample"), r.get("cell")) == sample_checker_scenario]
            if not none or not nano:
                return None
            n = sum(r[obj] for r in none) / len(none)
            m = sum(r[obj] for r in nano) / len(nano)
            return None if n == 0 else (n - m) / n
        train_g = gain(train_rows)
        held_g = gain(held_rows)
        out["per_metric"][obj] = {
            "train_gain": train_g,
            "held_out_gain": held_g,
            "survived_fraction": None if train_g in (None, 0) or held_g is None else held_g / train_g,
        }
    return out


def render_docs(payload) -> str:
    frozen = payload.get("frozen_env") or NANO_TS_FRONTIER
    lines = [
        "# TypeScript agent worktrees",
        "",
        "MAP-Elites cells are **checker × scenario**. Each cell keeps a Pareto",
        "set over wall time, files re-checked, store size, unique disk, and peak",
        "RSS. Injected type errors are a hard gate: a false hit cannot occupy.",
        "",
        "Checkers: `tsc` 5.9.3, TypeScript 7 (`tsgo`), `tsrs --checkers 4`, `bun check`.",
        "Scenarios: cold worktree off warm main; leaf-file edit; shared-types edit;",
        "tsconfig/config change; 3–4 worktrees checking concurrently.",
        "",
        "Setup uses real `git worktree add` off a warm main. `node_modules` is a",
        "**symlink to main's install** (one copy; unique disk counts that inode",
        "set once). `nanocompile worktree init` writes `.cargo/config.toml` and",
        "`.nanocompile/{env,bin/tsc,tsgo,tsrs,bun}` so a new worktree uses the",
        "same shared `NANOCOMPILE_DIR`.",
        "",
        "condensation-site is the intended train repo. This environment cannot",
        "clone that private tree, so train is a 126-file public stand-in with the",
        "same checker × scenario grid. Re-run on the real app with:",
        "",
        "```sh",
        "python3 bench/ts_worktrees.py --repo /path/to/condensation-site --phase all",
        "python3 bench/ts_worktrees.py --repo /path/to/any-ts-app --phase all",
        "```",
        "",
        payload.get("vite_note") or (
            "vite (github.com/vitejs/vite) is a pnpm monorepo: `preinstall` allows "
            "only pnpm, there is no root `tsconfig.json`, and `typecheck` is "
            "`tsc -p scripts && pnpm -r typecheck`. Held-out here is ajv + prettier."
        ),
        "",
        "## Frozen vs baselines (checker × scenario)",
        "",
        "Shipped lever vs `none` / `incremental_local`. **front** = nanocompile is",
        "non-dominated in that cell.",
        "",
        "| split | cell | front | wall nano/none | files nano/none | store | disk nano/none | rss nano/none | correct |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    frozen_lever = (payload.get("hill_climb") or {}).get("frozen_lever") or "l2_seed_buildinfo"
    grid = payload.get("pareto") or {}
    for split_name, rows in (("train", payload.get("train") or []), ("held_out", payload.get("held_out") or [])):
        cells = grid.get(split_name) or {}
        seen = []
        for r in rows:
            key = (r.get("sample"), r.get("checker"), r.get("scenario"))
            if key in seen or not all(key):
                continue
            seen.append(key)
            sample, checker, scenario = key
            nano = next((x for x in rows if x.get("sample")==sample and x.get("checker")==checker and x.get("scenario")==scenario and x.get("approach")=="nanocompile" and x.get("lever") in (frozen_lever, "frozen")), None)
            none = next((x for x in rows if x.get("sample")==sample and x.get("checker")==checker and x.get("scenario")==scenario and x.get("approach")=="none"), None)
            cell = "%s/%s|%s" % (sample, checker, scenario)
            info = cells.get(cell) or cells.get("%s|%s" % (checker, scenario)) or {}
            on = "yes" if info.get("nano_on_frontier") else "NO"
            def pair(attr, digits=0):
                a = (nano or {}).get(attr)
                b = (none or {}).get(attr)
                if a is None and b is None:
                    return ""
                fa = ("%.0f" % a) if isinstance(a, float) and digits==0 else (("%.1f" % a) if isinstance(a, float) else ("" if a is None else str(a)))
                fb = ("%.0f" % b) if isinstance(b, float) and digits==0 else (("%.1f" % b) if isinstance(b, float) else ("" if b is None else str(b)))
                if attr == "files_rechecked":
                    fa = "%.1f" % a if a is not None else ""
                    fb = "%.1f" % b if b is not None else ""
                return "%s / %s" % (fa, fb)
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                split_name, cell, on,
                pair("wall_ms"), pair("files_rechecked"),
                "" if not nano else nano.get("store_bytes"),
                pair("disk_bytes"), pair("rss_kb"),
                "yes" if (nano or {}).get("correctness_ok") else "no",
            ))
    lines += [
        "",
        "## Setup Rach should use",
        "",
        "```sh",
        "zig build -Doptimize=ReleaseFast",
        "./zig-out/bin/nanocompile worktree init   # Rust + TypeScript",
        "git worktree add --detach ../agent-1",
        "./zig-out/bin/nanocompile worktree init --store \"$NANOCOMPILE_DIR\" ../agent-1",
        "ln -s \"$PWD/node_modules\" ../agent-1/node_modules   # shared install",
        "export PATH=\"$PWD/.nanocompile/bin:$PATH\"",
        "tsc --noEmit          # or tsrs / tsgo / bun check",
        "```",
        "",
        "Frozen env:",
        "",
        "```",
        json.dumps(frozen, indent=2),
        "```",
        "",
        "Cache key: checker identity + argv + tsconfig + source hashes, paths as",
        "`$NANO_ROOT`. Only zero-error results are stored.",
        "",
        "## Hill-climb",
        "",
        "| lever | vs | keep | note |",
        "| --- | --- | --- | --- |",
    ]
    for entry in (payload.get("hill_climb") or {}).get("log") or []:
        lines.append("| `%s` | %s | %s | %s |" % (
            entry.get("lever"), entry.get("vs"),
            "yes" if entry.get("keep") else "stall",
            entry.get("note") or "",
        ))
    lines += ["", "## Generalization (held-out vs none)", "",
              "| metric | train gain vs none | held-out gain vs none | fraction that survived |",
              "| --- | --- | --- | --- |"]
    for metric, info in (payload.get("survival") or {}).get("per_metric", {}).items():
        def pct(v):
            return "n/a" if v is None else "%.1f%%" % (v * 100)
        lines.append("| %s | %s | %s | %s |" % (
            metric, pct(info.get("train_gain")), pct(info.get("held_out_gain")), pct(info.get("survived_fraction")),
        ))
    lines += ["", "## Pareto frontier per cell", ""]
    grid = payload.get("pareto") or {}
    for split_name, label in (("train", "Train"), ("held_out", "Held-out")):
        block = grid.get(split_name) or {}
        lines += ["### %s" % label, ""]
        if not block:
            lines += ["(not measured yet)", ""]
            continue
        for cell, info in block.items():
            on = "yes" if info.get("nano_on_frontier") else "NO"
            lines.append("**%s** — nanocompile on frontier: %s" % (cell, on))
            lines.append("")
            lines.append("| approach | lever | wall | files | store | disk | rss kb |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- |")
            for row in info.get("frontier") or []:
                lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                    row.get("approach"), row.get("lever"),
                    "%.0f" % row["wall_ms"] if row.get("wall_ms") is not None else "",
                    "%.1f" % row["files_rechecked"] if row.get("files_rechecked") is not None else "",
                    row.get("store_bytes") if row.get("store_bytes") is not None else "",
                    row.get("disk_bytes") if row.get("disk_bytes") is not None else "",
                    row.get("rss_kb") if row.get("rss_kb") is not None else "",
                ))
            if info.get("nano_dominated_by"):
                for dom in info["nano_dominated_by"]:
                    lines.append("- dominated by `%s` (%s)" % (dom.get("by"), dom.get("lever")))
            lines.append("")
    lines += [
        "",
        "## Rows",
        "",
        "| sample | cell | approach | wall | files | store | disk | rss | correct | ok |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in (payload.get("train") or []) + (payload.get("held_out") or []):
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            row.get("sample"), row.get("cell"), row.get("approach"),
            "%.0f" % row["wall_ms"] if row.get("wall_ms") is not None else "",
            "%.1f" % row["files_rechecked"] if row.get("files_rechecked") is not None else "",
            row.get("store_bytes") or "",
            row.get("disk_bytes") or "",
            row.get("rss_kb") or "",
            "yes" if row.get("correctness_ok") else "no",
            "yes" if row.get("ok") else "no",
        ))
    lines += [
        "",
        "## What climbed",
        "",
        "- **L0** content-addressed result cache (file hashes + `$NANO_ROOT`).",
        "- **L1** store/restore `.tsbuildinfo` with the result.",
        "- **L2** seed key (no source hashes) so an edit starts from sibling buildinfo.",
        "",
        "`bun check` has no incremental file; L1/L2 do not apply.",
        "prettier + tsgo/tsrs/bun: the program is `checkJs` with `module: NodeNext`.",
        "TS 7 rejects a bundler override on NodeNext and stops before typechecking, so",
        "the inject gate cannot be certified. tsc 5.9 on prettier is on the frontier.",
        "Correctness: `tests/typescript_worktrees.py` uses real `git worktree add`.",
        "",
        "Harness: `python3 bench/ts_worktrees.py --repo PATH`.",
        "Archive: `bench/archive/ts-worktrees.json` → `map_elites.json` `typescript_worktrees`.",
        "",
    ]
    return "\n".join(lines)


def default_nano():
    return REPO / "zig-out" / "bin" / "nanocompile"


def register_repo(path: Path, name=None, split="train"):
    path = path.resolve()
    name = name or path.name
    SAMPLE_CATALOG[name] = {"path": path, "size": "mid", "args": ["--noEmit"], "split": split}
    return name


def train_names():
    names = []
    for name, meta in SAMPLE_CATALOG.items():
        if meta.get("split") == "train" and meta["path"].exists():
            names.append(name)
    return names or ["condensation-site"]


def held_names():
    return [n for n, m in SAMPLE_CATALOG.items() if m.get("split") == "held_out" and m["path"].exists()]


def record_elites(payload, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    elites = REPO / "bench" / "map_elites.json"
    data = json.loads(elites.read_text(encoding="utf-8")) if elites.exists() else {}
    data["typescript_worktrees"] = {
        "source": str(dest.relative_to(REPO)) if dest.is_relative_to(REPO) else str(dest),
        "docs": "docs/typescript-worktrees.md",
        "harness": "bench/ts_worktrees.py",
        "commit": aw.git_commit(),
        "grid_axes": {"checker": [c["id"] for c in CHECKERS], "scenario": list(SCENARIOS)},
        "objectives": list(OBJECTIVES),
        "hill_climb": payload.get("hill_climb"),
        "frozen_env": payload.get("frozen_env"),
        "pareto": payload.get("pareto"),
        "survival": payload.get("survival"),
        "train": payload.get("train") or [],
        "held_out": payload.get("held_out") or [],
        "train_note": payload.get("train_note"),
        "node_modules": "symlink-to-main",
    }
    elites.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", choices=("all", "train", "held-out", "record"), default="all")
    p.add_argument("--repo", default="", help="Any TS repo path; becomes the train sample")
    p.add_argument("--samples", default="")
    p.add_argument("--worktrees", type=int, default=N_WORKTREES)
    p.add_argument("--nano", type=Path, default=default_nano())
    p.add_argument("--work", type=Path, default=Path("/tmp/ts-worktrees"))
    p.add_argument("--out", type=Path, default=REPO / "bench" / "archive" / "ts-worktrees.json")
    p.add_argument("--checkers", default="")
    p.add_argument("--held-samples", default="", help="Comma-separated held-out sample names")
    return p.parse_args(argv)


def measure_approach(sample, src, checker, approach, lever, wrapper, work, env, args, split, n):
    setup = measure_setup(sample, src, checker, approach, wrapper, work, env, args, n)
    try:
        return scenario_rows(sample, checker, approach, lever, split, setup, wrapper, args)
    finally:
        prune_worktrees(setup["main"], setup["trees"])


def main(argv=None):
    args = parse_args(argv)
    wrapper = args.nano.resolve()
    if not wrapper.exists():
        raise SystemExit("missing nanocompile binary: %s" % wrapper)
    if args.repo:
        register_repo(Path(args.repo), split="train")
    checkers = available_checkers()
    if args.checkers:
        want = {x.strip() for x in args.checkers.split(",") if x.strip()}
        checkers = [c for c in checkers if c["id"] in want]
    if not checkers:
        raise SystemExit("no TypeScript checkers on PATH")
    samples = [s.strip() for s in args.samples.split(",") if s.strip()] or train_names()
    payload = {}
    if args.out.exists() and args.phase != "train":
        try:
            payload = json.loads(args.out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}

    if args.phase in ("all", "train"):
        rows = []
        climb_log = []
        stalled = {c["id"]: 0 for c in checkers}
        frozen_env = dict(NANO_TS_FRONTIER)
        frozen_lever = "l0_result_cache"
        for checker in checkers:
            for sample in samples:
                meta = SAMPLE_CATALOG[sample]
                src = meta["path"]
                if not src.exists():
                    continue
                baselines = ["none"] + ([] if checker["id"] == "bun" else ["incremental_local"])
                for approach in baselines:
                    print(json.dumps({"measure": sample, "checker": checker["id"], "approach": approach}), flush=True)
                    rows.extend(measure_approach(
                        sample, src, checker, approach, approach, wrapper, args.work, {}, meta["args"], "train", args.worktrees,
                    ))
                last_keep = False
                vs = "none"
                for delta in CLIMB_DELTAS:
                    print(json.dumps({"climb": delta["id"], "checker": checker["id"], "sample": sample}), flush=True)
                    nxt = measure_approach(
                        sample, src, checker, delta["id"], delta["id"], wrapper, args.work, delta["env"], meta["args"], "train", args.worktrees,
                    )
                    rows.extend(nxt)
                    improved = False
                    for scenario in SCENARIOS:
                        cell_rows = [r for r in rows if r.get("sample") == sample and r.get("checker") == checker["id"] and r.get("scenario") == scenario]
                        info = cell_summary(cell_rows)
                        if info["nano_on_frontier"]:
                            improved = True
                    climb_log.append({
                        "lever": delta["id"], "vs": vs, "keep": improved,
                        "checker": checker["id"], "sample": sample,
                        "note": "on frontier in at least one cell" if improved else "no cell improved",
                    })
                    if improved:
                        last_keep = True
                        vs = delta["id"]
                        frozen_env = dict(delta["env"])
                        frozen_env.setdefault("NANOCOMPILE_TSRS_CHECKERS", "4")
                        frozen_lever = delta["id"]
                        stalled[checker["id"]] = 0
                    else:
                        stalled[checker["id"]] += 1
                        if stalled[checker["id"]] >= STALL_ROUNDS:
                            break
        payload["train"] = rows
        payload["hill_climb"] = {"log": climb_log, "frozen_env": frozen_env, "frozen_lever": frozen_lever, "stall_rounds": STALL_ROUNDS}
        payload["frozen_env"] = frozen_env
        payload["pareto"] = {"train": {}}
        for checker in checkers:
            for sample in samples:
                for scenario in SCENARIOS:
                    cell = "%s/%s|%s" % (sample, checker["id"], scenario)
                    subset = [r for r in rows if r.get("sample") == sample and r.get("checker") == checker["id"] and r.get("scenario") == scenario]
                    payload["pareto"]["train"][cell] = cell_summary(subset)
        payload["train_note"] = "condensation-site private; trained on " + ",".join(samples)
        payload["vite_note"] = (
            "vite (github.com/vitejs/vite) is a pnpm-only monorepo with no root tsconfig; "
            "typecheck is workspace-wide. Held-out is ajv + prettier. Re-run with "
            "`python3 bench/ts_worktrees.py --repo /path/to/vite-app`."
        )
        payload["commit"] = aw.git_commit()
        args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if args.phase in ("all", "held-out"):
        frozen_env = (payload.get("hill_climb") or {}).get("frozen_env") or NANO_TS_FRONTIER
        frozen_lever = (payload.get("hill_climb") or {}).get("frozen_lever") or "frozen"
        held_sample_names = [s.strip() for s in args.held_samples.split(",") if s.strip()] or held_names()
        measured = []
        for checker in checkers:
            for sample in held_sample_names:
                meta = SAMPLE_CATALOG[sample]
                src = meta["path"]
                baselines = ["none"] + ([] if checker["id"] == "bun" else ["incremental_local"])
                for approach in baselines:
                    print(json.dumps({"held": sample, "checker": checker["id"], "approach": approach}), flush=True)
                    measured.extend(measure_approach(
                        sample, src, checker, approach, approach, wrapper, args.work / "held", {}, meta["args"], "held_out", args.worktrees,
                    ))
                print(json.dumps({"held": sample, "checker": checker["id"], "approach": "frozen"}), flush=True)
                measured.extend(measure_approach(
                    sample, src, checker, "frozen", frozen_lever, wrapper, args.work / "held", frozen_env, meta["args"], "held_out", args.worktrees,
                ))
        replaced = {(r.get("sample"), r.get("checker")) for r in measured}
        kept = [r for r in (payload.get("held_out") or []) if (r.get("sample"), r.get("checker")) not in replaced]
        held = kept + measured
        payload["held_out"] = held
        payload.setdefault("pareto", {})
        payload["pareto"]["held_out"] = {}
        samples_for_pareto = sorted({r.get("sample") for r in held if r.get("sample")})
        checkers_for_pareto = sorted({r.get("checker") for r in held if r.get("checker")})
        for checker_id in checkers_for_pareto:
            for sample in samples_for_pareto:
                for scenario in SCENARIOS:
                    cell = "%s/%s|%s" % (sample, checker_id, scenario)
                    subset = [r for r in held if r.get("sample") == sample and r.get("checker") == checker_id and r.get("scenario") == scenario]
                    payload["pareto"]["held_out"][cell] = cell_summary(subset)
        payload["survival"] = survival(payload.get("train") or [], held, frozen_lever)
        args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if args.phase in ("all", "record"):
        payload.setdefault("docs", "docs/typescript-worktrees.md")
        payload.setdefault("vite_note", (
            "vite (github.com/vitejs/vite) is a pnpm-only monorepo with no root tsconfig; "
            "typecheck is workspace-wide. Held-out is ajv + prettier."
        ))
        record_elites(payload, args.out)
        (REPO / "docs" / "typescript-worktrees.md").write_text(render_docs(payload), encoding="utf-8")
        print("recorded", args.out, "and docs/typescript-worktrees.md", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
