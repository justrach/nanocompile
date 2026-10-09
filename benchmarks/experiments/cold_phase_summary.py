"""Join cold miss and save phase records; sums overlap across Cargo jobs."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('records_dir', type=Path)
    parser.add_argument('--builds', type=Path, required=True)
    parser.add_argument('--patch', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    builds = json.loads(args.builds.read_text())
    assert builds['tracked_sources_unchanged'] and builds['miss_profile']
    misses, saves = {}, {}
    digests = {}
    for marker, records in (('NANOCOMPILE_MISS_PHASE', misses), ('NANOCOMPILE_SAVE_PHASE', saves)):
        for path in sorted(args.records_dir.glob(marker+'-*.json')):
            row = json.loads(path.read_text())
            assert row['key'] not in records
            records[row['key']] = row
            digests[path.name] = sha(path)
    assert len(misses) == builds['builds'][0]['events']['miss'] == 167
    assert misses.keys() == saves.keys()
    rows = [{**row, **saves[key]} for key, row in misses.items()]
    outer = ('precompile_ns', 'compiler_ns', 'postcompile_ns')
    inner = ('validation_ns', 'graph_ns', 'store_ns')
    for row in rows:
        assert all(row[p] >= 0 for p in (*outer, *inner))
        assert sum(row[p] for p in outer) == row['total_ns']
        assert sum(row[p] for p in inner) <= row['postcompile_ns']
    groups = {}
    for mode in sorted({row['mode'] for row in rows}):
        selected = [row for row in rows if row['mode'] == mode]
        groups[mode] = {'jobs': len(selected),
                        'aggregate_seconds': {p.removesuffix('_ns'): sum(row[p] for row in selected)/1e9 for p in (*outer, *inner)}}
    aggregate = {p.removesuffix('_ns'): sum(row[p] for row in rows)/1e9 for p in (*outer, *inner)}
    report = {'method': 'Isolated diagnostic executable, explicit profiling environment switch. All successful cold misses joined to completed save records by exact cache key. Aggregate per-job elapsed durations overlap across four Cargo jobs and are not additive critical-path savings. Postcompile includes save plus producer linking-input collection/revalidation and forwarding/materialization. Inner save phases are a subset of postcompile. Instrumentation is diagnostic, not an A/B optimization result.',
              'record_file_sha256': digests, 'builds_sha256': sha(args.builds),
              'patch_sha256': sha(args.patch), 'script_sha256': sha(Path(__file__)),
              'jobs': len(rows), 'aggregate_seconds': aggregate, 'by_mode': groups,
              'largest_postcompile_jobs': sorted(rows, key=lambda row: row['postcompile_ns'], reverse=True)[:15],
              'records': rows}
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ('jobs', 'aggregate_seconds', 'by_mode', 'largest_postcompile_jobs')}, indent=2))


if __name__ == '__main__':
    main()
