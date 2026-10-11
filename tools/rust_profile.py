#!/usr/bin/env python3
"""Critical-path profiler and what-if scheduler for Cargo builds.

Inputs are Cargo `--timings` HTML reports (`UNIT_DATA`) and, optionally, the
matching `cargo build --unit-graph` JSON (same command, `RUSTC_BOOTSTRAP=1
... -Z unstable-options`). Unit indices of both outputs are identical for the
same resolved build; `load` verifies this before joining them.

Subcommands:
  path      critical path of one build, with slot waits and unit categories
  simulate  replay one build on N job slots; check the model against reality
  diff      compare two builds; attribute the wall-time gap by substituting
            unit durations from the other build into a simulated schedule
  phases    aggregate Nano compiler-phase trace lines per request
  study     summarize every Cargo timing kept by a benchmark report
  trace     export an observed or simulated schedule for Perfetto

Interval sums overlap and never predict wall time. This tool instead replays
Cargo's scheduler: a unit becomes ready when all of its dependencies have
finished (or, for pipelined libraries, emitted metadata) and the ready unit
with the most transitive dependents takes the next free job slot. Simulated
predictions are estimates. Always report the model error measured on the
baseline, and confirm a predicted win with repeated untraced builds.
"""
import argparse
import collections
import heapq
import json
from pathlib import Path
import re
import statistics
import sys


# --------------------------------------------------------------------------- loading

def load_timing(path):
    text = Path(path).read_text()
    marker = 'const UNIT_DATA = '
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f'{path}: no UNIT_DATA; pass a cargo --timings HTML report')
    end = text.find(';\n', start)
    units = json.loads(text[start + len(marker):end])
    return {u['i']: u for u in units}


def category(unit):
    target = unit['target'].strip()
    if unit['mode'] == 'run-custom-build':
        return 'build-script-run'
    if target.startswith('build-script'):
        return 'build-script-compile'
    if '"bin"' in target or target.endswith('(bin)'):
        return 'binary'
    if target == '' or target.startswith('lib'):
        return 'library'
    return target.split()[0] if target else 'library'


def label(unit):
    target = unit['target'].strip()
    suffix = f' [{target}]' if target else ''
    run = ' (run)' if unit['mode'] == 'run-custom-build' and '(run)' not in target else ''
    return f"{unit['name']} {unit['version']}{suffix}{run}"


def unit_key(unit):
    return (unit['name'], unit['version'], unit['mode'], unit['target'].strip(), tuple(sorted(unit['features'])))


LINKING_TYPES = {'bin', 'dylib', 'cdylib', 'staticlib', 'proc-macro'}


