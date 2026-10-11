"""Record aggregate process activity alongside a live benchmark (macOS/Linux)."""
import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

BUILD_TOOL = re.compile(r'^(cargo|rustc|zig|clang(?:\+\+)?(?:-\d+)?|gcc(?:-\d+)?|g\+\+(?:-\d+)?|cc|c\+\+|cc1|cc1plus|swiftc|swift-frontend|xcodebuild|ld|ld64|ld64\.lld|ld\.lld|lld|ninja|make)$')


def parse_processes(text):
    rows = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split(None, 3)
        if len(fields) != 4:
            raise ValueError('Incomplete process observation')
        pid, parent, cpu = int(fields[0]), int(fields[1]), float(fields[2])
        if pid <= 0 or parent < 0 or not math.isfinite(cpu) or cpu < 0 or pid in rows:
            raise ValueError('Invalid process observation')
        rows[pid] = (parent, cpu, Path(fields[3]).name)
    if not rows:
        raise ValueError('Empty process observation')
    return rows


def summarize(rows, root, additional_roots=()):
    owned = {root, *additional_roots}
    while True:
        expanded = owned | {pid for pid, (parent, _, _) in rows.items() if parent in owned}
        if expanded == owned:
            break
        owned = expanded
    external = [value for pid, value in rows.items() if pid not in owned]
    compilers = [value for value in external if BUILD_TOOL.fullmatch(value[2])]
    return dict(root_present=root in rows, owned_process_count=sum(pid in owned for pid in rows),
                owned_cpu_percent=sum(value[1] for pid, value in rows.items() if pid in owned),
                other_cpu_percent=sum(value[1] for value in external),
                external_build_process_count=len(compilers),
                external_build_cpu_percent=sum(value[1] for value in compilers))


def snapshot(root, additional_roots=()):
    result = subprocess.run(['ps', '-axo', 'pid=,ppid=,pcpu=,comm='],
                            capture_output=True, text=True, check=True, timeout=10)
    return summarize(parse_processes(result.stdout), root, additional_roots)


def write_report(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid', type=int, required=True, help='live benchmark runner PID')
    parser.add_argument('--owned-pid', type=int, action='append', default=[], help='additional owned daemon/process root')
    parser.add_argument('--output', type=Path, required=True, help='new report path; samples use the same path plus .jsonl')
    parser.add_argument('--interval', type=float, default=1)
    parser.add_argument('--max-seconds', type=float, default=3600)
    args = parser.parse_args()
    if args.pid <= 0 or any(pid <= 0 for pid in args.owned_pid):
        parser.error('process IDs must be positive')
    if not math.isfinite(args.interval) or not .5 <= args.interval <= 60:
        parser.error('--interval must be finite and between 0.5 and 60 seconds')
    if not math.isfinite(args.max_seconds) or args.max_seconds <= 0:
        parser.error('--max-seconds must be positive and finite')
    output = args.output.resolve()
    samples = output.with_suffix(output.suffix + '.jsonl')
    if output.exists() or samples.exists():
        parser.error('report and sample paths must be new')
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = dict(completed=False, runner_pid=args.pid, additional_owned_pids=args.owned_pid,
                  observed_from=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  interval_seconds=args.interval, samples_path=samples.name, sample_count=0,
                  external_build_observations=0, max_external_build_process_count=0,
                  tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  limits='Snapshots cover only the monitor interval. Known build-tool names and ancestry are heuristic; zero observations do not prove an idle machine. ps CPU values are platform-specific snapshots, not integrated CPU time. No command arguments, environments, executable paths or unrelated process IDs are retained. No samples are removed and no process is stopped.')
    write_report(output, report)
    try:
        with samples.open('x') as stream:
            while True:
                observation = snapshot(args.pid, [os.getpid(), *args.owned_pid])
                if report['sample_count'] == 0 and not observation['root_present']:
                    raise RuntimeError('Benchmark PID is not live at monitor start')
                observation.update(observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                   elapsed_seconds=time.monotonic() - started)
                stream.write(json.dumps(observation) + '\n')
                stream.flush()
                report['sample_count'] += 1
                report['external_build_observations'] += int(observation['external_build_process_count'] > 0)
                report['max_external_build_process_count'] = max(report['max_external_build_process_count'], observation['external_build_process_count'])
                if not observation['root_present']:
                    report.update(completed=True, stop_reason='benchmark_process_ended')
                    break
                if observation['elapsed_seconds'] >= args.max_seconds:
                    report['stop_reason'] = 'observation_duration_reached'
                    break
                write_report(output, report)
                time.sleep(args.interval)
    except BaseException as error:
        report.update(error_type=type(error).__name__, stop_reason='observation_failed')
        raise
    finally:
        if samples.exists():
            report['samples_sha256'] = hashlib.sha256(samples.read_bytes()).hexdigest()
        report['elapsed_seconds'] = time.monotonic() - started
        write_report(output, report)


if __name__ == '__main__':
    main()
