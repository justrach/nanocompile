#!/usr/bin/env python3
"""Real compiler and failure checks for the private cache-hit service."""
import argparse
import concurrent.futures
import hashlib
import json
import mmap
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from restore_worker_pool import Pool


def artifacts(out):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("worker", type=Path)
    parser.add_argument("front", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expect-pruning", action="store_true")
    args = parser.parse_args()
    args.worker, args.front, args.baseline = (p.resolve() for p in [args.worker, args.front, args.baseline])
    checks = []
    with tempfile.TemporaryDirectory(prefix="nanocompile-worker-check-") as temp:
        root = Path(temp)
        pool = Pool(args.worker, args.baseline, root / "service")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("NANOCOMPILE_", "R2_", "KACHE_"))}
        env.update(NANOCOMPILE_WORKER_DIR=str(pool.root), NANOCOMPILE_FALLBACK=str(args.baseline),
                   NANOCOMPILE_DIR=str(root / "cache"), RUSTUP_TOOLCHAIN="1.97.1", TEST_VALUE="one")
        src = root / "lib.rs"
        src.write_text('pub const VALUE: &str = env!("TEST_VALUE");\npub fn unused() { let dead = 1; }\n')
        zig_src = root / "main.zig"
        zig_src.write_text("pub fn main() void {}\n")
        out = root / "out"
        out.mkdir()
        other = root / "other"
        other.mkdir()
        rust = ["rustc", str(src), "--crate-name", "fixture", "--crate-type", "rlib",
                "--emit=dep-info,metadata,link", "--out-dir", str(out)]

        def events():
            p = root / "cache/events"
            return p.read_text().splitlines() if p.exists() else []

        def run(command=rust, *, binary=args.front, e=env, cwd=root):
            result = subprocess.run([str(binary), *command], cwd=cwd, env=e, capture_output=True, timeout=60)
            assert result.returncode == 0, result.stderr.decode(errors="replace")
            return result

        def remove():
            for p in out.iterdir():
                p.unlink()

        try:
            prime = run()
            expected = artifacts(out)
            assert events()[-1] == "miss"
            remove()
            served_before = pool.counts()["served"]
            warm = run()
            assert events()[-1] == "hit" and artifacts(out) == expected
            assert pool.counts()["served"] > served_before, "warm hit must be served by the worker"
            assert (warm.stdout, warm.stderr) == (prime.stdout, prime.stderr) and warm.stderr
            remove()
            baseline = run(binary=args.baseline)
            assert (baseline.stdout, baseline.stderr) == (warm.stdout, warm.stderr)
            assert artifacts(out) == expected
            checks.append("miss falls back; worker hit preserves every artifact and diagnostic byte")

            trace_env = dict(env, NANOCOMPILE_TRACE="1")
            remove(); run(e=trace_env)
            remove(); trace_front = run(e=trace_env)
            remove(); trace_base = run(binary=args.baseline, e=trace_env)
            assert (trace_front.stdout, trace_front.stderr) == (trace_base.stdout, trace_base.stderr)
            assert b"nanocompile: hit\n" in trace_front.stderr
            checks.append("trace-enabled worker hit preserves exact diagnostics and trace bytes")

            if args.expect_pruning:
                before_probe = pool.counts()
                probe = run(["rustc", "-vV"])
                assert b"rustc 1.97.1" in probe.stdout and pool.counts() == before_probe
                checks.append("obvious rustc version probe skips worker IPC")

            src.write_text(src.read_text().replace("let dead = 1", "let dead = 2"))
            remove(); run()
            assert events()[-1] == "miss"
            checks.append("source mutation causes normal compiler miss")

            changed_env = dict(env, TEST_VALUE="two")
            remove(); run(e=changed_env)
            assert events()[-1] == "miss"
            changed = artifacts(out)
            assert changed != expected
            remove(); run(e=env)
            assert events()[-1] == "hit"
            checks.append("per-request environment changes invalidate and previous environment restores correctly")

            remove(); run(cwd=other)
            assert events()[-1] == "miss"
            remove(); run(cwd=root)
            assert events()[-1] == "hit"
            checks.append("per-request cwd isolation and original cwd reuse")

            # Blob corruption must not be hidden by any cross-request memo.
            blobs = list((root / "cache/blobs").glob("*/*"))
            output_bytes = (out / "libfixture.rlib").read_bytes()
            blob = next(p for p in blobs if p.read_bytes() == output_bytes)
            content = blob.read_bytes()
            blob.write_bytes(bytes([content[0] ^ 1]) + content[1:])
            remove(); run()
            assert events()[-1] == "miss"
            remove(); run()
            assert events()[-1] == "hit"
            checks.append("artifact blob corruption recompiled and repaired")

            # Reproduce the preceding watcher failure against a live source;
            # full reads in this worker must see the second unflushed change.
            code1 = b"pub const N: u32 = 1;\n"
            code2 = b"pub const N: u32 = 2;\n"
            mapped = root / "mapped.rs"
            mapped.write_bytes(code1)
            command = list(rust)
            command[1] = str(mapped)
            with mapped.open("r+b") as file:
                with mmap.mmap(file.fileno(), 0) as mapping:
                    mapping[:] = code1
                    remove(); run(command)
                    remove(); run(command)
                    assert events()[-1] == "hit"
                    mapping[:] = code2
                    remove(); run(command)
                    assert events()[-1] == "miss"
            checks.append("already-dirty live mmap source mutation is detected by full hashing")

            invalid = ["rustc", str(src), "--crate-type", "rlib", "--bad-invalid-option"]
            front_error = subprocess.run([str(args.front), *invalid], env=env, cwd=root, capture_output=True, timeout=60)
            base_error = subprocess.run([str(args.baseline), *invalid], env=env, cwd=root, capture_output=True, timeout=60)
            assert front_error.returncode == base_error.returncode != 0
            assert (front_error.stdout, front_error.stderr) == (base_error.stdout, base_error.stderr)
            checks.append("unsupported invocation preserves compiler failure status and diagnostics")

            stdin_command = ["rustc", "-", "--crate-name", "stdin_fixture", "--crate-type", "bin", "-o", str(root / "stdin-bin")]
            stdin_code = b"fn main() { println!(\"stdin preserved\"); }\n"
            before_stdin = pool.counts()
            front_stdin = subprocess.run([str(args.front), *stdin_command], input=stdin_code, env=env, cwd=root, capture_output=True, timeout=60)
            stdin_artifact = (root / "stdin-bin").read_bytes()
            base_stdin = subprocess.run([str(args.baseline), *stdin_command], input=stdin_code, env=env, cwd=root, capture_output=True, timeout=60)
            assert front_stdin.returncode == base_stdin.returncode == 0
            assert (front_stdin.stdout, front_stdin.stderr) == (base_stdin.stdout, base_stdin.stderr)
            assert (root / "stdin-bin").read_bytes() == stdin_artifact
            assert subprocess.check_output([str(root / "stdin-bin")]) == b"stdin preserved\n"
            checks.append("fallback compiler receives original stdin and produces identical executable")
            if args.expect_pruning:
                assert pool.counts() == before_stdin
                checks.append("obvious Rust binary producer skips worker IPC")

            zig_output = root / "zig-bin"
            zig_command = ["zig", "build-exe", str(zig_src), "-O", "ReleaseFast", "-femit-bin=" + str(zig_output)]
            run(zig_command)
            zig_bytes = zig_output.read_bytes()
            zig_output.unlink()
            served_before = pool.counts()["served"]
            run(zig_command)
            assert events()[-1] == "hit" and pool.counts()["served"] > served_before
            assert zig_output.read_bytes() == zig_bytes
            checks.append("stable Zig 0.17.0 executable restored by worker with identical bytes")

            # Eight concurrent requests sharing destinations retain ordinary
            # per-key/output locks; all returned diagnostics must be equal.
            remove(); run(); remove()
            before = len(events())
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(lambda _: run(), range(8)))
            assert events()[before:] == ["hit"] * 8
            assert all((r.stdout, r.stderr) == (results[0].stdout, results[0].stderr) for r in results)
            checks.append("concurrent same-key restores preserve outputs and locks")

            # A bad peer must not kill or poison the next job.
            for frame in [struct.pack("<I", 1024 * 1024 + 1), struct.pack("<I", 1) + b"{"]:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(5)
                    client.connect(str(pool.root / "0.sock"))
                    client.sendall(frame)
                    header = client.recv(9)
                    assert header and header[0] == 200
            remove(); run()
            assert events()[-1] == "hit" and all(p.poll() is None for p in pool.processes)
            checks.append("oversized/malformed requests leave workers usable")

            pool.close()
            remove(); run()
            assert events()[-1] == "hit"
            checks.append("terminated workers and leftover sockets fall back to accepted wrapper")
        finally:
            pool.close()

    report = {"scope": "private macOS cache-hit worker and lightweight C client; not production adoption",
              "checks": checks, "passed": len(checks),
              "binary_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest()
                                for name, path in [("worker", args.worker), ("front", args.front), ("baseline", args.baseline)]}}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": len(checks)}))


if __name__ == "__main__":
    main()
