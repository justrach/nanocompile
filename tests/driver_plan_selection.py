"""Compare live-plan and legacy Apple selection under real selector changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    p.add_argument('candidate', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    binaries = {name: getattr(args, name).resolve() for name in ('baseline', 'candidate')}
    rows = []
    with tempfile.TemporaryDirectory(prefix='nano driver plan selectors, ') as tmp:
        root = Path(tmp).resolve()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
               and k not in ('SDKROOT', 'DEVELOPER_DIR', 'TOOLCHAINS', 'RUSTC_BOOTSTRAP')}
        env['NANOCOMPILE_DIR'] = str(root / 'cache')
        sdk = root / 'private SDK'
        sdk.mkdir()
        settings = sdk / 'SDKSettings.json'
        settings.write_bytes(b'{"Version":"first_"}')
        def check(label, overrides=None, driver='/usr/bin/cc', success=True):
            selected_env = dict(env, **(overrides or {}))
            responses = {}
            for name, binary in binaries.items():
                result = subprocess.run([str(binary), 'internal-native-identity', driver],
                                        cwd=root, env=selected_env, capture_output=True, timeout=120)
                assert (result.returncode == 0) == success, (name, label, result.stderr.decode())
                responses[name] = json.loads(result.stdout) if success else None
            assert responses['baseline'] == responses['candidate'], (label, responses)
            plan = subprocess.run([driver, '-v', '-###', '-x', 'c', '/dev/null', '-o', '/dev/null'],
                                  cwd=root, env=selected_env, capture_output=True, timeout=120)
            rows.append({'case': label, 'driver': driver, 'accepted': success,
                         'full_selection_and_fingerprint_equal': True,
                         'driver_plan_exit_code': plan.returncode,
                         'driver_plan_has_error_diagnostic': b': error:' in plan.stderr,
                         'identity': responses['candidate']})
            return responses['candidate']
        original = check('default')
        check('default_clang', driver='/usr/bin/clang')
        check('explicit_selected_sdk', {'SDKROOT': original['sdk']})
        for developer in (Path('/Library/Developer/CommandLineTools'), Path('/Applications/Xcode.app/Contents/Developer')):
            if developer.is_dir():
                check('developer_' + developer.parent.name, {'DEVELOPER_DIR': str(developer)})
        before = check('private_sdk_selection', {'SDKROOT': str(sdk)})
        stamp = settings.stat()
        settings.write_bytes(b'{"Version":"second"}')
        os.utime(settings, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert settings.stat().st_size == stamp.st_size
        after = check('private_sdk_preserved_mtime_change', {'SDKROOT': str(sdk)})
        assert before['hash'] != after['hash']
        check('invalid_deployment_legacy_fallback', {'MACOSX_DEPLOYMENT_TARGET': 'not-a-version'})
        assert rows[-1]['driver_plan_exit_code'] != 0 or rows[-1]['driver_plan_has_error_diagnostic'], 'Expected invalid deployment plan to need legacy fallback'
        check('missing_sdk', {'SDKROOT': str(root / 'missing-sdk')}, success=False)
        check('missing_developer', {'DEVELOPER_DIR': str(root / 'missing-developer')}, success=False)
        for key in ('CCC_OVERRIDE_OPTIONS', 'CCC_ADD_ARGS', 'DYLD_INSERT_LIBRARIES', 'LD_PRELOAD'):
            check('unsupported_' + key, {key: ''}, success=False)
        assert sorted(x.name for x in root.iterdir()) == ['cache', 'private SDK']
        evidence = {'method': 'Identical private environment, cwd and cache. Each real selector case calls both binaries; successful selection structures and fingerprints must be identical. Default Apple driver plans do not execute compiler/linker jobs.',
                    'binary_sha256': {name: sha(binary) for name, binary in binaries.items()},
                    'probe_sha256': sha(Path(__file__)), 'cases': rows,
                    'preserved_mtime_sdk_change_detected': True,
                    'unparseable_driver_plan_legacy_fallback_verified': True,
                    'no_compilation_outputs_created_in_cwd': True}
        args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print('PASS: live plan and legacy selection match for tools, SDKs, developer roots, fallback and invalid selectors')


if __name__ == '__main__':
    main()
