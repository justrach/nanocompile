"""Measure clean Cargo builds, never a Cargo no-op. Outputs and hit counts are recorded."""
import argparse
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from r2_cache import transfer


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("binary")
    p.add_argument("project")
    p.add_argument("--package", default="harness-adapters")
    p.add_argument("--state", required=True, help="dedicated new benchmark directory")
    p.add_argument("--output", required=True)
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--runs", type=int, default=2)
    p.add_argument("--r2-config")
    p.add_argument("--snapshot", default="harness-local")
    args = p.parse_args()
    binary = str(Path(args.binary).resolve())
    project = Path(args.project).resolve()
    state = Path(args.state).resolve()
    state.mkdir(parents=True, exist_ok=False)
    target, cache = state / "target", state / "cache"
    env = dict(os.environ, CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL="0",
               NANOCOMPILE_DIR=str(cache), RUSTC_WRAPPER=binary)
    for k in list(env):
        if k.startswith("R2_") or k in ("NANOCOMPILE_TRACE", "NANOCOMPILE_DISABLE", "RUSTC_WORKSPACE_WRAPPER"):
            del env[k]
    command = ["cargo", "build", "--release", "--locked", "--offline", "--lib",
               "-p", args.package, "-j", str(args.jobs), "--message-format=json-render-diagnostics"]
    result = {"project": str(project), "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip(),
              "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=project)),
              "platform": platform.platform(), "cpu": platform.processor(), "jobs": args.jobs,
              "rustc": subprocess.check_output(["rustc", "--version", "--verbose"], cwd=project, text=True),
              "binary_sha256": sha(Path(binary)), "command": command,
              "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "builds": [],
              "method": "same target path; target directory deleted before every timed build; offline dependencies; release library package and dependency graph"}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        output.write_text(json.dumps(result, indent=2) + "\n")

    # Fetch outside measurements. Builds themselves must be offline.
    with (state / "fetch.log").open("w") as log:
        subprocess.run(["cargo", "fetch", "--locked"], cwd=project, env=env,
                       stdout=log, stderr=log, check=True)
    reference = None

    def build(mode):
        nonlocal reference
        shutil.rmtree(target, ignore_errors=True)
        before = collections.Counter((cache / "events").read_text().splitlines()) if (cache / "events").exists() else collections.Counter()
        build_env = dict(env)
        if mode == "direct":
            build_env.pop("RUSTC_WRAPPER")
        number = len(result["builds"])
        print(f"Starting {mode} clean release build {number + 1}", flush=True)
        start = time.monotonic()
        log_path = state / f"{number}-{mode}.log"
        with log_path.open("w") as log:
            proc = subprocess.run(command, cwd=project, env=build_env, stdout=log, stderr=log)
        seconds = time.monotonic() - start
        after = collections.Counter((cache / "events").read_text().splitlines()) if (cache / "events").exists() else collections.Counter()
        artifacts = {}
        for path in sorted((target / "release/deps").glob("*.rlib")):
            artifacts[str(path.relative_to(target))] = sha(path)
        row = {"mode": mode, "seconds": seconds, "exit_code": proc.returncode,
               "events": dict(after - before), "rlibs": len(artifacts), "artifacts": artifacts}
        if reference is None and proc.returncode == 0:
            reference = artifacts
        elif proc.returncode == 0:
            row["artifact_hashes_equal_first_wrapped"] = artifacts == reference
        result["builds"].append(row)
        save()
        print(json.dumps({k: v for k, v in row.items() if k != "artifacts"}), flush=True)
        if proc.returncode:
            raise SystemExit(f"Build failed; see {log_path}")

    # First populate and retain a reference for byte equality. Proc-macro/native
    # bypasses are visible in events, not silently called hits.
    build("cold")
    if args.r2_config:
        result["r2_push"] = transfer("push", cache, args.snapshot, args.r2_config)
        save()
    for _ in range(args.runs):
        build("warm")
        build("direct")
    if args.r2_config:
        # Preserve fingerprint memos and counters; remove every artifact/entry.
        # Network prefetch is timed independently, then included in total.
        shutil.rmtree(cache / "entries")
        shutil.rmtree(cache / "blobs")
        result["r2_pull"] = transfer("pull", cache, args.snapshot, args.r2_config)
        build("r2_restored")
        result["r2_total_seconds"] = result["r2_pull"]["seconds"] + result["builds"][-1]["seconds"]
        save()


if __name__ == "__main__":
    main()
