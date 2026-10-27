"""Create unsigned, metadata-normalized release archives using only the standard library."""
import argparse
import gzip
import hashlib
import io
from pathlib import Path
import re
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "aarch64-macos": ("macos", "aarch64"),
    "x86_64-macos": ("macos", "x86_64"),
    "x86_64-linux-musl": ("linux", "x86_64"),
    "aarch64-linux-musl": ("linux", "aarch64"),
    "x86_64-windows-gnu": ("windows", "x86_64"),
}
# Explicit ancillary files, including the optional Python worktree frontend.
DOCUMENTS = ("LICENSE", "NOTICE", "README.md", "docs/releases.md", "docs/worktrees.md", "docs/cache-limits.md",
             "tools/worktree.py", "tools/worktree_setup.py", "tools/nextjs_cache.py")


def version():
    match = re.search(r'\.version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"',
                      (ROOT / "build.zig.zon").read_text())
    if match is None:
        raise ValueError("build.zig.zon must contain a numeric release version")
    return match.group(1)


OPTIMIZATIONS = ("ReleaseFast", "ReleaseSafe")


def archive_name(target, optimize="ReleaseFast"):
    if optimize not in OPTIMIZATIONS:
        raise ValueError(f"unsupported optimization: {optimize}")
    system, arch = TARGETS[target]
    suffix = "-release-safe" if optimize == "ReleaseSafe" else ""
    return f"nanocompile-{version()}-{system}-{arch}{suffix}"


def archive_filename(target, optimize="ReleaseFast"):
    extension = ".zip" if target == "x86_64-windows-gnu" else ".tar.gz"
    return archive_name(target, optimize) + extension


def executable_name(target):
    return "nanocompile.exe" if target == "x86_64-windows-gnu" else "nanocompile"


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package(binary, target, output, optimize="ReleaseFast"):
    name = archive_name(target, optimize)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / archive_filename(target, optimize)
    # Explicit members and metadata keep caches, logs and host identities out.
    members = [(executable_name(target), binary, 0o755)]
    members.extend((name, ROOT / name, 0o644) for name in DOCUMENTS)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zipped:
            for member, source, mode in members:
                info = zipfile.ZipInfo(name + "/" + member, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (0o100000 | mode) << 16
                zipped.writestr(info, source.read_bytes())
    else:
        with archive.open("wb") as destination:
            with gzip.GzipFile(filename="", mode="wb", fileobj=destination, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as tar:
                    for member, source, mode in members:
                        data = source.read_bytes()
                        info = tarfile.TarInfo(name + "/" + member)
                        info.size = len(data)
                        info.mode = mode
                        tar.addfile(info, io.BytesIO(data))
    archive.with_suffix(archive.suffix + ".sha256").write_bytes(
        f"{checksum(archive)}  {archive.name}\n".encode("ascii"))
    return archive


def verify(directory, optimizations=("ReleaseFast",)):
    if not optimizations or len(set(optimizations)) != len(optimizations):
        raise ValueError("select at least one distinct optimization mode")
    archives = {archive_filename(target, optimize)
                for target in TARGETS for optimize in optimizations}
    expected = archives | {name + ".sha256" for name in archives}
    if {path.name for path in directory.iterdir()} != expected:
        raise ValueError(f"release must contain exactly all {len(archives)} archives and their checksums")
    lines = []
    for name in sorted(archives):
        archive = directory / name
        line = f"{checksum(archive)}  {archive.name}\n"
        if archive.with_suffix(archive.suffix + ".sha256").read_text() != line:
            raise ValueError(f"checksum mismatch: {archive.name}")
        lines.append(line)
    (directory / "SHA256SUMS").write_bytes("".join(lines).encode("ascii"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("version")
    create = commands.add_parser("package")
    create.add_argument("--binary", type=Path, required=True)
    create.add_argument("--target", choices=TARGETS, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--optimize", choices=OPTIMIZATIONS, default="ReleaseFast")
    check = commands.add_parser("verify")
    check.add_argument("directory", type=Path)
    modes = check.add_mutually_exclusive_group()
    modes.add_argument("--optimize", choices=OPTIMIZATIONS, default="ReleaseFast")
    modes.add_argument("--all-modes", action="store_true")
    args = parser.parse_args()
    if args.command == "version":
        print(version())
    elif args.command == "package":
        print(package(args.binary, args.target, args.output, args.optimize))
    else:
        verify(args.directory, OPTIMIZATIONS if args.all_modes else (args.optimize,))


if __name__ == "__main__":
    main()
