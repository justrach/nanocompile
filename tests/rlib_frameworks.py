"""Real command-line framework metadata, final links and multi-output refusal."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import time


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    root = args.state.resolve() if args.state else Path(tempfile.mkdtemp(prefix='nano-rlib-frameworks-'))
    if args.state:
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
    output = args.output.resolve() if args.output else root/'result.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    env = {k:v for k,v in os.environ.items() if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
           and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTC_BOOTSTRAP')}
    env.update(NANOCOMPILE_DIR=str(root/'cache'), NANOCOMPILE_TRACE='1', RUSTUP_TOOLCHAIN='1.97.1')
    result = dict(binary_sha256=sha(binary), script_sha256=sha(Path(__file__)),
                  platform=platform.platform(), state=str(root), executions=[], completed=False)

    def save():
        output.write_text(json.dumps(result, indent=2)+'\n')

    def run(name, command, wrapped=False, enabled=True, clean=True):
        if clean:
            shutil.rmtree(root/'out', ignore_errors=True)
            (root/'out').mkdir()
        child_env = dict(env, NANOCOMPILE_RLIB_FRAMEWORKS='1' if enabled else '0')
        started = time.monotonic()
        proc = subprocess.run(([str(binary)] if wrapped else [])+command, cwd=root,
                              env=child_env, capture_output=True, timeout=180)
        number = len(result['executions'])
        stdout, stderr = root/f'{number}-{name}.stdout', root/f'{number}-{name}.stderr'
        stdout.write_bytes(proc.stdout); stderr.write_bytes(proc.stderr)
        artifacts = {p.name:dict(sha256=sha(p), mode=oct(p.stat().st_mode & 0o777))
                     for p in sorted((root/'out').iterdir()) if p.is_file()}
        row = dict(name=name, seconds=time.monotonic()-started, exit_code=proc.returncode,
                   artifacts=artifacts, hit=b'nanocompile: hit' in proc.stderr,
                   stdout_sha256=sha(stdout), stderr_sha256=sha(stderr))
        result['executions'].append(row); save()
        return proc, row

    def compare(name, command, reference, hit=None, enabled=True):
        proc, row = run(name, command, True, enabled)
        assert proc.returncode == 0, proc.stderr.decode(errors='replace')
        assert row['artifacts'] == reference, (name, row['artifacts'], reference)
        if hit is not None:
            assert row['hit'] == hit, proc.stderr.decode(errors='replace')
        return proc, row

    def consume(expected=None):
        (root/'main.rs').write_text('fn main(){println!("{}",provider::answer());}\n')
        proc = subprocess.run(['rustc', 'main.rs', '--edition=2021', '--extern',
                               'provider=out/libprovider.rlib', '-o', 'consumer'],
                              cwd=root, env=env, capture_output=True, timeout=180)
        if expected is None:
            assert proc.returncode != 0, 'Missing framework unexpectedly linked'
        else:
            assert proc.returncode == 0, proc.stderr.decode(errors='replace')
            observed = subprocess.check_output([str(root/'consumer')], cwd=root, env=env,
                                               timeout=30).decode().strip()
            assert observed == str(expected), (observed, expected)
        return proc.returncode

    def refused(name, command):
        direct, reference = run(name+'-direct', command)
        proc, row = run(name+'-refused', command, True)
        assert proc.returncode == direct.returncode and row['artifacts'] == reference['artifacts']
        assert not row['hit'] and b'UnsupportedNativeLibrary' in proc.stderr
        clean_stderr = b'\n'.join(line for line in proc.stderr.splitlines() if not line.startswith(b'nanocompile:'))
        assert clean_stderr == b'\n'.join(direct.stderr.splitlines()) and proc.stdout == direct.stdout

    try:
        # Both orders must pass through until every output type is supported.
        (root/'lib.rs').write_text('pub fn answer()->u32 {42}\n')
        common = ['rustc', 'lib.rs', '--edition=2021', '--crate-name', 'provider',
                  '--emit=dep-info,metadata,link', '--out-dir', 'out', '-C', 'opt-level=3']
        for types in (('staticlib','rlib'), ('rlib','staticlib')):
            command = common + [arg for kind in types for arg in ('--crate-type', kind)]
            direct, reference = run('multi-direct-'+types[0], command)
            assert direct.returncode == 0 and 'libprovider.a' in reference['artifacts']
            for repeat in range(2):
                proc, row = compare('multi-wrapped-'+types[0]+str(repeat), command, reference['artifacts'], False)
                assert b'UnsupportedCrateType' in proc.stderr
        result['both_multi_output_orders_preserve_all_bytes_and_modes'] = True
        if platform.system() == 'Darwin':
            source = root/'lib.rs'
            original = (b'extern "C" {fn NSGetSizeAndAlignment(t:*const i8,s:*mut usize,a:*mut usize)->*const i8;}\n'
                        b'pub fn answer()->u32 {let mut size=0;let mut alignment=0;unsafe{NSGetSizeAndAlignment(b"q\\0".as_ptr().cast(),&mut size,&mut alignment);}size as u32 + 0}\n')
            source.write_bytes(original)
            command = common + ['--crate-type', 'rlib', '-l', 'framework=Foundation']
            direct, baseline = run('framework-direct', command)
            assert direct.returncode == 0
            consume(8)
            compare('framework-default-off', command, baseline['artifacts'], False, False)
            compare('framework-cold', command, baseline['artifacts'], False)
            compare('framework-hit', command, baseline['artifacts'], True)
            consume(8)
            stamp = source.stat()
            source.write_bytes(original.replace(b' + 0', b' + 1'))
            assert source.stat().st_size == stamp.st_size and source.read_bytes() != original
            os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            edited, changed = run('framework-edited-direct', command)
            assert edited.returncode == 0
            compare('framework-edit-miss', command, changed['artifacts'], False)
            consume(9)
            compare('framework-edit-hit', command, changed['artifacts'], True)
            source.write_bytes(original)
            os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            compare('framework-revert-hit', command, baseline['artifacts'], True)
            consume(8)
            # Rlib compilation defers resolution; the final link remains live.
            missing = command[:-1] + ['framework=NanoDefinitelyAbsentFramework']
            proc, reference = run('absent-framework-direct', missing)
            assert proc.returncode == 0
            direct_link_status = consume()
            compare('absent-framework-cold', missing, reference['artifacts'], False)
            compare('absent-framework-hit', missing, reference['artifacts'], True)
            assert consume() == direct_link_status
            host = next(line.split(': ',1)[1] for line in subprocess.check_output(
                ['rustc','-vV'],env=env,text=True).splitlines() if line.startswith('host: '))
            explicit_target = command + ['--target', host]
            proc, reference = run('explicit-target-direct', explicit_target)
            assert proc.returncode == 0
            proc, _ = compare('explicit-target-refused', explicit_target, reference['artifacts'], False)
            assert b'UnsupportedNativeLibrary' in proc.stderr
            refused('framework-modifier', command[:-1]+['framework:+bundle=Foundation'])
            for kind, control in (('bin','NANOCOMPILE_EXECUTABLE_PRODUCERS'), ('proc-macro','NANOCOMPILE_PROC_MACRO_PRODUCERS')):
                env[control] = '1'
                try:
                    refused('framework-'+kind, common+['--crate-type',kind,'-l','framework=Foundation'])
                finally:
                    del env[control]
            result['framework_checks'] = dict(direct_cold_hit_bytes_and_modes=True,
                preserved_mtime_source_edit=True, revert=True, linked_behavior=[8,9,8],
                missing_framework_final_link_fails=True, explicit_target_refused=True,
                default_off=True, modified_framework_kind_refused=True, producer_links_refused=True)
        else:
            result['framework_checks'] = 'macOS-only; multi-output checks ran'
        result['completed'] = True; save()
        print('PASS: multi-output passthrough and native framework eligibility/linked behavior')
    except BaseException as error:
        result['failure'] = dict(type=type(error).__name__, message=str(error)); save()
        raise


if __name__ == '__main__':
    main()
