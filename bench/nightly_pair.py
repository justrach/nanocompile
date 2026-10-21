#!/usr/bin/env python3
"""Nightly LLVM vs nightly cranelift on one Cargo project.

Uses the official harness copy/edit protocol. Times cargo +nightly build
and cargo +nightly test --no-run so the backend is isolated from the
stable toolchain and from test-runner / doctest time.

    python3 bench/nightly_pair.py PROJECT --name SAMPLE
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bench"))
import rust_loop_bench as bench  # noqa: E402


def pair_argv(command, cranelift, jobs, offline):
    extra = ["--no-run"] if command == "test" else None
    flags = ["-Zcodegen-backend"] if cranelift else None
    if extra and flags:
        flags = flags + extra
    elif extra:
        flags = extra
    return bench.cargo_argv(command, jobs, offline, "nightly", flags)


def extra_env(cranelift):
    if not cranelift:
        return {}
    return {
        "CARGO_PROFILE_DEV_CODEGEN_BACKEND": "cranelift",
        "CARGO_PROFILE_TEST_CODEGEN_BACKEND": "cranelift",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    parser.add_argument("--name")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=0)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    sample = args.name or project.name
    output = Path(args.output).resolve() if args.output else (REPO / "bench" / "results" / ("%s-nightly-pair" % sample))
    output.mkdir(parents=True, exist_ok=True)
    work_root = Path(tempfile.mkdtemp(prefix="nano-nightly-pair-"))
    work = work_root / "project"
    bench.copy_project(project, work)
    fetch = bench.run(["cargo", "+nightly", "fetch"], cwd=work)
    offline = args.offline and fetch.returncode == 0
    base_env = {k: v for k, v in os.environ.items() if not k.startswith("NANOCOMPILE_")}
    rows = []
    for command in ("build", "test"):
        for cranelift, label in ((False, "nightly-llvm"), (True, "nightly-cranelift")):
            target = work_root / "targets" / label / command
            env = bench.cargo_env(base_env, target, extra_env(cranelift))
            argv = pair_argv(command, cranelift, args.jobs or None, offline)
            step = type("S", (), {"id": label, "title": label})()
            bench.empty_target(target)
            rows.append(bench.run_cell(step, command, "cold", argv, work, env, target, args.warmup, args.runs))
            rows.append(bench.run_cell(step, command, "noop", argv, work, env, target, args.warmup, args.runs))
            for phase, kind in (("edit_body", "body"), ("edit_sig", "sig")):
                record = bench.edit_project(work, kind)
                if record is None:
                    rows.append({
                        "step": label, "command": command, "phase": phase,
                        "skipped": True, "skip_reason": "no safe edit site",
                        "median_ms": None, "ok": False,
                    })
                    continue
                try:
                    rows.append(bench.run_cell(step, command, phase, argv, work, env, target, args.warmup, args.runs))
                finally:
                    bench.restore_edit(record)
    report = {
        "schema": 1,
        "kind": "nanocompile.rust-loop.nightly-pair",
        "sample": sample,
        "project": str(project),
        "note": "cargo +nightly build and cargo +nightly test --no-run; llvm vs cranelift on the same toolchain",
        "cells": rows,
    }
    (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# nightly LLVM vs cranelift: %s" % sample, "",
             "| Backend | Command | Phase | Median ms | OK |",
             "| --- | --- | --- | ---: | --- |"]
    for cell in rows:
        if cell.get("skipped"):
            lines.append("| %s | %s | %s | skipped | — |" % (cell["step"], cell.get("command"), cell.get("phase")))
            continue
        lines.append("| %s | %s | %s | %.1f | %s |" % (
            cell["step"], cell["command"], cell["phase"],
            cell["median_ms"] or 0, "yes" if cell.get("ok") else "no"))
    (output / "result.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    sys.stdout.write((output / "result.md").read_text(encoding="utf-8"))
    shutil.rmtree(work_root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
