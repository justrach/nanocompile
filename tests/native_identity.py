"""Verify selected Apple tools and private SDK metadata invalidation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    if sys.platform != 'darwin':
        print('SKIP: Apple tool selection requires macOS')
        return
    with tempfile.TemporaryDirectory(prefix='nano native, identity ') as tmp:
        root = Path(tmp).resolve()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
               and k not in ('SDKROOT', 'RUSTC_BOOTSTRAP')}
        env['NANOCOMPILE_DIR'] = str(root / 'cache')
        def invoke(changes=None, success=True):
            result = subprocess.run([str(binary), 'internal-native-identity', '/usr/bin/cc'],
                cwd=root, env=dict(env, **(changes or {})), capture_output=True, timeout=120)
            assert (result.returncode == 0) == success, result.stderr.decode()
            return json.loads(result.stdout) if success else None
        first = invoke()
        assert invoke() == first
        assert Path(first['clang']).is_file() and Path(first['linker']).is_file()
        assert Path(first['sdk']).is_dir() and Path(first['resource_dir']).is_dir()
        assert all(Path(p).is_file() for p in first['files'])
        # Do not edit the real installation. Private metadata tests the same
        # explicit SDK selection and digest invalidation boundary.
        sdk = root / 'private SDK'
        sdk.mkdir()
        settings = sdk / 'SDKSettings.json'
        settings.write_bytes(b'{"Version":"first_"}')
        private = {'SDKROOT': str(sdk)}
        selected = invoke(private)
        assert selected['sdk'] == str(sdk) and selected['hash'] != first['hash']
        stamp = settings.stat()
        settings.write_bytes(b'{"Version":"second"}')
        os.utime(settings, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert settings.stat().st_size == stamp.st_size
        assert settings.stat().st_mtime_ns == stamp.st_mtime_ns
        changed = invoke(private)
        assert changed['hash'] != selected['hash']
        assert invoke(private) == changed
        # Sealed memo corruption causes content recomputation, never trust.
        for memo in (root / 'cache' / 'toolchain-files').iterdir():
            memo.write_bytes(b'corrupt')
        assert invoke(private) == changed
        invoke({'SDKROOT': str(root / 'missing-sdk')}, success=False)
        invoke({'DEVELOPER_DIR': str(root / 'missing-developer')}, success=False)
        evidence = {'platform': sys.platform, 'selected': first,
                    'observer_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                    'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'stable_warm_identity': True, 'private_sdk_selection_changes_identity': True,
                    'preserved_mtime_sdk_metadata_change_detected': True,
                    'corrupt_memos_recomputed': True, 'invalid_selections_rejected': True,
                    'limits': 'Apple dispatch shim only; no production producer keys yet; '
                              'link input contents and negative lookup guards remain separate'}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print('PASS: Apple selection, warm identity, SDK metadata edits, corruption and invalid selectors')


if __name__ == '__main__':
    main()
