#!/usr/bin/env python3
"""Measure rust-loop steps on any Cargo project.

Stable CLI (do not rename flags other agents already use):

    bench/rust_loop_bench PROJECT
        --nanocompile PATH
        --runs N --warmup N --jobs N
        --output DIR --name SAMPLE
        --steps LIST --commands LIST
        --offline --skip-install --self-test
        --genome FILE --map-elites --emit-archive FILE

Schema 1 JSON + markdown go to --output (default bench/results/<sample>/).
See docs/rust-iteration-bench.md.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

SCHEMA = 1
REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / "tools" / "rust_loop.py"
DEFAULT_STEPS = (
    "baseline",
    "nanocompile-wrapper",
    "fast-check",
    "validate-graph",
    "cranelift-dev",
    "fast-linker",
    "sccache",
    "crate-shape",
    "disk-hygiene",
)
DEFAULT_COMMANDS = ("check", "build", "test")
PHASES = ("cold", "noop", "edit_body", "edit_sig")
BODY_MARK = "nano-loop-body"
SIG_MARK = "nano-loop-sig"
BODY_INSERT = "let _nano_loop_body = 1u8;"
FORBIDDEN_VALIDATE = ("cranelift", "codegen-backend", "cg_clif", "rustd", "lust", "relax")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def which(name):
    return shutil.which(name)


def run(argv, cwd=None, env=None, timeout=600):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, timeout=timeout)


def dir_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            file = Path(root) / name
            try:
                total += file.stat().st_size
            except OSError:
                pass
    return total


def median(values):
    if not values:
        return None
    return statistics.median(values)


def spread(values):
    if not values:
        return None
    if len(values) == 1:
        return 0.0
    return statistics.pstdev(values)


def cargo_env(base, target, extra=None):
    env = {k: v for k, v in base.items()
           if k not in ("RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER")
           and not k.startswith("CARGO_PROFILE_")
           and k != "CARGO_ENCODED_RUSTFLAGS"
           and (k == "NANOCOMPILE_DIR" or not k.startswith("NANOCOMPILE_"))}
    env["CARGO_TARGET_DIR"] = str(target)
    env["CARGO_TERM_COLOR"] = "never"
    if extra:
        env.update(extra)
    return env


def detect_rust_loop(nanocompile: Path | None):
    if nanocompile and nanocompile.is_file():
        probe = run([str(nanocompile), "rust-loop", "list"])
        if probe.returncode == 0 and b"fast-check" in probe.stdout:
            return ("zig", [str(nanocompile), "rust-loop"])
    return ("python", [sys.executable, "-I", "-S", "-B", str(HELPER)])


def copy_project(src: Path, dest: Path):
    dest.mkdir(parents=True)
    ignore = shutil.ignore_patterns(
        "target", ".git", ".nanocompile-loop", ".turbo", "node_modules",
        "zig-out", ".zig-cache",
    )
    for item in src.iterdir():
        if item.name in ("target", ".git", ".nanocompile-loop"):
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=ignore, symlinks=False)
        else:
            shutil.copy2(item, target)


def rust_files(root: Path):
    files = []
    for path in sorted(root.rglob("*.rs")):
        if any(part in {"target", ".git", ".nanocompile-loop"} for part in path.parts):
            continue
        files.append(path)
    return files


def find_marked(root: Path, mark: str):
    for path in rust_files(root):
        text = path.read_text(encoding="utf-8")
        if mark in text:
            return path, text
    return None, None


FN_RE = re.compile(
    r"(?P<prefix>^[\t ]*(?:pub(?:\s*\([^)]*\))?\s+)?(?:async\s+)?fn\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P<rest>[^{]*))\{",
    re.M,
)


def first_function(text):
    for match in FN_RE.finditer(text):
        if match.group("name").startswith("_"):
            continue
        return match
    return None


def apply_body_edit(text):
    marked = re.search(r"//\s*" + re.escape(BODY_MARK) + r".*?\n(?P<fn>[\t ]*(?:pub\s+)?fn\s+[^{]+\{)", text, re.S)
    if marked:
        start = marked.end("fn")
        return text[:start] + " " + BODY_INSERT + text[start:], True
    match = first_function(text)
    if not match:
        return text, False
    return text[:match.end()] + " " + BODY_INSERT + text[match.end():], True


def apply_sig_edit(text):
    marked = re.search(
        r"//\s*" + re.escape(SIG_MARK) + r".*?\n(?P<fn>[\t ]*(?:pub\s+)?fn\s+[A-Za-z0-9_]+[^{]*)\(",
        text, re.S,
    )
    if marked:
        insert_at = marked.end()
        return text[:insert_at] + "_nano_loop_sig: (), " + text[insert_at:], True
    match = first_function(text)
    if not match:
        return text, False
    open_paren = text.find("(", match.start())
    if open_paren < 0:
        return text, False
    return text[:open_paren + 1] + "_nano_loop_sig: (), " + text[open_paren + 1:], True


def apply_broken_edit(text):
    edited, ok = apply_body_edit(text)
    if not ok:
        return text + "\nfn _nano_loop_broken() -> u32 { \"nope\" }\n", True
    return edited.replace(BODY_INSERT, 'let _nano_loop_body: u32 = "nope";'), True


def edit_project(root: Path, kind: str):
    mark = BODY_MARK if kind == "body" else SIG_MARK if kind == "sig" else None
    path, text = (find_marked(root, mark) if mark else (None, None))
    if path is None:
        candidates = [p for p in rust_files(root) if p.name in ("lib.rs", "main.rs")] or rust_files(root)
        if not candidates:
            return None
        path = candidates[0]
        text = path.read_text(encoding="utf-8")
    original = text
    if kind == "body":
        text, ok = apply_body_edit(text)
    elif kind == "sig":
        text, ok = apply_sig_edit(text)
    else:
        text, ok = apply_broken_edit(text)
    if not ok or text == original:
        return None
    path.write_text(text, encoding="utf-8")
    return path, original


def restore_edit(record):
    if not record:
        return
    path, original = record
    path.write_text(original, encoding="utf-8")


def rust_loop_cmd(driver, action, extra):
    return driver + [action, *extra]


def measure_once(argv, cwd, env, target):
    start = time.perf_counter()
    result = run(argv, cwd=cwd, env=env)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return {
        "ms": elapsed_ms,
        "returncode": result.returncode,
        "target_bytes": dir_bytes(target),
        "stderr_tail": result.stderr.decode(errors="replace")[-2000:],
        "stdout_tail": result.stdout.decode(errors="replace")[-1000:],
    }


def _clear_nano_cache(env):
    cache = env.get("NANOCOMPILE_DIR")
    if cache and Path(cache).exists():
        shutil.rmtree(cache)


def empty_target(target: Path):
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)


class StepPlan:
    def __init__(self, step_id, title, commands, extra_env=None, rustflags=None, toolchain=None,
                 graph=False, skip=None, linker=None):
        self.id = step_id
        self.title = title
        self.commands = commands
        self.extra_env = extra_env or {}
        self.rustflags = rustflags
        self.toolchain = toolchain
        self.graph = graph
        self.skip = skip
        self.linker = linker


def available_steps(args, tools):
    nano = tools["nanocompile"]
    mold = tools["mold"]
    lld_flag = "-fuse-ld=mold" if mold else "-fuse-ld=lld"
    linker_env = {"RUSTFLAGS": "-C link-arg=%s" % lld_flag} if (mold or tools["rust_lld"]) else None
    steps = [
        StepPlan("baseline", "plain cargo", list(args.commands)),
        StepPlan(
            "nanocompile-wrapper", "RUSTC_WRAPPER=nanocompile, CARGO_INCREMENTAL=0",
            list(args.commands),
            extra_env={"RUSTC_WRAPPER": str(nano), "CARGO_INCREMENTAL": "0"} if nano else {},
            skip=None if nano else "nanocompile binary not found",
        ),
        StepPlan(
            "fast-check", "cargo check only (skip codegen)",
            ["check"],
        ),
        StepPlan(
            "validate-graph", "declared fast-check then cargo test",
            ["graph"],
            graph=True,
            extra_env={"RUSTC_WRAPPER": str(nano), "CARGO_INCREMENTAL": "0"} if nano else {},
        ),
        StepPlan(
            "cranelift-dev", "nightly cranelift codegen backend (dev build)",
            ["build"],
            toolchain="nightly",
            extra_env={"CARGO_PROFILE_DEV_CODEGEN_BACKEND": "cranelift"},
            skip=None if tools["cranelift"] else "nightly rustc-codegen-cranelift-preview not installed",
        ),
        StepPlan(
            "fast-linker", "mold or lld via -C link-arg",
            [c for c in args.commands if c in ("build", "test")],
            extra_env=linker_env or {},
            skip=None if linker_env else "neither mold nor rust-lld is available",
        ),
        StepPlan(
            "sccache", "RUSTC_WRAPPER=sccache",
            list(args.commands),
            extra_env={"RUSTC_WRAPPER": tools["sccache"], "SCCACHE_DIR": str(args.work / "sccache")}
            if tools["sccache"] else {},
            skip=None if tools["sccache"] else "sccache not installed",
        ),
        StepPlan(
            "crate-shape", "explicit -C codegen-units=256",
            [c for c in args.commands if c in ("build", "test", "check")],
            extra_env={"RUSTFLAGS": "-C codegen-units=256"},
        ),
        StepPlan(
            "disk-hygiene", "line-tables-only debuginfo",
            [c for c in args.commands if c in ("build", "test")],
            extra_env={"RUSTFLAGS": "-C debuginfo=line-tables-only"},
        ),
    ]
    wanted = set(args.steps)
    return [step for step in steps if step.id in wanted]


def cargo_argv(command, jobs, offline, toolchain=None, extra_flags=None):
    argv = ["cargo"]
    if toolchain:
        argv = ["cargo", "+" + toolchain]
    argv.append(command)
    if jobs:
        argv.extend(["-j", str(jobs)])
    if offline:
        argv.append("--offline")
    if extra_flags:
        argv.extend(extra_flags)
    if command == "test":
        argv.extend(["--", "--test-threads", "1"])
    return argv


def prepare_graph(work, driver, target, wrapper, offline):
    spec = work / "nanocompile.tasks.json"
    extra = ["--manifest", str(work / "Cargo.toml"), "--write", str(spec),
             "--target-dir", str(target)]
    if offline:
        extra.append("--offline")
    if wrapper:
        extra.extend(["--wrapper", str(wrapper)])
    built = run(rust_loop_cmd(driver, "spec", extra), cwd=work)
    if built.returncode != 0:
        return None, built.stderr.decode(errors="replace")
    checked = run(rust_loop_cmd(driver, "check-spec", [str(spec)]), cwd=work)
    if checked.returncode != 0:
        return None, checked.stderr.decode(errors="replace")
    return spec, None


def graph_argv(nanocompile, spec):
    if nanocompile:
        return [str(nanocompile), "task", str(spec)]
    return None


def summarize(samples):
    times = [row["ms"] for row in samples]
    disks = [row["target_bytes"] for row in samples]
    codes = [row["returncode"] for row in samples]
    return {
        "samples_ms": times,
        "median_ms": median(times),
        "mean_ms": statistics.mean(times) if times else None,
        "stdev_ms": spread(times),
        "min_ms": min(times) if times else None,
        "max_ms": max(times) if times else None,
        "target_bytes": disks[-1] if disks else 0,
        "target_bytes_median": median(disks),
        "returncodes": codes,
        "ok": all(code == 0 for code in codes) if codes else False,
    }


def markdown_table(report):
    lines = [
        "# rust-loop bench: %s" % report["sample"],
        "",
        "Project: `%s`" % report["project"],
        "Runs: %d timed, %d warmup. Schema %d." % (report["runs"], report["warmup"], report["schema"]),
        "",
        "| Step | Command | Phase | Median ms | Spread ms | Target bytes | OK |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for cell in report["cells"]:
        if cell.get("skipped"):
            lines.append("| %s | %s | — | skipped | %s | — | — |" % (
                cell["step"], cell.get("command", ""), cell.get("skip_reason", "")))
            continue
        lines.append("| %s | %s | %s | %.1f | %.1f | %d | %s |" % (
            cell["step"], cell["command"], cell["phase"],
            cell["median_ms"] or 0, cell["stdev_ms"] or 0,
            cell["target_bytes"] or 0, "yes" if cell["ok"] else "no"))
    lines.append("")
    correctness = report.get("correctness") or {}
    lines.append("## Correctness")
    lines.append("")
    lines.append("- broken edit applied: %s" % correctness.get("broken_edit", False))
    lines.append("- fast-check failed: %s" % correctness.get("fast_failed", False))
    lines.append("- validate failed or did not run: %s" % correctness.get("validate_is_final", False))
    lines.append("- fast and rustc agree (both fail): %s" % correctness.get("agree_on_broken", False))
    if correctness.get("notes"):
        lines.append("- notes: %s" % correctness["notes"])
    lines.append("")
    return "\n".join(lines) + "\n"


def tool_probe():
    rust_lld = []
    try:
        sysroot = subprocess.check_output(["rustc", "--print", "sysroot"], text=True).strip()
        rust_lld = [str(p) for p in Path(sysroot).glob("lib/rustlib/*/bin/rust-lld*")]
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    cranelift = False
    nightly = which("rustup") is not None
    if nightly:
        probe = run(["rustup", "component", "list", "--toolchain", "nightly", "--installed"])
        cranelift = probe.returncode == 0 and b"rustc-codegen-cranelift" in probe.stdout
    return {
        "cargo": which("cargo"),
        "rustc": which("rustc"),
        "mold": which("mold"),
        "sccache": which("sccache"),
        "hyperfine": which("hyperfine"),
        "rust_lld": bool(rust_lld),
        "cranelift": cranelift,
        "nightly": nightly,
    }


def maybe_install(skip):
    notes = []
    if skip:
        return notes
    if which("rustup"):
        if run(["rustup", "toolchain", "install", "nightly", "--profile", "minimal"]).returncode == 0:
            notes.append("installed or confirmed nightly")
        add = run(["rustup", "component", "add", "rustc-codegen-cranelift-preview", "--toolchain", "nightly"])
        notes.append("cranelift-preview: %s" % ("ok" if add.returncode == 0 else add.stderr.decode(errors="replace")[-200:]))
    if not which("mold"):
        apt = run(["apt-get", "install", "-y", "mold"])
        if apt.returncode != 0:
            notes.append("mold apt install failed (may need root)")
        else:
            notes.append("installed mold")
    if not which("sccache") and which("cargo"):
        notes.append("sccache not installed; pass --skip-install and install cargo-sccache yourself for that cell")
    if not which("hyperfine"):
        notes.append("hyperfine optional; this harness times itself")
    return notes


def run_correctness(work, driver, nanocompile, offline, jobs, tools_env):
    record = edit_project(work, "broken")
    notes = []
    if record is None:
        return {
            "broken_edit": False,
            "fast_failed": False,
            "validate_is_final": False,
            "agree_on_broken": False,
            "notes": "could not apply a broken edit",
        }
    try:
        target = work / "target-correctness"
        empty_target(target)
        env = cargo_env(tools_env, target)
        check = run(cargo_argv("check", jobs, offline), cwd=work, env=env)
        test = run(cargo_argv("test", jobs, offline), cwd=work, env=env)
        fast_failed = check.returncode != 0
        validate_failed = test.returncode != 0
        spec, spec_err = prepare_graph(work, driver, target, nanocompile, offline)
        graph_fast = None
        graph_validate_ran = None
        if spec and nanocompile:
            graph = run([str(nanocompile), "task", str(spec)], cwd=work, env=cargo_env(tools_env, target))
            graph_fast = graph.returncode != 0
            # If fast-check fails the runner stops; validate must not be the
            # successful final signal.
            graph_validate_ran = (work / ".nanocompile-loop" / "validate.ok").exists()
        elif spec_err:
            notes.append(spec_err[-300:])
        banned = any(token in " ".join(cargo_argv("test", jobs, offline)).lower() for token in FORBIDDEN_VALIDATE)
        agree = fast_failed and validate_failed
        validate_is_final = validate_failed and not banned and graph_validate_ran is not True
        return {
            "broken_edit": True,
            "fast_failed": fast_failed,
            "validate_failed": validate_failed,
            "validate_is_final": validate_is_final,
            "agree_on_broken": agree,
            "graph_fast_failed": graph_fast,
            "graph_validate_stamp_written": graph_validate_ran,
            "notes": "; ".join(notes),
        }
    finally:
        restore_edit(record)


def run_cell(step, command, phase, argv, cwd, env, target, warmup, runs):
    samples = []
    reset = phase in ("cold",)
    # Edits: time the first rebuild only. Extra samples would be no-ops of the
    # already-edited tree. Cold: empty target and the isolated nanocompile cache
    # so a graph hit is not mistaken for a cold miss.
    if phase in ("edit_body", "edit_sig", "body", "sig_dep"):
        warmup = 0
        runs = 1
    for _ in range(warmup):
        if reset:
            empty_target(target)
            _clear_nano_cache(env)
        measure_once(argv, cwd, env, target)
    for _ in range(runs):
        if reset:
            empty_target(target)
            _clear_nano_cache(env)
        samples.append(measure_once(argv, cwd, env, target))
    summary = summarize(samples)
    summary.update({
        "step": step.id,
        "title": step.title,
        "command": command,
        "phase": phase,
        "skipped": False,
        "skip_reason": None,
    })
    return summary


def execute(args):
    project = args.project.resolve()
    if not (project / "Cargo.toml").is_file():
        raise SystemExit("rust-loop-bench: no Cargo.toml in %s" % project)
    sample = args.name or project.name
    output = Path(args.output).resolve() if args.output else (REPO / "bench" / "results" / sample)
    output.mkdir(parents=True, exist_ok=True)
    args.output = output
    install_notes = maybe_install(args.skip_install)
    tools = tool_probe()
    nano = Path(args.nanocompile).resolve() if args.nanocompile else None
    if nano and not nano.is_file():
        nano = None
    tools["nanocompile"] = nano
    driver_kind, driver = detect_rust_loop(nano)
    work_root = Path(tempfile.mkdtemp(prefix="nano-rust-loop-bench-"))
    work = work_root / "project"
    copy_project(project, work)
    base_env = {k: v for k, v in os.environ.items() if not k.startswith("NANOCOMPILE_")}
    base_env["NANOCOMPILE_DIR"] = str(work_root / "nano-cache")
    fetch = run(["cargo", "fetch"], cwd=work, env=base_env)
    offline = args.offline and fetch.returncode == 0
    if fetch.returncode != 0 and args.offline:
        offline = False
    correctness = run_correctness(work, driver, nano, offline, args.jobs, base_env)
    size_info = classify_project(project)
    args.work_root = work_root
    map_elites_meta = None
    if getattr(args, "held_out", None):
        dest, evs, matrix = execute_held_out(args, work, driver, nano, tools, base_env, offline, correctness, size_info["size"])
        map_elites_meta = {"shard": str(dest), "evaluations": len(evs), "size": size_info, "held_out": len(matrix)}
    elif getattr(args, "map_elites", False) or getattr(args, "genome", None):
        dest, evs = execute_map_elites(args, work, driver, nano, tools, base_env, offline, correctness, size_info["size"])
        map_elites_meta = {"shard": str(dest), "evaluations": len(evs), "size": size_info}
    cells = []
    skip_steps = bool(getattr(args, "map_elites", False) or getattr(args, "genome", None) or getattr(args, "held_out", None))
    for step in [] if skip_steps else available_steps(argparse.Namespace(
            commands=args.commands, steps=args.steps, work=work_root), tools):
        if step.skip:
            cells.append({
                "step": step.id, "title": step.title, "command": ",".join(step.commands),
                "phase": None, "skipped": True, "skip_reason": step.skip,
                "median_ms": None, "stdev_ms": None, "target_bytes": None, "ok": False,
            })
            continue
        for command in step.commands:
            target = work_root / "targets" / step.id / command
            extra = dict(step.extra_env)
            env = cargo_env(base_env, target, extra)
            if step.graph:
                spec, err = prepare_graph(work, driver, target, nano, offline)
                if spec is None or nano is None:
                    cells.append({
                        "step": step.id, "title": step.title, "command": "graph",
                        "phase": None, "skipped": True,
                        "skip_reason": err or "nanocompile binary required for task graph",
                        "median_ms": None, "stdev_ms": None, "target_bytes": None, "ok": False,
                    })
                    continue
                argv = [str(nano), "task", str(spec)]
                command_name = "graph"
            else:
                argv = cargo_argv(command, args.jobs, offline, step.toolchain)
                command_name = command
            empty_target(target)
            if (work / ".nanocompile-loop").exists():
                shutil.rmtree(work / ".nanocompile-loop")
            cells.append(run_cell(step, command_name, "cold", argv, work, env, target, args.warmup, args.runs))
            cells.append(run_cell(step, command_name, "noop", argv, work, env, target, args.warmup, args.runs))
            for phase, kind in (("edit_body", "body"), ("edit_sig", "sig")):
                record = edit_project(work, kind)
                if record is None:
                    cells.append({
                        "step": step.id, "title": step.title, "command": command_name,
                        "phase": phase, "skipped": True, "skip_reason": "no safe %s edit site" % kind,
                        "median_ms": None, "stdev_ms": None, "target_bytes": None, "ok": False,
                    })
                    continue
                try:
                    cells.append(run_cell(step, command_name, phase, argv, work, env, target, args.warmup, args.runs))
                finally:
                    restore_edit(record)
                    if step.graph:
                        prepare_graph(work, driver, target, nano, offline)
    report = {
        "schema": SCHEMA,
        "sample": sample,
        "project": str(project),
        "timestamp": now_iso(),
        "runs": args.runs,
        "warmup": args.warmup,
        "offline": offline,
        "platform": os.uname().sysname + " " + os.uname().machine,
        "driver": driver_kind,
        "tools": {k: (str(v) if isinstance(v, Path) else v) for k, v in tools.items()},
        "install_notes": install_notes,
        "correctness": correctness,
        "cells": cells,
        "size": size_info,
        "map_elites": map_elites_meta,
    }
    if getattr(args, "emit_archive", None) or map_elites_meta:
        shard_path = Path(args.emit_archive) if getattr(args, "emit_archive", None) else (
            Path(map_elites_meta["shard"]) if map_elites_meta else (REPO / "bench" / "archive" / ("%s.json" % sample))
        )
        if not map_elites_meta:
            write_shard(shard_path, sample, shard_from_report(report, size_info["size"]), git_commit())
            report["map_elites"] = {"shard": str(shard_path), "evaluations": "from-steps", "size": size_info}
    (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output / "result.md").write_text(markdown_table(report), encoding="utf-8")
    shutil.rmtree(work_root, ignore_errors=True)
    return report


EDIT_FROM_PHASE = {"cold": "cold", "noop": "noop", "edit_body": "body", "edit_sig": "sig_dep"}
STEP_GENOMES = {
    "baseline": {"loop": "check"},
    "nanocompile-wrapper": {"wrapper": True, "incremental": False, "loop": "check"},
    "fast-check": {"fast_check": "cargo-check", "loop": "check"},
    "validate-graph": {"wrapper": True, "incremental": False, "loop": "graph"},
    "cranelift-dev": {"dev_backend": "cranelift", "loop": "check"},
    "fast-linker": {"linker": "mold", "loop": "test"},
    "sccache": {"sccache": True, "loop": "check"},
    "crate-shape": {"codegen_units": 256, "loop": "check"},
    "disk-hygiene": {"debuginfo": "line-tables-only", "loop": "test"},
}


def default_genome(**overrides):
    genome = {
        "wrapper": False,
        "dev_backend": "llvm",
        "linker": "default",
        "sccache": False,
        "codegen_units": None,
        "incremental": True,
        "debuginfo": "full",
        "fast_check": "cargo-check",
        "loop": "check",
        "jobs": None,
        "offline": False,
    }
    genome.update({k: v for k, v in overrides.items() if v is not None or k == "codegen_units"})
    return genome


def classify_project(root: Path):
    sys.path.insert(0, str(REPO / "tools"))
    import map_elites
    return map_elites.classify(root)


def git_commit():
    result = run(["git", "-C", str(REPO), "rev-parse", "HEAD"])
    if result.returncode != 0:
        return None
    return result.stdout.decode().strip()


def genome_env(genome, nano, tools, sccache_dir, isolate_cache):
    extra = {}
    rustflags = []
    if genome.get("wrapper") and nano:
        extra["RUSTC_WRAPPER"] = str(nano)
        extra["CARGO_INCREMENTAL"] = "0"
    elif genome.get("sccache") and tools.get("sccache"):
        extra["RUSTC_WRAPPER"] = tools["sccache"]
        extra["SCCACHE_DIR"] = str(sccache_dir)
    if genome.get("incremental") is False:
        extra["CARGO_INCREMENTAL"] = "0"
    elif genome.get("incremental") and "CARGO_INCREMENTAL" not in extra:
        extra["CARGO_INCREMENTAL"] = "1"
    if genome.get("dev_backend") == "cranelift":
        extra["CARGO_PROFILE_DEV_CODEGEN_BACKEND"] = "cranelift"
    linker = genome.get("linker") or "default"
    if linker == "mold":
        rustflags.append("-C link-arg=-fuse-ld=mold")
    elif linker == "lld":
        rustflags.append("-C link-arg=-fuse-ld=lld")
    if genome.get("codegen_units"):
        rustflags.append("-C codegen-units=%s" % genome["codegen_units"])
    debuginfo = genome.get("debuginfo") or "full"
    if debuginfo == "line-tables-only":
        rustflags.append("-C debuginfo=line-tables-only")
    elif debuginfo == "none":
        rustflags.append("-C debuginfo=0")
    if rustflags:
        extra["RUSTFLAGS"] = " ".join(rustflags)
    if isolate_cache:
        extra["NANOCOMPILE_DIR"] = str(isolate_cache)
    return extra


def genome_argv(genome, command, jobs, offline, nano, spec):
    kind = genome.get("loop") or "check"
    if kind == "graph":
        if not nano or spec is None:
            return None
        return [str(nano), "task", str(spec)]
    if kind == "test":
        command = "test"
    elif kind == "check":
        command = "check"
    return cargo_argv(command, jobs or genome.get("jobs"), offline or genome.get("offline"))


def mutate_genome(genome, tools):
    import copy
    import random
    next_genome = copy.deepcopy(genome)
    genes = ["wrapper", "linker", "incremental", "debuginfo", "codegen_units", "loop", "sccache"]
    if tools.get("cranelift"):
        genes.append("dev_backend")
    for gene in random.sample(genes, k=min(2, len(genes))):
        if gene == "wrapper":
            next_genome["wrapper"] = not next_genome.get("wrapper")
            if next_genome["wrapper"]:
                next_genome["sccache"] = False
                next_genome["incremental"] = False
        elif gene == "sccache":
            next_genome["sccache"] = not next_genome.get("sccache")
            if next_genome["sccache"]:
                next_genome["wrapper"] = False
        elif gene == "incremental":
            next_genome["incremental"] = not next_genome.get("incremental")
        elif gene == "linker":
            order = ["default", "mold", "lld"]
            next_genome["linker"] = order[(order.index(next_genome.get("linker") or "default") + 1) % 3]
        elif gene == "debuginfo":
            order = ["full", "line-tables-only", "none"]
            next_genome["debuginfo"] = order[(order.index(next_genome.get("debuginfo") or "full") + 1) % 3]
        elif gene == "codegen_units":
            order = [None, 16, 256]
            current = next_genome.get("codegen_units")
            next_genome["codegen_units"] = order[(order.index(current) + 1) % 3] if current in order else 256
        elif gene == "loop":
            order = ["check", "graph", "test"]
            nxt = order[(order.index(next_genome.get("loop") or "check") + 1) % 3]
            if nxt == "test":
                next_genome["dev_backend"] = "llvm"
            next_genome["loop"] = nxt
        elif gene == "dev_backend":
            next_genome["dev_backend"] = "llvm" if next_genome.get("dev_backend") == "cranelift" else "cranelift"
            if next_genome.get("loop") == "test":
                next_genome["dev_backend"] = "llvm"
    return next_genome


def seed_genomes(nano, tools):
    seeds = [
        default_genome(),
        default_genome(wrapper=True, incremental=False) if nano else None,
        default_genome(loop="graph", wrapper=True, incremental=False) if nano else None,
        default_genome(linker="mold", loop="test") if tools.get("mold") else default_genome(linker="lld", loop="test"),
        default_genome(sccache=True) if tools.get("sccache") else None,
        default_genome(codegen_units=256),
        default_genome(debuginfo="line-tables-only", loop="test"),
        default_genome(incremental=False),
        default_genome(dev_backend="cranelift", loop="check") if tools.get("cranelift") else None,
        default_genome(wrapper=True, incremental=False, debuginfo="line-tables-only", loop="graph") if nano else None,
    ]
    return [row for row in seeds if row]


def evaluation_row(cell, size, edit, genome, summary, correctness, sample, commit):
    ok = bool(correctness.get("agree_on_broken") and correctness.get("validate_is_final"))
    return {
        "cell": cell,
        "size": size,
        "edit": edit,
        "genome": genome,
        "fitness_ms": summary.get("median_ms"),
        "spread_ms": summary.get("stdev_ms"),
        "disk_bytes": summary.get("target_bytes"),
        "correctness": {
            "ok": ok,
            "agree_on_broken": bool(correctness.get("agree_on_broken")),
            "validate_is_final": bool(correctness.get("validate_is_final")),
        },
        "sample": sample,
        "commit": commit,
        "timestamp": now_iso(),
        "n_evals": len(summary.get("samples_ms") or []),
        "non_improving": 0,
        "stopped": False,
    }


def write_shard(path: Path, sample, evaluations, commit):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": 1,
        "kind": "nanocompile.rust-loop.map-elites.shard",
        "sample": sample,
        "commit": commit,
        "timestamp": now_iso(),
        "evaluations": evaluations,
    }, indent=2) + "\n", encoding="utf-8")


def shard_from_report(report, size):
    commit = git_commit()
    evaluations = []
    for cell in report.get("cells") or []:
        if cell.get("skipped") or not cell.get("ok"):
            continue
        edit = EDIT_FROM_PHASE.get(cell.get("phase"))
        if not edit:
            continue
        step = cell.get("step")
        overrides = dict(STEP_GENOMES.get(step) or {"loop": "check"})
        if step == "fast-linker" and (report.get("tools") or {}).get("mold"):
            overrides["linker"] = "mold"
        elif step == "fast-linker":
            overrides["linker"] = "lld"
        genome = default_genome(**overrides)
        evaluations.append(evaluation_row(
            "%s|%s" % (size, edit), size, edit, genome, cell,
            report.get("correctness") or {}, report.get("sample"), commit,
        ))
    return evaluations


def measure_genome(genome, work, driver, nano, tools, base_env, jobs, offline, warmup, runs, edit, work_root, target):
    isolate = work_root / "nano-cache"
    extra = genome_env(genome, nano, tools, work_root / "sccache", isolate)
    env = cargo_env(base_env, target, extra)
    if genome.get("loop") == "test":
        env.pop("CARGO_PROFILE_DEV_CODEGEN_BACKEND", None)
        env.pop("CARGO_PROFILE_TEST_CODEGEN_BACKEND", None)
    spec = None
    if genome.get("loop") == "graph":
        spec, err = prepare_graph(work, driver, target, nano, offline or genome.get("offline"))
        if spec is None:
            return None, err or "graph spec failed"
    argv = genome_argv(genome, "check", jobs, offline, nano, spec)
    if argv is None:
        return None, "cannot build argv for genome"
    record = None
    if edit == "cold":
        empty_target(target)
        if (work / ".nanocompile-loop").exists():
            shutil.rmtree(work / ".nanocompile-loop")
    elif edit in ("body", "sig_dep"):
        record = edit_project(work, "body" if edit == "body" else "sig")
        if record is None:
            return None, "no safe edit site"
    try:
        summary = run_cell(type("S", (), {"id": "genome", "title": "genome"})(), genome.get("loop"), edit, argv, work, env, target, warmup, runs)
        return summary, None
    finally:
        restore_edit(record)


def execute_map_elites(args, work, driver, nano, tools, base_env, offline, correctness, size):
    commit = git_commit()
    sample = args.name or args.project.name
    evaluations = []
    seeds = seed_genomes(nano, tools)
    if args.genome:
        seeds = [default_genome(**json.loads(Path(args.genome).read_text(encoding="utf-8")))]
    edits = ("cold", "noop", "body", "sig_dep")
    elites = {}
    for genome in seeds:
        genome = default_genome(**genome)
        genome["offline"] = offline
        genome["jobs"] = args.jobs
        target = args.work_root / "targets" / "genome" / ("%s-%s-%s" % (
            genome.get("loop"), genome.get("linker"), genome.get("debuginfo")))
        for edit in edits:
            summary, err = measure_genome(
                genome, work, driver, nano, tools, base_env, args.jobs, offline,
                args.warmup, args.runs, edit, args.work_root, target,
            )
            if summary is None or not summary.get("ok"):
                continue
            row = evaluation_row(
                "%s|%s" % (size, edit), size, edit, genome, summary, correctness, sample, commit,
            )
            evaluations.append(row)
            elite = elites.get(row["cell"])
            if elite is None or row["fitness_ms"] < elite["fitness_ms"] * 0.97:
                elites[row["cell"]] = row
    if not args.genome:
        for key, elite in list(elites.items()):
            tries = 0
            current = elite["genome"]
            while tries < (args.mutations or 4):
                mutant = mutate_genome(current, tools)
                mutant["offline"] = offline
                mutant["jobs"] = args.jobs
                mutant_target = args.work_root / "targets" / "mutant" / elite["edit"]
                if elite["edit"] != "cold":
                    # Warm the mutant target once so body/sig/noop are incremental.
                    measure_genome(
                        mutant, work, driver, nano, tools, base_env, args.jobs, offline,
                        0, 1, "cold", args.work_root, mutant_target,
                    )
                summary, err = measure_genome(
                    mutant, work, driver, nano, tools, base_env, args.jobs, offline,
                    args.warmup, args.runs, elite["edit"], args.work_root, mutant_target,
                )
                if summary is None or not summary.get("ok"):
                    tries += 1
                    continue
                row = evaluation_row(key, size, elite["edit"], mutant, summary, correctness, sample, commit)
                evaluations.append(row)
                if row["fitness_ms"] <= elite["fitness_ms"] * 0.97:
                    elites[key] = row
                    current = mutant
                    elite = row
                    tries = 0
                else:
                    tries += 1
    destination = Path(args.emit_archive) if args.emit_archive else (REPO / "bench" / "archive" / ("%s.json" % sample))
    write_shard(destination, sample, evaluations, commit)
    return destination, evaluations


def execute_held_out(args, work, driver, nano, tools, base_env, offline, correctness, size):
    archive = json.loads(Path(args.held_out).read_text(encoding="utf-8"))
    cells = archive.get("cells") or {}
    if archive.get("kind") == "nanocompile.rust-loop.map-elites.shard":
        cells = {row["cell"]: row for row in archive.get("evaluations") or []}
    sample = args.name or args.project.name
    commit = git_commit()
    matrix = []
    evaluations = []
    for key, elite in cells.items():
        genome = default_genome(**(elite.get("genome") or {}))
        genome["offline"] = offline
        edit = elite.get("edit") or key.split("|", 1)[-1]
        target = args.work_root / "targets" / "held-out" / key.replace("|", "-")
        if edit != "cold":
            measure_genome(genome, work, driver, nano, tools, base_env, args.jobs, offline, 0, 1, "cold", args.work_root, target)
        summary, err = measure_genome(
            genome, work, driver, nano, tools, base_env, args.jobs, offline,
            args.warmup, args.runs, edit, args.work_root, target,
        )
        if summary is None:
            continue
        local_key = "%s|%s" % (size, edit)
        row = evaluation_row(local_key, size, edit, genome, summary, correctness, sample, commit)
        evaluations.append(row)
        local_elite = cells.get(local_key)
        delta = None
        if local_elite and local_elite.get("fitness_ms"):
            delta = (row["fitness_ms"] - local_elite["fitness_ms"]) / local_elite["fitness_ms"] * 100.0
        matrix.append({
            "genome_from": key,
            "trained_on": elite.get("sample"),
            "tested_on": sample,
            "cell": local_key,
            "fitness_ms": row["fitness_ms"],
            "spread_ms": row["spread_ms"],
            "disk_bytes": row["disk_bytes"],
            "correctness_ok": row["correctness"]["ok"],
            "delta_vs_local_elite_pct": delta,
        })
    destination = Path(args.emit_archive) if args.emit_archive else (REPO / "bench" / "archive" / ("%s-held-out.json" % sample))
    shard = {
        "schema_version": 1,
        "kind": "nanocompile.rust-loop.map-elites.shard",
        "sample": sample,
        "commit": commit,
        "timestamp": now_iso(),
        "evaluations": evaluations,
        "generalization": {"samples": [sample], "matrix": matrix},
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(shard, indent=2) + "\n", encoding="utf-8")
    return destination, evaluations, matrix


def parse_list(value, allowed, default):
    if not value:
        return list(default)
    items = [part.strip() for part in value.split(",") if part.strip()]
    unknown = [item for item in items if item not in allowed]
    if unknown:
        raise SystemExit("unknown value(s): %s" % ", ".join(unknown))
    return items


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", help="path to a Cargo project")
    parser.add_argument("--nanocompile", default=str(REPO / "zig-out" / "bin" / "nanocompile"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=0)
    parser.add_argument("--output", help="directory for result.json and result.md")
    parser.add_argument("--name", help="sample name (default: project directory name)")
    parser.add_argument("--steps", help="comma-separated step ids")
    parser.add_argument("--commands", help="comma-separated cargo commands: check,build,test")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--genome", help="evaluate one MAP-Elites genome JSON")
    parser.add_argument("--map-elites", action="store_true", help="seed + mutate elites for this sample")
    parser.add_argument("--emit-archive", help="write a MAP-Elites shard (default bench/archive/<name>.json when --map-elites)")
    parser.add_argument("--mutations", type=int, default=4, help="non-improving tries per cell for --map-elites")
    parser.add_argument("--held-out", help="evaluate elite genomes from a MAP-Elites archive on this sample")
    args = parser.parse_args(argv)
    args.steps = parse_list(args.steps, DEFAULT_STEPS, DEFAULT_STEPS)
    args.commands = parse_list(args.commands, DEFAULT_COMMANDS, DEFAULT_COMMANDS)
    args.jobs = args.jobs or None
    if args.self_test:
        args.project = args.project or (REPO / "examples" / "rust-loop")
        args.runs = 1
        args.warmup = 0
        args.skip_install = True
        args.commands = ["check"]
        args.steps = ["baseline", "fast-check", "validate-graph"]
        args.name = args.name or "self-test"
        args.output = args.output or (REPO / "bench" / "results" / "self-test")
    if not args.project:
        parser.error("PROJECT is required (or pass --self-test)")
    args.project = Path(args.project)
    report = execute(args)
    sys.stdout.write((Path(args.output) / "result.md").read_text(encoding="utf-8")
                     if args.output else markdown_table(report))
    if args.self_test:
        ok = report["correctness"].get("agree_on_broken") and report["correctness"].get("validate_is_final")
        if not ok:
            raise SystemExit("rust-loop-bench: correctness self-test failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
