"""Summarize observed script-phase events without publishing raw stderr."""
import collections
import hashlib
import re
import statistics


EVENT = re.compile(r'nanocompile: script-phase ([a-z][a-z0-9_.]*) ns=([0-9]+)')


def collect(directory):
    """Caller must verify an existing capture, or own its in-progress creation."""
    rows = []
    for path in sorted(directory.glob('build-script-outputs/*/stderr')):
        raw = path.read_bytes()
        phases = collections.defaultdict(list)
        for line in raw.decode('utf-8', errors='replace').splitlines():
            event = EVENT.fullmatch(line.strip())
            if event is None:
                continue
            digits = event[2]
            if len(digits) > 19:
                continue
            ns = int(digits)
            if ns > 2**63 - 1:
                continue
            phases[event[1]].append(ns)
        for phase, values in sorted(phases.items()):
            rows.append(dict(script=path.parent.name, stage=phase,
                             samples=len(values), samples_ns=values,
                             median_seconds=statistics.median(values) / 1e9,
                             min_seconds=min(values) / 1e9,
                             max_seconds=max(values) / 1e9,
                             source_record=str(path.relative_to(directory)),
                             source_bytes=len(raw),
                             source_sha256=hashlib.sha256(raw).hexdigest()))
    return rows
