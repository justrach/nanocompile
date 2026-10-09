"""Rotate native selection queries on two binaries; require identical identities."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    p.add_argument('candidate', type=Path)
    p.add_argument('--runs', type=int, default=25)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.runs < 1:
        p.error('runs must be positive')
    binaries = {name: str(path.resolve()) for name, path in [('baseline', args.baseline), ('candidate', args.candidate)]}
    samples = {name: [] for name in binaries}
    reference = None
    with tempfile.TemporaryDirectory(prefix='nano native query comparison, ') as tmp:
        env = {k: v for k, v in os.environ.items() if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))}
        env['NANOCOMPILE_DIR'] = tmp
        def run(name, timed):
            nonlocal reference
            start = time.monotonic()
            r = subprocess.run([binaries[name], 'internal-native-identity', '/usr/bin/cc'], env=env, capture_output=True, check=True, timeout=120)
            seconds = time.monotonic() - start
            identity = json.loads(r.stdout)
            if reference is None:
                reference = identity
            assert identity == reference, 'selection or native fingerprint differs'
            if timed:
                samples[name].append(seconds)
        for name in binaries:
            run(name, False)
        for i in range(args.runs):
            for name in (('baseline', 'candidate') if i % 2 == 0 else ('candidate', 'baseline')):
                run(name, True)
    result = {'platform': platform.platform(), 'identity_equal': True,
              'method': 'same environment and cache; prime both; rotate full process queries; every selection field and fingerprint must match',
              'binary_sha256': {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in binaries.items()},
              'samples_seconds': samples,
              'median_seconds': {name: statistics.median(values) for name, values in samples.items()},
              'limits': 'native selection latency only; not a project build benchmark'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result['median_seconds']))


if __name__ == '__main__':
    main()
