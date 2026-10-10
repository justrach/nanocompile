"""Summarize the isolated default-phase-profile.patch diagnostic records."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('records', type=Path)
    p.add_argument('--binary', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    rows = [json.loads(path.read_text()) for path in sorted(args.records.glob('*.json'))]
    if not rows:
        raise RuntimeError('No completed ordinary compiler records')
    for row in rows:
        assert row['label'] in ('hit', 'miss', 'save')
        assert len(row['key']) == 64
        assert row['data'] and all(isinstance(v, int) and v >= 0 for v in row['data'].values())
    stages = sorted({key for row in rows for key in row['data']})
    summary = {}
    for label in sorted({row['label'] for row in rows}):
        selected = [row for row in rows if row['label'] == label]
        summary[label] = {'records': len(selected), 'stages': {}}
        for stage in stages:
            values = [row['data'][stage] / 1e9 for row in selected if stage in row['data']]
            if values:
                summary[label]['stages'][stage.removesuffix('_ns')] = {
                    'samples': len(values), 'median_seconds': statistics.median(values),
                    'sum_seconds': sum(values), 'max_seconds': max(values)}
    result = {
        'diagnostic_only': True,
        'scope': 'Completed ordinary compiler calls only; producers, scripts, native calls, failures and bypasses excluded. Save rows subdivide miss save intervals and must not be added to containing intervals. Intervals overlap and sums are not build wall time. Atomic diagnostic writes add overhead after recorded phases.',
        'binary_sha256': hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        'summary': summary,
        'records': rows,
    }
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
