"""Install the checksum-pinned kache 1.0.0 benchmark reference."""
import argparse
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import platform
import tarfile
import urllib.request

CHECKSUMS = {
    'aarch64-apple-darwin': '6d1be0079d0689a85fa04b7fed7eaa94f7e08259cafb8bd361a5c25c4c98c4a3',
    'x86_64-apple-darwin': 'ae0792b17e1c5f2438b39be888896c20aaf006bef5959c44fa3bc5bc66d93b5b',
    'aarch64-unknown-linux-musl': '88abd848be7d300d4e30b8510ebdc45990dae3f96b6591e3498209639cf34701',
    'x86_64-unknown-linux-musl': '756e9701a6afb8354fd8b1d76164e13272d320354d84f01197e57d8a3b4be397',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    args = parser.parse_args()
    arch = {'arm64': 'aarch64', 'aarch64': 'aarch64', 'x86_64': 'x86_64'}.get(platform.machine())
    system = {'Darwin': 'apple-darwin', 'Linux': 'unknown-linux-musl'}.get(platform.system())
    target = f'{arch}-{system}'
    if target not in CHECKSUMS:
        parser.error('No pinned reference binary for this platform')
    url = f'https://github.com/kunobi-ninja/kache/releases/download/v1.0.0/kache-{target}.tar.gz'
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != CHECKSUMS[target]:
        raise RuntimeError('kache release checksum mismatch')
    root = Path(args.directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = [m for m in archive.getmembers() if PurePosixPath(m.name).name == 'kache' and m.isfile()]
        if len(members) != 1:
            raise RuntimeError('Unexpected kache archive contents')
        temporary = root / '.kache-download'
        temporary.write_bytes(archive.extractfile(members[0]).read())
        temporary.chmod(0o755)
        temporary.replace(root / 'kache')
    if os.environ.get('GITHUB_PATH'):
        with open(os.environ['GITHUB_PATH'], 'a') as output:
            output.write(str(root) + '\n')
    print(root / 'kache')


if __name__ == '__main__':
    main()
