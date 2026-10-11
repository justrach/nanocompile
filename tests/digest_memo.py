"""Digest memo correctness with real rustc and inputs/outputs above the memo threshold."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

BIN = str(Path(sys.argv[1]).resolve())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    with tempfile.TemporaryDirectory(prefix="nanocompile-memo-") as temp:
        root = Path(temp)
        env = dict(os.environ, NANOCOMPILE_DIR=str(root / "cache"), NANOCOMPILE_TRACE="1")
        env.pop("NANOCOMPILE_DIGEST_MEMO", None)

        def run(args, custom_env=None, success=True):
            (root / "out").mkdir(exist_ok=True)
            p = subprocess.run([BIN, *args], cwd=root, env=custom_env or env, capture_output=True)
            if success:
                assert p.returncode == 0, p.stderr.decode(errors="replace")
            return p

        def last_event():
            return (root / "cache/events").read_text().splitlines()[-1]

        def memo_count():
            memo = root / "cache/memo"
            return sum(1 for p in memo.rglob("*") if p.is_file()) if memo.exists() else 0

        def direct(args):
            out = root / "direct"
            shutil.rmtree(out, ignore_errors=True)
            out.mkdir()
            command = [part if part != "out" else str(out) for part in args]
            subprocess.run(command, cwd=root, check=True, capture_output=True)
            return {p.name: digest(p) for p in out.iterdir() if p.suffix == ".rlib"}

        data = root / "data.bin"
        data.write_bytes(bytes(range(256)) * 1024)  # 256 KiB: above the memo threshold.
        (root / "lib.rs").write_text('pub static DATA: &[u8] = include_bytes!("data.bin");\n'
                                     'pub fn byte(i: usize) -> u8 { DATA[i] }\n')
        rust = ["rustc", "lib.rs", "--crate-name", "memo", "--crate-type", "rlib",
                "--emit=dep-info,metadata,link", "--out-dir", "out"]
        run(rust)
        assert last_event() == "miss"
        assert memo_count() > 0, "large output and blob digests are memoized"
        shutil.rmtree(root / "out")
        run(rust)
        assert last_event() == "hit"
        rlib = root / "out/libmemo.rlib"
        assert rlib.stat().st_size > 256 * 1024
        assert {rlib.name: digest(rlib)} == direct(rust)

        # Same-size in-place edit with preserved mtime: ctime still changes,
        # so the memoized digest of the large input must not be trusted.
        stamp = data.stat()
        payload = bytearray(data.read_bytes())
        payload[-1] ^= 0xFF
        data.write_bytes(bytes(payload))
        os.utime(data, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert data.stat().st_size == stamp.st_size and data.stat().st_mtime_ns == stamp.st_mtime_ns
        run(rust)
        assert last_event() == "miss"
        assert {rlib.name: digest(rlib)} == direct(rust)
        run(rust)
        assert last_event() == "hit"

        # Same-size corruption of a large cached output blob with preserved
        # mtime forces recompilation and repairs the blob.
        corrupted = 0
        for manifest in (root / "cache/entries").iterdir():
            entry = json.loads(manifest.read_text().split("\n", 1)[1])
            for output in entry.get("outputs", []):
                blob = root / "cache/blobs" / output["hash"][:2] / output["hash"]
                if blob.exists() and blob.stat().st_size > 256 * 1024:
                    stamp = blob.stat()
                    payload = bytearray(blob.read_bytes())
                    payload[-1] ^= 0xFF
                    os.chmod(blob, 0o600)
                    blob.write_bytes(bytes(payload))
                    os.utime(blob, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                    corrupted += 1
        assert corrupted > 0
        shutil.rmtree(root / "out")
        run(rust)
        assert last_event() == "miss"
        assert {rlib.name: digest(rlib)} == direct(rust)
        run(rust)
        assert last_event() == "hit"

        # A restored output modified in place by a later tool is rehashed.
        stamp = rlib.stat()
        payload = bytearray(rlib.read_bytes())
        payload[-1] ^= 0xFF
        rlib.write_bytes(bytes(payload))
        os.utime(rlib, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        (root / "consumer.rs").write_text("pub fn first() -> u8 { memo::byte(0) }\n")
        consumer = ["rustc", "consumer.rs", "--edition=2021", "--crate-name", "consumer", "--crate-type", "rlib",
                    "--emit=dep-info,metadata,link", "--out-dir", "out", "--extern", "memo=out/libmemo.rlib", "-L", "dependency=out"]
        first = run(consumer, success=False)
        reference = subprocess.run(consumer, cwd=root, capture_output=True)
        assert first.returncode == reference.returncode
        run(rust)  # Repairs libmemo.rlib from the cache.
        run(consumer)
        run(consumer)
        assert last_event() == "hit"

        # Garbage memo records are ignored rather than trusted.
        for memo in (root / "cache/memo").rglob("*"):
            if memo.is_file():
                memo.write_text("garbage")
        shutil.rmtree(root / "out")
        run(rust)
        assert last_event() == "hit"
        assert {rlib.name: digest(rlib)} == direct(rust)

        # gc keeps live memo records and removes stale ones.
        shutil.rmtree(root / "out")
        run(rust)
        live = memo_count()
        assert live > 0
        rlib.unlink()  # Its materialization memo is now stale.
        g = subprocess.run([BIN, "gc"], cwd=root, env=env, capture_output=True, text=True)
        assert g.returncode == 0 and "stale digest memos removed:" in g.stdout, g.stdout + g.stderr
        removed = int(g.stdout.rsplit(":", 1)[1])
        assert removed >= 1 and memo_count() == live - removed, (g.stdout, live)
        run(rust)
        assert last_event() == "hit"

        # The control disables both lookup and recording.
        shutil.rmtree(root / "cache/memo")
        off = dict(env, NANOCOMPILE_DIGEST_MEMO="0")
        run(rust, custom_env=off)
        shutil.rmtree(root / "out")
        run(rust, custom_env=off)
        assert last_event() == "hit"
        assert memo_count() == 0
        print("PASS: digest memo invalidation, corruption repair, garbage records and disable control")


if __name__ == "__main__":
    main()
