"""Verify the managed Xcode CAS against actual compiler inputs and products."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from xcode_fixture import generate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nanocompile', required=True)
    parser.add_argument('--developer-dir', default='/Applications/Xcode.app/Contents/Developer')
    parser.add_argument('--output')
    args = parser.parse_args()
    binary = str(Path(args.nanocompile).resolve())
    with tempfile.TemporaryDirectory(prefix='nanocompile-xcode-integration-') as directory:
        root = Path(directory)
        project = generate(root / 'source', units=4)
        header = project.parent / 'value.h'
        header.write_text('#define VALUE 1\n')
        main_file = project.parent / 'main.c'
        main_file.write_text('#include "value.h"\n' + main_file.read_text().replace('puts("fixture-ok");', 'printf("value=%d\\n", VALUE);'))
        env = {k: v for k, v in os.environ.items() if not k.startswith(('R2_', 'NANOCOMPILE_'))}
        env.update(DEVELOPER_DIR=args.developer_dir, NANOCOMPILE_DIR=str(root / 'cache'))
        derived = root / 'derived'
        command = [binary, 'xcodebuild', '-project', str(project), '-scheme', 'ClangFixture',
                   '-configuration', 'Release', '-destination', 'platform=macOS', '-derivedDataPath',
                   str(derived), '-jobs', '2', 'COMPILATION_CACHE_ENABLE_DIAGNOSTIC_REMARKS=YES', 'build']
        rows = []

        def build(label, expected='value=1', extra=(), disabled=False, success=True):
            # Remove all products and Xcode's ordinary incremental state. Only
            # nanocompile's managed CAS survives between these builds.
            shutil.rmtree(derived, ignore_errors=True)
            current_env = dict(env)
            if disabled:
                current_env['NANOCOMPILE_DISABLE'] = '1'
            proc = subprocess.run([*command, *extra], env=current_env, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
            (root / (label + '.log')).write_text(proc.stdout)
            assert (proc.returncode == 0) == success, proc.stdout[-6000:]
            objects = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in derived.rglob('*.o')}
            if success:
                output = subprocess.check_output([str(derived / 'Build/Products/Release/ClangFixture')], text=True).strip()
                assert output == expected, (label, output, expected)
                assert len(objects) == 5, (label, objects)
            row = {'case': label, 'exit_code': proc.returncode, 'objects': objects,
                   'cache_hits': len(re.findall(r'cache hit', proc.stdout, re.I))}
            rows.append(row)
            print(json.dumps(row), flush=True)
            return row

        # Queries and explicit bypasses must not create a managed native store.
        subprocess.run([binary, 'xcodebuild', '-version'], env=env, check=True)
        assert not (root / 'cache/xcode').exists()
        build('disabled', disabled=True)
        assert not (root / 'cache/xcode').exists()
        build('explicit-no', extra=['COMPILATION_CACHE_ENABLE_CACHING=NO'])
        assert not (root / 'cache/xcode').exists()
        cold = build('cold')
        warm = build('warm')
        assert warm['objects'] == cold['objects']
        assert warm['cache_hits'] >= 5, 'Native CAS did not restore the five compilation jobs'
        stores = list((root / 'cache/xcode').iterdir())
        assert len(stores) == 1 and stores[0].stat().st_mode & 0o777 == 0o700
        stamp = header.stat()
        header.write_text('#define VALUE 2\n')
        os.utime(header, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        changed = build('header-preserved-mtime', expected='value=2')
        assert changed['objects'] != cold['objects'], 'Changed header reused stale objects'
        header.write_text('#error intentional invalidation test\n')
        build('failed-input', success=False)
        header.write_text('#define VALUE 1\n')
        restored = build('restored-header')
        assert restored['objects'] == cold['objects']
        external = root / 'external-cas'
        build('explicit-cas', extra=['COMPILATION_CACHE_CAS_PATH=' + str(external)])
        assert any(external.rglob('*')), 'Explicit CAS path was ignored'
        stats = subprocess.check_output([binary, 'stats'], env=env, text=True)
        assert 'native Xcode invocations: 6' in stats and 'native Xcode failures: 1' in stats, stats
        subprocess.run([binary, 'clear'], env=env, check=True)
        assert not list((root / 'cache/xcode').iterdir())
        assert any(external.rglob('*')), 'Clear removed the user-owned external CAS'
        build('after-clear')
        result = {'xcode': subprocess.check_output(['xcodebuild', '-version'], env=env, text=True).strip(),
                  'cases': rows, 'passed': True}
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
