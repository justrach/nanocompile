"""Native search directories with the pinned stock rustc: a library that bundles
nothing does not depend on -L native= directory contents, a static #[link]
expanded from another crate's macro is never cached, a static library named
on the command line is still tracked, and other compiler spellings keep the
full directory snapshot."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

BIN = str(Path(sys.argv[1]).resolve())


def main():
    rustc = subprocess.check_output(["rustup", "which", "--toolchain", "1.97.1", "rustc"], text=True).strip()
    with tempfile.TemporaryDirectory(prefix="nanocompile-native-search-") as temp:
        root = Path(temp)
        env = dict(os.environ, RUSTUP_TOOLCHAIN="1.97.1", NANOCOMPILE_DIR=str(root / "cache"), NANOCOMPILE_TRACE="1")
        native, deps = root / "native", root / "deps"
        native.mkdir()
        deps.mkdir()

        def archive(value):
            (root / "probe.c").write_text(f"unsigned value(void) {{ return {value}; }}\n")
            subprocess.run(["cc", "-c", "probe.c", "-o", str(native / "probe.o")], cwd=root, check=True)
            (native / "libprobe.a").unlink(missing_ok=True)
            subprocess.run(["ar", "crs", str(native / "libprobe.a"), str(native / "probe.o")], cwd=root, check=True)

        def compile(source, name, *extra, compiler=rustc, out="out"):
            (root / out).mkdir(exist_ok=True)
            for f in (root / out).iterdir():
                f.unlink()
            p = subprocess.run([BIN, compiler, source, "--edition=2021", "--crate-name", name, "--crate-type", "rlib",
                                "--emit=dep-info,metadata,link", "--out-dir", out, "-L", "native=native", *extra],
                               cwd=root, env=env, capture_output=True, text=True)
            assert p.returncode == 0, p.stderr
            return p.stderr, {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in (root / out).iterdir()}

        def run(name, expected, *extra):
            subprocess.run([rustc, "main.rs", "--edition=2021", "--extern", f"{name}=out/lib{name}.rlib", "-L", "dependency=deps",
                            "-L", "native=native", *extra, "-o", "probe"], cwd=root, env=env, check=True, capture_output=True)
            assert subprocess.check_output([str(root / "probe")]).strip() == str(expected).encode()

        archive(41)
        # A library that bundles nothing: native directory contents are not inputs.
        (root / "plain.rs").write_text("pub fn answer() -> u32 { 42 }\n")
        assert "miss: compiling" in compile("plain.rs", "plain")[0]
        assert "nanocompile: hit" in compile("plain.rs", "plain")[0]
        archive(43)
        (native / "libcompeting.a").write_bytes((native / "libprobe.a").read_bytes())
        assert "nanocompile: hit" in compile("plain.rs", "plain")[0]
        (native / "libcompeting.a").unlink()

        # A static #[link] expanded from another crate's macro is never cached.
        (root / "macros.rs").write_text('#[macro_export] macro_rules! declare { () => {\n'
                                        '  #[link(name = "probe", kind = "static")] unsafe extern "C" { fn value() -> u32; }\n'
                                        '  pub fn answer() -> u32 { unsafe { value() } }\n} }\n')
        subprocess.run([rustc, "macros.rs", "--edition=2021", "--crate-name", "macros", "--crate-type", "rlib",
                        "--emit=dep-info,metadata,link", "--out-dir", "deps"], cwd=root, env=env, check=True, capture_output=True)
        (root / "hidden.rs").write_text("macros::declare!();\n")
        hidden = ("--extern", "macros=deps/libmacros.rlib", "-L", "dependency=deps")
        for _ in range(2):
            trace, _ = compile("hidden.rs", "hidden", *hidden)
            assert "miss: compiling" in trace and "uncached: HiddenNativeLinkInput" in trace, trace
        (root / "main.rs").write_text("fn main() { println!(\"{}\", hidden::answer()); }\n")
        run("hidden", 43)
        archive(44)
        trace, _ = compile("hidden.rs", "hidden", *hidden)
        assert "hit" not in trace, trace
        run("hidden", 44)

        # A static library named on the command line is a tracked input.
        (root / "named.rs").write_text('unsafe extern "C" { fn value() -> u32; }\npub fn answer() -> u32 { unsafe { value() } }\n')
        named = ("-l", "static=probe")
        assert "miss: compiling" in compile("named.rs", "named", *named)[0]
        assert "nanocompile: hit" in compile("named.rs", "named", *named)[0]
        archive(45)
        assert "hit" not in compile("named.rs", "named", *named)[0]
        (root / "main.rs").write_text("fn main() { println!(\"{}\", named::answer()); }\n")
        run("named", 45)

        # Another compiler spelling (the rustup proxy) keeps the full snapshot.
        assert "miss: compiling" in compile("plain.rs", "plain", compiler="rustc")[0]
        assert "nanocompile: hit" in compile("plain.rs", "plain", compiler="rustc")[0]
        archive(46)
        assert "hit" not in compile("plain.rs", "plain", compiler="rustc")[0]
        print("PASS: native search precision: unbundled libraries, macro-expanded static links, named static libraries, proxy snapshot")


if __name__ == "__main__":
    main()