class Build:
    """One build: timing units plus a dependency graph (full or inferred)."""

    def __init__(self, timing_path, graph_path=None):
        self.path = str(timing_path)
        self.units = load_timing(timing_path)
        self.end = max(u['start'] + u['duration'] for u in self.units.values())
        # Cargo resolves and fingerprints before the first unit starts.
        self.offset = min(u['start'] for u in self.units.values())
        self.deps = {i: set() for i in self.units}
        self.rmeta_ok = {}
        self.graph = 'inferred-from-unblock-edges'
        if graph_path:
            self._join_graph(graph_path)
        else:
            for unit in self.units.values():
                for target in unit['unblocked_units']:
                    self.deps[target].add(unit['i'])
                for target in unit['unblocked_rmeta_units']:
                    self.deps[target].add(unit['i'])
                    self.rmeta_ok[(unit['i'], target)] = True
        self.dependents = {i: set() for i in self.units}
        for unit, deps in self.deps.items():
            for dep in deps:
                self.dependents[dep].add(unit)
        self.priority = self._priorities()

    def _join_graph(self, graph_path):
        graph = json.loads(Path(graph_path).read_text())['units']
        if len(graph) != len(self.units) or set(self.units) != set(range(len(graph))):
            raise SystemExit('unit graph does not match timing units (different command, features or lockfile?)')
        for index, node in enumerate(graph):
            unit = self.units[index]
            if sorted(node['features']) != sorted(unit['features']) or \
                    (node['mode'] == 'run-custom-build') != (unit['mode'] == 'run-custom-build'):
                raise SystemExit(f'unit {index} differs between timing and unit graph')
        for index, node in enumerate(graph):
            links = node['mode'] != 'build' or bool(set(node['target']['crate_types']) & LINKING_TYPES) or \
                'custom-build' in node['target']['kind']
            for dep in node['dependencies']:
                source = graph[dep['index']]
                pipelined_source = source['mode'] == 'build' and 'lib' in source['target']['kind'] or \
                    set(source['target']['crate_types']) <= {'lib', 'rlib'} and source['mode'] == 'build'
                self.deps[index].add(dep['index'])
                self.rmeta_ok[(dep['index'], index)] = not links and pipelined_source
        # Observed rmeta unblocks are ground truth for Cargo's pipelining choice.
        mismatched = 0
        for unit in self.units.values():
            for target in unit['unblocked_rmeta_units']:
                if not self.rmeta_ok.get((unit['i'], target)):
                    mismatched += 1
                    self.rmeta_ok[(unit['i'], target)] = True
        self.graph = f'cargo-unit-graph ({mismatched} rmeta edges corrected from observation)'

    def _priorities(self):
        # Cargo prefers ready units with more transitive dependents.
        memo = {}
        order = sorted(self.units, key=lambda i: -len(self.dependents[i]))
        def reach(i):
            if i in memo:
                return memo[i]
            stack, seen = [i], set()
            while stack:
                for dependent in self.dependents[stack.pop()]:
                    if dependent not in seen:
                        seen.add(dependent)
                        stack.append(dependent)
            memo[i] = len(seen)
            return memo[i]
        return {i: 1 + reach(i) for i in order}

    def rmeta_time(self, i, duration=None):
        unit = self.units[i]
        duration = unit['duration'] if duration is None else duration
        for name, span in unit.get('sections') or []:
            if name == 'frontend' and unit['duration'] > 0:
                # Keep the observed frontend fraction when a duration is substituted.
                return duration * min(1.0, span['end'] / unit['duration'])
        return duration

    def ready_edge(self, dep, unit):
        return self.rmeta_ok.get((dep, unit), False)


# --------------------------------------------------------------------------- simulation

def simulate(build, jobs, durations=None, spawn=0.0):
    """List-schedule the build; returns per-unit start/end/rmeta and the wall time."""
    durations = durations or {i: u['duration'] for i, u in build.units.items()}
    offset = build.offset
    remaining = {i: len(build.deps[i]) for i in build.units}
    ready_at = {i: offset for i in build.units}
    binding = {i: None for i in build.units}
    ready = []
    for i, count in remaining.items():
        if count == 0:
            heapq.heappush(ready, (0.0, -build.priority[i], i))
    events = []  # (time, kind, unit) kind 0 = rmeta, 1 = finish
    free = jobs
    now = offset
    start, end, rmeta = {}, {}, {}
    queued = []  # ready units waiting for a slot, by priority
    satisfied = collections.defaultdict(set)

    def release(dep, time, edge_kind):
        for unit in build.dependents[dep]:
            pipelined = build.ready_edge(dep, unit)
            if (edge_kind == 0) != pipelined or dep in satisfied[unit]:
                continue
            satisfied[unit].add(dep)
            remaining[unit] -= 1
            if time >= ready_at[unit]:
                ready_at[unit], binding[unit] = time, dep
            if remaining[unit] == 0:
                heapq.heappush(queued, (-build.priority[unit], unit))

    for _, _, i in ready:
        heapq.heappush(queued, (-build.priority[i], i))
    while queued or events:
        while free and queued:
            _, i = heapq.heappop(queued)
            start[i] = max(now, ready_at[i]) + spawn
            duration = durations[i]
            end[i] = start[i] + duration
            rmeta[i] = start[i] + build.rmeta_time(i, duration)
            heapq.heappush(events, (rmeta[i], 0, i))
            heapq.heappush(events, (end[i], 1, i))
            free -= 1
        if not events:
            break
        now, kind, i = heapq.heappop(events)
        if kind == 1:
            free += 1
        release(i, now, kind)
    if len(end) != len(build.units):
        raise SystemExit('simulation deadlocked: dependency graph is incomplete or cyclic')
    return dict(start=start, end=end, rmeta=rmeta, ready_at=ready_at, binding=binding, wall=max(end.values()))


