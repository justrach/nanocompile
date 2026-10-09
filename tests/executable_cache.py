"""Real executable producer restore; execution and runtime inputs stay live."""
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
        print('SKIP: experimental executable producers require Apple tools')
        return
    with tempfile.TemporaryDirectory(prefix='nano executable cache, ') as tmp:
        root = Path(tmp).resolve()
        for name in ('src', 'out', 'native'):
            (root / name).mkdir()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
               and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTC_BOOTSTRAP')}
        env.update(RUSTUP_TOOLCHAIN='1.97.1', NANOCOMPILE_DIR=str(root / 'cache'),
                   NANOCOMPILE_TRACE='1', NANOCOMPILE_EXECUTABLE_PRODUCERS='1')
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
        source = ('extern "C" {fn value()->u32;} fn main(){'
                  'let s=std::fs::read_to_string("runtime.txt").unwrap();'
                  'println!("{} {}",unsafe{value()},s.trim());}\n')
        src = root / 'src' / 'producer.rs'
        src.write_text(source)
        runtime = root / 'runtime.txt'
        runtime.write_text('first\n')
        rust = ['rustc', '--edition=2021', 'src/producer.rs', '--crate-name', 'build_script_build',
                '--crate-type', 'bin', '--emit=dep-info,link', '--out-dir', 'out',
                '-C', 'extra-filename=-fixture', '-C', 'strip=symbols',
                '-L', 'native=native', '-l', 'static=probe', '--error-format=json', '--json=artifacts']
        executable = root / 'out' / 'build_script_build-fixture'
        dep_info = root / 'out' / 'build_script_build-fixture.d'
        def hashes():
            return [hashlib.sha256(p.read_bytes()).hexdigest() for p in (executable, dep_info)]
        def remove():
            executable.unlink(missing_ok=True)
            dep_info.unlink(missing_ok=True)
        def execute(expected):
            assert run([str(executable)]).stdout == expected.encode() + b'\n'
        direct = run(rust)
        reference = hashes()
        mode = executable.stat().st_mode & 0o777
        execute('12 first')
        remove()
        cold = run([str(binary), *rust])
        assert b'miss: compiling executable producer' in cold.stderr and hashes() == reference, cold.stderr.decode()
        execute('12 first')
        remove()
        runtime.write_text('second\n')
        warm = run([str(binary), *rust])
        assert b'hit: executable producer' in warm.stderr and hashes() == reference, warm.stderr.decode()
        assert executable.stat().st_mode & 0o777 == mode
        execute('12 second')
        def diagnostics(r):
            return [line for line in r.stderr.splitlines() if not line.startswith(b'nanocompile: ')]
        assert direct.stdout == cold.stdout == warm.stdout
        assert diagnostics(direct) == diagnostics(cold) == diagnostics(warm)
        stamp = (root / 'native' / 'libprobe.a').stat()
        archive(13)
        os.utime(root / 'native' / 'libprobe.a', ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        remove()
        assert b'hit: executable producer' not in run([str(binary), *rust]).stderr
        execute('13 second')
        src.write_text(source.replace('unsafe{value()}', 'unsafe{value()+1}'))
        remove()
        assert b'hit: executable producer' not in run([str(binary), *rust]).stderr
        execute('14 second')
        entry_path = next((root / 'cache' / 'entries').iterdir())
        entry = json.loads(entry_path.read_bytes()[65:])
        blob = next(o['hash'] for o in entry['outputs'] if o['path'] == str(executable))
        (root / 'cache' / 'blobs' / blob[:2] / blob).write_bytes(b'corrupt')
        remove()
        assert b'hit: executable producer' not in run([str(binary), *rust]).stderr
        execute('14 second')
        entry_path.write_bytes(b'corrupt')
        remove()
        assert b'hit: executable producer' not in run([str(binary), *rust]).stderr
        execute('14 second')
        remove()
        assert b'hit: executable producer' in run([str(binary), *rust]).stderr
        execute('14 second')
        assert b'bypass: UnsupportedProducerConfiguration' in run([str(binary), *rust, '-C', 'debuginfo=2']).stderr
        disabled_env = dict(env)
        disabled_env.pop('NANOCOMPILE_EXECUTABLE_PRODUCERS')
        disabled = subprocess.run([str(binary), *rust], cwd=root, env=disabled_env, capture_output=True, timeout=180)
        assert disabled.returncode == 0 and b'bypass: UnsupportedCrateType' in disabled.stderr
        src.write_text('invalid Rust\n')
        failed = run([str(binary), *rust], success=False)
        assert b'hit: executable producer' not in failed.stderr
        evidence = {'platform': sys.platform, 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                    'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'direct_cold_warm_artifacts_equal': True, 'diagnostics_replayed': True,
                    'executable_permissions_preserved': True, 'runtime_reads_stay_live_after_restore': True,
                    'source_and_preserved_mtime_native_changes_detected': True,
                    'corrupt_blob_and_manifest_repaired': True, 'failed_compilation_not_cached': True,
                    'debug_and_default_policy_bypass': True,
                    'limits': 'Apple native zero-debug executable compilation only; execution is not cached; no project speed claim'}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print('PASS: executable restore, artifact equality, live execution, invalidation, corruption and fallback')


if __name__ == '__main__':
    main()
