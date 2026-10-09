#!/usr/bin/env python3
"""Reproduce the standalone APFS watch-hash experiment (not a compiler wrapper)."""
import argparse
import hashlib
import json
import mmap
import os
from pathlib import Path
import platform
import select
import statistics
import struct
import subprocess
import tempfile
import threading
import time


class Worker:
    def __init__(self, binary, capacity=8):
        self.proc = subprocess.Popen([str(binary), str(capacity)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def read_exact(self, length):
        result = bytearray()
        deadline = time.monotonic() + 30
        while len(result) < length:
            assert select.select([self.proc.stdout], [], [], max(0, deadline - time.monotonic()))[0], "worker timed out"
            part = os.read(self.proc.stdout.fileno(), length - len(result))
            assert part, f"worker closed pipe: {self.proc.stderr.read().decode()}"
            result.extend(part)
        return bytes(result)

    def request(self, paths=(), mode="watch"):
        payload = json.dumps({"mode": mode, "paths": [str(p) for p in paths]}).encode()
        start = time.perf_counter_ns()
        self.proc.stdin.write(struct.pack("<I", len(payload)) + payload)
        self.proc.stdin.flush()
        size, = struct.unpack("<I", self.read_exact(4))
        assert 0 < size <= 1024 * 1024
        response = json.loads(self.read_exact(size))
        response["roundtrip_ns"] = time.perf_counter_ns() - start
        return response

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)
        assert self.proc.returncode == 0, self.proc.stderr.read().decode()
        self.proc.stdout.close()
        self.proc.stderr.close()


def checked(worker, path, reused=None):
    response = worker.request([path])
    item = response["results"][0]
    direct = worker.request([path], "full")["results"][0]
    assert item["failure"] is None and direct["failure"] is None
    assert item["hash"] == direct["hash"]
    if reused is not None:
        assert item["reused"] == reused, response
    return response


def correctness(binary):
    cases = []
    with tempfile.TemporaryDirectory(prefix="nanocompile-watch-tests-") as temp:
        root = Path(temp)
        p = root / "input"
        p.write_bytes(b"A" * 4096)
        worker = Worker(binary)
        try:
            first = checked(worker, p, False)
            assert first["results"][0]["watched"], "local APFS required for this experiment"
            checked(worker, p, True)
            cases.append("unchanged file reuses canonical BLAKE3")

            stamp = p.stat()
            p.write_bytes(b"B" * 4096)
            os.utime(p, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            changed = checked(worker, p, False)
            assert changed["invalidations"] > first["invalidations"]
            cases.append("same-size write with preserved mtime invalidates")

            stamp = p.stat()
            p.write_bytes(b"C" * 4096)
            p.write_bytes(b"B" * 4096)
            os.utime(p, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            checked(worker, p, False)
            cases.append("write then restore identical bytes still rehashes")

            with p.open("r+b") as file:
                with mmap.mmap(file.fileno(), 0) as mapping:
                    mapping[:4096] = b"M" * 4096
                    mapping.flush()
            checked(worker, p, False)
            cases.append("writable mmap mutation invalidates")

            replacement = root / "replacement"
            replacement.write_bytes(b"R" * 4096)
            os.replace(replacement, p)
            checked(worker, p, False)
            cases.append("atomic inode replacement invalidates")

            renamed = root / "renamed"
            p.rename(renamed)
            failed = worker.request([p])["results"][0]
            assert failed["hash"] is None and failed["failure"] is not None
            p.write_bytes(b"N" * 4096)
            checked(worker, p, False)
            cases.append("rename, missing pathname and recreation cannot reuse old fd")

            p.unlink()
            assert worker.request([p])["results"][0]["hash"] is None
            p.write_bytes(b"D" * 4096)
            checked(worker, p, False)
            cases.append("delete/recreate invalidates")

            alias = root / "alias"
            os.link(p, alias)
            alias.write_bytes(b"H" * 4096)
            checked(worker, p, False)
            cases.append("mutation through hardlink invalidates")

            link = root / "link"
            link.symlink_to(p)
            checked(worker, link, False)
            checked(worker, link, True)
            target = root / "target"
            target.write_bytes(b"T" * 4096)
            link.unlink()
            link.symlink_to(target)
            checked(worker, link, False)
            cases.append("symlink target inode retarget invalidates")

            p.write_bytes(b"short")
            checked(worker, p, False)
            p.write_bytes(b"")
            empty = checked(worker, p, False)
            assert empty["results"][0]["hash"] == "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"
            cases.append("truncate and canonical empty BLAKE3")

            os.chmod(p, 0o600)
            checked(worker, p, False)
            cases.append("attribute change invalidates")

            files = [root / f"evict-{i}" for i in range(9)]
            for i, file in enumerate(files):
                file.write_bytes(bytes([i]) * 1024)
            worker.request(mode="reset")
            reply = worker.request(files)
            assert reply["resident"] == 8 and all(x["failure"] is None for x in reply["results"])
            checked(worker, files[0], False)
            assert worker.request()["resident"] <= 8
            cases.append("bounded descriptors and fd recycling eviction")

            for invalid in ["relative", str(root), str(root / "missing"), "/bad\u0000path", "/" + "x" * 4097]:
                assert worker.request([invalid])["results"][0]["hash"] is None
            fifo = root / "fifo"
            os.mkfifo(fifo)
            assert worker.request([fifo])["results"][0]["failure"] == "NotRegularFile"
            cases.append("invalid/missing/directory/FIFO requests fail without digest or blocking")

            # Sustained writes span watch registration and the entire full read.
            large = root / "concurrent"
            with large.open("wb") as file:
                file.truncate(128 * 1024 * 1024)
            stop = threading.Event()
            started = threading.Event()
            writes = [0]

            def mutate():
                with large.open("r+b", buffering=0) as file:
                    started.set()
                    while not stop.is_set():
                        file.seek(0)
                        file.write(bytes([writes[0] % 256]) * 4096)
                        writes[0] += 1
                        time.sleep(0.0001)

            thread = threading.Thread(target=mutate)
            thread.start()
            started.wait()
            try:
                concurrent = worker.request([large])["results"][0]
            finally:
                stop.set()
                thread.join()
            assert writes[0] > 2 and concurrent["failure"] == "InputChanged", (writes, concurrent)
            checked(worker, large, False)
            checked(worker, large, True)
            cases.append("concurrent writes during initial read reject digest; stable retry succeeds")

            checked(worker, p)
            worker.request(mode="lose_queue")
            first = checked(worker, p, False)
            second = checked(worker, p, False)
            assert not first["watch_available"] and second["resident"] == 0
            cases.append("lost queue clears all memos and permanently falls back to full hashing")
        finally:
            worker.close()

    # Malformed frames must terminate the private worker, never yield a digest.
    for payload in [struct.pack("<I", 1024 * 1024 + 1), struct.pack("<I", 10) + b"{}", struct.pack("<I", 1) + b"{"]:
        process = subprocess.run([str(binary)], input=payload, capture_output=True, timeout=10)
        assert process.returncode != 0 and not process.stdout
    cases.append("oversized/truncated/malformed frames terminate without output")
    return {"passed": len(cases), "cases": cases}


def benchmark(binary, paths, pairs, capacity):
    worker = Worker(binary, capacity)
    samples = []
    try:
        prime = worker.request(paths)
        assert all(x["watched"] and not x["reused"] and x["failure"] is None for x in prime["results"])
        expected = [x["hash"] for x in prime["results"]]
        for i in range(pairs):
            pair = {}
            for mode in (["full", "watch"] if i % 2 == 0 else ["watch", "full"]):
                result = worker.request(paths, mode)
                assert [x["hash"] for x in result["results"]] == expected
                assert all(x["failure"] is None for x in result["results"])
                if mode == "watch":
                    assert all(x["reused"] for x in result["results"])
                pair[mode] = {"worker_ns": result["nanoseconds"], "roundtrip_ns": result["roundtrip_ns"]}
            samples.append(pair)
        return {"pairs": pairs, "capacity": capacity, "samples": samples, "prime_worker_ns": prime["nanoseconds"],
                "full_roundtrip_median_ns": statistics.median(x["full"]["roundtrip_ns"] for x in samples),
                "watch_roundtrip_median_ns": statistics.median(x["watch"]["roundtrip_ns"] for x in samples),
                "files": [{"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]}
    finally:
        worker.close()


def mmap_counterexample(binary):
    """Show why successful ordinary mutation tests do not prove safe reuse."""
    worker = Worker(binary)
    try:
        with tempfile.TemporaryDirectory(prefix="nanocompile-watch-counterexample-") as temp:
            p = Path(temp) / "input"
            p.write_bytes(b"A" * 4096)
            with p.open("r+b") as file:
                with mmap.mmap(file.fileno(), 0) as mapping:
                    # Dirty the mapped page BEFORE registration, then keep the
                    # mapping live across hashing and later memory writes.
                    mapping[:] = b"B" * 4096
                    prime = worker.request([p])
                    warm = worker.request([p])
                    before = p.stat()
                    mapping[:] = b"C" * 4096
                    after = p.stat()
                    watched = worker.request([p])
                    full = worker.request([p], "full")
                    w, f = watched["results"][0], full["results"][0]
                    assert w["failure"] is None and f["failure"] is None
                    same_metadata = all(getattr(before, field) == getattr(after, field)
                                        for field in ["st_dev", "st_ino", "st_size", "st_mode", "st_nlink", "st_mtime_ns", "st_ctime_ns"])
                    observed = w["reused"] and w["hash"] != f["hash"]
                    return {"stale_digest_observed": observed, "same_metadata": same_metadata,
                            "primed_watched": prime["results"][0]["watched"],
                            "warm_reused": warm["results"][0]["reused"],
                            "after_write_reused": w["reused"],
                            "invalidations_after_write": watched["invalidations"],
                            "watched_hash": w["hash"], "full_hash": f["hash"]}
    finally:
        worker.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--file", type=Path, action="append", default=[])
    parser.add_argument("--pairs", type=int, default=25)
    parser.add_argument("--capacity", type=int, default=256)
    parser.add_argument("--entry", type=Path, help="sealed compiler entry; benchmark its regular dependencies and output blobs")
    parser.add_argument("--cache-root", type=Path)
    args = parser.parse_args()
    if args.pairs < 1 or not 1 <= args.capacity <= 4096:
        parser.error("pairs must be positive and capacity must be 1..4096")
    report = {"scope": "standalone persistent hash worker; not a project build or production integration",
              "platform": platform.platform(), "machine": platform.machine(),
              "zig": subprocess.check_output(["zig", "version"], text=True).strip(),
              "sources_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                 for name in ["watch_hash.zig", "watch_hash_fs.c", "watch_hash.py"]},
              "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
              "correctness": correctness(args.binary)}
    report["mmap_counterexample"] = mmap_counterexample(args.binary)
    report["decision"] = "rejected: watch events and metadata can miss writes through an already-dirty writable mmap"
    # This is an executable regression reproducer for the rejected model.
    # If OS behavior changes, stop rather than silently claiming the old result.
    assert report["mmap_counterexample"]["stale_digest_observed"], report["mmap_counterexample"]
    if args.entry:
        if not args.cache_root:
            parser.error("--entry needs --cache-root")
        entry_bytes = args.entry.read_bytes()
        entry = json.loads(entry_bytes[65:])
        paths = [Path(d["path"]) for d in entry["dependencies"]
                 if not d.get("directory") and d.get("missing") is None and d.get("symlink_target") is None]
        paths.extend(args.cache_root / "blobs" / o["hash"][:2] / o["hash"] for o in entry["outputs"])
        args.file.extend(dict.fromkeys(paths))
        report["entry_sha256"] = hashlib.sha256(entry_bytes).hexdigest()
        report["entry_regular_dependencies"] = len(paths) - len(entry["outputs"])
        report["entry_output_blobs"] = len(entry["outputs"])
    if args.file:
        report["benchmark"] = benchmark(args.binary, args.file, args.pairs, args.capacity)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"ordinary_checks_passed": report["correctness"]["passed"],
                      "stale_digest_observed": report["mmap_counterexample"]["stale_digest_observed"],
                      "decision": "rejected",
                      "full_ms": report.get("benchmark", {}).get("full_roundtrip_median_ns", 0) / 1e6,
                      "watch_ms": report.get("benchmark", {}).get("watch_roundtrip_median_ns", 0) / 1e6}))


if __name__ == "__main__":
    main()
