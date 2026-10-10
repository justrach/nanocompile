"""Explicit common bindgen tool selection for benchmark implementations."""
import json
import hashlib
from pathlib import Path


def load(path):
    raw = Path(path).read_bytes()
    values = json.loads(raw)
    if not isinstance(values, dict) or set(values) != {'LIBCLANG_PATH', 'CLANG_PATH', 'RUSTFMT'}:
        raise ValueError('Bindgen tools must select exactly LIBCLANG_PATH, CLANG_PATH and RUSTFMT')
    for name, value in values.items():
        if not isinstance(value, str) or not Path(value).is_absolute() or not Path(value).is_file():
            raise ValueError('Bindgen tool selection must name an existing absolute file: '+name)
    return values, hashlib.sha256(raw).hexdigest()
