#!/usr/bin/env python3
"""Install a native, revision-pinned executable from a trusted cache or source.

Cache checksums detect corruption, NOT malicious writers. Only restore this
cache from the same trust domain as the source and toolchain you execute.
Python 3.9+, standard library only. No downloads or implicit latest versions.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
ZIG_VERSION = "0.17.0"
SCHEMA = 1
OVERRIDES = (
    "ZIG_LIB_DIR", "ZIG_LIBC", "ZIG_LOCAL_PKG_DIR", "CC", "CXX", "PKG_CONFIG",
    "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "LIBRARY_PATH", "CPATH",
    "NIX_CFLAGS_COMPILE", "NIX_CFLAGS_LINK", "NIX_LDFLAGS",
)


def run(command, **kwargs):
    try:
        return subprocess.run([str(arg) for arg in command], check=True, **kwargs)
    except subprocess.CalledProcessError as error:
        # Captured compiler/setup diagnostics must not disappear behind only
        # CalledProcessError's command and exit code (also used by the fixture).
        diagnostic = error.stderr or error.stdout
        if diagnostic:
            if isinstance(diagnostic, bytes):
                diagnostic = diagnostic.decode("utf-8", errors="replace")
            print(diagnostic.rstrip(), file=sys.stderr)
        raise


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_digest(paths):
    """Hash names and bytes, not mtimes; include symlink targets and their bytes.

    Each supplied label is portable. Installed SDKs have cycles/aliases, so
    traverse each resolved directory once, recording all link spellings.
    """
    digest = hashlib.sha256()
    visited = set()

    def record(value):
        data = value.encode("utf-8")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)

    def visit(path, label):
        record(label)
        if path.is_symlink():
            record("link:" + os.readlink(path))
        if path.is_dir():
            real = path.resolve()
            record("directory")
            if real in visited:
                record("visited")
                return
            visited.add(real)
            for child in sorted(path.iterdir()):
                visit(child, label + "/" + child.name)
        elif path.is_file():
            record(checksum(path))
        elif path.is_symlink() and not path.exists():
            record("dangling")
        else:
            raise ValueError("unsupported input type: " + label)

    for label, path in sorted(paths):
        visit(Path(path), label)
    return digest.hexdigest()


def host_identity():
    machine = platform.machine().lower()
    arch = {"arm64": "aarch64", "amd64": "x86_64"}.get(machine, machine)
    system = {"Darwin": "macos", "Linux": "linux-musl",
              "Windows": "windows-gnu"}.get(platform.system())
    target = arch + "-" + str(system)
    if target not in ("aarch64-macos", "x86_64-macos", "aarch64-linux-musl",
                      "x86_64-linux-musl", "x86_64-windows-gnu"):
        raise ValueError("unsupported native platform")
    return {"target": target, "os_release": platform.release(),
            "os_version": platform.version()}


def cache_key(identity):
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return "nanocompile-setup-v1-" + hashlib.sha256(payload).hexdigest()


def plan(root, revision, zig_name):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("--revision must be a full lowercase 40-character Git commit")
    actual = run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                 text=True).stdout.strip()
    if actual != revision:
        raise ValueError("checkout HEAD does not match --revision")
    for name in OVERRIDES:
        if os.environ.get(name):
            raise ValueError("unsupported build override: " + name)
    zig = shutil.which(zig_name)
    if not zig:
        raise ValueError("Zig executable not found")
    version = run([zig, "version"], capture_output=True, text=True).stdout.strip()
    if version != ZIG_VERSION:
        raise ValueError("setup requires Zig " + ZIG_VERSION)
    info = run([zig, "env"], capture_output=True, text=True).stdout
    paths = {}
    for name in ("zig_exe", "lib_dir"):
        match = re.search(r'\.' + name + r'\s*=\s*("(?:[^"\\]|\\.)*")', info)
        if not match:
            raise ValueError("zig env omitted " + name)
        paths[name] = Path(json.loads(match.group(1))).resolve(strict=True)
    host = host_identity()
    resources = list(paths.items())
    sdk = None
    if host["target"].endswith("-macos"):
        sdk = Path(os.environ.get("SDKROOT") or run(
            ["xcrun", "--sdk", "macosx", "--show-sdk-path"],
            capture_output=True, text=True).stdout.strip()).resolve(strict=True)
        resources.append(("sdk", sdk))
    match = re.search(r'\.version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"',
                      (root / "build.zig.zon").read_text())
    if not match:
        raise ValueError("missing numeric package version")
    identity = {
        "schema": SCHEMA, "revision": revision, "host": host,
        "source_sha256": tree_digest([(name, root / name) for name in
                                      ("build.zig", "build.zig.zon", "src")]),
        "setup_sha256": checksum(Path(__file__)),
        "toolchain_sha256": tree_digest(resources), "zig_version": version,
        "version": match.group(1), "optimize": "ReleaseFast",
    }
    return identity, paths["zig_exe"], sdk


def compatible(binary, identity):
    expected = "nanocompile {} (Zig {})\n".format(identity["version"], ZIG_VERSION)
    result = run([binary, "--version"], capture_output=True, text=True, timeout=30)
    if result.stdout != expected:
        raise ValueError("executable version mismatch")
    result = run([binary, "--help"], capture_output=True, text=True, timeout=30)
    if "Usage:" not in result.stdout:
        raise ValueError("executable help check failed")


def restore(entry, staging, identity):
    """Verify the copied bytes BEFORE executing; never trust an entry's paths."""
    manifest = json.loads((entry / "manifest.json").read_text())
    if manifest.get("identity") != identity:
        raise ValueError("cache identity mismatch")
    shutil.copyfile(entry / staging.name, staging)
    if checksum(staging) != manifest.get("sha256"):
        raise ValueError("cache executable checksum mismatch")
    staging.chmod(0o755)
    compatible(staging, identity)


