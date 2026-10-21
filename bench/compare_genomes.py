#!/usr/bin/env python3
"""Run one or more MAP-Elites genomes on a project under official_first_rebuild."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bench"))
import rust_loop_bench as bench  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    parser.add_argument("--genomes", required=True, help="comma-separated genome JSON files")
    parser.add_argument("--name", required=True)
    parser.add_argument("--edits", default="cold,noop,body,sig_dep")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--nanocompile", default=str(REPO / "zig-out/bin/nanocompile"))
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    output = Path(args.output).resolve() if args.output else (REPO / "bench" / "results" / ("%s-compare" % args.name))
    output.mkdir(parents=True, exist_ok=True)
    sys.argv = ["rust_loop_bench", str(project), "--name", args.name, "--skip-install"]
    if args.offline:
        sys.argv.append("--offline")
    # Reuse execute() via a thin genome loop so SCCACHE_DIR is per-target.
    report = {"sample": args.name, "project": str(project), "cells": []}
    nano = Path(args.nanocompile) if Path(args.nanocompile).is_file() else None
    tools = bench.tool_probe()
    tools["nanocompile"] = nano
    driver_kind, driver = bench.detect_rust_loop(nano)
    work_root = Path(bench.tempfile.mkdtemp(prefix="nano-compare-"))
    work = work_root / "project"
    bench.copy_project(project, work)
    base_env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("NANOCOMPILE_")}
    fetch = bench.run(["cargo", "fetch"], cwd=work, env=base_env)
    offline = args.offline and fetch.returncode == 0
    correctness = bench.run_correctness(work, driver, nano, offline, None, base_env)
    size = bench.classify_project(project)["size"]
    edits = [part.strip() for part in args.edits.split(",") if part.strip()]
    rows = []
    for genome_path in [Path(part.strip()) for part in args.genomes.split(",") if part.strip()]:
        genome = bench.default_genome(**json.loads(genome_path.read_text(encoding="utf-8")))
        genome["offline"] = offline
        label = genome_path.stem
        target = work_root / "targets" / label
        for edit in edits:
            summary, err = bench.measure_genome(
                genome, work, driver, nano, tools, base_env, None, offline,
                args.warmup, args.runs, edit, work_root, target,
            )
            row = {
                "genome_file": str(genome_path),
                "label": label,
                "edit": edit,
                "ok": bool(summary and summary.get("ok")),
                "error": err,
                "median_ms": None if summary is None else summary.get("median_ms"),
                "n_evals": 0 if summary is None else len(summary.get("samples_ms") or []),
                "genome": genome,
                "size": size,
            }
            rows.append(row)
            print("%s %s %s %.1f ok=%s n=%s" % (
                label, edit, size, row["median_ms"] or 0, row["ok"], row["n_evals"]), flush=True)
    report["correctness"] = correctness
    report["cells"] = rows
    (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    bench.shutil.rmtree(work_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
