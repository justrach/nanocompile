"""Real cache restores for native metadata; dynamic execution and static refusal."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    results = {}
    with tempfile.TemporaryDirectory(prefix='nano-native-cache-') as tmp:
        root = Path(tmp)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
               and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTC_BOOTSTRAP')}
        env.update(RUSTUP_TOOLCHAIN='1.97.1', NANOCOMPILE_DIR=str(root / 'cache'), NANOCOMPILE_TRACE='1')
        mac = platform.system() == 'Darwin'
        attrs = {'default': '#[link(name="probe")]',
                 'dynamic': '#[link(name="probe",kind="dylib")]',
                 'two_dynamic': '#[link(name="probe",kind="dylib")] #[link(name="c",kind="dylib")]',
                 'inactive': '#[cfg(any())] #[link(name="probe",kind="static")]',
                 'static': '#[link(name="probe",kind="static")]',
                 'macro_static': 'macro_rules! native { () => { #[link(name="probe",kind="static")] extern "C" {fn value()->u32;} }; } native!();'}
        if mac:
            attrs['framework'] = '#[link(name="probe",kind="dylib")] #[link(name="Foundation",kind="framework")]'
        for case, attr in attrs.items():
            work = root / case
            work.mkdir()
            (work / 'out').mkdir()
            (work / 'native').mkdir()
            def run(command, success=True):
                r = subprocess.run(command, cwd=work, env=env, capture_output=True, timeout=180)
                assert (r.returncode == 0) == success, r.stderr.decode(errors='replace')
                return r
            def native(value):
                (work / 'native.c').write_text(f'unsigned value(void) {{return {value};}}\n')
                run(['cc', '-fPIC', '-c', 'native.c', '-o', 'native.o'])
                archive = work / 'native/libprobe.a'
                archive.unlink(missing_ok=True)
                run(['ar', 'crs', str(archive), 'native.o'])
                if mac:
                    dylib = work / 'native/libprobe.dylib'
                    run(['cc', '-dynamiclib', 'native.o', '-o', str(dylib), '-Wl,-install_name,' + str(dylib)])
                else:
                    run(['cc', '-shared', 'native.o', '-o', 'native/libprobe.so'])
                    env['LD_LIBRARY_PATH'] = str(work / 'native')
            native(12)
            declaration = attr if case == 'macro_static' else attr + '\nextern "C" {fn value()->u32;}'
            answer = '12' if case == 'inactive' else 'unsafe{value()+0}'
            source = work / 'lib.rs'
            source.write_text(declaration + f'\npub fn answer()->u32 {{{answer}}}\n')
            command = ['rustc', 'lib.rs', '--edition=2021', '--crate-name', 'provider',
                       '--crate-type', 'rlib', '--emit=dep-info,metadata,link', '--out-dir', 'out']
            if case in ('static', 'macro_static'):
                command += ['-L', 'native=native']
            outputs = [work / 'out' / x for x in ('libprovider.rlib', 'libprovider.rmeta', 'provider.d')]
            def hashes():
                return {p.name: {'sha256': sha(p), 'mode': p.stat().st_mode & 0o777} for p in outputs}
            def clear():
                for p in outputs:
                    p.unlink(missing_ok=True)
            def consume(expected):
                (work / 'main.rs').write_text('fn main(){println!("{}",provider::answer());}\n')
                run(['rustc', 'main.rs', '--edition=2021', '--extern', 'provider=out/libprovider.rlib',
                     '-L', 'native=native', '-o', 'consumer'])
                assert run([str(work / 'consumer')]).stdout == str(expected).encode() + b'\n'
            run(command)
            reference = hashes()
            consume(12)
            clear()
            first = run([str(binary), *command])
            assert hashes() == reference and b'miss: compiling' in first.stderr
            clear()
            second = run([str(binary), *command])
            eligible = case not in ('static', 'macro_static')
            assert (b'nanocompile: hit' in second.stderr) == eligible, second.stderr.decode()
            if not eligible:
                assert b'HiddenNativeLinkInput' in second.stderr, second.stderr.decode()
            assert hashes() == reference
            consume(12)
            native(13)
            clear()
            changed = run([str(binary), *command])
            assert (b'nanocompile: hit' in changed.stderr) == eligible, changed.stderr.decode()
            consume(12 if case == 'inactive' else 13)
            if eligible:
                assert hashes() == reference
                stamp = source.stat()
                # Source bytes remain fully validated even when mtime is preserved.
                source.write_text(source.read_text().replace(answer, '13' if case == 'inactive' else answer.replace('+0', '+1')))
                assert source.stat().st_size == stamp.st_size
                os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                clear()
                assert b'nanocompile: hit' not in run([str(binary), *command]).stderr
                consume(13 if case == 'inactive' else 14)
            results[case] = {'restored': eligible, 'direct_cold_warm_bytes_and_modes_equal': True,
                             'native_change_execution_verified': True,
                             'source_preserved_mtime_change_detected': eligible}
        # A real different compiler must retain refusal rather than interpret its
        # private metadata using the pinned version's field layout.
        installed = subprocess.check_output(['rustup', 'toolchain', 'list'], env=env, text=True)
        available = subprocess.CompletedProcess([], 1)
        fallback_env = None
        for line in installed.splitlines():
            name = line.split()[0]
            candidate_env = dict(env, RUSTUP_TOOLCHAIN=name)
            check = subprocess.run(['rustc', '-V'], env=candidate_env, capture_output=True, timeout=30)
            if check.returncode == 0 and check.stdout.strip() != b'rustc 1.97.1 (8bab26f4f 2026-07-14)':
                available, fallback_env = check, candidate_env
                break
        older_refused = False
        if available.returncode == 0:
            fallback = root / 'default'
            for path in (fallback / 'out').iterdir():
                path.unlink()
            command = [str(binary), 'rustc', 'lib.rs', '--edition=2021', '--crate-name', 'provider',
                       '--crate-type', 'rlib', '--emit=dep-info,metadata,link', '--out-dir', 'out']
            result = subprocess.run(command, cwd=fallback, env=fallback_env, capture_output=True, timeout=180)
            assert result.returncode == 0 and b'nanocompile: uncached:' in result.stderr and b'nanocompile: hit' not in result.stderr, result.stderr.decode()
            older_refused = True
        evidence = {'other_compiler_available': available.returncode == 0,
                    'other_compiler_version': available.stdout.decode().strip() if available.returncode == 0 else None,
                    'other_compiler_refused_native_metadata_storage': older_refused,
                    'binary_sha256': sha(binary), 'probe_sha256': sha(Path(__file__)),
                    'compiler': run(['rustc', '-Vv']).stdout.decode(), 'cases': results}
        if args.output:
            args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print('PASS: native metadata restores, dynamic execution, static/macro refusal and source content')


if __name__ == '__main__':
    main()
