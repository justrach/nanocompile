#!/usr/bin/env python3
"""Bounded, local-only archive A/B check; never emits private cache names.

Example (run serially, not alongside other performance experiments):
  python3 benchmarks/experiments/archive_hill_check.py BASELINE CANDIDATE \
      --cache-dir CACHE_ROOT --output REPORT.json

Only _store_archive is timed. Copying, hashing, archive comparison and restore
checks are outside both clocks. Confirmation uses fresh temporary fixture and
output directories, not a claim of cold filesystem caches. Imports run in one
process; use trusted modules only. Input cache files are read, never modified.
"""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import statistics
import sys
import tempfile
import time

ROOTS = ('swc', 'webpack')
MAX_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 10000
CHUNK = 1024 * 1024


class CheckFailed(Exception):
    pass


class PrivateParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's normal diagnostics can echo private argument values.
        self.print_usage(sys.stderr)
        self.exit(2, 'Invalid arguments; see --help.\n')


def require(condition):
    if not condition:
        raise CheckFailed()


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(callable(module._store_archive) and callable(module._restore))
    return module


def nodes(root):
    """Walk only plain directories and singly linked regular files, bounded."""
    count = 0
    require(root.is_dir() and not root.is_symlink())
    for name in ROOTS:
        target = root / name
        require(target.is_dir() and not target.is_symlink())
        for current, dirs, files in os.walk(target, followlinks=False):
            dirs.sort()
            files.sort()
            # Validate child directories before os.walk can descend into them.
            for child in dirs:
                require(stat.S_ISDIR((Path(current) / child).lstat().st_mode))
            for path in [Path(current)] + [Path(current) / f for f in files]:
                info = path.lstat()
                directory = stat.S_ISDIR(info.st_mode)
                require(directory or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1))
                count += 1
                require(count <= MAX_MEMBERS)
                yield path, path.relative_to(root), directory


def copy_fixture(source, destination):
    """Snapshot with bounded streaming reads; refuse unsafe nodes, no hardlinks."""
    destination.mkdir()
    total = 0
    for path, relative, directory in nodes(source):
        output = destination / relative
        if directory:
            output.mkdir()
        else:
            with path.open('rb') as src, output.open('xb') as dst:
                while chunk := src.read(CHUNK):
                    total += len(chunk)
                    require(total <= MAX_BYTES)
                    dst.write(chunk)
    return destination


def manifest(root):
    files, directories, total = {}, set(), 0
    for path, relative, directory in nodes(root):
        if directory:
            directories.add(relative)
        else:
            digest = hashlib.sha256()
            size = 0
            with path.open('rb') as stream:
                while chunk := stream.read(CHUNK):
                    size += len(chunk)
                    total += len(chunk)
                    require(total <= MAX_BYTES)
                    digest.update(chunk)
            files[relative] = (size, digest.digest())
    return files, directories


def equal_archives(first, second):
    if first.stat().st_size != second.stat().st_size:
        return False
    with first.open('rb') as a, second.open('rb') as b:
        while True:
            left, right = a.read(CHUNK), b.read(CHUNK)
            if left != right:
                return False
            if not left:
                return True


def trial(module, fixture, expected, archive, project):
    targets = [fixture / name for name in ROOTS]
    wall_start = time.perf_counter_ns()
    cpu_start = time.process_time_ns()
    stored = module._store_archive(archive, targets)
    cpu_ns = time.process_time_ns() - cpu_start
    wall_ns = time.perf_counter_ns() - wall_start
    # Everything below is deliberately outside the measured interval.
    require(stored and archive.is_file() and archive.stat().st_size <= MAX_BYTES)
    project.mkdir()
    require(module._restore(archive, project, '.next'))
    require(manifest(project / '.next' / 'cache') == expected)
    shutil.rmtree(project)
    return {'wall_ns': wall_ns, 'cpu_ns': cpu_ns}


