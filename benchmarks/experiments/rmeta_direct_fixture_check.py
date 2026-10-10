"""Real compiler oracle checks for the exact-version direct metadata reader."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from rmeta_direct_check import oracle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('NANOCOMPILE_', 'R2_', 'KACHE_'))}
    env.update(RUSTUP_TOOLCHAIN='1.97.1', RUSTC_BOOTSTRAP='1')
    checked = []
    with tempfile.TemporaryDirectory(prefix='nano direct metadata fixtures ') as temp:
        root = Path(temp)
        def compile(name, source, extra=(), kind='rlib'):
            path = root / (name + '.rs')
            path.write_text(source)
            cmd = ['rustc', str(path), '--crate-name', name, '--crate-type', kind,
                   '--emit=metadata,link', '--out-dir', str(root), *extra]
            subprocess.run(cmd, env=env, check=True, capture_output=True)
            return next(root.glob('lib' + name + '*.rmeta'))
        leaf = compile('leaf_fixture', '#![no_std]\npub fn answer() -> u32 { 42 }\n',
                       ['-C', 'extra-filename=-direct_fixture'])
        consumer = compile('consumer_fixture',
                           'extern crate leaf_fixture; pub fn answer() -> u32 { leaf_fixture::answer() }\n',
                           ['--extern', 'leaf_fixture=' + str(leaf.with_suffix('.rlib'))])
        macro = compile('macro_fixture',
                        'extern crate proc_macro; use proc_macro::TokenStream; '
                        '#[proc_macro] pub fn identity(input: TokenStream) -> TokenStream { input }\n',
                        kind='proc-macro')
        dylib = macro.with_suffix('.dylib' if sys.platform == 'darwin' else '.so')
        macro_consumer = compile('macro_consumer_fixture',
                                'extern crate macro_fixture; '
                                'pub fn answer() -> u32 { macro_fixture::identity!(42) }\n',
                                ['--extern', 'macro_fixture=' + str(dylib)])
        rows = json.loads(subprocess.check_output([str(binary), str(leaf), str(consumer), str(macro_consumer)]))
        for row in rows:
            assert row['graph'] is not None, row
            expected = oracle(Path(row['file']), env)
            assert row['graph'] == expected, row['file']
            checked.append({'fixture': Path(row['file']).name, 'dependencies': len(expected['dependencies']),
                            'macros_only': sum(dep['proc_macro'] for dep in expected['dependencies'])})
        assert checked[-1]['macros_only'] > 0
        refused = json.loads(subprocess.check_output([str(binary), str(macro)]))
        assert refused[0]['graph'] is None
        original = consumer.read_bytes()
        bad = root/'bad.rmeta'
        for data in [b'', original[:20], original[:-13],
                     original[:8] + bytes([255]) * 8 + original[16:],
                     original.replace(b'rustc 1.97.1', b'rustc 9.99.9', 1)]:
            bad.write_bytes(data)
            row = json.loads(subprocess.check_output([str(binary), str(bad)]))[0]
            assert row['graph'] is None and row['failure']
    report = {'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'rustc': subprocess.check_output(['rustc', '-vV'], env=env, text=True),
              'fixtures': checked, 'checks': ['no_std root and extra filename match rustc',
                 'transitive dependency graph matches rustc', 'MacrosOnly dependency matches rustc',
                 'proc-macro producer metadata refuses', 'malformed and unknown-version records refuse']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