def critical_path(build, schedule):
    """Walk back from the last unit through binding dependencies."""
    i = max(schedule['end'], key=schedule['end'].get)
    path = []
    while i is not None:
        wait = schedule['start'][i] - schedule['ready_at'][i]
        path.append(dict(unit=i, label=label(build.units[i]), category=category(build.units[i]),
                         start=schedule['start'][i], duration=schedule['end'][i] - schedule['start'][i],
                         slot_wait=max(0.0, wait)))
        i = schedule['binding'][i]
    path.reverse()
    return path


def observed_schedule(build):
    start = {i: u['start'] for i, u in build.units.items()}
    end = {i: u['start'] + u['duration'] for i, u in build.units.items()}
    rmeta = {i: u['start'] + build.rmeta_time(i) for i, u in build.units.items()}
    ready_at, binding = {}, {}
    for i in build.units:
        best, best_time = None, 0.0
        for dep in build.deps[i]:
            time = rmeta[dep] if build.ready_edge(dep, i) else end[dep]
            if time >= best_time:
                best, best_time = dep, time
        ready_at[i], binding[i] = best_time, best
    return dict(start=start, end=end, rmeta=rmeta, ready_at=ready_at, binding=binding, wall=max(end.values()))


# --------------------------------------------------------------------------- reports

def summarize_path(path):
    by_category = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for step in path:
        row = by_category[step['category']]
        row[0] += 1
        row[1] += step['duration']
        row[2] += step['slot_wait']
    return {name: dict(units=v[0], seconds=round(v[1], 3), slot_wait_seconds=round(v[2], 3))
            for name, v in sorted(by_category.items(), key=lambda kv: -kv[1][1])}


def fmt(seconds):
    return f'{seconds:8.3f}s'


def print_path(title, path, wall, limit):
    print(f'\n## {title}: critical path {len(path)} units, wall {wall:.3f}s')
    busy = sum(s['duration'] for s in path)
    wait = sum(s['slot_wait'] for s in path)
    print(f'   on-path work {busy:.3f}s, slot/spawn waits {wait:.3f}s, other gaps {max(0.0, wall - busy - wait):.3f}s')
    for name, row in summarize_path(path).items():
        print(f"   {name:22} {row['units']:4d} units {row['seconds']:8.3f}s  waits {row['slot_wait_seconds']:.3f}s")
    shown = sorted(path, key=lambda s: -(s['duration'] + s['slot_wait']))[:limit]
    print('   heaviest steps:')
    for step in shown:
        print(f"   {fmt(step['duration'])} +wait {step['slot_wait']:.3f}s  {step['label']}")


def cmd_path(args):
    build = Build(args.timing, args.unit_graph)
    schedule = observed_schedule(build)
    path = critical_path(build, schedule)
    print(f'{build.path}: {len(build.units)} units, graph {build.graph}')
    print_path('observed', path, schedule['wall'], args.top)
    if args.json:
        Path(args.json).write_text(json.dumps(dict(timing=build.path, graph=build.graph, wall=schedule['wall'],
                                                   critical_path=path, summary=summarize_path(path)), indent=2) + '\n')


