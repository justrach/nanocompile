"""Bounded Windows Rust path/invalidation and artifact checks; also runnable on POSIX."""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def compiler_smoke(binary):
    binary = str(Path(binary).resolve())
    rustc = os.environ.get("NANOCOMPILE_RUSTC") or shutil.which("rustc")
    assert rustc, "rustc must be installed or selected with NANOCOMPILE_RUSTC"
    rustc = str(Path(shutil.which(rustc) or rustc).absolute())
    with tempfile.TemporaryDirectory(prefix="nanocompile-windows-rust-") as temp:
        root = Path(temp).resolve() / "project with spaces"
        source_dir = root / "source files"
        dependency_dir = root / "dependency outputs"
        output = root / "library outputs"
        for directory in (source_dir, dependency_dir, output):
            directory.mkdir(parents=True)
        env = dict(os.environ, NANOCOMPILE_DIR=str(root / "compiler cache"),
                   NANOCOMPILE_RUSTC=rustc, NANOCOMPILE_TRACE="1")

        def run(command, custom_env=None):
            result = subprocess.run(command, cwd=root, env=custom_env or env,
                                    capture_output=True, timeout=120)
            assert result.returncode == 0, (command, result.returncode, result.stderr)
            return result

        dependency_source = source_dir / "dependency library.rs"
        source = source_dir / "consumer library.rs"
        dependency_source.write_bytes(b"pub const VALUE: u32 = 41;\n")
        source.write_bytes(b"extern crate release_dependency;\npub const VALUE: u32 = release_dependency::VALUE + 1;\n")
        dependency_args = [str(dependency_source), "--crate-name", "release_dependency",
                           "--crate-type", "rlib", "--emit=dep-info,metadata,link",
                           "--out-dir", str(dependency_dir)]
        run([rustc, *dependency_args])
        dependency_rlibs = list(dependency_dir.glob("*.rlib"))
        assert len(dependency_rlibs) == 1
        dependency_rlib = dependency_rlibs[0]
        args = [str(source), "--crate-name", "release_consumer", "--crate-type", "rlib",
                "--emit=dep-info,metadata,link", "--out-dir", str(output),
                "--extern", f"release_dependency={dependency_rlib}",
                "-L", f"dependency={dependency_dir}", "-C", "opt-level=2"]

        def outputs():
            result = {path.name: path.read_bytes() for path in output.iterdir()}
            assert any(name.endswith(".rlib") for name in result)
            return result

        def remove_outputs():
            shutil.rmtree(output)
            output.mkdir()

        def check_revision(previous=None):
            remove_outputs()
            cold = run([binary, "rustc", *args])
            assert b"nanocompile: miss" in cold.stderr, cold.stderr
            cold_outputs = outputs()
            if previous is not None:
                assert any(data != previous[name] for name, data in cold_outputs.items()
                           if name.endswith(".rlib")), "changed inputs produced stale library bytes"
            # Reuse identical absolute output paths so dep-info is comparable byte for byte.
            remove_outputs()
            run([rustc, *args])
            direct_outputs = outputs()
            assert cold_outputs == direct_outputs, "cached cold compilation differs from direct rustc"
            remove_outputs()
            warm = run([binary, "rustc", *args])
            assert b"nanocompile: hit" in warm.stderr, warm.stderr
            assert outputs() == direct_outputs, "warm restoration differs from direct rustc"
            return direct_outputs

        initial = check_revision()
        dependency_source.write_bytes(b"pub const VALUE: u32 = 42;\n")
        run([rustc, *dependency_args])
        changed_dependency = check_revision(initial)
        before = source.stat()
        original = source.read_bytes()
        edited = original.replace(b" + 1;", b" + 2;")
        assert edited != original and len(edited) == len(original)
        source.write_bytes(edited)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert source.stat().st_mtime_ns == before.st_mtime_ns
        changed_source = check_revision(changed_dependency)

        if os.name == "nt":
            # Validate extensionless compiler selection separately from explicit-path correctness.
            path_env = dict(env)
            path_env.pop("NANOCOMPILE_RUSTC")
            path_env["PATH"] = str(Path(rustc).parent) + os.pathsep + path_env.get("PATH", "")
            path_env["PATHEXT"] = ".EXE;" + path_env.get("PATHEXT", ".COM;.BAT;.CMD")
            path_env["NANOCOMPILE_DIR"] = str(root / "PATH selection cache")
            remove_outputs()
            selected = run([binary, "rustc", *args], custom_env=path_env)
            assert b"nanocompile: miss" in selected.stderr, selected.stderr
            assert outputs() == changed_source, "PATH/PATHEXT selection differs from direct rustc"
    print("absolute spaced Rust paths, extern/search paths, dependency and preserved-mtime source invalidation passed")


def smoke(binary):
    binary = str(Path(binary).resolve())
    with tempfile.TemporaryDirectory(prefix="nanocompile-windows-") as temp:
        root = Path(temp) / "project with spaces"
        root.mkdir()
        env = dict(os.environ, NANOCOMPILE_DIR=str(root / "cache with spaces"))

        def run(args, code=0):
            result = subprocess.run([binary, *args], cwd=root, env=env,
                                    capture_output=True, timeout=60)
            assert result.returncode == code, (args, result.returncode, result.stderr)
            return result

        assert json.loads(run(["artifact", "head", "release-test", "missing"], code=3).stdout) == {"hit": False}
        payloads = [(bytes([index]) * 65536) + bytes(range(256)) for index in range(4)]
        sources = []
        for index, payload in enumerate(payloads):
            source = root / f"payload {index}.bin"
            source.write_bytes(payload)
            sources.append(source)

        def put(source):
            return run(["artifact", "put", "release-test", "shared-key", str(source), '{"test":true}'])

        # Competing writers must leave one complete sealed entry and CAS blob.
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(put, sources))
        assert all(json.loads(result.stdout) == {"stored": True} for result in results)
        info = json.loads(run(["artifact", "head", "release-test", "shared-key"]).stdout)
        assert info["hit"] and info["bytes"] == len(payloads[0])
        assert json.loads(info["metadata"]) == {"test": True}
        restored = root / "restored payload.bin"
        run(["artifact", "get", "release-test", "shared-key", str(restored)])
        expected = restored.read_bytes()
        assert expected in payloads, "concurrent writers produced torn artifact bytes"
        restored.write_bytes(b"local mutation")
        run(["artifact", "get", "release-test", "shared-key", str(restored)])
        assert restored.read_bytes() == expected, "restoring an artifact must not alias its CAS blob"
        run(["stats"])
        run(["gc", "0"])
        run(["artifact", "head", "release-test", "shared-key"], code=3)
        put(sources[0])
        run(["clear"])
        run(["artifact", "head", "release-test", "shared-key"], code=3)
    print("artifact roundtrip, concurrent writes, copy isolation, GC and clear smoke passed")
    compiler_smoke(binary)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--compiler-only":
        compiler_smoke(sys.argv[2])
    elif len(sys.argv) == 2:
        smoke(sys.argv[1])
    else:
        raise SystemExit("usage: python tests/windows_cache.py [--compiler-only] PATH/TO/nanocompile.exe")
