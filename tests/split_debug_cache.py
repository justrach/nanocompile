"""Unpacked split debug info (Cargo's macOS dev profile) with real rustc: library
sidecar objects are cached and restored, debug-free builds are cached, and
binaries with debug info stay uncached."""
import hashlib
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
    with tempfile.TemporaryDirectory(prefix="nanocompile-split-debug-") as temp:
        root = Path(temp)
        env = dict(os.environ, NANOCOMPILE_DIR=str(root / "cache"), NANOCOMPILE_TRACE="1")
        (root / "lib.rs").write_text("pub fn f() -> u32 { 7 }\npub fn g(x: u32) -> u32 { x * 3 + f() }\n")
        (root / "main.rs").write_text("fn main() { println!(\"{}\", 3); }\n")

        def rustc(source, crate_type, out, *extra):
            return ["rustc", source, "--crate-name", "split", "--crate-type", crate_type, "--emit=dep-info,metadata,link"
                    if crate_type == "lib" else "--emit=dep-info,link", "--out-dir", out, "-C", "split-debuginfo=unpacked", *extra]

        def run(args):
            out = Path(root / args[args.index("--out-dir") + 1])
            shutil.rmtree(out, ignore_errors=True)
            out.mkdir()
            p = subprocess.run([BIN, *args], cwd=root, env=env, capture_output=True)
            assert p.returncode == 0, p.stderr.decode(errors="replace")
            return p.stderr.decode(errors="replace"), {f.name: digest(f) for f in out.iterdir()}

        def direct(args):
            out = root / "direct"
            shutil.rmtree(out, ignore_errors=True)
            out.mkdir()
            command = [part if part != args[args.index("--out-dir") + 1] else "direct" for part in args]
            subprocess.run(command, cwd=root, check=True, capture_output=True)
            return {f.name: digest(f) for f in out.iterdir()}

        debug = rustc("lib.rs", "lib", "out", "-C", "debuginfo=2", "-C", "extra-filename=-a1", "-C", "codegen-units=4")
        cold_trace, cold = run(debug)
        assert "miss: compiling" in cold_trace, cold_trace
        sidecars = sorted(name for name in cold if name.endswith(".rcgu.o"))
        assert sidecars and all(name.startswith("split-a1.") for name in sidecars), cold
        warm_trace, warm = run(debug)
        assert "nanocompile: hit" in warm_trace, warm_trace
        assert warm == cold, (warm, cold)
        assert set(direct(debug)) == set(cold)

        # The same crate under another extra-filename shares no sidecars.
        other = rustc("lib.rs", "lib", "out", "-C", "debuginfo=2", "-C", "extra-filename=-b2", "-C", "codegen-units=4")
        other_trace, other_files = run(other)
        assert "miss: compiling" in other_trace and not any(n.startswith("split-a1.") for n in other_files), other_files
        assert run(other)[1] == other_files

        # Without debug info rustc leaves no sidecars, so the request is cached.
        plain = rustc("lib.rs", "lib", "out", "-C", "debuginfo=0", "-C", "extra-filename=-c3")
        assert "miss: compiling" in run(plain)[0]
        trace, files = run(plain)
        assert "nanocompile: hit" in trace and not any(n.endswith(".rcgu.o") for n in files), (trace, files)

        # A binary's debug map names its objects by absolute path: stay uncached.
        binary = rustc("main.rs", "bin", "out", "-C", "debuginfo=2", "-C", "extra-filename=-d4")
        for producers in ("0", "1"):
            env["NANOCOMPILE_EXECUTABLE_PRODUCERS"] = producers
            for _ in range(2):
                trace, files = run(binary)
                assert "bypass:" in trace and "hit" not in trace, trace
        print("PASS: unpacked split-debug sidecars cached and restored, prefix isolation, debug-free caching, binary bypass")


if __name__ == "__main__":
    main()
