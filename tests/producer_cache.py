"""Real opt-in macro cache restores, native/source invalidation and corruption."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary', type=Path)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    binary = args.binary.resolve()
    if sys.platform != 'darwin':
        print('SKIP: experimental producer integration currently requires Apple tools')
        return
    with tempfile.TemporaryDirectory(prefix='nano macro cache, ') as tmp:
        root = Path(tmp).resolve()
        for name in ('src', 'out', 'native'):
            (root / name).mkdir()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
               and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTC_BOOTSTRAP')}
        env.update(RUSTUP_TOOLCHAIN='1.97.1', NANOCOMPILE_DIR=str(root / 'cache'),
                   NANOCOMPILE_TRACE='1', NANOCOMPILE_PROC_MACRO_PRODUCERS='1')
        cc = shutil.which('cc')
        assert cc
        def run(command, success=True):
            r = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=180)
            assert (r.returncode == 0) == success, r.stderr.decode(errors='replace')
            return r
        def archive(value):
            (root / 'native.c').write_text(f'unsigned value(void) {{return {value};}}\n')
            run([cc, '-fPIC', '-c', 'native.c', '-o', 'native.o'])
            path = root / 'native' / 'libprobe.a'
            path.unlink(missing_ok=True)
            run(['ar', 'crs', str(path), 'native.o'])
        archive(12)
        macro = root / 'src' / 'producer.rs'
        source = ('extern crate proc_macro;\n#[link(name="probe",kind="static")] '
                  'extern "C" {fn value()->u32;}\n#[proc_macro] '
                  'pub fn answer(_:proc_macro::TokenStream)->proc_macro::TokenStream '
                  '{unsafe{value()}.to_string().parse().unwrap()}\n')
        macro.write_text(source)
        (root / 'src' / 'consumer.rs').write_text('fn main(){println!("{}",cache_macro::answer!());}\n')
        rust = ['rustc', '--edition=2021', 'src/producer.rs', '--crate-name', 'cache_macro',
                '--crate-type', 'proc-macro', '--emit=dep-info,link', '--out-dir', 'out',
                '-C', 'opt-level=3', '-L', 'native=native', '--extern', 'proc_macro',
                '--error-format=json', '--json=artifacts']
        dylib = root / 'out' / 'libcache_macro.dylib'
        dep_info = root / 'out' / 'cache_macro.d'
        def hashes():
            return [hashlib.sha256(p.read_bytes()).hexdigest() for p in (dylib, dep_info)]
        def remove():
            dylib.unlink(missing_ok=True)
            dep_info.unlink(missing_ok=True)
        def consume(expected):
            run(['rustc', '--edition=2021', 'src/consumer.rs', '--extern',
                 'cache_macro=' + str(dylib), '-o', 'consumer'])
            assert run([str(root / 'consumer')]).stdout == str(expected).encode() + b'\n'
        direct = run(rust)
        reference = hashes()
        consume(12)
        remove()
        cold = run([str(binary), *rust])
        assert hashes() == reference
        assert b'miss: compiling proc-macro producer' in cold.stderr
        consume(12)
        remove()
        warm = run([str(binary), *rust])
        assert b'hit: proc-macro producer' in warm.stderr, warm.stderr.decode()
        assert hashes() == reference
        consume(12)
        assert direct.stdout == cold.stdout == warm.stdout
        def diagnostics(r):
            return [line for line in r.stderr.splitlines() if not line.startswith(b'nanocompile: ')]
        assert diagnostics(direct) == diagnostics(cold) == diagnostics(warm)
        original_stamp = (root / 'native' / 'libprobe.a').stat()
        archive(13)
        os.utime(root / 'native' / 'libprobe.a', ns=(original_stamp.st_atime_ns, original_stamp.st_mtime_ns))
        remove()
        changed = run([str(binary), *rust])
        assert b'hit: proc-macro producer' not in changed.stderr
        consume(13)
        macro.write_text(source.replace('value()}.to_string()', 'value()+1}.to_string()'))
        remove()
        changed_source = run([str(binary), *rust])
        assert b'hit: proc-macro producer' not in changed_source.stderr
        consume(14)
        entry_path = next((root / 'cache' / 'entries').iterdir())
        entry = json.loads(entry_path.read_bytes().split(b'\n', 1)[1])
        blob = next(o['hash'] for o in entry['outputs'] if o['path'].endswith('.dylib'))
        (root / 'cache' / 'blobs' / blob[:2] / blob).write_bytes(b'corrupt')
        remove()
        repaired = run([str(binary), *rust])
        assert b'hit: proc-macro producer' not in repaired.stderr
        consume(14)
        entry_path.write_bytes(b'corrupt')
        remove()
        repaired_manifest = run([str(binary), *rust])
        assert b'hit: proc-macro producer' not in repaired_manifest.stderr
        consume(14)
        remove()
        final = run([str(binary), *rust])
        assert b'hit: proc-macro producer' in final.stderr
        consume(14)
        debug = run([str(binary), *rust, '-C', 'debuginfo=2'])
        assert b'bypass: UnsupportedProducerConfiguration' in debug.stderr
        consume(14)
        disabled_env = dict(env)
        disabled_env.pop('NANOCOMPILE_PROC_MACRO_PRODUCERS')
        disabled = subprocess.run([str(binary), *rust], cwd=root, env=disabled_env,
                                  capture_output=True, timeout=180)
        assert disabled.returncode == 0 and b'bypass:' in disabled.stderr
        consume(14)
        macro.write_text('this is invalid Rust\n')
        failed = run([str(binary), *rust], success=False)
        assert b'hit: proc-macro producer' not in failed.stderr
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({'platform': sys.platform,
                'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'direct_cold_warm_artifacts_equal': True, 'diagnostics_replayed': True,
                'loaded_macro_values': [12, 12, 12, 13, 14, 14, 14, 14, 14, 14],
                'native_preserved_mtime_change_detected': True, 'source_change_detected': True,
                'corrupt_blob_and_manifest_repaired': True, 'failed_compilation_not_cached': True,
                'unsupported_debug_and_default_policy_bypass': True,
                'limits': 'experimental opt-in; Apple default driver; debug-info zero; '
                          'no cross-target or custom linker; no project speed claim'}, indent=2) + '\n')
    print('PASS: real producer cache restore, macro loading, invalidation, corruption and failure')


if __name__ == '__main__':
    main()