def calibrate(build, jobs):
    """Per-unit spawn latency that makes the simulated wall match this build."""
    low, high = 0.0, 0.2
    if simulate(build, jobs)['wall'] >= build.end:
        return 0.0
    for _ in range(30):
        middle = (low + high) / 2
        if simulate(build, jobs, spawn=middle)['wall'] < build.end:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def resolve_spawn(build, args):
    if args.spawn == 'auto':
        args.spawn = calibrate(build, args.jobs)
        print(f'calibrated spawn latency {args.spawn * 1000:.2f} ms/unit on {build.path}')
    else:
        args.spawn = float(args.spawn)
    return args.spawn


def model_check(build, jobs, spawn):
    schedule = simulate(build, jobs, spawn=spawn)
    error = (schedule['wall'] - build.end) / build.end if build.end else 0.0
    return schedule, error


def cmd_simulate(args):
    build = Build(args.timing, args.unit_graph)
    resolve_spawn(build, args)
    schedule, error = model_check(build, args.jobs, args.spawn)
    print(f'{build.path}: observed wall {build.end:.3f}s, simulated {schedule["wall"]:.3f}s '
          f'({error:+.1%} model error, {args.jobs} jobs, graph {build.graph})')
    durations = {i: u['duration'] for i, u in build.units.items()}
    changed = []
    for spec in args.scale or []:
        pattern, factor = spec.rsplit('=', 1)
        regex = re.compile(pattern)
        categories = {category(u) for u in build.units.values()}
        for i, unit in build.units.items():
            if (category(unit) == pattern) if pattern in categories else regex.search(label(unit)):
                durations[i] = unit['duration'] * float(factor)
                changed.append(i)
    if changed:
        what_if = simulate(build, args.jobs, durations, spawn=args.spawn)
        print(f'what-if ({len(changed)} units changed): {what_if["wall"]:.3f}s, '
              f'{schedule["wall"] - what_if["wall"]:+.3f}s versus the simulated baseline')
        print_path('what-if', critical_path(build, what_if), what_if['wall'], args.top)
    print_path('simulated baseline', critical_path(build, schedule), schedule['wall'], args.top)


