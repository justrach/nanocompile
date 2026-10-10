"""Compare a bounded exact-version decoder against rustc's complete root graph."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import tempfile
import time


def oracle(path, env):
    result = subprocess.run(['rustc', '-Zls=root', str(path)], cwd='/tmp', env=env,
                            capture_output=True, text=True, check=True).stdout
    head = result.split('=', 1)[0]
    root = {key: re.search('^' + key + r' (\S+)', head, re.M)[1]
            for key in ['name', 'hash', 'triple', 'proc_macro']}
    root['proc_macro'] = root['proc_macro'] == 'true'
    lines = result.split('=External Dependencies=\n', 1)[1].split('\n\n', 1)[0].splitlines()
    deps = []
    for line in lines:
        words = line.split()
        deps.append({'name': words[1], 'hash': words[3],
                     'proc_macro': 'kind MacrosOnly' in line})
    return {'root': root, 'dependencies': deps}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('artifacts', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve()
    paths = sorted(args.artifacts.rglob('*.rmeta'))
    assert paths
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('NANOCOMPILE_', 'R2_', 'KACHE_'))}
    env.update(RUSTUP_TOOLCHAIN='1.97.1', RUSTC_BOOTSTRAP='1')
    command = [str(binary), *map(str, paths)]
    samples = []
    for _ in range(9):
        start = time.perf_counter()
        output = subprocess.check_output(command, env=env)
        samples.append(time.perf_counter() - start)
    rows = json.loads(output)
    accepted = [row for row in rows if row['graph']]
    assert accepted
    comparisons = []
    start = time.perf_counter()
    for row in accepted:
        expected = oracle(row['file'], env)
        assert row['graph'] == expected, row['file']
        path = Path(row['file'])
        comparisons.append({'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                            'dependencies': len(expected['dependencies'])})
    oracle_seconds = time.perf_counter() - start
    with tempfile.TemporaryDirectory(prefix='nano metadata refusal ') as temp:
        root = Path(temp)
        original = Path(accepted[0]['file']).read_bytes()
        mutations = {'empty': b'', 'truncated': original[:20],
                     'bad-magic': b'fail' + original[4:],
                     'invalid-root': original[:8] + bytes([255]) * 8 + original[16:],
                     'missing-end': original[:-13],
                     'unknown-version': original.replace(b'rustc 1.97.1', b'rustc 9.99.9', 1)}
        for name, content in mutations.items():
            (root / (name + '.rmeta')).write_bytes(content)
        refused = json.loads(subprocess.check_output([str(binary), *map(str, sorted(root.glob('*.rmeta')))]))
        assert all(row['graph'] is None and row['failure'] for row in refused)
        (root / 'lib.rs').write_text('pub fn answer() -> u32 { 42 }\n')
        other_env = dict(env, RUSTUP_TOOLCHAIN='1.98.1')
        subprocess.run(['rustc', str(root/'lib.rs'), '--crate-type', 'rlib', '--emit=metadata',
                        '-o', str(root/'other.rmeta')], env=other_env, check=True, capture_output=True)
        other = json.loads(subprocess.check_output([str(binary), str(root/'other.rmeta')]))
        assert other[0]['graph'] is None and other[0]['failure']
    report = {'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'rustc': subprocess.check_output(['rustc', '-vV'], env=env, text=True),
              'files': len(rows), 'accepted': len(accepted),
              'fallback_files': [Path(row['file']).name for row in rows if not row['graph']],
              'comparisons': comparisons, 'checks': ['every accepted root and ordered dependency list matches rustc',
                'truncated/malformed/unknown-version metadata refuses', 'Rust 1.98.1 metadata refuses'],
              'diagnostic_batch_seconds': samples,
              'diagnostic_batch_median_seconds': statistics.median(samples),
              'oracle_seconds': oracle_seconds,
              'timing_limits': 'The direct batch amortizes process startup and includes reading all files and JSON output; the oracle launches rustc separately per accepted file. These timings are diagnostics, not an end-to-end build comparison.'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'comparisons'}))


if __name__ == '__main__':
    main()
