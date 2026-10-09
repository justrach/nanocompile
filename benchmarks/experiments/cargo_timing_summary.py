"""Extract Cargo's recorded unit timings; diagnostic durations are not A/B results."""
import argparse
import hashlib
import json
from pathlib import Path


def summarize(path):
    source = path.read_text()
    marker = 'const UNIT_DATA = '
    units, _ = json.JSONDecoder().raw_decode(source.split(marker, 1)[1])
    assert units and all(u['duration'] >= 0 for u in units)
    end = max(u['start'] + u['duration'] for u in units)
    fields = ('i', 'name', 'version', 'mode', 'target', 'start', 'duration',
              'unblocked_units', 'unblocked_rmeta_units')
    rows = [{key: unit[key] for key in fields} for unit in units]
    return {'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'unit_count': len(rows), 'last_unit_end_seconds': end,
            'longest_units': sorted(rows, key=lambda u: u['duration'], reverse=True)[:10],
            'last_units': sorted(rows, key=lambda u: u['start']+u['duration'], reverse=True)[:10],
            'units': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('timings', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = {'method': 'Cargo stable --timings embedded UNIT_DATA extracted without executing HTML. Durations/start times are rounded by Cargo. Unblock edges are recorded scheduling data, not a complete dependency or CPU profile. Longest units alone do not establish an exact critical path.',
              'reports': [summarize(path) for path in args.timings]}
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    for row in report['reports']:
        print(json.dumps({key: row[key] for key in ('file', 'unit_count', 'last_unit_end_seconds', 'longest_units')}))


if __name__ == '__main__':
    main()
