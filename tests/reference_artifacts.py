"""Private byte snapshots for benchmark artifact mismatch diagnosis."""
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def relative(name):
    path = Path(name)
    if path.is_absolute() or not path.parts or '..' in path.parts:
        raise ValueError('Invalid reference artifact path')
    return path


def retain(target, destination, artifacts):
    """Copy independently; target mutation must never alter reference bytes."""
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, expected in artifacts.items():
        path = relative(name)
        copied = destination / path
        copied.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copy2(target / path, copied)
        if digest(copied) != expected:
            raise ValueError('Artifact changed before reference retention: ' + name)
    manifest = destination / 'manifest.json'
    manifest.write_text(json.dumps({'schema': 1, 'files': artifacts}, indent=2) + '\n')
    manifest.chmod(0o600)
    return manifest


def verify(destination):
    manifest = json.loads((destination / 'manifest.json').read_text())
    if manifest['schema'] != 1:
        raise ValueError('Unsupported reference manifest')
    for name, expected in manifest['files'].items():
        path = destination / relative(name)
        if path.is_symlink() or digest(path) != expected:
            raise ValueError('Reference artifact mismatch: ' + name)
    return len(manifest['files'])
