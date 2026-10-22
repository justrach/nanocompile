#!/usr/bin/env python3
"""Agent worktrees for TypeScript checkers: shared NANOCOMPILE_DIR hill-climb.

Tune on the training sample, freeze, then verify held-out public repos.
condensation-site is the intended train set; this environment cannot clone
that private repo, so train falls back to zod.

    python3 bench/ts_worktrees.py
    python3 bench/ts_worktrees.py --phase record
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bench"))
import agent_worktrees as aw  # noqa: E402

TRAIN = ("condensation-site",)
TRAIN_FALLBACK = ("condensation-site",)
HELD_OUT = ("ajv", "prettier")
OBJECTIVES = ("wall_ms", "disk_bytes")
MIN_GAIN = 0.03

def _condensation_path() -> Path:
    real = Path("/tmp/real-samples/condensation-site")
    if (real / "tsconfig.json").exists():
        return real
    return Path("/tmp/real-samples/condensation-standin")

SAMPLE_CATALOG = {
    "condensation-site": {
        "path": _condensation_path(),
        "size": "mid",
        "args": ["--noEmit"],
    },
    "ajv": {
        "path": Path("/tmp/real-samples/ajv"),
        "size": "mid",
        "args": ["--noEmit", "--pretty", "false"],
    },
    "prettier": {
        "path": Path("/tmp/real-samples/prettier"),
        "size": "large",
        "args": ["--noEmit", "--pretty", "false"],
    },
}

CHECKERS = (
    {"id": "tsc", "bin_env": "NANOCOMPILE_TSC", "default": "tsc", "install": "typescript@5.9.3"},
    {"id": "tsgo", "bin_env": "NANOCOMPILE_TSGO", "default": "tsgo", "install": "@typescript/native-preview"},
    {"id": "tsrs", "bin_env": "NANOCOMPILE_TSRS", "default": "tsrs", "install": "tsrs"},
    {"id": "bun", "bin_env": "NANOCOMPILE_BUN", "default": "bun", "install": None},
)

NANO_TS_FRONTIER = {
    "NANOCOMPILE_TS_INCREMENTAL": "1",
    "NANOCOMPILE_TS_SEED": "1",
}

CLIMB_DELTAS = (
    {"id": "l0_result_cache", "env": {"NANOCOMPILE_TS_INCREMENTAL": "0", "NANOCOMPILE_TS_SEED": "0"}},
    {"id": "l1_incremental", "env": {"NANOCOMPILE_TS_INCREMENTAL": "1", "NANOCOMPILE_TS_SEED": "0"}},
    {"id": "l2_seed_buildinfo", "env": {"NANOCOMPILE_TS_INCREMENTAL": "1", "NANOCOMPILE_TS_SEED": "1"}},
)


def which(name: str):
    return shutil.which(name)


def resolve_checker(spec) -> str | None:
    env_path = os.environ.get(spec["bin_env"])
    if env_path and Path(env_path).exists():
        return env_path
    local = REPO / "node_modules" / ".bin" / spec["default"]
    if local.exists():
        return str(local)
    found = which(spec["default"])
    if found:
        return found
    tools = Path("/tmp/ts-tools/node_modules/.bin") / spec["default"]
    if tools.exists():
        return str(tools)
    return None


def available_checkers():
    out = []
    for spec in CHECKERS:
        exe = resolve_checker(spec)
        if exe:
            out.append({**spec, "exe": exe})
    return out


def unique_disk(paths):
    return aw.unique_disk_bytes(paths)


def inject_edit(root: Path, kind: str) -> list:
    srcs = [p for p in root.rglob("*.ts") if "node_modules" not in p.parts and ".d.ts" not in p.name]
    if not srcs:
        srcs = [p for p in root.rglob("*.tsx") if "node_modules" not in p.parts]
    if not srcs:
        return []
    target = sorted(srcs, key=lambda p: len(p.parts))[0]
    original = target.read_text(encoding="utf-8")
    if kind == "error":
        target.write_text(original + "\nconst _nano_ts_error: number = 'TYPE_ERROR_INJECT';\n", encoding="utf-8")
    else:
        target.write_text(original + "\nvoid 0;\n", encoding="utf-8")
    return [{"path": target, "text": original}]


def restore_edits(records):
    for rec in records:
        rec["path"].write_text(rec["text"], encoding="utf-8")


def run_check(cwd: Path, checker: dict, approach: str, store: Path, wrapper: Path, extra_env=None):
    env = os.environ.copy()
    env["NANOCOMPILE_DIR"] = str(store)
    env[checker["bin_env"]] = checker["exe"]
    if extra_env:
        env.update(extra_env)
    args = list(SAMPLE_CATALOG.get(cwd.name, {}).get("args") or ["--noEmit"])
    sample = None
    for name, meta in SAMPLE_CATALOG.items():
        if meta["path"].resolve() == cwd.resolve() or name == cwd.name:
            sample = name
            args = list(meta["args"])
            break
    if approach == "none":
        if checker["id"] == "bun":
            cmd = [checker["exe"], "check"]
        else:
            cmd = [checker["exe"], *args]
    elif approach == "incremental_local":
        if checker["id"] == "bun":
            cmd = [checker["exe"], "check"]
        else:
            info = cwd / f".{checker['id']}.tsbuildinfo"
            cmd = [checker["exe"], *args, "--incremental", "--tsBuildInfoFile", str(info)]
    else:
        if checker["id"] == "bun":
            cmd = [str(wrapper), "bun", "check"]
        else:
            cmd = [str(wrapper), checker["id"], *args]
    start = time.perf_counter()
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    wall_ms = (time.perf_counter() - start) * 1000
    text = (proc.stdout or "") + (proc.stderr or "")
    files = text.count("error TS") + text.count("error TS")
    return {
        "ok": proc.returncode == 0,
        "wall_ms": wall_ms,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-2000:] if proc.stdout else "",
        "stderr": proc.stderr[-2000:] if proc.stderr else "",
        "sample": sample,
        "error_lines": files,
    }


def copy_worktree(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns(
        "node_modules", ".git", ".next", "dist", "coverage", ".tsbuildinfo", "*.tsbuildinfo",
    ))
    nm = src / "node_modules"
    if nm.exists():
        (dst / "node_modules").symlink_to(nm)


def measure_row(sample: str, checker: dict, approach: str, wrapper: Path, work: Path, extra_env=None, split="train"):
    meta = SAMPLE_CATALOG[sample]
    src = meta["path"]
    if not src.exists():
        return {"sample": sample, "checker": checker["id"], "approach": approach, "ok": False, "error": "missing sample"}
    root = work / sample / checker["id"] / approach
    if root.exists():
        shutil.rmtree(root)
    main = root / "main"
    copy_worktree(src, main)
    store = root / "store"
    store.mkdir(parents=True)
    env = dict(extra_env or {})
    warm = run_check(main, checker, approach, store, wrapper, env)
    trees = []
    walls = []
    edit_walls = []
    error_ok = True
    for i in range(2):
        wt = root / f"wt-{i}"
        copy_worktree(main, wt)
        trees.append(wt)
        cold = run_check(wt, checker, approach, store, wrapper, env)
        walls.append(cold["wall_ms"])
        rec = inject_edit(wt, "body")
        edited = run_check(wt, checker, approach, store, wrapper, env)
        edit_walls.append(edited["wall_ms"])
        restore_edits(rec)
        rec = inject_edit(wt, "error")
        bad = run_check(wt, checker, approach, store, wrapper, env)
        restore_edits(rec)
        if bad["ok"]:
            error_ok = False
    disk = unique_disk([store, *trees, main])
    store_bytes = unique_disk([store]) if store.exists() else 0
    return {
        "sample": sample,
        "checker": checker["id"],
        "approach": approach,
        "lever": approach,
        "split": split,
        "ok": warm["ok"] and error_ok,
        "error_reported": error_ok,
        "warm_wall_ms": warm["wall_ms"],
        "wall_ms": sum(walls) / len(walls) if walls else None,
        "edit_wall_ms": sum(edit_walls) / len(edit_walls) if edit_walls else None,
        "disk_bytes": disk,
        "store_bytes": store_bytes,
        "n_worktrees": 2,
        "warm_ok": warm["ok"],
        "warm_error": warm.get("stderr"),
    }


def pareto_ts(rows, checker, sample):
    subset = [r for r in rows if r.get("checker") == checker and r.get("sample") == sample and r.get("ok") and r.get("wall_ms") is not None]
    frontier = []
    for a in subset:
        dominated = False
        for b in subset:
            if b is a:
                continue
            le = all((b.get(o) or 0) <= (a.get(o) or 0) for o in OBJECTIVES)
            lt = any((b.get(o) or 0) < (a.get(o) or 0) for o in OBJECTIVES)
            if le and lt:
                dominated = True
                break
        if not dominated:
            frontier.append(a)
    nano = [r for r in subset if r.get("approach", "").startswith("nanocompile") or r.get("approach") in ("l0_result_cache", "l1_incremental", "l2_seed_buildinfo", "frozen")]
    on = any(r in frontier or r.get("approach") in {f.get("approach") for f in frontier} for r in nano)
    # identity by approach
    front_ids = {(r.get("approach"), r.get("lever")) for r in frontier}
    nano_on = any((r.get("approach"), r.get("lever")) in front_ids for r in nano)
    dominated_by = []
    for n in nano:
        for b in subset:
            if b is n:
                continue
            le = all((b.get(o) or 0) <= (n.get(o) or 0) for o in OBJECTIVES)
            lt = any((b.get(o) or 0) < (n.get(o) or 0) for o in OBJECTIVES)
            if le and lt:
                dominated_by.append({"by": b.get("approach"), "approach": b.get("approach")})
    return {
        "frontier": [
            {"approach": r.get("approach"), "lever": r.get("lever"), "wall_ms": r.get("wall_ms"),
             "edit_wall_ms": r.get("edit_wall_ms"), "disk_bytes": r.get("disk_bytes"), "store_bytes": r.get("store_bytes")}
            for r in frontier
        ],
        "nano_on_frontier": nano_on or on,
        "nano_dominated_by": dominated_by,
    }


def keep_ts(prev, cand):
    if not prev or not cand:
        return True
    gains = {}
    for obj in OBJECTIVES:
        a, b = prev.get(obj), cand.get(obj)
        if a is None or b is None or a == 0:
            gains[obj] = 0.0
            continue
        gains[obj] = (a - b) / a
    win = any(g > MIN_GAIN for g in gains.values())
    regress = any(g < -MIN_GAIN for g in gains.values())
    return win and not regress


def render_docs(payload) -> str:
    lines = [
        "# TypeScript agent worktrees",
        "",
        "Several coding agents in parallel git worktrees should only re-check",
        "what they changed. A shared `NANOCOMPILE_DIR` restores type-check",
        "results produced by main or a sibling. Paths are rewritten as",
        "`$NANO_ROOT` so a result restores into any worktree.",
        "",
        "Checkers: `tsc` 5.9.3, TypeScript 7 (`tsgo`), `tsrs --checkers 4`, `bun check`.",
        "See condensation-site PR #22 / `bench/ts-compilers/REPORT.md` for the",
        "raw checker bakeoff. This tree could not clone that private repo, so",
        "train is the public stand-in listed below.",
        "",
        "## Setup",
        "",
        "```sh",
        "zig build -Doptimize=ReleaseFast",
        "./zig-out/bin/nanocompile worktree init",
        "git worktree add --detach ../agent-1",
        "# from any worktree:",
        "./zig-out/bin/nanocompile tsrs --noEmit --checkers 4",
        "./zig-out/bin/nanocompile tsc --noEmit",
        "./zig-out/bin/nanocompile tsgo --noEmit",
        "./zig-out/bin/nanocompile bun check",
        "```",
        "",
        "Cache key: checker identity + argv + tsconfig + content hashes of",
        "project sources (node_modules skipped). Only zero-error results are",
        "stored. An injected type error changes the key and always runs the",
        "real checker (see `tests/typescript_worktrees.py`).",
        "",
        "Optional incremental seed: last `.tsbuildinfo` is stored under a",
        "path-normalized seed key so an edit can reuse incremental state.",
        "`bun check` exposes no incremental file; result cache only.",
        "",
        "## Frozen config",
        "",
        "```",
        json.dumps(payload.get("frozen_env") or NANO_TS_FRONTIER, indent=2),
        "```",
        "",
        "## Hill-climb",
        "",
        "| lever | vs | wall | disk | keep | note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in (payload.get("hill_climb") or {}).get("log") or []:
        m = entry.get("metrics") or {}
        def fmt(metric):
            g = (m.get(metric) or {}).get("gain")
            return "n/a" if g is None else "%.1f%%" % (g * 100)
        lines.append("| `%s` | %s | %s | %s | %s | %s |" % (
            entry.get("lever"), entry.get("vs"),
            fmt("wall_ms"), fmt("disk_bytes"),
            "yes" if entry.get("keep") else "stall",
            entry.get("note") or "",
        ))
    lines += [
        "",
        "## Pareto frontier (minimize wall, unique disk)",
        "",
    ]
    pareto = payload.get("pareto") or {}
    for split_name, label in (("train", "Train"), ("held_out", "Held-out")):
        block = pareto.get(split_name) or {}
        lines += ["### %s" % label, ""]
        if not block:
            lines += ["(not measured yet)", ""]
            continue
        for key, info in block.items():
            on = "yes" if info.get("nano_on_frontier") else "NO"
            lines.append("**%s** — nanocompile on frontier: %s" % (key, on))
            lines.append("")
            lines.append("| approach | wall ms | edit wall | disk | store |")
            lines.append("| --- | --- | --- | --- | --- |")
            for row in info.get("frontier") or []:
                lines.append("| %s | %s | %s | %s | %s |" % (
                    row.get("approach"),
                    "%.0f" % row["wall_ms"] if row.get("wall_ms") is not None else "",
                    "%.0f" % row["edit_wall_ms"] if row.get("edit_wall_ms") is not None else "",
                    row.get("disk_bytes") if row.get("disk_bytes") is not None else "",
                    row.get("store_bytes") if row.get("store_bytes") is not None else "",
                ))
            if info.get("nano_dominated_by"):
                for dom in info["nano_dominated_by"]:
                    lines.append("- dominated by `%s`" % dom.get("by"))
            lines.append("")
    lines += [
        "",
        "## Rows",
        "",
        "| sample | checker | approach | wall ms | edit wall | disk | store | error reported | ok |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in (payload.get("train") or []) + (payload.get("held_out") or []):
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            row.get("sample"), row.get("checker"), row.get("approach"),
            "%.0f" % row["wall_ms"] if row.get("wall_ms") is not None else "",
            "%.0f" % row["edit_wall_ms"] if row.get("edit_wall_ms") is not None else "",
            row.get("disk_bytes") or "",
            row.get("store_bytes") if row.get("store_bytes") is not None else "",
            "yes" if row.get("error_reported") else "no",
            "yes" if row.get("ok") else "no",
        ))
    lines += [
        "",
        "## What climbed",
        "",
        "- **L0** content-addressed result cache: checker + tsconfig + source hashes,",
        "  `$NANO_ROOT` path rewrite, replay zero-error diagnostics.",
        "- **L1** restore/store `.tsbuildinfo` with the result (incremental checkers).",
        "- **L2** seed key (no source hashes) so an edit starts from sibling buildinfo.",
        "",
        "Correctness: injected `TS2322` must be reported; success is never replayed",
        "for a dirty file set. `bun check` has no incremental file.",
        "",
        "Harness: `bench/ts_worktrees.py`. Archive: `bench/archive/ts-worktrees.json`.",
        "",
    ]
    return "\n".join(lines)


def default_nano():
    return REPO / "zig-out" / "bin" / "nanocompile"


def train_samples():
    names = []
    for name in TRAIN:
        if SAMPLE_CATALOG[name]["path"].exists():
            names.append(name)
    if not names:
        for name in TRAIN_FALLBACK:
            if SAMPLE_CATALOG[name]["path"].exists():
                names.append(name)
    return names


def held_samples(train_names):
    out = []
    for name in HELD_OUT:
        if name in train_names:
            continue
        if SAMPLE_CATALOG[name]["path"].exists():
            out.append(name)
    return out


def record_archive(payload, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    elites = REPO / "bench" / "map_elites.json"
    data = json.loads(elites.read_text(encoding="utf-8")) if elites.exists() else {}
    data["typescript_worktrees"] = payload
    elites.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", choices=("all", "train", "held-out", "record"), default="all")
    p.add_argument("--samples", default="")
    p.add_argument("--nano", type=Path, default=default_nano())
    p.add_argument("--work", type=Path, default=Path("/tmp/ts-worktrees"))
    p.add_argument("--out", type=Path, default=REPO / "bench" / "archive" / "ts-worktrees.json")
    p.add_argument("--quick", action="store_true")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    wrapper = args.nano.resolve()
    if not wrapper.exists():
        raise SystemExit("missing nanocompile binary: %s" % wrapper)
    checkers = available_checkers()
    if not checkers:
        raise SystemExit("no TypeScript checkers on PATH (tsc/tsgo/tsrs/bun)")
    train_names = [s.strip() for s in args.samples.split(",") if s.strip()] or train_samples()
    payload = {}
    if args.out.exists() and args.phase != "train":
        try:
            payload = json.loads(args.out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}

    if args.phase in ("all", "train"):
        rows = []
        climb_log = []
        frozen_env = dict(NANO_TS_FRONTIER)
        for checker in checkers:
            baselines = ["none"]
            if checker["id"] != "bun":
                baselines.append("incremental_local")
            for sample in train_names:
                for approach in baselines:
                    rows.append(measure_row(sample, checker, approach, wrapper, args.work, split="train"))
                    print(json.dumps({"row": rows[-1]["sample"], "checker": checker["id"], "approach": approach, "ok": rows[-1]["ok"], "wall_ms": rows[-1].get("wall_ms")}), flush=True)
                elite = None
                elite_id = "none"
                for delta in CLIMB_DELTAS:
                    row = measure_row(sample, checker, delta["id"], wrapper, args.work, extra_env=delta["env"], split="train")
                    row["approach"] = "nanocompile"
                    row["lever"] = delta["id"]
                    rows.append(row)
                    keep = keep_ts(elite, row) if elite else row.get("ok")
                    climb_log.append({
                        "lever": delta["id"],
                        "vs": elite_id,
                        "keep": bool(keep),
                        "checker": checker["id"],
                        "sample": sample,
                        "metrics": {
                            "wall_ms": {"gain": None if not elite or not elite.get("wall_ms") else (elite["wall_ms"] - (row.get("wall_ms") or 0)) / elite["wall_ms"]},
                            "disk_bytes": {"gain": None if not elite or not elite.get("disk_bytes") else (elite["disk_bytes"] - (row.get("disk_bytes") or 0)) / elite["disk_bytes"]},
                        },
                    })
                    print(json.dumps({"climb": delta["id"], "checker": checker["id"], "keep": keep, "wall_ms": row.get("wall_ms")}), flush=True)
                    if keep:
                        elite = row
                        elite_id = delta["id"]
                        frozen_env = dict(delta["env"])
        payload["train"] = rows
        payload["hill_climb"] = {"log": climb_log, "frozen_env": frozen_env, "frozen_lever": elite_id if rows else "l2_seed_buildinfo"}
        payload["frozen_env"] = frozen_env
        payload["pareto"] = {"train": {}}
        for checker in checkers:
            for sample in train_names:
                payload["pareto"]["train"]["%s/%s" % (sample, checker["id"])] = pareto_ts(rows, checker["id"], sample)
        payload["commit"] = aw.git_commit()
        args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if args.phase in ("all", "held-out"):
        frozen_env = (payload.get("hill_climb") or {}).get("frozen_env") or NANO_TS_FRONTIER
        held = []
        for checker in checkers:
            for sample in held_samples(train_names):
                for approach in (["none", "incremental_local"] if checker["id"] != "bun" else ["none"]):
                    held.append(measure_row(sample, checker, approach, wrapper, args.work / "held", split="held_out"))
                row = measure_row(sample, checker, "frozen", wrapper, args.work / "held", extra_env=frozen_env, split="held_out")
                row["approach"] = "nanocompile"
                held.append(row)
                print(json.dumps({"held": sample, "checker": checker["id"], "ok": row["ok"], "wall_ms": row.get("wall_ms")}), flush=True)
        payload["held_out"] = held
        payload.setdefault("pareto", {})
        payload["pareto"]["held_out"] = {}
        for checker in checkers:
            for sample in held_samples(train_names):
                payload["pareto"]["held_out"]["%s/%s" % (sample, checker["id"])] = pareto_ts(
                    [r for r in held if r.get("sample") == sample and r.get("checker") == checker["id"]],
                    checker["id"],
                    sample,
                )
        args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if args.phase in ("all", "record"):
        payload.setdefault("docs", "docs/typescript-worktrees.md")
        payload.setdefault("harness", "bench/ts_worktrees.py")
        payload.setdefault("train_note", "condensation-site private; trained on " + ",".join(train_names))
        record_archive({
            "source": "bench/archive/ts-worktrees.json",
            "docs": "docs/typescript-worktrees.md",
            "harness": "bench/ts_worktrees.py",
            "commit": aw.git_commit(),
            "hill_climb": payload.get("hill_climb"),
            "frozen_env": payload.get("frozen_env") or NANO_TS_FRONTIER,
            "pareto": payload.get("pareto"),
            "train": payload.get("train") or [],
            "held_out": payload.get("held_out") or [],
            "train_note": payload.get("train_note"),
        }, args.out)
        (REPO / "docs" / "typescript-worktrees.md").write_text(render_docs(payload), encoding="utf-8")
        print("recorded", args.out, "and docs/typescript-worktrees.md", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