def cmd_diff(args):
    base = Build(args.baseline, args.unit_graph)
    other = Build(args.candidate, args.unit_graph)
    if base.units.keys() == other.units.keys() and all(unit_key(base.units[i]) == unit_key(other.units[i]) for i in base.units):
        match = {i: i for i in base.units}  # Same resolved graph: Cargo unit indices are identical.
    else:
        # Host and target copies of one package can share a key; match only unique keys.
        counts = collections.Counter(unit_key(u) for u in base.units.values())
        keys = {unit_key(u): i for i, u in base.units.items() if counts[unit_key(u)] == 1}
        match = {}
        for j, unit in other.units.items():
            i = keys.get(unit_key(unit))
            if i is not None:
                match[i] = j
    unmatched = len(base.units) - len(match)
    resolve_spawn(base, args)
    deltas = sorted(((other.units[j]['duration'] - base.units[i]['duration'], i) for i, j in match.items()), reverse=True)
    sim, error = model_check(base, args.jobs, args.spawn)
    other_sim, other_error = model_check(other, args.jobs, args.spawn)
    print(f'baseline  {base.path}: observed {base.end:.3f}s, simulated {sim["wall"]:.3f}s ({error:+.1%})')
    print(f'candidate {other.path}: observed {other.end:.3f}s, simulated {other_sim["wall"]:.3f}s ({other_error:+.1%})')
    print(f'graph {base.graph}; {len(match)} matched units, {unmatched} unmatched')

    def substituted(selector):
        durations = {i: u['duration'] for i, u in base.units.items()}
        for i, j in match.items():
            if selector(i):
                durations[i] = other.units[j]['duration']
        return simulate(base, args.jobs, durations, spawn=args.spawn)['wall']

    everything = substituted(lambda i: True)
    print(f'\nbaseline graph with every candidate duration: {everything:.3f}s '
          f'(explains {sim["wall"] - everything:+.3f}s of the {base.end - other.end:+.3f}s observed gap)')
    categories = sorted({category(u) for u in base.units.values()})
    attribution = {}
    print('\nwall effect of adopting candidate durations for one category (positive = candidate faster):')
    for name in categories:
        saved = sim['wall'] - substituted(lambda i, name=name: category(base.units[i]) == name)
        attribution[name] = saved
        total = sum(other.units[j]['duration'] - base.units[i]['duration'] for i, j in match.items()
                    if category(base.units[i]) == name)
        print(f'   {name:22} {saved:+8.3f}s wall   (summed unit delta {total:+.3f}s)')
    path = critical_path(base, sim)
    on_path = {s['unit'] for s in path}
    print('\nlargest per-unit differences (candidate minus baseline; * = on simulated baseline critical path):')
    rows = []
    for delta, i in deltas[:args.top] + deltas[-args.top:]:
        single = sim['wall'] - substituted(lambda k, i=i: k == i)
        rows.append(dict(unit=label(base.units[i]), delta=delta, wall_effect=single, critical=i in on_path))
    seen = set()
    for row in sorted(rows, key=lambda r: -abs(r['wall_effect']) - abs(r['delta']) * 1e-3):
        if row['unit'] in seen:
            continue
        seen.add(row['unit'])
        print(f"   {'*' if row['critical'] else ' '} {row['delta']:+8.3f}s unit  {row['wall_effect']:+8.3f}s wall  {row['unit']}")
    print_path('baseline (simulated)', path, sim['wall'], args.top)
    print_path('candidate (simulated)', critical_path(other, other_sim), other_sim['wall'], args.top)
    if args.json:
        Path(args.json).write_text(json.dumps(dict(
            baseline=base.path, candidate=other.path, graph=base.graph, jobs=args.jobs,
            observed=dict(baseline=base.end, candidate=other.end),
            simulated=dict(baseline=sim['wall'], candidate=other_sim['wall'], baseline_error=error, candidate_error=other_error,
                           baseline_with_candidate_durations=everything),
            category_wall_effect=attribution, unit_differences=rows,
            baseline_critical_path=path, candidate_critical_path=critical_path(other, other_sim),
            limitations='Simulated list scheduling with Cargo-like priorities; ignores jobserver tokens used inside rustc, '
                        'process spawn variance and host contention. Effects are estimates; confirm with repeated untraced builds.'),
            indent=2) + '\n')


PHASE = re.compile(r'(compiler|script)-phase (\S+) ns=(\d+)')


def request_name(record):
    args = record.get('args') or record.get('argv') or []
    if '--crate-name' in args:
        name = args[args.index('--crate-name') + 1]
        kind = 'build-script-compile' if name.startswith('build_script_') else 'rustc'
        return name, kind
    if args:
        parts = Path(args[0]).parts
        if 'build' in parts and parts[-1].startswith('build-script-build'):
            return parts[parts.index('build') + 1].rsplit('-', 1)[0], 'build-script-run'
        return Path(args[0]).name, 'other'
    return 'unknown', 'other'


def frontend_seconds(meta, record):
    """Seconds from request start until the compiler's rmeta artifact notification reached
    the wrapper, from the capture's stream arrival log; None when it was not emitted."""
    chunks, stderr = meta.with_suffix('.chunks'), meta.with_suffix('.stderr')
    if not (chunks.exists() and stderr.exists()):
        return None
    data = stderr.read_bytes()
    for line in chunks.read_text().splitlines():
        try:
            stream, offset, size, arrival = map(int, line.split(','))
        except ValueError:
            return None
        piece = data[offset:offset + size]
        if stream == 1 and b'"artifact"' in piece and b'.rmeta"' in piece:
            return (arrival - record['start_ns']) / 1e9
    return None


