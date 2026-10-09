"""Rotate two binaries over identical cold entries with warm toolchain/reader memos."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    p.add_argument('candidate', type=Path)
    p.add_argument('--runs', type=int, default=9)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    assert args.runs > 0
    binaries = {name: getattr(args, name).resolve() for name in ('baseline', 'candidate')}
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
           and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTC_BOOTSTRAP')}
    env['RUSTUP_TOOLCHAIN'] = '1.97.1'
    rows = []
    with tempfile.TemporaryDirectory(prefix='nano-postcompile-hashes-') as tmp:
        root = Path(tmp)
        for name in ('deps', 'out'):
            (root / name).mkdir()
        env.update(NANOCOMPILE_DIR=str(root / 'cache'), NANOCOMPILE_TRACE='1')

        def run(command):
            result = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=180)
            assert result.returncode == 0, result.stderr.decode(errors='replace')
            return result

        payload_bytes = 8 * 1024 * 1024
        (root / 'payload.bin').write_bytes(bytes(range(256)) * (payload_bytes // 256))
        externs = []
        for i in range(8):
            name = f'dep{i}'
            (root / (name + '.rs')).write_text('pub const PAYLOAD: &[u8] = include_bytes!("payload.bin");\n')
            run(['rustc', name + '.rs', '--crate-name', name, '--crate-type', 'rlib',
                 '--emit=metadata,link', '--out-dir', 'deps'])
            externs += ['--extern', name + '=deps/lib' + name + '.rmeta']
        (root / 'top.rs').write_text('pub fn lengths()->[usize;8] {[' +
                                    ','.join(f'dep{i}::PAYLOAD.len()' for i in range(8)) + ']}\n')
        command = ['rustc', 'top.rs', '--crate-name', 'top', '--crate-type', 'rlib',
                   '--emit=dep-info,metadata,link', '--out-dir', 'out', '-Ldependency=deps', *externs]
        run(command)
        reference = {p.name: sha(p) for p in (root / 'out').iterdir()}
        manifest_reference = None

        def cold(name, measured):
            nonlocal manifest_reference
            shutil.rmtree(root / 'cache/entries', ignore_errors=True)
            for path in (root / 'out').iterdir():
                path.unlink()
            start = time.perf_counter()
            result = run([str(binaries[name]), *command])
            elapsed = time.perf_counter() - start
            assert b'miss: compiling' in result.stderr and b'uncached:' not in result.stderr, result.stderr.decode()
            assert {p.name: sha(p) for p in (root / 'out').iterdir()} == reference
            manifests = list((root / 'cache/entries').iterdir())
            assert len(manifests) == 1
            manifest = json.loads(manifests[0].read_text().split('\n', 1)[1])
            if manifest_reference is None:
                manifest_reference = manifest
            assert manifest == manifest_reference
            if measured:
                rows.append({'implementation': name, 'seconds': elapsed})
        for name in binaries:
            cold(name, False)
        for i in range(args.runs):
            for name in (('baseline', 'candidate') if i % 2 == 0 else ('candidate', 'baseline')):
                cold(name, True)
        for name in binaries:
            for path in (root / 'out').iterdir():
                path.unlink()
            result = run([str(binaries[name]), *command])
            assert b'nanocompile: hit' in result.stderr, result.stderr.decode()
            assert {p.name: sha(p) for p in (root / 'out').iterdir()} == reference
        evidence = {
            'method': 'rotating two-binary cold entry compilation; identical arguments, environment and paths; toolchain and metadata reader memos primed; output/manifest bytes compared after every run',
            'rustc': run(['rustc', '-vV']).stdout.decode().strip(),
            'binary_sha256': {name: sha(path) for name, path in binaries.items()},
            'script_sha256': sha(Path(__file__)), 'runs_per_binary': args.runs,
            'explicit_metadata_files': 8,
            'explicit_metadata_bytes': sum(p.stat().st_size for p in (root / 'deps').glob('*.rmeta')),
            'samples': rows,
            'median_seconds': {name: statistics.median(r['seconds'] for r in rows if r['implementation'] == name)
                               for name in binaries},
            'all_outputs_and_manifests_equal': True, 'both_binaries_restore_same_entry': True,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(evidence['median_seconds']))


if __name__ == '__main__':
    main()
