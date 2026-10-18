#!/usr/bin/env python3
"""Real local savings checks: declared Zig object builds, no uploaded diagnostics.

The shared export (when explicitly requested) contains aggregate metrics only.
All project/specification/prepare files and raw records remain temporary.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from task_layering import OVERRIDES, resources_under

TOOL = ROOT / 'tools/cache_savings.py'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(command, *, cwd, env, expected=0):
    result = subprocess.run([str(x) for x in command], cwd=cwd, env=env,
                            capture_output=True, timeout=300)
    require(result.returncode == expected, 'savings fixture command failed')
    return result


def make_project(root, zig, env):
    info = run([zig, 'env'], cwd=root, env=env).stdout.decode()
    paths = {}
    for name in ('zig_exe', 'lib_dir'):
        match = re.search(r'\.' + name + r'\s*=\s*("(?:[^"\\]|\\.)*")', info)
        require(match is not None, 'unsupported Zig environment response')
        paths[name] = Path(json.loads(match.group(1))).resolve(strict=True)
    compiler = paths['zig_exe']
    require(run([compiler, 'version'], cwd=root, env=env).stdout.strip() == b'0.17.0',
            'savings fixture requires Zig 0.17.0')
    links = {}
    resources = [str(compiler)] + sorted(resources_under(paths['lib_dir'], links))
    (root / 'links.json').write_text(json.dumps(links, sort_keys=True))
    (root / 'source.zig').write_text('export fn answer() u32 { return 42; }\n')
    # Object-only output avoids runtime/SDK dependencies and is supported on all
    # CI hosts. Full installed Zig resources still participate in the task key.
    command = [str(compiler), 'build-obj', 'source.zig', '-OReleaseFast', '-fstrip',
               '-femit-bin=artifact.o', '--cache-dir', str(root / 'zig-local')]
    spec = {'schema': 1, 'tasks': [{
        'name': 'private-fixture-name', 'command': command,
        'inputs': ['source.zig', 'links.json'], 'outputs': ['artifact.o'],
        'tool_resources': sorted(set(resources)),
    }]}
    spec_path = root / 'private-spec.json'
    spec_path.write_text(json.dumps(spec))
    (root / 'prepare-command.json').write_text(json.dumps(command))
    # Both sides of a measured pair get the same real warm compiler cache,
    # not a cold compiler compared with a Nano restore. Preparation is measured
    # separately; the paired speedup is explicitly process-wall-only.
    (root / 'prepare.py').write_text(
        "import json, subprocess\nfrom pathlib import Path\n"
        "command = json.loads(Path('prepare-command.json').read_text())\n"
        "subprocess.run(command, check=True, capture_output=True)\n"
        "Path('artifact.o').unlink()\n")
    return spec_path


def assert_private_free(value, root, binary):
    encoded = json.dumps(value)
    for forbidden in (str(root), str(binary), 'private-fixture-name',
                      'private-spec.json', 'source.zig', 'artifact.o',
                      'SECRET_SAVINGS_CANARY', 'prepare-command.json'):
        require(forbidden not in encoded, 'private fixture details entered metrics')


def exercise(binary, root, env, setup_report=None, anonymous_output=None):
    import cache_savings as savings
    started = time.perf_counter()
    zig = shutil.which('zig')
    require(zig is not None, 'Zig executable is unavailable')
    spec = make_project(root, zig, env)
    fixture_setup = time.perf_counter() - started
    setup_seconds = None
    if setup_report is not None:
        setup_seconds = savings.number(savings.load(setup_report)['setup_seconds']) + fixture_setup
    machine = __import__('platform').machine().lower()
    target = {'arm64': 'aarch64', 'amd64': 'x86_64', 'aarch64': 'aarch64',
              'x86_64': 'x86_64'}.get(machine, 'other')
    base = [sys.executable, '-I', '-S', '-B', str(TOOL)]
    records, filenames = [], []
    reference = None
    for index in range(6):
        (root / 'artifact.o').unlink(missing_ok=True)
        destination = root / ('record-%d.json' % index)
        command = base + ['record', '--binary', str(binary), '--spec', str(spec),
                          '--target', target, '--transfer-seconds', '0', '--output', str(destination)]
        # Attribute this invocation series' observed tool/fixture setup once,
        # not once per build. An omitted external setup remains unknown.
        cost = setup_seconds if index == 0 else 0
        if cost is not None:
            command += ['--setup-seconds', str(cost)]
        run(command, cwd=root, env=env)
        record = savings.load(destination)
        assert_private_free(record, root, binary)
        require(record['status'] == 'ok', 'native measurement was incomplete')
        outcome = 'miss' if index == 0 else 'hit'
        require(record['task_counts'][outcome] == 1, 'unexpected build-cache outcome')
        metrics = record['metrics']
        require(metrics['task_lookup_seconds'] > 0, 'lookup timing missing')
        require(metrics['task_restore_seconds'] == 0 if index == 0 else
                metrics['task_restore_seconds'] > 0, 'restore timing incorrect')
        require(metrics['task_child_seconds'] > 0 if index == 0 else
                metrics['task_child_seconds'] == 0, 'build-command timing incorrect')
        output = (root / 'artifact.o').read_bytes()
        require(metrics['artifact_bytes'] == len(output), 'artifact size incorrect')
        if reference is None:
            reference = output
        else:
            require(output == reference, 'restored compiler artifact differs')
        records.append(record)
        filenames.append(str(destination))
    local = root / 'local.json'
    run(base + ['summary'] + filenames + ['--output', str(local)], cwd=root, env=env)
    summary = savings.load(local)
    require(summary['aggregate']['samples'] == 6, 'sample count incorrect')
    require(summary['aggregate']['hit_rate'] == 5 / 6, 'hit rate incorrect')
    require(summary['measured_speedup'] is None, 'ordinary builds invented a speedup')
    require(summary['estimated_savings'] is None, 'ordinary builds invented savings')
    estimate = root / 'estimate.json'
    run(base + ['summary'] + filenames[1:] + ['--baseline', filenames[0],
        '--attest-comparable', '--output', str(estimate)], cwd=root, env=env)
    historical = savings.load(estimate)
    require(historical['estimated_savings']['baseline_kind'] == 'miss', 'missing miss-baseline provenance')
    require(not historical['estimated_savings']['controlled_measurement'], 'estimate mislabeled as measured')
    prepare = [sys.executable, '-I', '-S', '-B', 'prepare.py']
    comparison_path = root / 'comparison.json'
    compare = base + ['compare', '--binary', str(binary), '--spec', str(spec),
        '--prepare-json', json.dumps(prepare), '--artifact', str(root / 'artifact.o'),
        '--pairs', '5', '--compiler-cache-condition', 'warm', '--attest-comparable',
        '--target', target, '--output', str(comparison_path)]
    for name in ('source.zig', 'links.json', 'prepare.py', 'prepare-command.json'):
        compare += ['--snapshot', str(root / name)]
    run(compare, cwd=root, env=env)
    comparison = savings.load(comparison_path)
    require(comparison['enabled']['task_counts']['hit'] == 5, 'enabled pairs did not hit')
    require(comparison['bypass']['task_counts']['bypass'] == 5, 'bypass not observed')
    measured = comparison['measured_speedup']
    require(measured['pairs'] == 5 and measured['compiler_cache_condition'] == 'warm',
            'paired provenance missing')
    require(measured['artifact_bytes_and_permissions_equal'], 'paired artifacts not checked')
    require(comparison['preparation']['enabled_seconds'] > 0 and
            comparison['preparation']['bypass_seconds'] > 0, 'preparation overhead missing')
    # Export must reject implicit consent and undersized cohorts, leaving no file.
    rejected = root / 'rejected-export.json'
    run(base + ['export'] + filenames + ['--output', str(rejected)], cwd=root, env=env, expected=2)
    run(base + ['export'] + filenames[:4] + ['--opt-in-anonymous-export', '--output', str(rejected)],
        cwd=root, env=env, expected=2)
    require(not rejected.exists(), 'rejected export wrote data')
    if anonymous_output is not None:
        run(base + ['export'] + filenames + ['--opt-in-anonymous-export', '--output', str(anonymous_output)],
            cwd=root, env=env)
        shared = savings.load(anonymous_output)
        assert_private_free(shared, root, binary)
        require(shared['aggregate']['samples'] == 6, 'anonymous sample count incorrect')
        require(shared['kind'] == 'anonymous_cache_aggregates', 'raw records exported')
    result = {'schema': 1, 'kind': 'local_savings_fixture',
        'observed': summary, 'historical_estimate': historical['estimated_savings'],
        'controlled_comparison': comparison,
        'limitations': ['Small Zig object fixture, not production throughput or hosted CI evidence.',
            'External transfer is zero: no remote artifact/cache transfer occurs in this fixture.',
            'Initial observed external/fixture setup is attributed once; only observer-supplied external costs are included.',
            'Paired process speedup excludes measured preparation and unknown external installation/transfer costs.',
            'Every pair primes the identical compiler command and deletes output before each timed build.',
            'Project/prepare files are snapshotted; installed Zig resources must remain stable throughout.',
            'Historical miss-based savings are uncontrolled estimates, not measured speedups.']}
    assert_private_free(result, root, binary)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--setup-report', type=Path)
    parser.add_argument('--summary', type=Path)
    parser.add_argument('--anonymous-output', type=Path,
                        help='explicitly opt into a local anonymous aggregate file; never uploads')
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    report = args.setup_report.resolve(strict=True) if args.setup_report else None
    anonymous = args.anonymous_output.resolve() if args.anonymous_output else None
    env = {k: v for k, v in os.environ.items() if not k.startswith('NANOCOMPILE_')}
    for name in OVERRIDES:
        env.pop(name, None)
    # Synthetic canary must never appear in records, summaries or export.
    env['PRIVATE_SAVINGS_TEST'] = 'SECRET_SAVINGS_CANARY'
    with tempfile.TemporaryDirectory(prefix='nano-savings-fixture-') as directory:
        root = Path(directory).resolve()
        env.update(NANOCOMPILE_DIR=str(root / 'nano'), ZIG_GLOBAL_CACHE_DIR=str(root / 'zig-global'))
        result = exercise(binary, root, env, report, anonymous)
    if args.summary is not None:
        import cache_savings as savings
        savings.write(args.summary, result)
    print('PASS: six real builds, five matched warm-compiler pairs, privacy and export consent checks')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.TimeoutExpired):
        raise SystemExit('FAIL: savings fixture failed; no private command or diagnostic output published')
