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
DOCUMENTS = ("LICENSE", "NOTICE", "README.md", "docs/releases.md")


def version():
    match = re.search(r'\.version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"',
                      (ROOT / "build.zig.zon").read_text())
    if match is None:
        raise ValueError("build.zig.zon must contain a numeric release version")
    return match.group(1)


def archive_name(target):
    system, arch = TARGETS[target]
    return f"nanocompile-{version()}-{system}-{arch}"


def archive_filename(target):
    extension = ".zip" if target == "x86_64-windows-gnu" else ".tar.gz"
    return archive_name(target) + extension


def executable_name(target):
    return "nanocompile.exe" if target == "x86_64-windows-gnu" else "nanocompile"


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package(binary, target, output):
    name = archive_name(target)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / archive_filename(target)
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


def verify(directory):
    archives = {archive_filename(target) for target in TARGETS}
    expected = archives | {name + ".sha256" for name in archives}
    if {path.name for path in directory.iterdir()} != expected:
        raise ValueError("release must contain exactly all five archives and their checksums")
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
    check = commands.add_parser("verify")
    check.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.command == "version":
        print(version())
    elif args.command == "package":
        print(package(args.binary, args.target, args.output))
    else:
        verify(args.directory)


if __name__ == "__main__":
    main()
