"""Libraries that also link a Rust dylib (crate types rlib+dylib, with or
without staticlib) with real rustc: cached in place, byte-identical to direct
builds, usable by consumers, invalidated by dependency changes, and covering
Cargo's macOS dev-profile split debug objects."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

BIN = str(Path(sys.argv[1]).resolve())


def main():
    with tempfile.TemporaryDirectory(prefix="nanocompile-rust-dylib-") as temp:
        root = Path(temp)
        deps = root / "deps"
        deps.mkdir()
        env = dict(os.environ, RUSTUP_TOOLCHAIN="1.97.1", NANOCOMPILE_DIR=str(root / "cache"), NANOCOMPILE_TRACE="1",
                   NANOCOMPILE_EXECUTABLE_PRODUCERS="1", NANOCOMPILE_RUST_STATICLIB="1")
        rustc = subprocess.check_output(["rustup", "which", "--toolchain", "1.97.1", "rustc"], text=True).strip()
        (root / "dep.rs").write_text("pub fn base() -> u32 { 40 }\n")
        (root / "lib.rs").write_text("pub fn value() -> u32 { dep::base() + 2 }\n")
        (root / "main.rs").write_text("fn main() { println!(\"{}\", lib::value()); }\n")

        def dependency(extra=()):
            subprocess.run([rustc, "dep.rs", "--crate-name", "dep", "--crate-type", "rlib", "--emit=dep-info,metadata,link",
                            "--out-dir", str(deps), "-C", "extra-filename=-d1", *extra], cwd=root, env=env, check=True, capture_output=True)

        def command(types, extra=()):
            return [rustc, "lib.rs", "--edition=2021", "--crate-name", "lib", *sum((["--crate-type", t] for t in types), []),
                    "--emit=dep-info,link", "--out-dir", str(deps), "-C", "extra-filename=-l2",
                    "--extern", "dep=" + str(deps / "libdep-d1.rlib"), "-L", "dependency=" + str(deps), *extra]

        def build(args, wrapped):
            for f in deps.iterdir():
                if f.name.startswith(("liblib-l2", "lib-l2")):
                    f.unlink()
            p = subprocess.run(([BIN] if wrapped else []) + args, cwd=root, env=env, capture_output=True)
            assert p.returncode == 0, p.stderr.decode(errors="replace")
            files = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in deps.iterdir() if f.name.startswith(("liblib-l2", "lib-l2"))}
            return p.stderr.decode(errors="replace"), files

        def consume(expected):
            subprocess.run([rustc, "main.rs", "--edition=2021", "--extern", "lib=" + str(deps / "liblib-l2.rlib"),
                            "-L", "dependency=" + str(deps), "-o", str(root / "consumer")], cwd=root, env=env, check=True, capture_output=True)
            assert subprocess.check_output([str(root / "consumer")]).strip() == str(expected).encode()

        for label, types, extra, debug in [("rlib+dylib+staticlib", ("rlib", "dylib", "staticlib"), (), False),
                                            ("rlib+dylib", ("rlib", "dylib"), (), False),
                                            ("dev-profile", ("rlib", "dylib"), ("-C", "debuginfo=2", "-C", "split-debuginfo=unpacked"), True)]:
            dependency(extra)
            args = command(types, extra)
            _, direct = build(args, False)
            assert "liblib-l2.dylib" in direct and (not debug or any(n.endswith(".rcgu.o") for n in direct)), direct
            trace, cold = build(args, True)
            assert "miss: compiling" in trace and "uncached" not in trace, (label, trace)
            assert cold == direct, (label, cold, direct)
            trace, warm = build(args, True)
            assert "nanocompile: hit" in trace and warm == direct, (label, trace)
            consume(42)
            # A dependency edit changes the linked dylib: never a hit.
            (root / "dep.rs").write_text("pub fn base() -> u32 { 41 }\n")
            dependency(extra)
            trace, changed = build(args, True)
            assert "hit" not in trace and changed != direct, (label, trace)
            consume(43)
            (root / "dep.rs").write_text("pub fn base() -> u32 { 40 }\n")

        # Without executable producers the dylib link stays uncached.
        dependency()
        env["NANOCOMPILE_EXECUTABLE_PRODUCERS"] = "0"
        trace, _ = build(command(("rlib", "dylib")), True)
        assert "bypass:" in trace, trace
        print("PASS: rlib+dylib(+staticlib) libraries cached in place, byte-identical, consumer use, dependency invalidation, dev profile")


if __name__ == "__main__":
    main()
