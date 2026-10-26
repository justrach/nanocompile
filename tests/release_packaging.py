"""Bounded archive tests; optional native smoke of an extracted release executable."""
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("package_release", ROOT / "tools/package_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class PackagingTests(unittest.TestCase):
    def test_archive_contents_metadata_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "nanocompile"
            binary.write_bytes(b"release executable fixture\n")
            (root / "private.log").write_text("must not be packaged")
            variants = [(target, optimize) for target in release.TARGETS
                        for optimize in release.OPTIMIZATIONS]
            self.assertEqual(len(variants), 10)
            for target, optimize in variants:
                with self.subTest(target=target, optimize=optimize):
                    archive = release.package(binary, target, root / "first", optimize)
                    prefix = release.archive_name(target, optimize) + "/"
                    executable = release.executable_name(target)
                    expected_names = [prefix + name for name in (executable, *release.DOCUMENTS)]
                    if archive.suffix == ".zip":
                        with zipfile.ZipFile(archive) as zipped:
                            self.assertEqual(zipped.namelist(), expected_names)
                            for member in zipped.infolist():
                                self.assertEqual(member.date_time, (1980, 1, 1, 0, 0, 0))
                                self.assertEqual(member.create_system, 3)
                                mode = 0o755 if member.filename == prefix + executable else 0o644
                                self.assertEqual(member.external_attr >> 16, 0o100000 | mode)
                                source = binary if member.filename == prefix + executable else ROOT / member.filename[len(prefix):]
                                self.assertEqual(zipped.read(member), source.read_bytes())
                    else:
                        with tarfile.open(archive) as tar:
                            members = tar.getmembers()
                            self.assertEqual([member.name for member in members], expected_names)
                            for member in members:
                                self.assertTrue(member.isfile())
                                self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 0))
                                self.assertEqual((member.uname, member.gname), ("", ""))
                                self.assertEqual(member.mode, 0o755 if member.name == prefix + executable else 0o644)
                                source = binary if member.name == prefix + executable else ROOT / member.name[len(prefix):]
                                self.assertEqual(tar.extractfile(member).read(), source.read_bytes())
                    os.utime(binary, (123456789, 123456789))
                    binary.chmod(0o600)
                    second = release.package(binary, target, root / "second", optimize)
                    self.assertEqual(archive.read_bytes(), second.read_bytes())
                    self.assertEqual(archive.with_suffix(archive.suffix + ".sha256").read_bytes(),
                                     f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n".encode("ascii"))

    def test_variant_names_preserve_fast_defaults(self):
        for target in release.TARGETS:
            with self.subTest(target=target):
                system, arch = release.TARGETS[target]
                base = f"nanocompile-{release.version()}-{system}-{arch}"
                extension = ".zip" if system == "windows" else ".tar.gz"
                self.assertEqual(release.archive_name(target), base)
                self.assertEqual(release.archive_name(target, "ReleaseFast"), base)
                self.assertEqual(release.archive_filename(target), base + extension)
                self.assertEqual(release.archive_filename(target, "ReleaseFast"), base + extension)
                self.assertEqual(release.archive_name(target, "ReleaseSafe"), base + "-release-safe")
                self.assertEqual(release.archive_filename(target, "ReleaseSafe"),
                                 base + "-release-safe" + extension)

    def test_verify_requires_complete_uncorrupted_release(self):
        selections = [("ReleaseFast",), ("ReleaseSafe",), release.OPTIMIZATIONS]
        for optimizations in selections:
            with self.subTest(optimizations=optimizations), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                binary = root / "nanocompile"
                binary.write_bytes(b"fixture")
                output = root / "dist"
                archives = [release.package(binary, target, output, optimize)
                            for target in release.TARGETS for optimize in optimizations]
                if optimizations == ("ReleaseFast",):
                    release.verify(output)  # The existing single-mode API remains valid.
                else:
                    release.verify(output, optimizations)
                expected_lines = [f"{release.checksum(archive)}  {archive.name}"
                                  for archive in sorted(archives)]
                self.assertEqual((output / "SHA256SUMS").read_text().splitlines(), expected_lines)
                (output / "SHA256SUMS").unlink()
                if len(optimizations) == 2:
                    with self.assertRaises(ValueError):
                        release.verify(output)  # Extra variants must not silently pass.
                for optimize in optimizations:
                    for target in ("aarch64-macos", "x86_64-windows-gnu"):
                        archive = output / release.archive_filename(target, optimize)
                        original = archive.read_bytes()
                        archive.write_bytes(original + b"corruption")
                        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                            release.verify(output, optimizations)
                        archive.write_bytes(original)
                unexpected = output / "private.log"
                unexpected.write_text("not a release asset")
                with self.assertRaises(ValueError):
                    release.verify(output, optimizations)
                unexpected.unlink()
                archive = archives[-1]
                checksum = archive.with_suffix(archive.suffix + ".sha256")
                checksum_bytes = checksum.read_bytes()
                checksum.unlink()
                with self.assertRaises(ValueError):
                    release.verify(output, optimizations)
                checksum.write_bytes(checksum_bytes)
                archive.unlink()
                with self.assertRaises(ValueError):
                    release.verify(output, optimizations)

    def test_smoke_archive_resolves_each_variant_and_shipped_worktree(self):
        for target in release.TARGETS:
            for optimize in release.OPTIMIZATIONS:
                with self.subTest(target=target, optimize=optimize), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    binary = root / "nanocompile"
                    binary.write_bytes(b"fixture")
                    release.package(binary, target, root / "dist", optimize)
                    with mock.patch(__name__ + ".smoke") as native_smoke, \
                            mock.patch(__name__ + ".subprocess.run",
                                       return_value=subprocess.CompletedProcess([], 0, stdout=b"usage:")), \
                            mock.patch.dict(sys.modules, {"windows_cache": mock.Mock()}):
                        smoke_archive(root / "dist")
                    args, kwargs = native_smoke.call_args
                    self.assertEqual(args[0].name, release.executable_name(target))
                    self.assertEqual(args[0].parent.name, release.archive_name(target, optimize))
                    self.assertEqual(kwargs, {"optimize": optimize, "target": target})

    def test_smoke_archive_rejects_missing_or_multiple_variants(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(AssertionError, "exactly one"):
                smoke_archive(root)
            binary = root / "fixture"
            binary.write_bytes(b"fixture")
            for optimize in release.OPTIMIZATIONS:
                release.package(binary, "aarch64-macos", root, optimize)
            with self.assertRaisesRegex(AssertionError, "exactly one"):
                smoke_archive(root)

    def test_build_info_requires_matching_variant_platform_and_zig(self):
        for target, (system, arch) in release.TARGETS.items():
            for optimize in release.OPTIMIZATIONS:
                with self.subTest(target=target, optimize=optimize):
                    info = {"optimize": optimize, "zig": "0.17.0", "os": system, "arch": arch}
                    check_build_info(info)
                    check_build_info(info, optimize, target)
                    for field, wrong in (("optimize", "Debug"), ("zig", "0.0.0"),
                                         ("os", "wrong"), ("arch", "wrong")):
                        with self.assertRaises(AssertionError):
                            check_build_info(dict(info, **{field: wrong}), optimize, target)
                    other = next(mode for mode in release.OPTIMIZATIONS if mode != optimize)
                    with self.assertRaises(AssertionError):
                        check_build_info(dict(info, optimize=other), optimize, target)


def check_build_info(info, optimize=None, target=None):
    assert info["optimize"] in release.OPTIMIZATIONS, "binary is not a supported release optimization"
    assert info["zig"] == "0.17.0", "binary Zig version differs from release toolchain"
    assert isinstance(info["os"], str) and isinstance(info["arch"], str)
    if optimize is not None:
        assert info["optimize"] == optimize, "binary optimization differs from archive filename"
    if target is not None:
        assert (info["os"], info["arch"]) == release.TARGETS[target], "binary platform differs from archive filename"


def smoke(binary, optimize=None, target=None):
    binary = str(Path(binary).resolve())
    with tempfile.TemporaryDirectory(prefix="nanocompile-release-") as temp:
        root = Path(temp)
        env = dict(os.environ, NANOCOMPILE_DIR=str(root / "cache"), NANOCOMPILE_TRACE="1")
        rustc = env.get("NANOCOMPILE_RUSTC") or shutil.which("rustc")
        assert rustc, "rustc must be installed or selected with NANOCOMPILE_RUSTC"
        env["NANOCOMPILE_RUSTC"] = rustc

        def run(args):
            return subprocess.run([binary, *args], cwd=root, env=env, capture_output=True, check=True, timeout=120)

        check_build_info(json.loads(run(["--build-info"]).stdout), optimize, target)
        expected = f"nanocompile {release.version()} (Zig 0.17.0)\n".encode()
        assert run(["--version"]).stdout == expected, "binary version differs from package version"
        assert b"Usage:" in run(["--help"]).stdout
        (root / "lib.rs").write_text("pub fn answer() -> u32 { 42 }\n")
        (root / "out").mkdir()
        args = ["rustc", "lib.rs", "--crate-name", "release_smoke", "--crate-type", "rlib",
                "--emit=dep-info,metadata,link", "--out-dir", "out", "-C", "opt-level=2"]
        first = run(args)
        assert b"nanocompile: miss" in first.stderr, first.stderr
        expected_outputs = {p.name: p.read_bytes() for p in (root / "out").iterdir()}
        assert any(name.endswith(".rlib") for name in expected_outputs)
        shutil.rmtree(root / "out")
        (root / "out").mkdir()
        second = run(args)
        assert b"nanocompile: hit" in second.stderr, second.stderr
        assert expected_outputs == {p.name: p.read_bytes() for p in (root / "out").iterdir()}
        (root / "lib.rs").write_text("pub fn answer() -> u32 { 43 }\n")
        changed = run(args)
        assert b"nanocompile: miss" in changed.stderr, changed.stderr
        changed_outputs = {p.name: p.read_bytes() for p in (root / "out").iterdir()}
        assert changed_outputs != expected_outputs, "edited source restored stale artifacts"
        run(["clear"])
        shutil.rmtree(root / "out")
        (root / "out").mkdir()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: run(args), range(4)))
        assert sum(b"nanocompile: miss" in result.stderr for result in results) == 1
        assert sum(b"nanocompile: hit" in result.stderr for result in results) == 3
        assert changed_outputs == {p.name: p.read_bytes() for p in (root / "out").iterdir()}
    print("release build info, version, CLI, Rust restore, edited-input miss and concurrent locking smoke passed")


