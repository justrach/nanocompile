"""Summarize diagnostic compiler phases from owned/verified request streams."""
import collections
import hashlib
import json
import re
import statistics

EVENT = re.compile(r'nanocompile: compiler-phase ([a-z][a-z0-9_.]*) ns=([0-9]+)')


def collect(directory):
    """Caller verifies existing captures. Failed compiler requests are excluded."""
    rows = []
    for record in sorted(directory.glob('*.json')):
        if record.name == 'manifest.json':
            continue
        request = json.loads(record.read_text())
        if request.get('exit_code') != 0:
            continue
        args = request['args']
        crate = args[args.index('--crate-name')+1] if '--crate-name' in args else 'compiler probe'
        path = record.with_suffix('.stderr'); raw = path.read_bytes()
        phases = collections.defaultdict(list)
        for line in raw.decode('utf-8', errors='replace').splitlines():
            event = EVENT.fullmatch(line.strip())
            if event is None or len(event[2]) > 19:
                continue
            ns = int(event[2])
            if ns > 2**63-1:
                continue
            phases[event[1]].append(ns)
        for phase, values in sorted(phases.items()):
            rows.append(dict(request=crate, stage=phase, samples=len(values), samples_ns=values,
                             median_seconds=statistics.median(values)/1e9,
                             min_seconds=min(values)/1e9, max_seconds=max(values)/1e9,
                             source_record=path.name, source_bytes=len(raw),
                             source_sha256=hashlib.sha256(raw).hexdigest()))
    return rows
