#!/usr/bin/env python3
"""Setup contract tests; --benchmark adds isolated real cold/warm setup + Rust."""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("setup_tool", ROOT / "tools/setup_nanocompile.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def test_key_invalidates_each_identity_component(self):
        identity = {"revision": "a" * 40, "source_sha256": "source",
                    "toolchain_sha256": "zig-and-sdk", "host": {"target": "aarch64-macos"},
                    "setup_sha256": "driver", "version": "0.1.0", "optimize": "ReleaseFast"}
        original = setup.cache_key(identity)
        for field in identity:
            changed = copy.deepcopy(identity)
            changed[field] = "changed"
            self.assertNotEqual(original, setup.cache_key(changed), field)
        self.assertEqual(original, setup.cache_key(dict(reversed(list(identity.items())))))

    def test_tree_hashes_bytes_membership_and_toolchain_not_mtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input"
            source.write_bytes(b"one")
            paths = [("src", root)]
            original = setup.tree_digest(paths)
            stat = source.stat()
            source.write_bytes(b"two")
            os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.assertNotEqual(original, setup.tree_digest(paths))
            source.write_bytes(b"one")
            self.assertEqual(original, setup.tree_digest(paths))
            (root / "added").write_bytes(b"")
            self.assertNotEqual(original, setup.tree_digest(paths))
            (root / "added").unlink()
            source.rename(root / "renamed")
            self.assertNotEqual(original, setup.tree_digest(paths))

    @unittest.skipIf(os.name == "nt", "symlink privilege not assumed on Windows")
    def test_tool_resource_symlink_bytes_and_cycles(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "tree").mkdir()
            (root / "external").write_text("one")
            (root / "tree/link").symlink_to(root / "external")
            (root / "tree/cycle").symlink_to(root / "tree", target_is_directory=True)
            before = setup.tree_digest([("tool", root / "tree")])
            (root / "external").write_text("two")
            self.assertNotEqual(before, setup.tree_digest([("tool", root / "tree")]))

    def test_restore_checks_identity_and_digest_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "nanocompile"
            binary.write_bytes(b"not really an executable")
            entry = root / "cache"
            identity = {"version": "0.1.0"}
            setup.save(entry, binary, identity)
            stage = root / "stage" / binary.name
            stage.parent.mkdir()
            with mock.patch.object(setup, "compatible") as execute:
                setup.restore(entry, stage, identity)
                execute.assert_called_once_with(stage, identity)
                execute.reset_mock()
                with self.assertRaisesRegex(ValueError, "identity mismatch"):
                    setup.restore(entry, stage, {"version": "different"})
                execute.assert_not_called()
                (entry / binary.name).write_bytes(b"corrupt")
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    setup.restore(entry, stage, identity)
                execute.assert_not_called()

    def test_valid_checksum_still_requires_compatible_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "nanocompile"
            binary.write_bytes(b"wrong architecture")
            setup.save(root / "entry", binary, {"version": "0.1.0"})
            with mock.patch.object(setup, "compatible", side_effect=OSError("exec format")):
                with self.assertRaises(OSError):
                    setup.restore(root / "entry", binary, {"version": "0.1.0"})

    def test_version_and_help_required(self):
        identity = {"version": "0.1.0"}
        with mock.patch.object(setup, "run", return_value=mock.Mock(stdout="wrong\n")):
            with self.assertRaisesRegex(ValueError, "version mismatch"):
                setup.compatible(Path("candidate"), identity)
        with mock.patch.object(setup, "run", side_effect=[
                mock.Mock(stdout="nanocompile 0.1.0 (Zig 0.17.0)\n"),
                mock.Mock(stdout="not help")]):
            with self.assertRaisesRegex(ValueError, "help check failed"):
                setup.compatible(Path("candidate"), identity)

    def test_unpinned_revision_and_wrong_checkout_refused(self):
        with self.assertRaisesRegex(ValueError, "full lowercase"):
            setup.plan(ROOT, "main", "zig")
        with mock.patch.object(setup, "run", return_value=mock.Mock(stdout="b" * 40)):
            with self.assertRaisesRegex(ValueError, "does not match"):
                setup.plan(ROOT, "a" * 40, "zig")

    def test_wrong_zig_and_custom_compiler_refused(self):
        revision = "a" * 40
        with mock.patch.dict(os.environ, {"CC": "custom"}):
            with mock.patch.object(setup, "run", return_value=mock.Mock(stdout=revision)):
                with self.assertRaisesRegex(ValueError, "build override"):
                    setup.plan(ROOT, revision, "zig")
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(setup.shutil, "which", return_value="zig"):
                with mock.patch.object(setup, "run", side_effect=[
                        mock.Mock(stdout=revision), mock.Mock(stdout="0.16.0")]):
                    with self.assertRaisesRegex(ValueError, "requires Zig 0.17.0"):
                        setup.plan(ROOT, revision, "zig")


def benchmark(destination):
    """One end-to-end sample, with fresh private Zig and Nano caches.

    Output contains timings/platform only, never environment dumps or local
    paths. Toolchain acquisition and remote cache transfer are not measured.
    """
    revision = setup.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    rustc = shutil.which("rustc")
    if not rustc:
        raise RuntimeError("benchmark requires rustc")
    with tempfile.TemporaryDirectory(prefix="nanocompile-setup-check-") as temp:
        root = Path(temp)
        # Snapshot build inputs so concurrent work in the checkout cannot make
        # cold/warm identities differ. Git metadata is read-only; no commits.
        source = root / "source"
        source.mkdir()
        for filename in ("build.zig", "build.zig.zon"):
            shutil.copyfile(ROOT / filename, source / filename)
        shutil.copytree(ROOT / "src", source / "src")
        (source / "tools").mkdir()
        shutil.copyfile(ROOT / "tools/setup_nanocompile.py", source / "tools/setup_nanocompile.py")
        git_dir = setup.run(["git", "rev-parse", "--absolute-git-dir"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
        setup_env = dict(os.environ, GIT_DIR=git_dir, GIT_WORK_TREE=str(source))
        prefix = root / "installed"
        cache = root / "executables"
        name = "nanocompile.exe" if os.name == "nt" else "nanocompile"
        binary = prefix / "bin" / name
        report = root / "report.json"
        command = [sys.executable, source / "tools/setup_nanocompile.py", "--revision", revision,
                   "--cache-dir", cache, "--prefix", prefix, "--report", report, "--clean-env"]
        (root / "lib.rs").write_text("pub fn answer() -> u32 { 42 }\n")
        out = root / "out"
        env = dict(os.environ, NANOCOMPILE_DIR=str(root / "rust-cache"),
                   NANOCOMPILE_TRACE="1", NANOCOMPILE_RUSTC=rustc)
        rows = []
        expected = None
        for label, event in (("cold", b"nanocompile: miss"), ("warm", b"nanocompile: hit")):
            if prefix.exists():
                shutil.rmtree(prefix)  # Warm setup must actually restore the executable.
            if out.exists():
                shutil.rmtree(out)
            out.mkdir()
            start = time.perf_counter()
            setup.run(command, env=setup_env, capture_output=True, text=True)
            setup_wall = time.perf_counter() - start
            details = json.loads(report.read_text())
            assert details["cache_status"] == ("miss" if label == "cold" else "hit")
            compile_start = time.perf_counter()
            result = setup.run([binary, "rustc", "lib.rs", "--crate-name", "setup_smoke",
                                "--crate-type", "rlib", "--emit=dep-info,metadata,link",
                                "--out-dir", "out", "-C", "opt-level=2"],
                               cwd=root, env=env, capture_output=True, timeout=120)
            compile_wall = time.perf_counter() - compile_start
            assert event in result.stderr, "expected Rust cache event missing"
            artifacts = {p.name: setup.checksum(p) for p in out.iterdir()}
            assert any(name.endswith(".rlib") for name in artifacts)
            if expected is None:
                expected = artifacts
                executable_digest = details["sha256"]
            else:
                assert expected == artifacts, "warm compiler outputs differ"
                assert executable_digest == details["sha256"], "warm executable differs"
            rows.append({"run": label, "setup_wall_seconds": setup_wall,
                         "setup_identity_seconds": details["identity_seconds"],
                         "setup_build_seconds": details["build_seconds"],
                         "compile_wall_seconds": compile_wall,
                         "end_to_end_seconds": time.perf_counter() - start,
                         "setup_cache": details["cache_status"],
                         "compiler_cache": "miss" if label == "cold" else "hit"})
        # A damaged cache must trigger a real source fallback, never execute it.
        entry = cache / details["key"]
        (entry / name).write_bytes(b"corrupt executable")
        setup.run(command, env=setup_env, capture_output=True, text=True)
        rejected = json.loads(report.read_text())
        assert rejected["cache_status"] == "rejected"
        setup.compatible(binary, json.loads((entry / "manifest.json").read_text())["identity"])
        data = {"schema": 1, "target": setup.host_identity()["target"],
                "python": ".".join(map(str, sys.version_info[:3])),
                "zig": setup.ZIG_VERSION,
                "rustc": setup.run([rustc, "--version"], capture_output=True,
                                   text=True).stdout.strip().split()[1],
                "samples": rows,
                "corruption_fallback_setup_seconds": rejected["setup_seconds"],
                "verified": ["deleted executable restored byte-identically",
                             "cold Rust miss and warm hit with identical output hashes",
                             "corrupt executable rejected and rebuilt from source"],
                "limitations": ["one local native sample, not hosted CI evidence",
                                "preinstalled toolchains; acquisition and remote cache transfer excluded",
                                "setup uses --clean-env to ignore custom compiler/library overrides",
                                "cold setup uses empty private Zig caches; OS file caches not flushed",
                                "tiny Rust library; not representative of large project speedups",
                                "working source bytes included in key; checkout contains uncommitted changes"]}
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(data, indent=2) + "\n")
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path)
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SetupTests))
    if not result.wasSuccessful():
        sys.exit(1)
    if args.benchmark:
        benchmark(args.benchmark)
