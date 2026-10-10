"""Inspect captured identity memo scopes without changing cache records."""
import argparse
import collections
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('memo_dir', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--exclude-selector', action='append', default=[], help='Explicit selector path to omit only from an additional diagnostic stamp grouping')
    args = p.parse_args()
    rows = []
    digests = {}
    for path in sorted(args.memo_dir.iterdir()):
        if not path.is_file():
            continue
        data = path.read_bytes()
        assert len(data) >= 65 and data[64:65] == b'\n'
        row = json.loads(data[65:])
        assert row['schema'] in (3, 4, 5)
        rows.append(row)
        digests[path.name] = hashlib.sha256(data).hexdigest()
    groups = collections.defaultdict(list)
    for row in rows:
        present = json.dumps([s for s in row['stamps'] if s['exists']], sort_keys=True, separators=(',', ':'))
        groups[present].append(row)
    absent = {s['path'] for row in rows for s in row['stamps'] if not s['exists']}
    report = {'method': 'Read captured toolchain identity memos without changing them. Group existing stamp lists separately from absent selector paths. Stamp equivalence is metadata evidence, not permission to remove compilation identity or content validation guards. File SHA-256 digests retain provenance.',
              'memo_count': len(rows), 'distinct_hashes': len({row['hash'] for row in rows}),
              'distinct_existing_stamp_lists': len(groups),
              'existing_stamp_groups': sorted([{'memos': len(group), 'distinct_hashes': len({r['hash'] for r in group})} for group in groups.values()], key=lambda row: row['memos'], reverse=True),
              'distinct_absent_paths': len(absent),
              'absent_path_suffix_counts': dict(collections.Counter(Path(path).name for path in absent)),
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'file_sha256': digests}
    if all(row.get('decoder_hash') for row in rows):
        report['distinct_decoder_hashes'] = len({row['decoder_hash'] for row in rows})
    if args.exclude_selector:
        excluded = set(args.exclude_selector)
        report['diagnostic_excluded_selector_paths'] = sorted(excluded)
        report['distinct_existing_stamp_lists_without_selected_selectors'] = len({
            json.dumps([s for s in row['stamps'] if s['exists'] and s['path'] not in excluded], sort_keys=True, separators=(',', ':'))
            for row in rows})
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key != 'file_sha256'}, indent=2))


if __name__ == '__main__':
    main()
