"""Bounded real declared-task A/B study; reports only allowlisted metrics.

The isolated Python command consumes every declared project input. Its startup
resources use the same explicit discovery as the focused-contract example.
Deletion and byte verification are outside subprocess wall timing, not hidden
inside a claimed whole-session/build saving. No network or user cache is used.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('focused_inputs', ROOT / 'tests/focused_task_inputs.py')
focused = importlib.util.module_from_spec(spec)
spec.loader.exec_module(focused)
SCRIPT = '''import sys
with open(sys.argv[1], 'wb') as output:
    for name in sys.argv[2:]:
        with open(name, 'rb') as source:
            data = source.read()
        encoded = name.encode('utf-8')
        output.write(str(len(encoded)).encode('ascii') + b':' + encoded)
        output.write(str(len(data)).encode('ascii') + b':' + data)
'''
WORKLOADS = {'small-batch': (8, 128, 1),
             'many-small': (256, 4096, 1),
             'large-files': (8, 1024 * 1024, 1),
             'ordered-graph': (1, 4096, 16)}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def study(binaries, workload, batches, pairs, resources):
    count, size, task_count = WORKLOADS[workload]
    with tempfile.TemporaryDirectory(prefix='nano-task-hill-') as temp:
        root = Path(temp)
        (root / 'out').mkdir()
        (root / 'generate.py').write_text(SCRIPT)
        inputs = [f'input-{i:04}.bin' for i in range(count)]
        for i, name in enumerate(inputs):
            (root / name).write_bytes(bytes([i % 251]) * size)
        tasks = []
        for i in range(task_count):
            consumed = inputs + ([f'out/{i - 1:02}.bin'] if i else [])
            tasks.append({'name': f'generate-{i:02}',
                          'command': [sys.executable, '-I', '-S', '-B', 'generate.py',
                                      f'out/{i:02}.bin', *consumed],
                          'inputs': ['generate.py', *consumed],
                          'outputs': [f'out/{i:02}.bin'],
                          'depends_on': [f'generate-{i - 1:02}'] if i else [],
                          'tool_resources': resources})
        (root / 'tasks.json').write_text(json.dumps({'schema': 1, 'tasks': tasks}))
        env = {k: v for k, v in os.environ.items() if not k.startswith('NANOCOMPILE_')}
        environments = {label: dict(env, NANOCOMPILE_DIR=str(root / label)) for label in binaries}
        serial = 0

        def clean():
            for task in tasks:
                for output in task['outputs']:
                    (root / output).unlink(missing_ok=True)

        def outputs():
            return {name: sha(root / name) for task in tasks for name in task['outputs']}

        def direct():
            clean()
            for task in tasks:
                result = subprocess.run(task['command'], cwd=root, env=env,
                                        capture_output=True, timeout=120)
                assert result.returncode == 0, 'direct fixture command failed'
            return outputs()

        reference = direct()

        def invoke(label, expected, outcomes, reporting=True):
            nonlocal serial
            clean()
            serial += 1
            report = root / f'report-{serial}.json'
            selected = dict(environments[label])
            if reporting:
                selected['NANOCOMPILE_TASK_REPORT'] = str(report)
            events = root / label / 'events'
            before = len(events.read_text().splitlines()) if events.exists() else 0
            started = time.perf_counter_ns()
            result = subprocess.run([str(binaries[label]), 'task', 'tasks.json'],
                                    cwd=root, env=selected, capture_output=True, timeout=120)
            wall = time.perf_counter_ns() - started
            assert result.returncode == 0, 'cached fixture command failed (private diagnostics omitted)'
            actual = events.read_text().splitlines()[before:]
            assert actual == ['task_' + outcome for outcome in outcomes], 'unexpected task execution'
            assert outputs() == expected, 'output bytes differ from uncached command'
            row = {'wall_ns': wall}
            if reporting:
                data = json.loads(report.read_text())
                assert [task['outcome'] for task in data['tasks']] == outcomes
                row['setup_ns'] = data['setup_ns']
                for key in data['tasks'][0]['timings']:
                    row[key] = sum(task['timings'][key] for task in data['tasks'])
            return row

        for label in binaries:
            invoke(label, reference, ['miss'] * task_count)
            for _ in range(2):
                invoke(label, reference, ['hit'] * task_count)
        rows = []
        labels = list(binaries)
        for batch in range(batches):
            runs = {label: [] for label in labels}
            for pair in range(pairs):
                order = labels if (batch + pair) % 2 == 0 else labels[::-1]
                for label in order:
                    runs[label].append(invoke(label, reference, ['hit'] * task_count))
            rows.append({'first_order': labels if batch % 2 == 0 else labels[::-1], 'runs': runs})
        # Report-file path is an observational control: separate unreported A/B
        # wall times avoid confusing report serialization with production cost.
        unreported = {label: [] for label in labels}
        for pair in range(pairs):
            for label in (labels if pair % 2 == 0 else labels[::-1]):
                unreported[label].append(invoke(label, reference, ['hit'] * task_count, False)['wall_ns'])
        edited = root / inputs[0]
        original = edited.read_bytes()
        state = edited.stat()
        edited.write_bytes(bytes([252]) + original[1:])
        os.utime(edited, ns=(state.st_atime_ns, state.st_mtime_ns))
        changed = direct()
        assert changed != reference
        for label in binaries:
            invoke(label, changed, ['miss'] * task_count)
            invoke(label, changed, ['hit'] * task_count)
        edited.write_bytes(original)
        restored = direct()
        assert restored == reference
        for label in binaries:
            invoke(label, restored, ['hit'] * task_count)
        medians = {}
        for label in labels:
            values = [row for batch in rows for row in batch['runs'][label]]
            medians[label] = {key: statistics.median(row[key] for row in values) for key in values[0]}
        return {'inputs': count, 'input_size': size, 'tasks': task_count,
                'batches': rows, 'median_ns': medians, 'unreported_wall_ns': unreported,
                'checks': ['direct output SHA-256 equality on every invocation',
                           'all warm hits with outputs deleted', 'same-size preserved-mtime miss',
                           'edited warm hit', 'source revert exact restore']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path, nargs='?')
    parser.add_argument('--batches', type=int, default=4)
    parser.add_argument('--pairs', type=int, default=8)
    parser.add_argument('--confirmation-batches', type=int, default=3)
    parser.add_argument('--workload', choices=WORKLOADS, action='append')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert args.batches > 0 and args.pairs > 0 and args.confirmation_batches >= 0
    binaries = {'baseline': args.baseline.resolve()}
    if args.candidate:
        binaries['candidate'] = args.candidate.resolve()
    resources = focused.python_resources()
    workloads = args.workload or WORKLOADS
    report = {'schema': 1, 'binary_sha256': {label: sha(binary) for label, binary in binaries.items()},
              'method': 'isolated real Python asset tasks; fresh output deletion; alternating AB/BA pairs; native task timers and separate unreported subprocess wall time; no network; warm filesystem caches',
              'profile': 'ReleaseSafe', 'initial': {}}
    for name in workloads:
        report['initial'][name] = study(binaries, name, args.batches, args.pairs, resources)
        print(name, json.dumps(report['initial'][name]['median_ns']), flush=True)
    if args.candidate and args.confirmation_batches:
        report['confirmation'] = {}
        for name in workloads:
            report['confirmation'][name] = study(binaries, name, args.confirmation_batches, args.pairs, resources)
            print('confirmation', name, json.dumps(report['confirmation'][name]['median_ns']), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
