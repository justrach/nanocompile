"""Real compiler tests; isolated caches and source trees, no global configuration."""
import concurrent.futures
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
    with tempfile.TemporaryDirectory(prefix="nanocompile-test-") as temp:
        root = Path(temp)
        env = dict(os.environ, NANOCOMPILE_DIR=str(root / "cache"), NANOCOMPILE_TRACE="1")

        def run(args, success=True, custom_env=None):
            (root / "out").mkdir(exist_ok=True)
            p = subprocess.run([BIN, *args], cwd=root, env=custom_env or env, capture_output=True)
            if success:
                assert p.returncode == 0, p.stderr.decode(errors="replace")
            return p

        def events():
            path = root / "cache/events"
            return path.read_text().splitlines() if path.exists() else []

        (root / "lib.rs").write_text('mod child; pub fn answer() -> u32 { child::VALUE }\n')
        (root / "child.rs").write_text('pub const VALUE: u32 = 42;\n')
        rust = ["rustc", "lib.rs", "--crate-name", "fixture", "--crate-type", "rlib",
                "--emit=dep-info,metadata,link", "--out-dir", "out", "-C", "opt-level=2"]
        run(rust)
        expected = {p.name: digest(p) for p in (root / "out").iterdir()}
        assert events()[-1] == "miss"
        shutil.rmtree(root / "out")
        p = run(rust)
        assert b"nanocompile: hit" in p.stderr, p.stderr
        assert expected == {p.name: digest(p) for p in (root / "out").iterdir()}
        # Mutating a restored output must not mutate the content-addressed blob.
        (root / "out/libfixture.rlib").write_bytes(b"modified")
        run(rust)
        assert digest(root / "out/libfixture.rlib") == expected["libfixture.rlib"]
        # Content changes invalidate even if size and mtime are unchanged.
        child = root / "child.rs"
        old_time = child.stat().st_mtime_ns
        child.write_text('pub const VALUE: u32 = 43;\n')
        os.utime(child, ns=(old_time, old_time))
        run(rust)
        assert events()[-1] == "miss"
        assert digest(root / "out/libfixture.rlib") != expected["libfixture.rlib"]
        run(rust)
        assert events()[-1] == "hit"
        # Adding a competing module path changes rustc's resolution even when
        # every previously recorded source file remains byte-for-byte equal.
        (root / "child").mkdir()
        (root / "child/mod.rs").write_text('pub const VALUE: u32 = 43;\n')
        assert run(rust, success=False).returncode != 0
        assert events()[-1] == "failed"
        shutil.rmtree(root / "child")
        run(rust)
        # Corruption forces recompilation and repairs the content-addressed blob.
        entry = json.loads(next((root / "cache/entries").iterdir()).read_text().split("\n", 1)[1])
        artifact = entry["outputs"][0]["hash"]
        (root / "cache/blobs" / artifact[:2] / artifact).write_bytes(b"corrupt")
        run(rust)
        assert events()[-1] == "miss"
        run(rust)
        assert events()[-1] == "hit"
        # Valid JSON with corrupted dependency metadata also forces a miss.
        manifest = next((root / "cache/entries").iterdir())
        seal, payload = manifest.read_text().split("\n", 1)
        corrupt = json.loads(payload)
        corrupt["dependencies"] = []
        manifest.write_text(seal + "\n" + json.dumps(corrupt))
        run(rust)
        assert events()[-1] == "miss"
        # Failed compiles retain their status and never create successful entries.
        (root / "child.rs").write_text("this is not rust\n")
        assert run(rust, success=False).returncode != 0
        assert events()[-1] == "failed"
        (root / "child.rs").write_text('pub const VALUE: u32 = 43;\n')
        run(rust)
        # Environment values are inputs, including arbitrary env! names.
        (root / "lib.rs").write_text('pub const VALUE: &str = env!("TEST_VALUE");\n')
        e1 = dict(env, TEST_VALUE="first")
        e2 = dict(env, TEST_VALUE="other")
        run(rust, custom_env=e1)
        first = digest(root / "out/libfixture.rlib")
        run(rust, custom_env=e2)
        assert events()[-1] == "miss"
        assert first != digest(root / "out/libfixture.rlib")
        # Include paths containing spaces are faithfully parsed from dep-info.
        (root / "some data.txt").write_text("hello")
        (root / "lib.rs").write_text('pub const TEXT: &str = include_str!("some data.txt");\n')
        run(rust)
        run(rust)
        assert events()[-1] == "hit"
        (root / "some data.txt").write_text("world")
        run(rust)
        assert events()[-1] == "miss"
        # Concurrent identical requests perform only one compilation.
        run(["clear"])
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda _: run(rust), range(6)))
        assert events().count("miss") == 1, events()
        assert events().count("hit") == 5, events()
        # Different keys sharing one destination cannot capture each other's output.
        (root / "lib.rs").write_text('#[cfg(first)] pub const VALUE: u32 = 11; #[cfg(second)] pub const VALUE: u32 = 22;\n')
        first_args = rust + ["--cfg=first"]
        second_args = rust + ["--cfg=second"]
        run(first_args)
        first_hash = digest(root / "out/libfixture.rlib")
        run(second_args)
        second_hash = digest(root / "out/libfixture.rlib")
        assert first_hash != second_hash
        run(["clear"])
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run, [first_args, second_args]))
        run(first_args)
        assert digest(root / "out/libfixture.rlib") == first_hash
        run(second_args)
        assert digest(root / "out/libfixture.rlib") == second_hash
        (root / "lib.rs").write_text('pub fn answer() -> u32 { 42 }\n')
        run(rust)
        blob_count = len([p for p in (root / "cache/blobs").rglob("*") if p.is_file()])
        # Distinct keys with identical compiler bytes share the same blobs.
        run(rust, custom_env=dict(env, NC_UNUSED_TEST_VALUE="one"))
        run(rust, custom_env=dict(env, NC_UNUSED_TEST_VALUE="two"))
        assert len([p for p in (root / "cache/blobs").rglob("*") if p.is_file()]) == blob_count
        # A corrupted toolchain memo is re-fingerprinted rather than trusted.
        memo = next((root / "cache/toolchains").iterdir())
        memo.write_bytes(b"corrupt memo")
        run(rust)
        assert events()[-1] == "hit"
        # Probes and unsupported invocations remain usable.
        assert b"rustc " in run(["rustc", "--version"]).stdout
        assert events()[-1] == "bypass"
        # Cache failure must not prevent compilation.
        bad = root / "not-a-directory"
        bad.write_text("x")
        run(rust, custom_env=dict(env, NANOCOMPILE_DIR=str(bad)))
        # Preserve diagnostic bytes on a hit.
        (root / "lib.rs").write_text('fn unused() {} pub fn answer() -> u32 { 42 }\n')
        first = run(rust)
        second = run(rust)
        def diagnostics(p):
            return b"\n".join(line for line in p.stderr.split(b"\n") if not line.startswith(b"nanocompile:"))
        assert diagnostics(first) == diagnostics(second)
        assert b"never used" in second.stderr

        (root / "main.zig").write_text('pub fn main() void {}\n')
        zig = ["zig", "build-exe", "main.zig", "-O", "ReleaseFast", "-femit-bin=hello"]
        run(zig)
        assert events()[-1] == "miss"
        before = digest(root / "hello")
        mode = (root / "hello").stat().st_mode
        (root / "hello").unlink()
        run(zig)
        assert events()[-1] == "hit"
        assert digest(root / "hello") == before
        assert (root / "hello").stat().st_mode == mode
        subprocess.run([str(root / "hello")], check=True)
        # Track literal Zig imports and embedded data.
        (root / "data.txt").write_text("42")
        (root / "child.zig").write_text('pub const value = @embedFile("data.txt");\n')
        (root / "main.zig").write_text('const child = @import("child.zig"); pub fn main() void { if (child.value[0] != \'4\') @panic("wrong"); }\n')
        run(zig)
        run(zig)
        assert events()[-1] == "hit"
        (root / "data.txt").write_text("43")
        run(zig)
        assert events()[-1] == "miss"
        # Zig's module graph command line is supported too.
        (root / "main.zig").write_text('const child = @import("child"); pub fn main() void { if (child.value[0] != \'4\') @panic("wrong"); }\n')
        module_zig = ["zig", "build-exe", "-O", "ReleaseFast", "--dep", "child", "-Mroot=main.zig", "-Mchild=child.zig", "-femit-bin=hello"]
        run(module_zig)
        run(module_zig)
        assert events()[-1] == "hit"
        (root / "data.txt").write_text("44")
        run(module_zig)
        assert events()[-1] == "miss"
        (root / "object.zig").write_text('export fn answer() u32 { return 42; }\n')
        for kind, output in [("build-obj", "out/answer.o"), ("build-lib", "out/libanswer.a")]:
            command = ["zig", kind, "object.zig", "-O", "ReleaseFast", "-femit-bin=" + output]
            run(command)
            expected = digest(root / output)
            (root / output).unlink()
            run(command)
            assert events()[-1] == "hit"
            assert digest(root / output) == expected
        # A transitive extern can change without the directly referenced rlib
        # changing. Search-directory fingerprints must still invalidate it.
        (root / "deps").mkdir()
        (root / "trans.rs").write_text('pub const VALUE: u32 = 41;\n')
        (root / "bridge.rs").write_text('pub fn value() -> u32 { trans::VALUE }\n')
        (root / "consumer.rs").write_text('pub fn value() -> u32 { bridge::value() }\n')
        def library(source, name, out, extras=()):
            return ["rustc", source, "--edition=2021", "--crate-name", name, "--crate-type", "rlib", "--emit=dep-info,metadata,link", "--out-dir", out, *extras]
        trans = library("trans.rs", "trans", "deps")
        bridge = library("bridge.rs", "bridge", "deps", ["--extern", "trans=deps/libtrans.rlib", "-L", "dependency=deps"])
        consumer = library("consumer.rs", "consumer", "out", ["--extern", "bridge=deps/libbridge.rlib", "-L", "dependency=deps"])
        run(trans)
        run(bridge)
        run(consumer)
        run(consumer)
        assert events()[-1] == "hit"
        (root / "trans.rs").write_text('pub const VALUE: u32 = 42;\n')
        run(trans)
        p = run(consumer, success=False)
        assert events()[-1] != "hit"
        direct = subprocess.run(consumer, cwd=root, env=env, capture_output=True)
        assert p.returncode == direct.returncode
        # Cargo exercises the wrapper protocol and real extern dependency paths.
        project = root / "cargo-project"
        (project / "src").mkdir(parents=True)
        (project / "dep/src").mkdir(parents=True)
        (project / "Cargo.toml").write_text('[package]\nname="consumer"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nlocaldep={path="dep"}\n')
        (project / "dep/Cargo.toml").write_text('[package]\nname="localdep"\nversion="0.1.0"\nedition="2021"\n')
        (project / "src/lib.rs").write_text('pub fn answer() -> u32 { localdep::answer() }\n')
        (project / "dep/src/lib.rs").write_text('pub fn answer() -> u32 { 42 }\n')
        cargo_env = dict(env, RUSTC_WRAPPER=BIN, CARGO_INCREMENTAL="0")
        def cargo(*args):
            result = subprocess.run(["cargo", *args], cwd=project, env=cargo_env, capture_output=True)
            assert result.returncode == 0, result.stderr.decode(errors="replace")
            return result
        memo_count = len(list((root / "cache/toolchains").iterdir()))
        cargo("build", "--release")
        # Package-specific Cargo environment values must not hash the same
        # installed toolchain again for every crate.
        assert len(list((root / "cache/toolchains").iterdir())) == memo_count + 1
        cargo("clean")
        p = cargo("build", "--release")
        assert b"nanocompile: hit" in p.stderr, p.stderr
        cargo("check")
        cargo("clean")
        p = cargo("check")
        assert b"nanocompile: hit" in p.stderr, p.stderr
        # Orphan collection and a zero-byte quota do not affect restored files.
        run(rust)
        orphan = root / "cache/blobs/ff" / ("f" * 64)
        orphan.parent.mkdir(exist_ok=True)
        orphan.write_bytes(b"orphan")
        run(["gc", "10737418240"])
        assert not orphan.exists()
        run(rust)
        assert events()[-1] == "hit"
        run(["gc", "0"])
        assert not list((root / "cache/entries").iterdir())
        assert not [p for p in (root / "cache/blobs").rglob("*") if p.is_file()]
        run(rust)
        assert events()[-1] == "miss"
        print("PASS: real Rust/Zig restore, invalidation, corruption, isolation, failures, environment, escaped paths, single-flight and bypass")


if __name__ == "__main__":
    main()