def smoke_archive(directory):
    directory = Path(directory)
    archives = [(directory / release.archive_filename(target, optimize), target, optimize)
                for target in release.TARGETS for optimize in release.OPTIMIZATIONS
                if (directory / release.archive_filename(target, optimize)).is_file()]
    assert len(archives) == 1, "native smoke requires exactly one platform/optimization archive"
    archive, target, optimize = archives[0]
    expected_checksum = f"{release.checksum(archive)}  {archive.name}\n".encode("ascii")
    assert archive.with_suffix(archive.suffix + ".sha256").read_bytes() == expected_checksum
    prefix = release.archive_name(target, optimize) + "/"
    executable = release.executable_name(target)
    expected_names = [prefix + name for name in (executable, *release.DOCUMENTS)]
    with tempfile.TemporaryDirectory(prefix="nanocompile-extracted-") as temp:
        root = Path(temp)
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as zipped:
                assert zipped.namelist() == expected_names, "unexpected archive members"
                contents = {name: zipped.read(name) for name in expected_names}
        else:
            with tarfile.open(archive) as tar:
                assert [member.name for member in tar.getmembers()] == expected_names
                assert all(member.isfile() for member in tar.getmembers())
                contents = {name: tar.extractfile(name).read() for name in expected_names}
        # Write only the validated allowlist, never arbitrary archive paths.
        for name, data in contents.items():
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        binary = root / prefix / executable
        binary.chmod(0o755)
        smoke(binary, optimize=optimize, target=target)
        if os.name == "posix" and release.TARGETS[target][0] != "windows":
            result = subprocess.run([str(binary), "worktree", "--help"],
                                    cwd=root, env=dict(os.environ, NANOCOMPILE_PYTHON=sys.executable),
                                    capture_output=True, check=True, timeout=30)
            assert b"usage:" in result.stdout, "shipped worktree frontend --help failed"
        if target == "x86_64-windows-gnu":
            from windows_cache import smoke as windows_smoke
            windows_smoke(binary)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke":
        smoke(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "--smoke-archive":
        smoke_archive(sys.argv[2])
    else:
        unittest.main()
