"""Install stable Zig 0.17.0 using the official archive's SHA-256."""
import hashlib
import os
from pathlib import Path
import platform
import subprocess
import sys
import urllib.request
import zipfile

ARCHIVES = {
    "x86_64-linux": "1cbe9df9f27e6b78d14ccbca43b6703a404ef79ef1c463de901d7f088d4e2026",
    "aarch64-macos": "b607e9b9234790a008116ae5bdb71c6243b84b9fb42a53a9e70fde41c06c536a",
    "x86_64-macos": "4f9a1c5269aa17ebda5e6d3c2b89d6cbf36f7d2b22a0306e9ab98f25f95529c6",
    "x86_64-windows": "b5663f69581dcf391293fbf16c06cb80d81d806545ce618b4d0bab7f0eb8c428",
}
machine = platform.machine().lower()
arch = {"arm64": "aarch64", "amd64": "x86_64"}.get(machine, machine)
key = arch + "-" + {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}[platform.system()]
name = "zig-" + key + "-0.17.0"
destination = Path(sys.argv[1]).resolve()
destination.mkdir(parents=True, exist_ok=True)
archive = destination / (name + (".zip" if key.endswith("-windows") else ".tar.xz"))
urllib.request.urlretrieve("https://ziglang.org/download/0.17.0/" + archive.name, archive)
assert hashlib.sha256(archive.read_bytes()).hexdigest() == ARCHIVES[key], "Zig checksum mismatch"
if key.endswith("-windows"):
    with zipfile.ZipFile(archive) as source:
        source.extractall(destination)
else:
    subprocess.run(["tar", "-xf", str(archive), "-C", str(destination)], check=True)
binary_dir = destination / name
binary = "zig.exe" if key.endswith("-windows") else "zig"
subprocess.run([str(binary_dir / binary), "version"], check=True)
if "GITHUB_PATH" in os.environ:
    with open(os.environ["GITHUB_PATH"], "a") as f:
        f.write(str(binary_dir) + "\n")
