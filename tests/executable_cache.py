"""Real executable producer restore; execution and runtime inputs stay live."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from macho_staging import validate_staging_difference
import tempfile



def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--thin-lto', action='store_true', help='exercise opt-in thin-LTO compilation and transitive bitcode changes')
    p.add_argument('--stable-alias-experiment', action='store_true', help='explicit experimental thin-LTO byte validation profile')
    p.add_argument('--state', type=Path, help='new directory to retain probe artifacts for diagnosis')
    p.add_argument('--retain-jobs', action='store_true', help='verify retained private compiler/linker diagnostics')
    args = p.parse_args()
    if args.stable_alias_experiment and not (args.thin_lto and args.retain_jobs):
        p.error("--stable-alias-experiment requires --thin-lto and --retain-jobs")
    binary = args.binary.resolve()
    if sys.platform != 'darwin':
        print('SKIP: experimental executable producers require Apple tools')
        return
    if args.state:
        args.state.mkdir(parents=True, exist_ok=False)
    with contextlib.nullcontext(str(args.state)) if args.state else tempfile.TemporaryDirectory(prefix='nano executable cache, ') as tmp:
        root = Path(tmp).resolve()
        for name in ('src', 'out', 'native'):
            (root / name).mkdir()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
               and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTC_BOOTSTRAP')}
        env.update(RUSTUP_TOOLCHAIN='1.97.1', NANOCOMPILE_DIR=str(root / 'cache'),
                   NANOCOMPILE_TRACE='1', NANOCOMPILE_EXECUTABLE_PRODUCERS='1')
        if args.thin_lto:
            env['NANOCOMPILE_THIN_LTO_PRODUCERS'] = '1'
        if args.retain_jobs:
            env['NANOCOMPILE_RETAIN_PRODUCER_JOBS'] = '1'
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
        if args.thin_lto:
            helper = root / 'helper.rs'
            helper.write_text('pub fn adjustment()->u32{0}\n')
            (root / 'helper-out').mkdir()
            helper_command = ['rustc', 'helper.rs', '--crate-type', 'rlib', '--crate-name', 'helper',
                              '--emit=dep-info,metadata,link', '--out-dir', 'helper-out', '-C', 'embed-bitcode=yes']
            run(helper_command)
            source = source.replace('unsafe{value()}', 'unsafe{value()}+helper::adjustment()')
            src.write_text(source)
            rust += ['-C', 'lto=thin', '--extern', 'helper=helper-out/libhelper.rlib', '-L', 'dependency=helper-out']
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
        if args.state:
            shutil.copy2(executable, root / 'direct-executable')
        direct_bytes = executable.read_bytes()
        staging_difference = None
        mode = executable.stat().st_mode & 0o777
        execute('12 first')
        remove()
        cold = run([str(binary), *rust])
        assert b'miss: compiling executable producer' in cold.stderr, cold.stderr.decode()
        if args.stable_alias_experiment:
            staging_difference = validate_staging_difference(direct_bytes, executable.read_bytes())
            run(['codesign', '--verify', '--strict', str(executable)])
            assert hashes()[1] == reference[1]
            reference = hashes()
            run([str(binary), 'clear'])
            remove()
            repeat = run([str(binary), *rust])
            assert b'miss: compiling executable producer' in repeat.stderr and hashes() == reference, repeat.stderr.decode()
            run(['codesign', '--verify', '--strict', str(executable)])
        else:
            assert hashes() == reference, (reference, hashes(), cold.stderr.decode())
        execute('12 first')
        remove()
        runtime.write_text('second\n')
        warm = run([str(binary), *rust])
        assert b'hit: executable producer' in warm.stderr and hashes() == reference, warm.stderr.decode()
        assert executable.stat().st_mode & 0o777 == mode
        execute('12 second')
        if args.stable_alias_experiment:
            # Stale foreign aliases must remain untouched and force direct
            # compilation rather than adopting an old private job.
            jobs = list((root / 'cache/producer-jobs').glob('*/compiler-result.json'))
            record = json.loads(jobs[-1].read_text())
            alias = Path(record['argv'][record['argv'].index('--out-dir') + 1]).parent
            shutil.rmtree(root / 'cache/entries')
            alias.symlink_to(jobs[-1].parent)
            remove()
            collision = run([str(binary), *rust])
            assert b'bypass: exclusive thin-LTO alias unavailable' in collision.stderr
            assert alias.is_symlink() and alias.resolve() == jobs[-1].parent
            assert executable.read_bytes() == direct_bytes
            alias.unlink()
            remove()
            # Key/output locks serialize same-key compilers: one genuine miss,
            # one restore, identical bytes, no shared physical compilation.
            children = [subprocess.Popen([str(binary), *rust], cwd=root, env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
            streams = [child.communicate(timeout=180) for child in children]
            assert all(child.returncode == 0 for child in children)
            assert sum(b'miss: compiling executable producer' in err for _, err in streams) == 1
            assert sum(b'hit: executable producer' in err for _, err in streams) == 1
            assert hashes() == reference
            execute('12 second')
        if args.thin_lto:
            helper.write_text('pub fn adjustment()->u32{1}\n')
            run(helper_command)
            remove()
            assert b'hit: executable producer' not in run([str(binary), *rust]).stderr
            execute('13 second')
            helper.write_text('pub fn adjustment()->u32{0}\n')
            run(helper_command)
            remove()
            run([str(binary), *rust])
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
        # Invalidate all historical candidates to require a miss, rather than
        # rejecting legitimate recovery through another validated manifest.
        for entry_path in (root / 'cache' / 'entries').iterdir():
            entry = json.loads(entry_path.read_bytes()[65:])
            blob = next(o['hash'] for o in entry['outputs'] if o['path'] == str(executable))
            (root / 'cache' / 'blobs' / blob[:2] / blob).write_bytes(b'corrupt')
        remove()
        assert b'hit: executable producer' not in run([str(binary), *rust]).stderr
        execute('14 second')
        for entry_path in (root / 'cache' / 'entries').iterdir():
            entry_path.write_bytes(b'corrupt')
        remove()
        assert b'hit: executable producer' not in run([str(binary), *rust]).stderr
        execute('14 second')
        remove()
        assert b'hit: executable producer' in run([str(binary), *rust]).stderr
        execute('14 second')
        assert b'bypass: UnsupportedProducerConfiguration' in run([str(binary), *rust, '-C', 'debuginfo=2']).stderr
        if args.thin_lto:
            assert b'bypass: UnsupportedProducerConfiguration' in run([str(binary), *rust, '-C', 'lto=fat']).stderr
            macro_env = dict(env, NANOCOMPILE_PROC_MACRO_PRODUCERS='1')
            macro_command = [*rust, '--crate-type=proc-macro']
            macro_direct = subprocess.run(macro_command, cwd=root, env=macro_env, capture_output=True, timeout=180)
            macro_guarded = subprocess.run([str(binary), *macro_command], cwd=root, env=macro_env, capture_output=True, timeout=180)
            assert b'bypass: UnsupportedProducerConfiguration' in macro_guarded.stderr
            assert macro_guarded.returncode == macro_direct.returncode
            assert diagnostics(macro_guarded) == diagnostics(macro_direct)
            guarded_env = dict(env, NANOCOMPILE_THIN_LTO_PRODUCERS='0')
            guarded = subprocess.run([str(binary), *rust], cwd=root, env=guarded_env, capture_output=True, timeout=180)
            assert guarded.returncode == 0 and b'bypass: UnsupportedProducerConfiguration' in guarded.stderr
        disabled_env = dict(env)
        disabled_env.pop('NANOCOMPILE_EXECUTABLE_PRODUCERS')
        disabled = subprocess.run([str(binary), *rust], cwd=root, env=disabled_env, capture_output=True, timeout=180)
        assert disabled.returncode == 0 and b'bypass: UnsupportedCrateType' in disabled.stderr
        src.write_text('invalid Rust\n')
        failed = run([str(binary), *rust], success=False)
        assert b'hit: executable producer' not in failed.stderr
        if args.retain_jobs:
            jobs = list((root / 'cache/producer-jobs').iterdir())
            completed = [j for j in jobs if (j / 'compiler-result.json').exists()]
            assert completed
            results = [json.loads((j / 'compiler-result.json').read_text()) for j in completed]
            assert any(r['exit_code'] == 0 for r in results) and any(r['exit_code'] != 0 for r in results)
            for job, result in zip(completed, results):
                assert result['end_ns'] >= result['start_ns'] and (job / 'compiler.stdout').is_file() and (job / 'compiler.stderr').is_file()
            manifests = list((root / 'cache/producer-jobs').glob('*/owned-inputs.json'))
            assert manifests and any(json.loads(p.read_text()) for p in manifests)
            for manifest in manifests:
                invocation = json.loads((manifest.parent / 'invocation').read_bytes()[65:])
                child_env = {r['name']: r['value'] for r in invocation['diagnostic_environment']}
                assert child_env['ZERO_AR_DATE'] == '1' and child_env['SDKROOT']
                assert not any(k.startswith(('R2_', 'KACHE_', 'AWS_')) for k in child_env)
                for item in json.loads(manifest.read_text()):
                    snapshot = Path(item['snapshot'])
                    assert snapshot.resolve().is_relative_to(manifest.parent.resolve())
                    assert snapshot.is_file() and not snapshot.is_symlink() and len(item['blake3']) == 64
                    assert snapshot.stat().st_mode & 0o777 == 0o600
        if args.stable_alias_experiment:
            assert not list((root / 'cache/producer-aliases').iterdir())
        evidence = {'platform': sys.platform, 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                    'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'direct_cold_warm_artifacts_equal': not args.stable_alias_experiment or staging_difference['changed_bytes'] == 0,
                    'own_cold_warm_artifacts_equal': True, 'staging_difference': staging_difference,
                    'diagnostics_replayed': True,
                    'executable_permissions_preserved': True, 'runtime_reads_stay_live_after_restore': True,
                    'source_and_preserved_mtime_native_changes_detected': True,
                    'corrupt_blob_and_manifest_repaired': True, 'failed_compilation_not_cached': True,
                    'debug_and_default_policy_bypass': True,
                    'thin_lto': args.thin_lto,
                    'stable_alias_collision_and_same_key_concurrency': args.stable_alias_experiment,
                    'private_producer_jobs_retained': args.retain_jobs,
                    'limits': 'Apple native zero-debug executable compilation only; execution is not cached; no project speed claim'}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print('PASS: executable restore, artifact equality, live execution, invalidation, corruption and fallback')


if __name__ == '__main__':
    main()
