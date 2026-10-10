"""Preserve the last valid benchmark report when storage fails."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


def save_report(path, result):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=path.parent, prefix='.' + path.name + '.',
                                         delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(result, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_failure(path, result):
    """Keep the original exception if even its report cannot be saved."""
    try:
        save_report(path, result)
    except OSError as error:
        print(f'Cannot save failure report: {error}; prior report preserved. '
              f'Build failure: {result.get("failure")}', file=sys.stderr, flush=True)


def require_space(path, minimum_gib):
    path = Path(path).resolve()
    while not path.exists():
        path = path.parent
    available = shutil.disk_usage(path).free
    minimum = int(minimum_gib * 1024**3)
    if available < minimum:
        raise OSError(f'Insufficient benchmark storage at {path}: '
                      f'{available / 1024**3:.2f} GiB free; '
                      f'{minimum_gib:g} GiB required before starting a build')
    return available