def save(entry, binary, identity):
    entry.mkdir(parents=True, exist_ok=True)
    # Atomic files, manifest last. Concurrent writes can cause a rejected entry,
    # never an unchecked executable. Use separate prefixes for parallel callers.
    with tempfile.TemporaryDirectory(prefix=".write-", dir=entry.parent) as temp:
        temp = Path(temp)
        shutil.copyfile(binary, temp / binary.name)
        manifest = {"identity": identity, "sha256": checksum(temp / binary.name)}
        (temp / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
        os.replace(str(temp / binary.name), str(entry / binary.name))
        os.replace(str(temp / "manifest.json"), str(entry / "manifest.json"))


def install(root, args):
    started = time.perf_counter()
    identity, zig, sdk = plan(root, args.revision, args.zig)
    key = cache_key(identity)
    if args.key_only:
        print(key)
        return None
    identity_seconds = time.perf_counter() - started
    cache = args.cache_dir.resolve()
    prefix = args.prefix.resolve()
    prefix.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    entry = cache / key
    name = "nanocompile.exe" if identity["host"]["target"].endswith("windows-gnu") else "nanocompile"
    output = prefix / "bin" / name
    output.parent.mkdir(parents=True, exist_ok=True)
    status = "miss"
    build_seconds = 0.0
    with tempfile.TemporaryDirectory(prefix=".setup-", dir=prefix) as temp:
        work = Path(temp)
        staged = work / name
        if entry.exists():
            try:
                restore(entry, staged, identity)
                status = "hit"
            except (OSError, ValueError, TypeError, AttributeError,
                    subprocess.SubprocessError):
                # Do not print arbitrary cache-provided text or host paths.
                print("setup: rejected cache entry; building pinned source", file=sys.stderr)
                status = "rejected"
        if status != "hit":
            command = [zig, "build", "-Doptimize=ReleaseFast",
                       "-Dtarget=" + identity["host"]["target"],
                       "--prefix", work / "build", "--cache-dir", work / "zig-local"]
            if sdk:
                command += ["--sysroot", sdk]
            before = time.perf_counter()
            # Private caches ensure neither another job nor the normal zig-out
            # is read/written. No hidden incremental build in cold measurements.
            build_env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(work / "zig-global"))
            run(command, cwd=root, env=build_env, stdout=sys.stderr)
            build_seconds = time.perf_counter() - before
            shutil.copyfile(work / "build" / "bin" / name, staged)
            staged.chmod(0o755)
            compatible(staged, identity)
            save(entry, staged, identity)
        digest = checksum(staged)
        os.replace(str(staged), str(output))
    result = {"schema": SCHEMA, "cache_status": status, "key": key,
              "target": identity["host"]["target"], "sha256": digest,
              "identity_seconds": identity_seconds, "build_seconds": build_seconds,
              "setup_seconds": time.perf_counter() - started}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--zig", default="zig")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".zig-cache" / "ci-setup")
    parser.add_argument("--prefix", type=Path, default=ROOT / ".zig-cache" / "ci-setup-install")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--key-only", action="store_true")
    parser.add_argument("--clean-env", action="store_true",
                        help="ignore compiler/library overrides for this process and its children")
    args = parser.parse_args()
    if args.clean_env:
        for name in OVERRIDES:
            if os.environ.pop(name, None):
                print("setup: ignoring " + name + " for this invocation", file=sys.stderr)
    try:
        install(ROOT, args)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print("setup: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
