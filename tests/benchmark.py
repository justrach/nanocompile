"""Repeatable cold/warm timings with output validation. Results are workload-specific."""
import argparse
import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("binary")
    parser.add_argument("--runs", type=int, default=9)
    parser.add_argument("--output")
    parser.add_argument("--kache", help="optional kache executable for the Rust fixture")
    args = parser.parse_args()
    binary = str(Path(args.binary).resolve())
    results = {"runs": args.runs, "platform": os.uname().sysname + " " + os.uname().machine,
               "timestamp": datetime.datetime.now(ZoneInfo("Asia/Singapore")).isoformat(),
               "binary_sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
               "binary_version": subprocess.check_output([binary, "--version"], text=True).strip(),
               "method": "rotating process-level measurements; primary output removed; recorded hits and artifact hashes verified"}
    with tempfile.TemporaryDirectory(prefix="nanocompile-bench-") as temp:
        root = Path(temp)
        env = dict(os.environ, NANOCOMPILE_DIR=str(root / "cache"))
        if args.kache:
            (root / "kache.toml").write_text("[cache]\nrecord_sessions=true\n")
            env.update(KACHE_CACHE_DIR=str(root / "kache"), KACHE_CONFIG=str(root / "kache.toml"),
                       KACHE_HOST_CONFIG="", KACHE_SOCKET_PATH=str(root / "absent-daemon.sock"), KACHE_DAEMON_IDLE_TIMEOUT="1")
        (root / "target/release/deps").mkdir(parents=True)
        (root / "cache").mkdir()
        (root / "kache").mkdir()
        (root / "lib.rs").write_text("\n".join(
            f"#[inline(never)] pub fn f{i}(x: u64) -> u64 {{ (x.wrapping_mul({i + 17})).rotate_left({i % 63 + 1}) }}"
            for i in range(1200)))
        (root / "main.zig").write_text("pub fn main() void {}\n")
        checks = []
        for i in [0, 17, 511, 1199]:
            value = (12345 * (i + 17)) & ((1 << 64) - 1)
            rotation = i % 63 + 1
            value = ((value << rotation) | (value >> (64 - rotation))) & ((1 << 64) - 1)
            checks.append(f"assert_eq!(bench::f{i}(12345), {value}u64);")
        (root / "consumer.rs").write_text("fn main() { " + " ".join(checks) + " }\n")
        cases = {
            "rust": ["rustc", "lib.rs", "--crate-name", "bench", "--crate-type", "rlib", "--emit=dep-info,metadata,link", "--out-dir", str(root / "target/release/deps"), "-C", "opt-level=2"],
            "zig": ["zig", "build-exe", "main.zig", "-O", "ReleaseFast", "-femit-bin=hello"],
        }
        for kind, command in cases.items():
            artifact = root / ("target/release/deps/libbench.rlib" if kind == "rust" else "hello")
            def measure(argv):
                artifact.unlink(missing_ok=True)
                start = time.perf_counter_ns()
                p = subprocess.run(argv, cwd=root, env=env, capture_output=True)
                duration = (time.perf_counter_ns() - start) / 1e6
                assert p.returncode == 0, p.stderr.decode(errors="replace")
                return duration, hashlib.sha256(artifact.read_bytes()).hexdigest()
            # Warm native compiler caches before comparing wrapper overhead.
            _, direct_hash = measure(command)
            cold, expected = measure([binary, *command])
            if kind == "rust":
                assert expected == direct_hash
            kache_command = None
            timings = []
            if kind == "rust" and args.kache:
                kache = str(Path(args.kache).resolve())
                kache_command = [kache, shutil.which("rustc"), *command[1:]]
                kache_cold, kache_expected = measure(kache_command)
                validation = subprocess.run(["rustc", "consumer.rs", "--extern", "bench=target/release/deps/libbench.rlib", "-o", "consumer"],
                                            cwd=root, env=env, capture_output=True)
                assert validation.returncode == 0, validation.stderr.decode(errors="replace")
                subprocess.run([str(root / "consumer")], check=True)
            direct = []
            warm = []
            initial_hits = (root / "cache/events").read_text().splitlines().count("hit")
            # Rotate the measurement order to reduce drift/thermal/order bias.
            schedule = ["direct", "nanocompile"] + (["kache"] if kache_command else [])
            for iteration in range(args.runs):
                offset = iteration % len(schedule)
                for name in schedule[offset:] + schedule[:offset]:
                    argv = command if name == "direct" else [binary, *command] if name == "nanocompile" else kache_command
                    duration, got = measure(argv)
                    if name == "kache":
                        assert got == kache_expected
                        timings.append(duration)
                    elif name == "nanocompile":
                        assert got == expected
                        warm.append(duration)
                    else:
                        if kind == "rust":
                            assert got == expected
                        else:
                            subprocess.run([str(artifact)], check=True, capture_output=True)
                        direct.append(duration)
            assert (root / "cache/events").read_text().splitlines().count("hit") - initial_hits == args.runs
            results[kind] = {"compiler": subprocess.check_output([command[0], "version" if kind == "zig" else "--version"], text=True).strip(),
                             "direct_ms": direct, "warm_ms": warm, "cold_ms": cold,
                             "direct_median_ms": statistics.median(direct), "warm_median_ms": statistics.median(warm),
                             "speedup": statistics.median(direct) / statistics.median(warm)}
            if kache_command:
                # Kache remaps embedded paths. Its own restores are compared
                # byte-for-byte, and a linked consumer verifies semantics.
                stats = subprocess.run([kache, "--json", "stats"], cwd=root, env=env, capture_output=True, text=True)
                subprocess.run([kache, "daemon", "stop"], cwd=root, env=env, capture_output=True)
                stats_json = json.loads(stats.stdout)
                assert stats_json["entries"] > 0, "Kache did not populate its cache: invalid comparison"
                events = (root / "kache/events.jsonl").read_text()
                assert sum("local_hit" in line for line in events.splitlines()) >= args.runs, "Kache did not record all cache hits: invalid comparison"
                results["kache"] = {"version": subprocess.check_output([kache, "--version"], text=True).strip(),
                                    "warm_ms": timings, "cold_ms": kache_cold, "warm_median_ms": statistics.median(timings),
                                    "stats": stats.stdout, "stats_stderr": stats.stderr,
                                    "nanocompile_speedup": statistics.median(timings) / statistics.median(warm),
                                    "daemon": "isolated nonexistent socket; local standalone cache"}
    text = json.dumps(results, indent=2)
    print(text)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n")


if __name__ == "__main__":
    main()
