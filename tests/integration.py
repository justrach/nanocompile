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
        first = run(rust)
        expected = {p.name: digest(p) for p in (root / "out").iterdir()}
        assert events()[-1] == "miss", first.stderr.decode(errors="replace")
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
        # Real source reverts must restore the historical artifact, including
        # preserved-mtime source edits; both variants remain fully validated.
        child.write_text('pub const VALUE: u32 = 42;\n')
        os.utime(child, ns=(old_time, old_time))
        shutil.rmtree(root / "out")
        run(rust)
        assert events()[-1] == "hit" and "variant_hit" in events()
        assert digest(root / "out/libfixture.rlib") == expected["libfixture.rlib"]
        child.write_text('pub const VALUE: u32 = 43;\n')
        os.utime(child, ns=(old_time, old_time))
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
        entries = [json.loads(path.read_text().split("\n", 1)[1]) for path in (root / "cache/entries").iterdir()]
        for entry in entries:
            for output in entry["outputs"]:
                artifact = output["hash"]
                (root / "cache/blobs" / artifact[:2] / artifact).write_bytes(b"corrupt")
        run(rust)
        assert events()[-1] == "miss"
        run(rust)
        assert events()[-1] == "hit"
        # Valid JSON with corrupted dependency metadata also forces a miss.
        # Corrupt every candidate: a valid historical duplicate is allowed to
        # recover a corrupt primary, but no unsealed candidate may be trusted.
        for manifest in (root / "cache/entries").iterdir():
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
        # Unrelated Cargo outputs in the same -L directory must not evict this
        # graph. In particular, mere presence of a proc-macro library is safe.
        run(library("trans.rs", "unrelated", "deps"))
        (root / "deps/libunrelated_macro.dylib").write_bytes(b"not loaded by this crate")
        run(consumer)
        assert events()[-1] == "hit"
        # A new candidate for a relevant transitive crate must invalidate even
        # if the original path and every tracked source stayed unchanged.
        shutil.copyfile(root / "deps/libtrans.rlib", root / "deps/libtrans-alternate.rlib")
        run(consumer, success=False)
        assert events()[-1] != "hit"
        (root / "deps/libtrans-alternate.rlib").unlink()
        run(consumer)
        (root / "trans.rs").write_text('pub const VALUE: u32 = 42;\n')
        run(trans)
        p = run(consumer, success=False)
        assert events()[-1] != "hit"
        direct = subprocess.run(consumer, cwd=root, env=env, capture_output=True)
        assert p.returncode == direct.returncode
        # Follow rustc's full extra-filename search before its broad fallback.
        # An alternate suffix is irrelevant while the primary remains valid;
        # a competing primary candidate or fallback replacement must invalidate.
        (root / "hashed").mkdir()
        (root / "hashed.rs").write_text('pub const VALUE: u32 = 41;\n')
        (root / "hashed_bridge.rs").write_text('pub fn value() -> u32 { hashdep::VALUE }\n')
        (root / "hashed_consumer.rs").write_text('pub fn value() -> u32 { hashbridge::value() }\n')
        provider = library("hashed.rs", "hashdep", "hashed", ["-C", "extra-filename=-first"])
        run(provider)
        run(library("hashed_bridge.rs", "hashbridge", "hashed", ["--extern", "hashdep=hashed/libhashdep-first.rlib", "-L", "dependency=hashed"]))
        hashed_consumer = library("hashed_consumer.rs", "hashconsumer", "out", ["--extern", "hashbridge=hashed/libhashbridge.rlib", "-L", "dependency=hashed"])
        run(hashed_consumer)
        run(hashed_consumer)
        assert events()[-1] == "hit"
        shutil.copyfile(root / "hashed/libhashdep-first.rlib", root / "hashed/libhashdep-second.rlib")
        run(hashed_consumer)
        assert events()[-1] == "hit"
        shutil.copyfile(root / "hashed/libhashdep-first.rlib", root / "hashed/libhashdep-first-extra.rlib")
        p = run(hashed_consumer, success=False)
        direct = subprocess.run(hashed_consumer, cwd=root, env=env, capture_output=True)
        assert events()[-1] != "hit" and p.returncode == direct.returncode
        (root / "hashed/libhashdep-first-extra.rlib").unlink()
        (root / "hashed/libhashdep-first.rlib").unlink()
        (root / "hashed/libhashdep-first.rmeta").unlink()
        run(hashed_consumer)
        assert events()[-1] != "hit"
        run(hashed_consumer)
        assert events()[-1] == "hit"
        # A filename match with the wrong metadata cannot select primary mode.
        shutil.copyfile(root / "deps/libunrelated.rlib", root / "hashed/libhashdep-first.rlib")
        run(hashed_consumer)
        assert events()[-1] != "hit"
        run(hashed_consumer)
        assert events()[-1] == "hit"
        # The valid fallback's content is still an input, including mtime edits.
        fallback = root / "hashed/libhashdep-second.rlib"
        stamp = fallback.stat()
        fallback.write_bytes(b"not Rust metadata")
        os.utime(fallback, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        p = run(hashed_consumer, success=False)
        direct = subprocess.run(hashed_consumer, cwd=root, env=env, capture_output=True)
        assert events()[-1] != "hit" and p.returncode == direct.returncode != 0
        # Native -L paths on consumers must track full directory membership,
        # regular files, and symlink targets, including preserved-mtime edits.
        (root / "native").mkdir()
        archive = root / "native/libcandidate.a"
        archive.write_bytes(b"!<arch>\nfirst___")
        # The scanner intentionally still declines ambiguous bare link calls.
        (root / "plain.rs").write_text('''/// A symbolic link (parent) is ordinary documentation.
pub struct Queue;
impl Queue { pub fn link(&self, x: u32) -> u32 { x + 1 } }
pub fn value() -> u32 { Queue.link(41) }
''')
        native_consumer = library("plain.rs", "plain", "out", ["-L", "native=native"])
        run(native_consumer)
        p = run(native_consumer)
        assert events()[-1] == "hit", p.stderr
        stamp = archive.stat()
        archive.write_bytes(b"!<arch>\nsecond__")
        os.utime(archive, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        run(native_consumer)
        assert events()[-1] == "miss"
        run(native_consumer)
        assert events()[-1] == "hit"
        competing = root / "native/libcompeting.a"
        competing.write_bytes(b"!<arch>\n")
        run(native_consumer)
        assert events()[-1] == "miss"
        competing.unlink()
        run(native_consumer)
        # Removing the competing archive restores a fully validated historical
        # directory state; its artifact is now eligible again.
        assert events()[-1] == "hit"
        (root / "external-native.a").write_bytes(b"!<arch>\ntarget_1")
        alias = root / "native/libalias.a"
        alias.symlink_to(root / "external-native.a")
        run(native_consumer)
        run(native_consumer)
        assert events()[-1] == "hit"
        (root / "external-native.a").write_bytes(b"!<arch>\ntarget_2")
        run(native_consumer)
        assert events()[-1] == "miss"
        thin = root / "native/libthin.a"
        thin.write_bytes(b"!<thin>\n")
        run(native_consumer)
        p = run(native_consumer)
        assert events()[-1] == "bypass" and b"ThinNativeArchive" in p.stderr, p.stderr
        thin.unlink()
        # Native declarations are classified from completed metadata on the pinned
        # compiler. Strings must not hide an attribute following the string.
        (root / "native_attr.rs").write_text('''const MARKER: &str = "/*";
#[link(name="c")] extern "C" { fn puts(s: *const u8) -> i32; }
pub fn value() -> u32 { 42 }
''')
        native_attribute = library("native_attr.rs", "native_attr", "out")
        run(native_attribute)
        p = run(native_attribute)
        rust_version = subprocess.check_output(["rustc", "-V"], env=env)
        if rust_version.strip() == b"rustc 1.97.1 (8bab26f4f 2026-07-14)":
            assert events()[-1] == "hit", p.stderr
        else:
            assert events()[-1] == "miss" and b"nanocompile: uncached:" in p.stderr, p.stderr
        # Exercise a real bundled C archive through a Rust provider and cached
        # consumer, then relink/run after changing the native implementation.
        (root / "native_provider.rs").write_text('''#[link(name="answer", kind="static")]
extern "C" { fn native_answer() -> u32; }
pub fn value() -> u32 { unsafe { native_answer() } }
''')
        provider = library("native_provider.rs", "native_provider", "deps", ["-L", "native=native"])
        (root / "native_consumer.rs").write_text('pub fn value() -> u32 { native_provider::value() }\n')
        native_chain = library("native_consumer.rs", "native_consumer", "out", ["--extern", "native_provider=deps/libnative_provider.rlib", "-L", "dependency=deps", "-L", "native=native"])
        def native_archive(value):
            (root / "native/answer.c").write_text(f'unsigned native_answer(void) {{ return {value}; }}\n')
            subprocess.run(['cc', '-c', 'native/answer.c', '-o', 'native/answer.o'], cwd=root, check=True, capture_output=True)
            subprocess.run(['ar', 'rcs', 'native/libanswer.a', 'native/answer.o'], cwd=root, check=True, capture_output=True)
            run(provider)
        def check_native(value):
            (root / "native_driver.rs").write_text(f'fn main() {{ assert_eq!(native_consumer::value(), {value}); }}\n')
            linked = subprocess.run(['rustc', 'native_driver.rs', '--extern', 'native_consumer=out/libnative_consumer.rlib', '-L', 'dependency=deps', '-L', 'native=native', '-o', 'native_driver'], cwd=root, env=env, capture_output=True)
            assert linked.returncode == 0, linked.stderr
            subprocess.run([str(root / 'native_driver')], check=True, capture_output=True)
        native_archive(41)
        run(native_chain)
        run(native_chain)
        assert events()[-1] == "hit"
        check_native(41)
        native_archive(42)
        run(native_chain)
        assert events()[-1] == "miss"
        run(native_chain)
        assert events()[-1] == "hit"
        check_native(42)
        # Reported-input macro mode is explicit. Test a real proc macro whose
        # hidden file read is absent from rustc dep-info, then declare that file
        # globally so every macro consumer tracks it by content.
        (root / "macro_read.rs").write_text("""extern crate proc_macro;
#[proc_macro] pub fn read(_: proc_macro::TokenStream) -> proc_macro::TokenStream {
    let path = std::env::var("MACRO_INPUT").unwrap();
    format!("{:?}", std::fs::read_to_string(path).unwrap()).parse().unwrap()
}
""")
        extension = ".dylib" if sys.platform == "darwin" else ".so"
        macro_path = "deps/libmacro_read" + extension
        def compile_macro():
            p = subprocess.run(["rustc", "macro_read.rs", "--crate-name", "macro_read", "--crate-type", "proc-macro", "-o", macro_path], cwd=root, env=env, capture_output=True)
            assert p.returncode == 0, p.stderr
        compile_macro()
        (root / "macro_consumer.rs").write_text('pub const DATA: &str = macro_read::read!();\n')
        (root / "macro_check.rs").write_text('fn main() { print!("{}", macro_consumer::DATA); }\n')
        def check_macro_value(expected_value):
            p = subprocess.run(["rustc", "macro_check.rs", "--edition=2021", "--extern", "macro_consumer=out/libmacro_consumer.rlib", "-L", "dependency=deps", "-o", "out/macro_check"], cwd=root, env=env, capture_output=True)
            assert p.returncode == 0, p.stderr
            assert subprocess.check_output([str(root / "out/macro_check")]) == expected_value

        (root / "macro-data.txt").write_text("one")
        (root / "macro-inputs.json").write_text(json.dumps(["macro-data.txt"]))
        macro_env = dict(env, MACRO_INPUT=str(root / "macro-data.txt"))
        macro_consumer = library("macro_consumer.rs", "macro_consumer", "out", ["--extern", "macro_read=" + macro_path, "-L", "dependency=deps"])
        run(macro_consumer, custom_env=macro_env)
        assert events()[-1] == "bypass"
        macro_env.update(NANOCOMPILE_PROC_MACROS="reported", NANOCOMPILE_EXTRA_INPUTS_FILE=str(root / "macro-inputs.json"))
        run(macro_consumer, custom_env=macro_env)
        original = digest(root / "out/libmacro_consumer.rlib")
        (root / "out/libmacro_consumer.rlib").unlink()
        p = run(macro_consumer, custom_env=macro_env)
        assert events()[-1] == "hit", p.stderr
        assert digest(root / "out/libmacro_consumer.rlib") == original
        check_macro_value(b"one")
        data = root / "macro-data.txt"
        old_time = data.stat().st_mtime_ns
        data.write_text("two")
        os.utime(data, ns=(old_time, old_time))
        run(macro_consumer, custom_env=macro_env)
        assert events()[-1] == "miss"
        assert digest(root / "out/libmacro_consumer.rlib") != original
        check_macro_value(b"two")
        run(macro_consumer, custom_env=macro_env)
        assert events()[-1] == "hit"
        # Changing the loaded macro itself invalidates an unchanged consumer.
        source = root / "macro_read.rs"
        source.write_text(source.read_text().replace('format!("{:?}", std::fs::read_to_string(path).unwrap())', 'format!("{:?}", std::fs::read_to_string(path).unwrap() + "!")'))
        compile_macro()
        run(macro_consumer, custom_env=macro_env)
        assert events()[-1] == "miss"
        # Reexporting a macro hides the DSO behind an ordinary --extern rlib.
        # The metadata graph must still find it and preserve the selected policy.
        (root / "macro_bridge.rs").write_text('pub use macro_read::read;\n')
        macro_bridge = library("macro_bridge.rs", "macro_bridge", "deps", ["--extern", "macro_read=" + macro_path, "-L", "dependency=deps"])
        run(macro_bridge, custom_env=macro_env)
        (root / "macro_reexport.rs").write_text('pub const DATA: &str = macro_bridge::read!();\n')
        macro_reexport = library("macro_reexport.rs", "macro_reexport", "out", ["--extern", "macro_bridge=deps/libmacro_bridge.rlib", "-L", "dependency=deps"])
        strict_env = dict(macro_env, NANOCOMPILE_PROC_MACROS="tracked")
        run(macro_reexport, custom_env=strict_env)
        p = run(macro_reexport, custom_env=strict_env)
        assert b"uncached: ProceduralMacroDependency" in p.stderr, p.stderr
        assert events()[-1] != "hit"
        run(macro_reexport, custom_env=macro_env)
        p = run(macro_reexport, custom_env=macro_env)
        assert events()[-1] == "hit", p.stderr
        data.write_text("new")
        run(macro_reexport, custom_env=macro_env)
        assert events()[-1] == "miss"
        missing_declaration = dict(macro_env, NANOCOMPILE_EXTRA_INPUTS_FILE=str(root / "missing-inputs.json"))
        run(macro_reexport, custom_env=missing_declaration)
        assert events()[-1] == "bypass"
        # Cargo exercises the wrapper protocol and real extern dependency paths.
        project = root / "cargo-project"
        (project / "src").mkdir(parents=True)
        (project / "dep/src").mkdir(parents=True)
        (project / "Cargo.toml").write_text('[package]\nname="consumer"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nlocaldep={path="dep"}\n[profile.release]\nlto="thin"\n')
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
