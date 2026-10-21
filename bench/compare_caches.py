#!/usr/bin/env python3
"""Head-to-head: nanocompile vs kache as competing build caches.

Races isolated stores across overlapping cache functions, not just a wrapper
gene. Official method: apply/revert per run, cargo test + LLVM rustc gate,
empty vs warm tagged.

    python3 bench/compare_caches.py --samples rust-loop,hashbrown --loops check
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bench"))
import rust_loop_bench as bench  # noqa: E402

SCENARIOS = (
    "empty_cold",
    "warm_emptied_target",
    "noop",
    "body",
    "sig_dep",
    "worktree",
    "cargo_clean",
)
LOOPS = ("check", "build", "test")
SAMPLE_CATALOG = {
    "rust-loop": {
        "path": REPO / "examples" / "rust-loop",
        "package": None,
        "size_hint": "small",
    },
    "hashbrown": {
        "path": REPO / "examples" / "pinned-hashbrown",
        "package": None,
        "size_hint": "mid",
    },
    "serde_derive": {
        "path": Path("/tmp/real-samples/serde"),
        "package": "serde_derive",
        "size_hint": "mid",
    },
    "axum": {
        "path": Path("/tmp/real-samples/axum"),
        "package": None,
        "size_hint": "mid",
    },
    "nalgebra": {
        "path": Path("/tmp/real-samples/nalgebra"),
        "package": None,
        "size_hint": "large",
    },
    "ripgrep": {
        "path": Path("/tmp/real-samples/ripgrep"),
        "package": None,
        "size_hint": "large",
    },
    "ruff": {
        "path": Path("/tmp/real-samples/ruff"),
        "package": "ruff",
        "size_hint": "large",
    },
    "bhumi": {
        "path": Path("/tmp/real-samples/bhumi"),
        "package": None,
        "size_hint": "mid",
    },
    "emergentDB": {
        "path": Path("/tmp/real-samples/emergentDB"),
        "package": None,
        "size_hint": "mid",
    },
}

FAMILIES = (
    {
        "label": "nanocompile-shipped",
        "cache_tool": "nanocompile",
        "wrapper": True,
        "incremental": False,
        "config": "shipped",
    },
    {
        "label": "nanocompile-best",
        "cache_tool": "nanocompile",
        "wrapper": True,
        "incremental": True,
        "config": "best",
    },
    {
        "label": "kache-shipped",
        "cache_tool": "kache",
        "kache": True,
        "incremental": True,
        "config": "shipped",
    },
    {
        "label": "kache-noinc",
        "cache_tool": "kache",
        "kache": True,
        "incremental": False,
        "config": "noinc",
    },
)


def parse_nano_stats(text: str) -> dict:
    numbers = {}
    for line in (text or "").splitlines():
        match = re.match(r"([a-z0-9 ]+): ([0-9]+)", line.strip())
        if match:
            numbers[match.group(1).strip()] = int(match.group(2))
    hits = numbers.get("hits", 0)
    misses = numbers.get("misses", 0)
    total = hits + misses
    return {
        "hits": hits,
        "misses": misses,
        "bypasses": numbers.get("bypasses", 0),
        "store_bytes": numbers.get("logical bytes", 0),
        "restore_ns_total": numbers.get("restore ns total", 0),
        "restore_ns_samples": numbers.get("restore ns samples", 0),
        "restore_reflink": numbers.get("restore reflink", 0),
        "restore_hardlink": numbers.get("restore hardlink", 0),
        "restore_copy": numbers.get("restore copy", 0),
        "hit_rate": (hits / total) if total else 0.0,
    }


def delta_stats(before: dict, after: dict) -> dict:
    out = {}
    for key in (
        "hits", "misses", "bypasses", "restore_ns_total", "restore_ns_samples",
        "restore_reflink", "restore_hardlink", "restore_copy",
    ):
        out[key] = max(0, int(after.get(key) or 0) - int(before.get(key) or 0))
    total = out["hits"] + out["misses"]
    out["hit_rate"] = (out["hits"] / total) if total else 0.0
    out["store_bytes"] = after.get("store_bytes") or 0
    samples = out["restore_ns_samples"]
    out["restore_ms"] = (out["restore_ns_total"] / samples / 1e6) if samples else None
    return out


def read_nano_stats(nano: Path | None, cache_dir: Path) -> dict:
    if not nano or not nano.is_file():
        return parse_nano_stats("")
    env = os.environ.copy()
    env["NANOCOMPILE_DIR"] = str(cache_dir)
    result = bench.run([str(nano), "stats"], env=env)
    return parse_nano_stats(result.stdout.decode(errors="replace"))


def read_kache_stats(cache_dir: Path) -> dict:
    env = os.environ.copy()
    env["KACHE_CACHE_DIR"] = str(cache_dir)
    env["KACHE_LOCAL_ONLY"] = "1"
    env["KACHE_SCHEDULER"] = "0"
    result = bench.run(["kache", "--json", "stats"], env=env)
    if result.returncode != 0:
        return {
            "hits": 0, "misses": 0, "bypasses": 0, "store_bytes": bench.dir_bytes(cache_dir),
            "restore_ns_total": 0, "restore_ns_samples": 0, "restore_reflink": 0,
            "restore_hardlink": 0, "restore_copy": 0, "hit_rate": 0.0,
        }
    payload = json.loads(result.stdout.decode() or "{}")
    hits = int(payload.get("local_hits") or 0) + int(payload.get("prefetch_hits") or 0)
    misses = int(payload.get("misses") or 0)
    total = hits + misses
    disk = payload.get("disk") or {}
    return {
        "hits": hits,
        "misses": misses,
        "bypasses": 0,
        "store_bytes": int(disk.get("store_bytes") or payload.get("stores", [{}])[0].get("bytes") or 0),
        "restore_ns_total": int(payload.get("hit_elapsed_ms") or 0) * 1_000_000,
        "restore_ns_samples": hits,
        "restore_reflink": 0,
        "restore_hardlink": 0,
        "restore_copy": 0,
        "hit_rate": (hits / total) if total else float(payload.get("hit_rate_pct") or 0) / 100.0,
    }


def snapshot(family: dict, nano: Path | None, cache_dir: Path) -> dict:
    if family.get("cache_tool") == "kache":
        return read_kache_stats(cache_dir)
    return read_nano_stats(nano, cache_dir)


def family_genome(family: dict, loop: str, package: str | None) -> dict:
    genome = bench.default_genome(
        wrapper=bool(family.get("wrapper")),
        kache=bool(family.get("kache")),
        incremental=bool(family.get("incremental")),
        loop=loop,
        offline=True,
    )
    if package:
        genome["package"] = package
    if loop in ("build", "test"):
        genome["linker"] = "default"
        genome["rustflags_extra"] = "-C link-arg=-fuse-ld=bfd"
    return genome


def family_env(family, genome, nano, tools, cache_dir, target):
    extra = bench.genome_env(
        genome, nano, tools,
        cache_dir if family.get("cache_tool") != "kache" else cache_dir.with_name(cache_dir.name + ".sccache"),
        cache_dir if family.get("cache_tool") == "nanocompile" else None,
        cache_dir if family.get("cache_tool") == "kache" else None,
    )
    rustflags = extra.get("RUSTFLAGS", "")
    extra_flags = genome.get("rustflags_extra")
    if extra_flags:
        extra["RUSTFLAGS"] = (rustflags + " " + extra_flags).strip()
    return bench.cargo_env(os.environ, target, extra)


def cargo_clean(cwd, env, target):
    bench.run(["cargo", "clean", "--target-dir", str(target)], cwd=cwd, env=env)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)


def run_scenario(scenario, argv, cwd, env, target, work_root, warmup, runs, keep_cache):
    samples = []
    sibling = None

    def prepare():
        nonlocal sibling
        if scenario == "empty_cold":
            bench.empty_target(target)
            bench._clear_nano_cache(env)
        elif scenario == "warm_emptied_target":
            if not keep_cache:
                bench._clear_nano_cache(env)
            populate = Path(str(target) + ".populate")
            bench.empty_target(populate)
            env_pop = dict(env)
            env_pop["CARGO_TARGET_DIR"] = str(populate)
            bench.measure_once(argv, cwd, env_pop, populate)
            bench.empty_target(target)
        elif scenario == "noop":
            bench.empty_target(target)
            bench.measure_once(argv, cwd, env, target)
        elif scenario in ("body", "sig_dep"):
            bench.empty_target(target)
            bench.measure_once(argv, cwd, env, target)
        elif scenario == "worktree":
            sibling = work_root / "worktree-b"
            if sibling.exists():
                shutil.rmtree(sibling)
            bench.copy_project(cwd, sibling)
            sib_target = work_root / "targets" / "worktree" / target.name
            bench.empty_target(target)
            bench.measure_once(argv, cwd, env, target)
            bench.empty_target(sib_target)
            return sibling, sib_target
        elif scenario == "cargo_clean":
            bench.empty_target(target)
            bench.measure_once(argv, cwd, env, target)
            cargo_clean(cwd, env, target)
        return cwd, target

    for _ in range(warmup + runs):
        tree, dest = prepare()
        record = None
        try:
            if scenario in ("body", "sig_dep"):
                record = bench.edit_project(tree, "body" if scenario == "body" else "sig")
                if record is None:
                    return {"skipped": True, "skip_reason": "no safe %s edit site" % scenario}
            sample = bench.measure_once(argv, tree, dict(env, CARGO_TARGET_DIR=str(dest)), dest)
            samples.append(sample)
        finally:
            if record:
                bench.restore_edit(record)
                bench.measure_once(argv, tree, dict(env, CARGO_TARGET_DIR=str(dest)), dest)

    timed = samples[warmup:]
    summary = bench.summarize(timed)
    summary["scenario"] = scenario
    summary["target_bytes"] = timed[-1]["target_bytes"] if timed else None
    return summary


def evaluation_row(sample, size, scenario, loop, family, summary, stats, correctness, commit):
    edit = {
        "empty_cold": "cold",
        "warm_emptied_target": "cold",
        "noop": "noop",
        "body": "body",
        "sig_dep": "sig_dep",
        "worktree": "worktree",
        "cargo_clean": "cold",
    }[scenario]
    genome = bench.default_genome(
        wrapper=bool(family.get("wrapper")),
        kache=bool(family.get("kache")),
        incremental=bool(family.get("incremental")),
        warm_store=scenario not in ("empty_cold",),
        loop=loop,
    )
    return {
        "cell": "%s|%s" % (size, edit),
        "size": size,
        "edit": edit,
        "scenario": scenario,
        "loop": loop,
        "sample": "%s-cache-%s" % (sample, family["label"]),
        "sample_class": "fixture" if sample == "rust-loop" else "real",
        "held_out": True,
        "cache_tool": family["cache_tool"],
        "cache_config": family["config"],
        "cache_state": "empty" if scenario == "empty_cold" else "warm_compiler_cache",
        "fitness_ms": summary.get("median_ms"),
        "spread_ms": summary.get("spread_ms"),
        "disk_bytes": (stats.get("store_bytes") or 0) + (summary.get("target_bytes") or 0),
        "store_bytes": stats.get("store_bytes"),
        "target_bytes": summary.get("target_bytes"),
        "hit_rate": stats.get("hit_rate"),
        "hits": stats.get("hits"),
        "misses": stats.get("misses"),
        "restore_ms": stats.get("restore_ms"),
        "restore_reflink": stats.get("restore_reflink"),
        "restore_hardlink": stats.get("restore_hardlink"),
        "restore_copy": stats.get("restore_copy"),
        "ok": bool(summary.get("ok")),
        "genome": genome,
        "correctness": correctness,
        "fitness_method": "official_first_rebuild",
        "commit": commit,
        "timestamp": bench.now_iso(),
    }


def markdown_report(report):
    lines = [
        "# nanocompile vs kache",
        "",
        "Isolated stores. Apply/revert per run. Gate is cargo test + LLVM rustc.",
        "",
        "| Sample | Loop | Scenario | Family | Config | Inc | Cache | Median ms | Hit rate | Store B | Target B | Restore ms | OK |",
        "| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report.get("cells") or []:
        if row.get("skipped"):
            lines.append("| %s | %s | %s | %s | — | — | — | skipped | %s | — | — | — | — |" % (
                row.get("sample_name") or row.get("sample"), row.get("loop"), row.get("scenario"),
                row.get("label"), row.get("skip_reason") or ""))
            continue
        lines.append(
            "| %s | %s | %s | %s | %s | %s | %s | %.1f | %.2f | %s | %s | %s | %s |" % (
                row.get("sample_name"), row.get("loop"), row.get("scenario"),
                row.get("label"), row.get("cache_config"),
                "on" if row.get("incremental") else "off",
                row.get("cache_state"),
                row.get("fitness_ms") or 0,
                row.get("hit_rate") or 0,
                row.get("store_bytes") or 0,
                row.get("target_bytes") or 0,
                ("%.2f" % row["restore_ms"]) if row.get("restore_ms") is not None else "—",
                "yes" if row.get("ok") else "no",
            )
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def write_shard(path: Path, evaluations, commit):
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            existing = list(payload.get("evaluations") or [])
        except json.JSONDecodeError:
            existing = []
    seen = {(
        row.get("sample"), row.get("scenario"), row.get("loop"),
        row.get("cache_tool"), row.get("cache_config"),
    ) for row in existing}
    for row in evaluations:
        key = (
            row.get("sample"), row.get("scenario"), row.get("loop"),
            row.get("cache_tool"), row.get("cache_config"),
        )
        if key in seen:
            existing = [item for item in existing if (
                item.get("sample"), item.get("scenario"), item.get("loop"),
                item.get("cache_tool"), item.get("cache_config"),
            ) != key]
        existing.append(row)
        seen.add(key)
    path.write_text(json.dumps({
        "schema_version": 1,
        "kind": "nanocompile.rust-loop.map-elites.shard",
        "sample": "cache-bakeoff",
        "commit": commit,
        "evaluations": existing,
    }, indent=2) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", default="rust-loop,hashbrown,serde_derive")
    parser.add_argument("--loops", default="check")
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--nanocompile", default=str(REPO / "zig-out/bin/nanocompile"))
    parser.add_argument("--output", default=str(REPO / "bench" / "results" / "cache-bakeoff"))
    parser.add_argument("--emit-archive", default=str(REPO / "bench" / "archive" / "cache-bakeoff.json"))
    args = parser.parse_args(argv)
    bench.RUN_TIMEOUT = args.timeout or 3600
    nano = Path(args.nanocompile).resolve() if args.nanocompile else None
    if nano and not nano.is_file():
        nano = None
    tools = bench.tool_probe()
    tools["nanocompile"] = nano
    driver_kind, driver = bench.detect_rust_loop(nano)
    commit = bench.git_commit()
    samples = [name.strip() for name in args.samples.split(",") if name.strip()]
    loops = [name.strip() for name in args.loops.split(",") if name.strip()]
    scenarios = [name.strip() for name in args.scenarios.split(",") if name.strip()]
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    cells = []
    evaluations = []
    for name in samples:
        spec = SAMPLE_CATALOG.get(name)
        if spec is None or not (spec["path"] / "Cargo.toml").is_file():
            cells.append({"sample_name": name, "skipped": True, "skip_reason": "sample missing"})
            continue
        work_root = Path(tempfile.mkdtemp(prefix="nano-cache-race-%s-" % name))
        work = work_root / "project"
        bench.copy_project(spec["path"], work)
        base_env = {k: v for k, v in os.environ.items() if not k.startswith("NANOCOMPILE_")}
        fetch = bench.run(["cargo", "fetch"], cwd=work, env=base_env)
        offline = fetch.returncode == 0
        correctness = bench.run_correctness(
            work, driver, nano, offline, args.jobs or None, base_env, package=spec["package"],
        )
        size_info = bench.classify_project(spec["path"])
        size = size_info["size"]
        for family in FAMILIES:
            if family.get("cache_tool") == "kache" and not tools.get("kache"):
                cells.append({
                    "sample_name": name, "label": family["label"], "skipped": True,
                    "skip_reason": "kache not installed",
                })
                continue
            if family.get("cache_tool") == "nanocompile" and not nano:
                cells.append({
                    "sample_name": name, "label": family["label"], "skipped": True,
                    "skip_reason": "nanocompile binary missing",
                })
                continue
            for loop in loops:
                genome = family_genome(family, loop, spec["package"])
                genome["offline"] = offline
                argv = bench.genome_argv(genome, loop, args.jobs or None, offline, nano, None)
                cache_dir = work_root / "stores" / family["label"] / loop
                cache_dir.mkdir(parents=True, exist_ok=True)
                target = work_root / "targets" / family["label"] / loop
                env = family_env(family, genome, nano, tools, cache_dir, target)
                for scenario in scenarios:
                    before = snapshot(family, nano, cache_dir)
                    keep = scenario != "empty_cold"
                    try:
                        summary = run_scenario(
                            scenario, argv, work, env, target, work_root,
                            args.warmup, args.runs, keep,
                        )
                    except Exception as exc:  # noqa: BLE001
                        cells.append({
                            "sample_name": name, "label": family["label"], "loop": loop,
                            "scenario": scenario, "skipped": True, "skip_reason": str(exc),
                        })
                        continue
                    after = snapshot(family, nano, cache_dir)
                    stats = delta_stats(before, after)
                    if summary.get("skipped"):
                        summary.update({
                            "sample_name": name, "label": family["label"], "loop": loop,
                        })
                        cells.append(summary)
                        continue
                    row = evaluation_row(
                        name, size, scenario, loop, family, summary, stats, correctness, commit,
                    )
                    row["sample_name"] = name
                    row["label"] = family["label"]
                    row["incremental"] = bool(family.get("incremental"))
                    cells.append(row)
                    evaluations.append(row)
                    write_shard(Path(args.emit_archive), evaluations, commit)
        shutil.rmtree(work_root, ignore_errors=True)
    report = {
        "schema": 1,
        "kind": "nanocompile.vs.kache",
        "timestamp": bench.now_iso(),
        "commit": commit,
        "samples": samples,
        "loops": loops,
        "scenarios": scenarios,
        "runs": args.runs,
        "warmup": args.warmup,
        "driver": driver_kind,
        "cells": cells,
        "evaluations": evaluations,
    }
    (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output / "result.md").write_text(markdown_report(report), encoding="utf-8")
    write_shard(Path(args.emit_archive), evaluations, commit)
    return report


if __name__ == "__main__":
    main()
