"""Measure whether private proc-macro output placement preserves compiler artifacts.

This exercises real rustc and loads every resulting macro. It does not enable
producer caching. Paths, compiler version and per-case hashes are recorded so
platform-specific differences remain visible rather than inferred away.
"""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--toolchain', default='1.97.1')
    parser.add_argument('--observer', type=Path)
    args = parser.parse_args()
    observer = args.observer.resolve() if args.observer else None
    if sys.platform not in ('darwin', 'linux'):
        parser.error('requires macOS or Linux')
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
           and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTC_BOOTSTRAP')}
    env['RUSTUP_TOOLCHAIN'] = args.toolchain
    result = {'platform': sys.platform,
              'observer_sha256': hashlib.sha256(observer.read_bytes()).hexdigest() if observer else None,
              'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'method': 'same source, cwd and environment; output directory changed; '
                        'Darwin install name preserved; all macros loaded and executed',
              'cases': []}
    with tempfile.TemporaryDirectory(prefix='nano producer, placement ') as tmp:
        root = Path(tmp).resolve()
        def run(command):
            p = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=120)
            if p.returncode:
                raise RuntimeError(f'{command[0]} failed: {p.stderr.decode(errors="replace")}')
            return p
        result['rustc'] = run(['rustc', '-vV']).stdout.decode().strip()
        (root / 'producer.rs').write_text(
            'extern crate proc_macro;\n'
            '#[proc_macro] pub fn answer(_: proc_macro::TokenStream) -> proc_macro::TokenStream '
            '{ "42".parse().unwrap() }\n')
        (root / 'consumer.rs').write_text('fn main() { println!("{}", producer::answer!()); }\n')
        suffix = '.dylib' if sys.platform == 'darwin' else '.so'
        cc = shutil.which('cc')
        assert cc
        linker = root / 'nanocompile-internal-linker'
        config = root / 'observer.json'
        invocation = root / 'invocation.json'
        if observer:
            linker.symlink_to(observer)
        for relative in (False, True):
            for name, flags in [('default', []), ('release', ['-C', 'opt-level=3']),
                                ('debug2', ['-C', 'debuginfo=2'])]:
                case = f'{"relative" if relative else "absolute"}-{name}'
                paths = [root / case / p for p in ('ordinary', 'isolated')]
                for path in paths:
                    path.mkdir(parents=True)
                original_output = str(paths[0].relative_to(root) if relative else paths[0])
                rows = []
                for index, path in enumerate(paths):
                    out = str(path.relative_to(root) if relative else path)
                    command = ['rustc', '--edition=2021', 'producer.rs', '--crate-name', 'producer',
                               '--crate-type', 'proc-macro', '--emit=dep-info,link', '--out-dir', out,
                               '--error-format=json', '--json=artifacts', *flags]
                    if observer:
                        config.write_text(json.dumps({'driver': str(Path(cc).absolute()),
                            'format': 'darwin' if sys.platform == 'darwin' else 'make',
                            'report': str(root / 'link.deps'), 'invocation': str(invocation),
                            'capture_id': case + '-' + str(index),
                            'ownership': {'out': str(path), 'canonical_out': str(path.resolve()),
                                          'output': out + '/libproducer' + suffix}}))
                        command.extend(['-C', 'linker=' + str(linker)])
                    if index and sys.platform == 'darwin':
                        install_name = original_output + '/libproducer' + suffix
                        for value in ('-Xlinker', '-install_name', '-Xlinker', install_name):
                            command.extend(['-C', 'link-arg=' + value])
                    compiled = run(command)
                    ownership_counts = None
                    if observer:
                        captured = json.loads(invocation.read_bytes().split(b'\n', 1)[1])
                        assert captured['capture_valid'], captured
                        inputs = captured['link']['inputs']
                        ownership_counts = {'owned': sum(p['owned'] for p in inputs),
                                            'persistent': sum(not p['owned'] for p in inputs)}
                        assert ownership_counts['owned'] > 0 and ownership_counts['persistent'] > 0
                    dylib = path / ('libproducer' + suffix)
                    consumer = root / ('consumer-' + case + '-' + str(index))
                    run(['rustc', '--edition=2021', 'consumer.rs', '--extern',
                         'producer=' + str(dylib), '-o', str(consumer)])
                    assert run([str(consumer)]).stdout == b'42\n'
                    artifacts = [json.loads(line)['artifact'] for line in compiled.stderr.splitlines()
                                 if json.loads(line).get('$message_type') == 'artifact']
                    # Each emitted artifact must be inside the requested private output.
                    assert all((root / p).resolve().parent == path for p in artifacts)
                    dep_info = (path / 'producer.d').read_text()
                    # Normalize only the known output path; source/cwd remain unchanged.
                    escaped_out = out.replace(' ', '\\ ')
                    mapped_dep_info = dep_info.replace(escaped_out, '<output>')
                    # rustc also writes literal spaces in target names.
                    mapped_dep_info = mapped_dep_info.replace(out, '<output>')
                    rows.append({'sha256': hashlib.sha256(dylib.read_bytes()).hexdigest(),
                                 'loaded_value': 42, 'artifacts': artifacts,
                                 'ownership_counts': ownership_counts,
                                 'normalized_dep_info': mapped_dep_info})
                equal = rows[0]['sha256'] == rows[1]['sha256']
                dep_equal = rows[0]['normalized_dep_info'] == rows[1]['normalized_dep_info']
                result['cases'].append({'case': case, 'byte_identical': equal,
                                        'dep_info_equal_after_output_mapping': dep_equal,
                                        'ordinary': rows[0], 'isolated': rows[1]})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    for case in result['cases']:
        print(case['case'], 'artifact_equal=', case['byte_identical'],
              'dep_info_equal=', case['dep_info_equal_after_output_mapping'])
    # Required baseline. Other modes record evidence for future eligibility gates.
    assert all(c['byte_identical'] for c in result['cases'] if c['case'].endswith('-default'))
    assert all(c['dep_info_equal_after_output_mapping'] for c in result['cases'])


if __name__ == '__main__':
    main()
