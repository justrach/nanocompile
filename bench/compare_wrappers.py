#!/usr/bin/env python3
"""Head-to-head: incremental vs sccache vs kache vs nanocompile wrapper.

Measures every edit type (cold, noop, body, sig_dep, worktree) with an
honestly empty compiler store and a warm store. Incremental on/off is a
separate axis. Correctness stays cargo test + LLVM rustc.

    python3 bench/compare_wrappers.py PROJECT --name SAMPLE --offline
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bench"))
import rust_loop_bench as bench  # noqa: E402


FAMILIES = (
    {"label": "incremental", "incremental": True},
    {"label": "noinc", "incremental": False},
    {"label": "sccache-inc", "sccache": True, "incremental": True},
    {"label": "sccache-noinc", "sccache": True, "incremental": False},
    {"label": "sccache-warm-inc", "sccache": True, "incremental": True, "warm_store": True},
    {"label": "sccache-warm-noinc", "sccache": True, "incremental": False, "warm_store": True},
    {"label": "kache-inc", "kache": True, "incremental": True},
    {"label": "kache-noinc", "kache": True, "incremental": False},
    {"label": "kache-warm-inc", "kache": True, "incremental": True, "warm_store": True},
    {"label": "kache-warm-noinc", "kache": True, "incremental": False, "warm_store": True},
    {"label": "wrapper-noinc", "wrapper": True, "incremental": False},
)


def family_ok(row, tools, nano):
    if row.get("sccache") and not tools.get("sccache"):
        return False, "sccache not installed"
    if row.get("kache") and not tools.get("kache"):
        return False, "kache not installed"
    if row.get("wrapper") and not nano:
        return False, "nanocompile binary not found"
    return True, None


def markdown_table(report):
    lines = [
        "# wrapper compare: %s" % report["sample"],
        "",
        "Project: `%s`" % report["project"],
        "Edits: %s. Runs %d, warmup %d." % (
            ", ".join(report["edits"]), report["runs"], report["warmup"]),
        "Correctness gate is cargo test + LLVM rustc. Clippy/nextest are not the gate.",
        "",
        "| Family | Edit | Cache | Inc | Median ms | Spread ms | OK |",
        "| --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for row in report.get("cells") or []:
        if row.get("skipped"):
            lines.append("| %s | %s | — | — | skipped | %s | — |" % (
                row["label"], row.get("edit") or "—", row.get("skip_reason") or ""))
            continue
        lines.append("| %s | %s | %s | %s | %.1f | %.1f | %s |" % (
            row["label"], row["edit"], row.get("cache_state") or "—",
            "on" if row.get("incremental") else "off",
            row.get("median_ms") or 0, row.get("spread_ms") or 0,
            "yes" if row.get("ok") else "no"))
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    parser.add_argument("--name", required=True)
    parser.add_argument("--edits", default="cold,noop,body,sig_dep,worktree")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=0)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--package")
    parser.add_argument("--nanocompile", default=str(REPO / "zig-out/bin/nanocompile"))
    parser.add_argument("--output")
    parser.add_argument("--emit-archive")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    output = Path(args.output).resolve() if args.output else (
        REPO / "bench" / "results" / ("%s-wrappers" % args.name)
    )
    output.mkdir(parents=True, exist_ok=True)
    bench.RUN_TIMEOUT = args.timeout or 3600
    nano = Path(args.nanocompile).resolve() if args.nanocompile else None
    if nano and not nano.is_file():
        nano = None
    tools = bench.tool_probe()
    tools["nanocompile"] = nano
    driver_kind, driver = bench.detect_rust_loop(nano)
    work_root = Path(bench.tempfile.mkdtemp(prefix="nano-wrappers-"))
    work = work_root / "project"
    bench.copy_project(project, work)
    base_env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("NANOCOMPILE_")}
    fetch = bench.run(["cargo", "fetch"], cwd=work, env=base_env)
    offline = args.offline and fetch.returncode == 0
    correctness = bench.run_correctness(
        work, driver, nano, offline, args.jobs or None, base_env, package=args.package,
    )
    size_info = bench.classify_project(project)
    size = size_info["size"]
    edits = [part.strip() for part in args.edits.split(",") if part.strip()]
    commit = bench.git_commit()
    evaluations = []
    cells = []
    for family in FAMILIES:
        ok, reason = family_ok(family, tools, nano)
        genome = bench.default_genome(**{k: v for k, v in family.items() if k != "label"})
        genome["offline"] = offline
        genome["jobs"] = args.jobs or None
        if args.package:
            genome["package"] = args.package
        if not ok:
            cells.append({
                "label": family["label"], "edit": None, "skipped": True,
                "skip_reason": reason, "ok": False, "genome": genome,
            })
            continue
        target = work_root / "targets" / family["label"]
        for edit in edits:
            summary, err = bench.measure_genome(
                genome, work, driver, nano, tools, base_env, args.jobs or None, offline,
                args.warmup, args.runs, edit, work_root, target,
            )
            row = {
                "label": family["label"],
                "edit": edit,
                "ok": bool(summary and summary.get("ok")),
                "error": err,
                "median_ms": None if summary is None else summary.get("median_ms"),
                "spread_ms": None if summary is None else summary.get("stdev_ms"),
                "n_evals": 0 if summary is None else len(summary.get("samples_ms") or []),
                "genome": genome,
                "size": size,
                "incremental": bool(genome.get("incremental")),
                "cache_state": (
                    "warm_compiler_cache" if edit in ("cold", "worktree", "body", "sig_dep") and genome.get("warm_store")
                    else "empty" if edit in ("cold", "worktree") else None
                ),
                "skipped": False,
            }
            cells.append(row)
            print("%s %s %s %.1f ok=%s cache=%s" % (
                family["label"], edit, size, row["median_ms"] or 0,
                row["ok"], row["cache_state"]), flush=True)
            if summary and summary.get("ok"):
                ev = bench.evaluation_row(
                    "%s|%s" % (size, edit), size, edit, genome, summary,
                    correctness, "%s-wrappers" % args.name, commit,
                )
                evaluations.append(ev)
    report = {
        "schema": bench.SCHEMA,
        "sample": args.name,
        "project": str(project),
        "timestamp": bench.now_iso(),
        "runs": args.runs,
        "warmup": args.warmup,
        "edits": edits,
        "size": size_info,
        "tools": {k: (str(v) if isinstance(v, Path) else v) for k, v in tools.items()},
        "correctness": correctness,
        "cells": cells,
    }
    (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output / "result.md").write_text(markdown_table(report), encoding="utf-8")
    dest = Path(args.emit_archive) if args.emit_archive else (
        REPO / "bench" / "archive" / ("%s-wrappers.json" % args.name)
    )
    bench.write_shard(dest, "%s-wrappers" % args.name, evaluations, commit)
    bench.shutil.rmtree(work_root, ignore_errors=True)
    sys.stdout.write(markdown_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
