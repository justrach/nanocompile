"""Extract diagnostic native invocation phases from Cargo's ring output."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build_output', type=Path)
    parser.add_argument('--patch', type=Path, required=True)
    parser.add_argument('--base-revision', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    records = [json.loads(line.split('NANOCOMPILE_CLANG_PHASE ', 1)[1])
               for line in args.build_output.read_text().splitlines()
               if 'NANOCOMPILE_CLANG_PHASE ' in line]
    assert len(records) == 24 and all(r['hit'] for r in records)
    phases = ('selection_ns', 'identity_ns', 'capability_ns', 'setup_ns', 'compiler_ns')
    for row in records:
        assert all(row[p] >= 0 for p in phases)
        assert sum(row[p] for p in phases) == row['total_ns']
    summary = {p: {'sum_ms': sum(r[p] for r in records)/1e6,
                   'median_ms': statistics.median(r[p] for r in records)/1e6,
                   'min_ms': min(r[p] for r in records)/1e6,
                   'max_ms': max(r[p] for r in records)/1e6}
               for p in (*phases, 'total_ns')}
    report = {'phase': 'warm-3',
              'method': 'All 24 eligible native compilations from final warm build; Cargo retains cc stderr as build-script warning records in ring output. Earlier output files were replaced by subsequent clean builds and are not claimed as per-invocation samples. Timings use monotonic awake clock inside diagnostic adapter; total excludes process startup and post-compile forwarding/events. Phase sums are aggregate invocation wall time and may overlap; they are not end-to-end critical-path savings.',
              'base_revision': args.base_revision, 'patch_sha256': sha(args.patch),
              'build_output_sha256': sha(args.build_output), 'script_sha256': sha(Path(__file__)),
              'records': records, 'summary': summary}
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
