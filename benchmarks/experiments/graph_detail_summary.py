"""Attribute diagnostic graph work to queries, hashing, memos and enumeration."""
import argparse
import collections
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('records_dir', type=Path)
    p.add_argument('--cold-phases', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    cold = json.loads(args.cold_phases.read_text())
    parents = {r['key']: r for r in cold['records']}
    files = sorted(path for path in args.records_dir.iterdir() if path.is_file())
    rows = [json.loads(path.read_text()) for path in files]
    assert rows and all(row['parent_key'] in parents for row in rows)
    counts = collections.Counter()
    times = collections.Counter()
    per_parent = collections.Counter()
    for row in rows:
        per_parent[row['parent_key']] += row['total_ns']
        for field in ('total_ns', 'sysroot_ns', 'own_root_query_ns', 'enumeration_ns'):
            assert row[field] >= 0
            times[field] += row[field]
        for field, value in row['resolver'].items():
            assert value >= 0
            (times if field.endswith('_ns') else counts)[field] += value
    for key, total in per_parent.items():
        assert total <= parents[key]['graph_ns']
    ranked = sorted(rows, key=lambda row: row['total_ns'], reverse=True)
    report = {'method': 'Per-collect records from the isolated graph-detail patch. Subprocess clocks cover process execution; digest clocks cover fresh checked content hashes; writes include classification serialization/sealing/atomic persistence. Times overlap across Cargo jobs. Remaining graph time includes guards, matching, metadata parsing, memo reads and uninstrumented work. Compiler identities are the existing complete fingerprints, not newly normalized identities.',
              'cold_phase_sha256': sha(args.cold_phases), 'script_sha256': sha(Path(__file__)),
              'file_sha256': {path.name: sha(path) for path in files},
              'collect_calls': len(rows), 'parent_jobs': len(per_parent),
              'compiler_identity_count': len({row['compiler_identity'] for row in rows}),
              'counts': dict(counts),
              'aggregate_seconds': {key.removesuffix('_ns'): value/1e9 for key,value in times.items()},
              'largest_collects': [{**row, 'parent_crate': parents[row['parent_key']]['crate'], 'parent_mode': parents[row['parent_key']]['mode']} for row in ranked[:10]],
              'records': rows}
    if all(row.get('decoder_identity') for row in rows):
        report['decoder_identity_count'] = len({row['decoder_identity'] for row in rows})
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    summary = {key: report[key] for key in ('collect_calls', 'parent_jobs', 'compiler_identity_count', 'counts', 'aggregate_seconds', 'largest_collects')}
    if 'decoder_identity_count' in report:
        summary['decoder_identity_count'] = report['decoder_identity_count']
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
