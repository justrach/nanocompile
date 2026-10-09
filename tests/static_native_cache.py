"""Real bundled static archive restore and native search invalidation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary', type=Path)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    binary = args.binary.resolve()
    with tempfile.TemporaryDirectory(prefix='nano static native, ') as tmp:
        root = Path(tmp).resolve()
        for name in ('src', 'out', 'preferred', 'fallback'):
            (root / name).mkdir()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
               and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTC_BOOTSTRAP')}
        env.update(RUSTUP_TOOLCHAIN='1.97.1', NANOCOMPILE_DIR=str(root / 'cache'), NANOCOMPILE_TRACE='1')
        cc = shutil.which('cc')
        assert cc
        def run(command, success=True):
            r = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=180)
            assert (r.returncode == 0) == success, r.stderr.decode(errors='replace')
            return r
        def archive(where, value):
            (root / 'native.c').write_text(f'unsigned value(void) {{return {value};}}\n')
            run([cc, '-fPIC', '-c', 'native.c', '-o', 'native.o'])
            path = root / where / 'libprobe.a'
            path.unlink(missing_ok=True)
            run(['ar', 'crs', str(path), 'native.o'])
        archive('fallback', 12)
        (root / 'src' / 'lib.rs').write_text('extern "C" {fn value()->u32;} pub fn answer()->u32 {unsafe{value()}}\n')
        (root / 'src' / 'main.rs').write_text('fn main(){println!("{}",native_cache::answer());}\n')
        rust = ['rustc', '--edition=2021', 'src/lib.rs', '--crate-name', 'native_cache',
                '--crate-type', 'rlib', '--emit=dep-info,metadata,link', '--out-dir', 'out',
                '-L', 'native=preferred', '-L', 'native=fallback', '-l', 'static=probe']
        outputs = [root / 'out' / x for x in ('libnative_cache.rlib', 'libnative_cache.rmeta', 'native_cache.d')]
        def hashes():
            return [hashlib.sha256(p.read_bytes()).hexdigest() for p in outputs]
        def remove():
            for p in outputs: p.unlink(missing_ok=True)
        def consume(value):
            run(['rustc', '--edition=2021', 'src/main.rs', '--extern', 'native_cache=' + str(outputs[0]), '-o', 'consumer'])
            assert run([str(root / 'consumer')]).stdout == str(value).encode() + b'\n'
        run(rust)
        reference = hashes()
        consume(12)
        remove()
        cold = run([str(binary), *rust])
        assert b'miss: compiling' in cold.stderr and hashes() == reference, cold.stderr.decode()
        remove()
        warm = run([str(binary), *rust])
        assert b'nanocompile: hit' in warm.stderr and hashes() == reference, warm.stderr.decode()
        consume(12)
        path = root / 'fallback' / 'libprobe.a'
        stamp = path.stat()
        archive('fallback', 13)
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        remove()
        changed = run([str(binary), *rust])
        assert b'nanocompile: hit' not in changed.stderr
        consume(13)
        archive('preferred', 14)
        remove()
        preferred = run([str(binary), *rust])
        assert b'nanocompile: hit' not in preferred.stderr
        consume(14)
        remove()
        assert b'nanocompile: hit' in run([str(binary), *rust]).stderr
        consume(14)
        # Non-bundled/renamed/verbatim and dynamic variants retain fallback.
        for flag in ('static:-bundle=probe', 'static:+verbatim=libprobe.a', 'static=probe:renamed', 'dylib=probe'):
            command = [str(binary), *rust[:-2], '-l', flag]
            r = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=180)
            assert b'bypass: UnsupportedNativeLibrary' in r.stderr, r.stderr.decode()
        (root / 'preferred' / 'libprobe.a').unlink()
        (root / 'fallback' / 'libprobe.a').unlink()
        missing = run([str(binary), *rust], success=False)
        assert b'bypass: UntrackedNativeLibrary' in missing.stderr
        (root / 'preferred' / 'libprobe.a').write_bytes(b'!<thin>\n')
        direct_thin = subprocess.run(rust, cwd=root, env=env, capture_output=True, timeout=180)
        thin = subprocess.run([str(binary), *rust], cwd=root, env=env, capture_output=True, timeout=180)
        assert thin.returncode == direct_thin.returncode and b'ThinNativeArchive' in thin.stderr
        evidence = {'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                    'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'direct_cold_warm_artifacts_equal': True, 'loaded_values': [12, 12, 13, 14, 14],
                    'preserved_mtime_archive_change_detected': True,
                    'new_preferred_candidate_detected': True,
                    'unsupported_forms_missing_and_thin_bypass': True}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print('PASS: static archive restore, executable behavior, native contents and search invalidation')


if __name__ == '__main__':
    main()
