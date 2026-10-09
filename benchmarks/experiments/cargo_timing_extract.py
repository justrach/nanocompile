"""Extract Cargo's embedded JSON without executing the timing report's JavaScript."""
import argparse
import hashlib
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('report', type=Path)
p.add_argument('captured_root', type=Path)
args = p.parse_args()
d = json.loads(args.report.read_text())
for row in d['builds']:
    path = args.captured_root / row['timing_file']
    assert path.name == row['timing_file']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row['timing_html_sha256']
    text = path.read_text()
    dec = json.JSONDecoder()
    units, _ = dec.raw_decode(text.split('const UNIT_DATA = ', 1)[1])
    concurrency, _ = dec.raw_decode(text.split('const CONCURRENCY_DATA = ', 1)[1])
    assert len({u['i'] for u in units}) == len(units)
    row['units'], row['concurrency'] = units, concurrency
    row['longest_units'] = [{k: u[k] for k in ['i', 'name', 'mode', 'target', 'start', 'duration']}
                            for u in sorted(units, key=lambda u: u['duration'], reverse=True)[:10]]
    row['ring_build_script'] = next(u for u in units if u['name'] == 'ring' and u['mode'] == 'run-custom-build')
d['timing_resolution'] = 'Cargo HTML reports start/duration rounded to hundredths of a second; units are wall-clock intervals, not CPU time or a formal dependency DAG.'
d['extract_script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
args.report.write_text(json.dumps(d, indent=2)+'\n')