def cmd_phases(args):
    """Aggregate wrapper request time, CPU and Nano phase lines from build_trace capture records."""
    totals = collections.defaultdict(list)
    per_request = collections.defaultdict(lambda: collections.defaultdict(float))
    requests = collections.defaultdict(list)
    for directory in args.capture:
        for meta in Path(directory).rglob('*.json'):
            try:
                record = json.loads(meta.read_text())
            except (ValueError, OSError):
                continue
            if 'start_ns' not in record:
                continue
            name, kind = request_name(record)
            elapsed = (record['end_ns'] - record['start_ns']) / 1e9
            cpu = (record.get('user_us', 0) + record.get('system_us', 0)) / 1e6
            counters = {k: record.get(k) for k in ('major_faults', 'block_reads', 'voluntary_switches', 'involuntary_switches', 'jobserver_free')}
            counters['frontend'] = frontend_seconds(meta, record) if elapsed > 1 else None
            requests[kind].append((elapsed, cpu, name, counters))
            stderr = meta.with_suffix('.stderr')
            text = stderr.read_text(errors='replace') if stderr.exists() else ''
            for family, stage, ns in PHASE.findall(text):
                seconds = int(ns) / 1e9
                totals[f'{family}:{stage}'].append(seconds)
                per_request[name][f'{family}:{stage}'] += seconds
    if not requests:
        raise SystemExit('no capture records; use tests/project_comparison.py --trace-builds')
    print('request kind              count   wall total  wall median   cpu total  cpu median')
    for kind, rows in sorted(requests.items(), key=lambda kv: -sum(r[0] for r in kv[1])):
        print(f'{kind:24} {len(rows):6d} {sum(r[0] for r in rows):11.3f}s {statistics.median(r[0] for r in rows) * 1000:10.2f}ms '
              f'{sum(r[1] for r in rows):10.3f}s {statistics.median(r[1] for r in rows) * 1000:9.2f}ms')
    slowest = sorted((r for rows in requests.values() for r in rows), key=lambda r: r[0], reverse=True)[:args.top]
    print('\nslowest requests:')
    for elapsed, cpu, name, counters in slowest:
        extra = ''
        if counters.get('voluntary_switches') is not None:
            extra = (f"  waits {counters['voluntary_switches']} preempted {counters['involuntary_switches']}"
                     f" page-ins {counters['major_faults']} block-reads {counters['block_reads']}")
        if counters.get('jobserver_free'):
            extra += f"  free-tokens mean {counters['jobserver_free']['mean']:.1f} min {counters['jobserver_free']['min']}"
        if counters.get('frontend') is not None:
            extra += f"  frontend {counters['frontend']:.2f}s codegen {elapsed - counters['frontend']:.2f}s"
        print(f'   {elapsed * 1000:9.2f}ms wall {cpu * 1000:8.2f}ms cpu  {name}{extra}')
    if totals:
        print('\nstage                                          calls      total     median        max')
        for stage, values in sorted(totals.items(), key=lambda kv: -sum(kv[1]))[:args.top * 2]:
            print(f'{stage:45} {len(values):6d} {sum(values):9.3f}s {statistics.median(values) * 1000:8.2f}ms {max(values) * 1000:8.2f}ms')
    for name in args.request or []:
        print(f'\n{name}:')
        for stage, value in sorted(per_request.get(name, {}).items(), key=lambda kv: -kv[1]):
            print(f'   {stage:45} {value * 1000:9.2f}ms')
    print('\nRequest times overlap across jobs and nested stages overlap; none of these sums is a wall-time saving.')
    print('Use `diff` on Cargo timings to estimate wall effects.')


def category_slot_time(build):
    totals = collections.defaultdict(float)
    for unit in build.units.values():
        totals[category(unit)] += unit['duration']
    return dict(totals)


def attribution(base, other, jobs, spawn):
    """Wall effect (positive = other faster) of adopting other's durations per category."""
    match = {i: i for i in base.units} if base.units.keys() == other.units.keys() else {}
    baseline = simulate(base, jobs, spawn=spawn)['wall']
    effects = {}
    for name in sorted({category(u) for u in base.units.values()}):
        durations = {i: u['duration'] for i, u in base.units.items()}
        for i, j in match.items():
            if category(base.units[i]) == name:
                durations[i] = other.units[j]['duration']
        effects[name] = baseline - simulate(base, jobs, durations, spawn=spawn)['wall']
    return effects