def measure(modules, source, directory, pairs, phase_offset):
    directory.mkdir()
    fixture = copy_fixture(source, directory / 'fixture')
    expected = manifest(fixture)
    raw, archives_identical, restores_verified = [], 0, 0
    archive_bytes = None
    for index in range(pairs):
        order = ('A', 'B') if (index + phase_offset) % 2 == 0 else ('B', 'A')
        sample = {'order': ''.join(order)}
        for label in order:
            sample[label] = trial(modules[label], fixture, expected,
                                  directory / (label + '.tar'),
                                  directory / 'restore')
            restores_verified += 1
        first, second = directory / 'A.tar', directory / 'B.tar'
        require(equal_archives(first, second))
        archives_identical += 1
        if archive_bytes is None:
            archive_bytes = first.stat().st_size
        require(archive_bytes == first.stat().st_size)
        first.unlink()
        second.unlink()
        raw.append(sample)
    require(manifest(fixture) == expected)
    medians = {
        label: {metric: statistics.median(row[label][metric] for row in raw)
                for metric in ('wall_ns', 'cpu_ns')}
        for label in ('A', 'B')
    }
    ratios = {
        metric: statistics.median(row['B'][metric] / max(1, row['A'][metric])
                                  for row in raw)
        for metric in ('wall_ns', 'cpu_ns')
    }
    return {
        'file_count': len(expected[0]),
        'file_bytes': sum(size for size, _ in expected[0].values()),
        'archive_bytes': archive_bytes,
        'raw_times': raw,
        'median_times': medians,
        'median_candidate_over_baseline_time_ratio': ratios,
        'checks': {'byte_identical_pairs': archives_identical,
                   'all_file_hash_restores': restores_verified,
                   'fixture_unchanged': True},
    }


def synthetic_fixture(root):
    root.mkdir()
    for name in ROOTS:
        target = root / name
        target.mkdir()
        for bucket in range(8):
            folder = target / str(bucket)
            folder.mkdir()
            for index in range(64):
                (folder / str(index)).write_bytes(bytes([index]) * 1024)
    return root


def run(args):
    # No import bytecode, module output, tracebacks, hashes, paths or identifiers
    # are included in the report. A/B labels mean baseline/candidate respectively.
    modules = {'A': load_module(args.baseline, '_archive_hill_baseline'),
               'B': load_module(args.candidate, '_archive_hill_candidate')}
    with tempfile.TemporaryDirectory(prefix='archive-hill-') as temporary:
        root = Path(temporary)
        real = copy_fixture(Path(args.cache_dir), root / 'real')
        real_manifest = manifest(real)
        require(sum(size for size, _ in real_manifest[0].values()) >= 1024 * 1024)
        small = synthetic_fixture(root / 'small')
        report = {}
        for offset, phase in enumerate(('initial', 'fresh_confirmation')):
            report[phase] = {}
            for name, fixture in (('real_multi_mb', real), ('many_small', small)):
                report[phase][name] = measure(
                    modules, fixture, root / (phase + '-' + name), args.pairs, offset)
        return report


def main():
    parser = PrivateParser(description=__doc__)
    parser.add_argument('baseline', help='baseline Python module')
    parser.add_argument('candidate', help='candidate Python module')
    parser.add_argument('--cache-dir', required=True, help='read-only real swc/webpack cache root')
    parser.add_argument('--output', required=True, help='new aggregate-only JSON report')
    parser.add_argument('--pairs', type=int, default=9,
                        help='alternating pairs per workload per phase (1..31; default 9)')
    args = parser.parse_args()
    if not 1 <= args.pairs <= 31:
        parser.error('invalid pair count')
    sys.dont_write_bytecode = True
    try:
        # Suppress incidental output from trusted imported modules as well.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            report = run(args)
        # Exclusive creation avoids overwriting any existing (possibly private) file.
        with Path(args.output).open('x') as output:
            json.dump(report, output, indent=2, sort_keys=True)
            output.write('\n')
    except Exception:
        print('Archive check failed; no private diagnostics emitted.', file=sys.stderr)
        return 1
    print('Archive check passed; aggregate-only report written.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
