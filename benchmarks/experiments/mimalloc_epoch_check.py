"""Check native mimalloc reproducibility with an explicit build timestamp."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--epoch', required=True, type=int)
p.add_argument('--output', required=True, type=Path)
args = p.parse_args()
assert args.epoch >= 0
env = {k: v for k, v in os.environ.items()
       if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
       and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER')}
env.update(RUSTUP_TOOLCHAIN='1.97.1', SOURCE_DATE_EPOCH=str(args.epoch))
samples = []
with tempfile.TemporaryDirectory(prefix='nano mimalloc epoch ') as temp:
    root = Path(temp)
    (root / 'src').mkdir()
    (root / 'src/lib.rs').write_text('pub use libmimalloc_sys::*;\n')
    (root / 'Cargo.toml').write_text(
        '[package]\nname="nano-mimalloc-epoch"\nversion="0.1.0"\nedition="2024"\n'
        '[dependencies]\nlibmimalloc-sys={version="=0.1.49",default-features=false,features=["v2"]}\n')
    env['CARGO_TARGET_DIR'] = str(root / 'target')
    for number in range(2):
        shutil.rmtree(root / 'target', ignore_errors=True)
        result = subprocess.run(['cargo', 'build', '--release', '--offline'],
                                cwd=root, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        files = [path for path in (root / 'target').rglob('*') if path.is_file()
                 and ('static.o' in path.name or path.name == 'libmimalloc.a'
                      or (path.suffix == '.rlib' and path.name.startswith('liblibmimalloc_sys')))]
        row = {str(path.relative_to(root / 'target')):
               hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
        assert len(row) == 3, row
        samples.append(row)
        if number == 0:
            time.sleep(2)
    assert samples[0] == samples[1], samples
args.output.write_text(json.dumps({
    'source_date_epoch': str(args.epoch), 'features': ['v2'],
    'method': 'Two empty-target real mimalloc builds at identical paths, separated wall times; native object/archive and Rust library hashes must match.',
    'samples': samples,
}, indent=2) + '\n')
print('PASS: fixed-epoch mimalloc object, archive and Rust library byte equality')