def cmd_study(args):
    """Summarize every Cargo timing kept by a benchmark report (--cargo-timings)."""
    report = json.loads(args.report.read_text())
    builds = [b for b in report['builds'] if b.get('cargo_timing')]
    if not builds:
        raise SystemExit('report has no cargo_timing records; rerun the benchmark with --cargo-timings')
    loaded = []
    for b in builds:
        path = args.state / b['cargo_timing']['path']
        loaded.append((b, Build(path, args.unit_graph)))
    groups = collections.defaultdict(list)
    for b, build in loaded:
        groups[(b.get('scenario') or b['phase'], b['implementation'])].append((b, build))
    summary = {}
    print(f"{'scenario/phase':16} {'implementation':14} {'n':>2} {'wall median':>12}  slot time by category (median)")
    for (phase, impl), rows in sorted(groups.items()):
        walls = [b['seconds'] for b, _ in rows]
        cats = collections.defaultdict(list)
        for _, build in rows:
            for name, value in category_slot_time(build).items():
                cats[name].append(value)
        summary.setdefault(phase, {})[impl] = dict(builds=len(rows), wall_median=statistics.median(walls),
                                                   slot_seconds={k: statistics.median(v) for k, v in cats.items()})
        text = ', '.join(f'{k} {statistics.median(v):.2f}s' for k, v in sorted(cats.items()))
        print(f'{phase:16} {impl:14} {len(rows):2d} {statistics.median(walls):11.3f}s  {text}')
    # Pair the candidate with each competitor build of the same phase, in order.
    effects = collections.defaultdict(lambda: collections.defaultdict(list))
    for phase in summary:
        mine = [build for b, build in groups.get((phase, args.candidate), [])]
        for other_impl in sorted(i for p, i in groups if p == phase and i != args.candidate):
            theirs = [build for b, build in groups[(phase, other_impl)]]
            for base, other in zip(mine, theirs):
                spawn = calibrate(base, args.jobs)
                for name, value in attribution(base, other, args.jobs, spawn).items():
                    effects[(phase, other_impl)][name].append(value)
    if effects:
        print(f'\nmedian simulated wall effect of adopting the competitor\'s unit durations, per category')
        print(f'(positive = competitor faster; {args.candidate} is the baseline schedule)')
        for (phase, other_impl), cats in sorted(effects.items()):
            text = ', '.join(f'{k} {statistics.median(v):+.3f}s' for k, v in sorted(cats.items()))
            print(f'{phase:16} vs {other_impl:10} {text}')
            summary[phase].setdefault('wall_effects', {})[other_impl] = {k: statistics.median(v) for k, v in cats.items()}
    if args.json:
        args.json.write_text(json.dumps(dict(report=str(args.report), candidate=args.candidate, jobs=args.jobs,
                                             summary=summary), indent=2) + '\n')


def cmd_trace(args):
    """Chrome/Perfetto trace of the observed (or simulated) schedule, one lane per job slot."""
    build = Build(args.timing, args.unit_graph)
    if args.simulated:
        spawn = calibrate(build, args.jobs)
        schedule = simulate(build, args.jobs, spawn=spawn)
        spans = [(schedule['start'][i], schedule['end'][i], i) for i in build.units]
    else:
        spans = [(u['start'], u['start'] + u['duration'], i) for i, u in build.units.items()]
    path = {s['unit'] for s in critical_path(build, simulate(build, args.jobs, spawn=calibrate(build, args.jobs))
                                             if args.simulated else observed_schedule(build))}
    lanes = []  # end time per lane
    events = []
    for start, end, i in sorted(spans):
        lane = next((k for k, busy in enumerate(lanes) if busy <= start + 1e-9), None)
        if lane is None:
            lane = len(lanes)
            lanes.append(end)
        lanes[lane] = end
        unit = build.units[i]
        events.append(dict(name=label(unit), cat=category(unit) + (',critical' if i in path else ''), ph='X',
                           ts=start * 1e6, dur=max(0.0, end - start) * 1e6, pid=1, tid=lane,
                           args=dict(unit=i, critical=i in path)))
    events.append(dict(name='process_name', ph='M', pid=1, args=dict(name=('simulated ' if args.simulated else '') + build.path)))
    args.output.write_text(json.dumps(dict(traceEvents=events, displayTimeUnit='ms')) + '\n')
    print(f'{args.output}: {len(build.units)} units on {len(lanes)} lanes, {len(path)} critical-path units')


