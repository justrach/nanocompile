"""Compare direct Cargo, nanocompile and kache on clean real-project builds."""
import argparse
import collections
import datetime
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import subprocess
import time

from project_benchmark import sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("binary")
    p.add_argument("project")
    p.add_argument("--kache", required=True)
    p.add_argument("--package", default="harness-adapters")
    p.add_argument("--state", required=True, help="new, dedicated benchmark directory")
    p.add_argument("--output", required=True)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--standalone", action="store_true", help="disable kache's daemon for this comparison")
    args = p.parse_args()
    if args.runs < 1 or args.jobs < 1:
        p.error("runs and jobs must be positive")
    binary, kache = str(Path(args.binary).resolve()), str(Path(args.kache).resolve())
    project, state = Path(args.project).resolve(), Path(args.state).resolve()
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    config = state / "kache.toml"
    config.write_text("[cache]\nrecord_sessions=true\n")
    target, cache, kcache = state / "target", state / "nano-cache", state / "kache-cache"
    # One environment for every build except RUSTC_WRAPPER. Remote credentials,
    # other wrapper overrides and user kache configuration are excluded.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("R2_", "KACHE_", "NANOCOMPILE_"))
           and k not in ("RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER")}
    env.update(CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL="0", NANOCOMPILE_DIR=str(cache),
               KACHE_CACHE_DIR=str(kcache), KACHE_CONFIG=str(config), KACHE_HOST_CONFIG="",
               KACHE_SOCKET_PATH=str(state / "daemon.sock"), KACHE_DAEMON_IDLE_TIMEOUT="600")
    command = ["cargo", "build", "--release", "--locked", "--offline", "--lib",
               "-p", args.package, "-j", str(args.jobs), "--message-format=json-render-diagnostics"]
    result = {"project": str(project), "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip(),
              "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=project)),
              "platform": platform.platform(), "jobs": args.jobs, "runs": args.runs,
              "rustc": subprocess.check_output(["rustc", "--version", "--verbose"], cwd=project, text=True),
              "nanocompile_sha256": sha(Path(binary)), "kache_sha256": sha(Path(kache)),
              "kache_version": subprocess.check_output([kache, "--version"], text=True).strip(),
              "kache_daemon": not args.standalone, "command": command,
              "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "builds": [],
              "method": "offline clean release package builds; same target path; prime direct build then empty caches; rotate three-way warm measurement order; validate each wrapper against its own cold artifact hashes (kache remaps paths)"}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        output.write_text(json.dumps(result, indent=2) + "\n")

    def nano_events():
        return collections.Counter((cache / "events").read_text().splitlines()) if (cache / "events").exists() else collections.Counter()

    def kache_events():
        path = kcache / "events.jsonl"
        counts = collections.Counter()
        if path.exists():
            for line in path.read_text().splitlines():
                event = json.loads(line)
                counts[event.get("result", "unknown")] += 1
        return counts

    references = {}

    def build(implementation, phase):
        shutil.rmtree(target, ignore_errors=True)
        before = nano_events() if implementation == "nanocompile" else kache_events() if implementation == "kache" else collections.Counter()
        build_env = dict(env)
        if implementation != "direct":
            build_env["RUSTC_WRAPPER"] = binary if implementation == "nanocompile" else kache
        number = len(result["builds"])
        print(f"Starting {implementation} {phase} clean release build {number + 1}", flush=True)
        log_path = state / f"{number}-{implementation}-{phase}.log"
        start = time.monotonic()
        with log_path.open("w") as log:
            proc = subprocess.run(command, cwd=project, env=build_env, stdout=log, stderr=log)
        seconds = time.monotonic() - start
        after = nano_events() if implementation == "nanocompile" else kache_events() if implementation == "kache" else collections.Counter()
        artifacts = {str(path.relative_to(target)): sha(path) for path in sorted((target / "release/deps").glob("*.rlib"))}
        row = {"implementation": implementation, "phase": phase, "seconds": seconds,
               "exit_code": proc.returncode, "events": dict(after - before), "rlibs": len(artifacts), "artifacts": artifacts}
        if implementation not in references:
            references[implementation] = artifacts
        else:
            row["matches_own_cold_artifacts"] = references[implementation] == artifacts
        if implementation == "nanocompile":
            row["matches_direct_artifacts"] = artifacts == references.get("direct")
        result["builds"].append(row)
        save()
        print(json.dumps({k: v for k, v in row.items() if k != "artifacts"}), flush=True)
        if proc.returncode or not artifacts:
            raise RuntimeError(f"Build failed or produced no libraries; see {log_path}")
        if row.get("matches_own_cold_artifacts") is False or row.get("matches_direct_artifacts") is False:
            raise RuntimeError(f"Artifact validation failed; see {log_path}")
        if phase == "warm" and implementation == "kache" and not row["events"].get("local_hit", 0):
            raise RuntimeError("kache recorded no local hits; comparison is invalid")

    daemon = None
    daemon_log = None
    try:
        with (state / "fetch.log").open("w") as log:
            subprocess.run(["cargo", "fetch", "--locked"], cwd=project, env=env, stdout=log, stderr=log, check=True)
        if not args.standalone:
            daemon_log = (state / "daemon.log").open("w")
            daemon = subprocess.Popen([kache, "daemon", "run"], cwd=project, env=env, stdout=daemon_log, stderr=daemon_log)
            deadline = time.monotonic() + 15
            while not (state / "daemon.sock").exists():
                if daemon.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Isolated kache daemon failed to start; see daemon.log")
                time.sleep(0.1)
            # Confirm the private daemon is reachable before any measurements.
            status = subprocess.run([kache, "--json", "daemon", "status"], cwd=project, env=env, capture_output=True, text=True, check=True)
            result["daemon_status"] = status.stdout
        build("direct", "prime")
        build("nanocompile", "cold")
        build("kache", "cold")
        schedule = ["direct", "nanocompile", "kache"]
        for iteration in range(args.runs):
            offset = iteration % len(schedule)
            for implementation in schedule[offset:] + schedule[:offset]:
                build(implementation, "warm")
        for implementation in schedule:
            samples = [r["seconds"] for r in result["builds"] if r["implementation"] == implementation and r["phase"] == "warm"]
            result.setdefault("summary", {})[implementation] = {"samples_seconds": samples, "median_seconds": statistics.median(samples)}
        stats = subprocess.run([kache, "--json", "stats"], cwd=project, env=env, capture_output=True, text=True, check=True)
        result["kache_stats"] = json.loads(stats.stdout)
        save()
        print(json.dumps(result["summary"], indent=2), flush=True)
    finally:
        if daemon is not None:
            if daemon.poll() is None:
                daemon.send_signal(signal.SIGINT)
                try:
                    daemon.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    daemon.kill()
                    daemon.wait()
        elif args.standalone:
            # stats may opportunistically start a daemon even in standalone mode.
            subprocess.run([kache, "daemon", "stop"], cwd=project, env=env, capture_output=True)
        if daemon_log is not None:
            daemon_log.close()


if __name__ == "__main__":
    main()
