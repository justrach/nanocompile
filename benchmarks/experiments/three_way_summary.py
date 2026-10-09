"""Summarize a completed rotating project comparison without dropping samples."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--measured-revision', required=True)
    parser.add_argument('--binary', type=Path, required=True)
    args = parser.parse_args()
    raw = json.loads(args.input.read_text())
    assert raw['tracked_sources_unchanged']
    assert raw['nanocompile_sha256'] == sha(args.binary)
    samples = {}
    for mode in ('direct', 'nanocompile', 'kache'):
        rows = [r for r in raw['builds'] if r['implementation'] == mode and r['phase'] == 'warm']
        assert len(rows) == raw['runs']
        assert all(r['exit_code'] == 0 for r in rows)
        for row in rows:
            for key in ('matches_own_cold_artifacts', 'matches_own_cold_native_artifacts',
                        'matches_own_cold_macro_dylibs', 'matches_own_cold_build_script_executables'):
                assert row[key] is True
        values = [row['seconds'] for row in rows]
        samples[mode] = {'samples_seconds': values, 'median_seconds': statistics.median(values),
                         'mean_seconds': statistics.mean(values), 'min_seconds': min(values),
                         'max_seconds': max(values), 'stdev_seconds': statistics.stdev(values)}
    differences = [n-k for n,k in zip(samples['nanocompile']['samples_seconds'], samples['kache']['samples_seconds'])]
    report = {'measured_revision': args.measured_revision, 'raw_file': args.input.name,
              'raw_sha256': sha(args.input), 'binary_sha256': sha(args.binary),
              'script_sha256': sha(Path(__file__)), 'summary': samples,
              'same_round_nano_minus_kache': {
                  'method': 'Descriptive differences within each rotating round. Samples share one host/session and are not independent machine trials; standard error is descriptive, not a general winner test.',
                  'samples_seconds': differences, 'nano_faster_rounds': sum(d < 0 for d in differences),
                  'median_seconds': statistics.median(differences), 'mean_seconds': statistics.mean(differences),
                  'descriptive_standard_error_seconds': statistics.stdev(differences)/math.sqrt(len(differences))}}
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