def cmd_unit_graph(args):
    """Write the unit graph for a cargo build command (stable toolchains via RUSTC_BOOTSTRAP)."""
    import os
    import subprocess
    command = list(args.cargo)
    if command and command[0] == '--':
        command = command[1:]
    if command[:2] != ['cargo', 'build']:
        raise SystemExit('pass the exact build command after --, e.g. -- cargo build --release -p app')
    env = dict(os.environ, RUSTC_BOOTSTRAP='1')
    result = subprocess.run(command + ['--unit-graph', '-Z', 'unstable-options'], env=env, cwd=args.cwd,
                            capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(result.stderr)
    graph = json.loads(result.stdout)
    args.output.write_text(result.stdout)
    print(f"{args.output}: {len(graph['units'])} units")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--unit-graph', type=Path, help='cargo --unit-graph JSON for the same build command')
    common.add_argument('--top', type=int, default=12)
    common.add_argument('--json', type=Path)
    sched = argparse.ArgumentParser(add_help=False)
    sched.add_argument('--jobs', type=int, default=8)
    sched.add_argument('--spawn', default='auto', help="per-unit spawn latency in seconds, or 'auto' to calibrate on the (baseline) build")
    s = sub.add_parser('path', parents=[common])
    s.add_argument('timing', type=Path)
    s.set_defaults(run=cmd_path)
    s = sub.add_parser('simulate', parents=[common, sched])
    s.add_argument('timing', type=Path)
    s.add_argument('--scale', action='append', help='REGEX=FACTOR on unit labels or a category name, e.g. build-script-run=0.25')
    s.set_defaults(run=cmd_simulate)
    s = sub.add_parser('diff', parents=[common, sched])
    s.add_argument('baseline', type=Path)
    s.add_argument('candidate', type=Path)
    s.set_defaults(run=cmd_diff)
    s = sub.add_parser('phases')
    s.add_argument('capture', nargs='+', type=Path)
    s.add_argument('--request', action='append')
    s.add_argument('--top', type=int, default=12)
    s.set_defaults(run=cmd_phases)
    s = sub.add_parser('study', parents=[common, sched], help='summarize all Cargo timings kept by a benchmark report')
    s.add_argument('report', type=Path)
    s.add_argument('--state', type=Path, required=True, help='benchmark state directory holding the timing reports')
    s.add_argument('--candidate', default='nanocompile')
    s.set_defaults(run=cmd_study)
    s = sub.add_parser('trace', parents=[common, sched], help='Perfetto/Chrome trace of a build schedule')
    s.add_argument('timing', type=Path)
    s.add_argument('--output', type=Path, required=True)
    s.add_argument('--simulated', action='store_true', help='export the simulated schedule instead of the observed one')
    s.set_defaults(run=cmd_trace)
    s = sub.add_parser('unit-graph', help='record cargo --unit-graph for the same command used with --timings')
    s.add_argument('--output', type=Path, required=True)
    s.add_argument('--cwd', type=Path, default=Path('.'))
    s.add_argument('cargo', nargs=argparse.REMAINDER)
    s.set_defaults(run=cmd_unit_graph)
    args = p.parse_args(argv)
    args.run(args)


if __name__ == '__main__':
    main()
