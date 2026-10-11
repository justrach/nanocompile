"""Synthetic checks for tools/rust_profile.py scheduling, critical path and diff attribution."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import rust_profile  # noqa: E402


def unit(i, name, start, duration, unblocked=(), rmeta_unblocked=(), target='', mode='todo', frontend=None):
    sections = None if frontend is None else [['frontend', {'start': 0.0, 'end': frontend}],
                                               ['codegen', {'start': frontend, 'end': duration}]]
    return dict(i=i, name=name, version='0.1.0', mode=mode, target=target, features=[], start=start,
                duration=duration, unblocked_units=list(unblocked), unblocked_rmeta_units=list(rmeta_unblocked),
                sections=sections)


def node(name, deps, kind=('lib',), crate_types=('lib',), mode='build'):
    return dict(pkg_id=f'path+file:///{name}#0.1.0', target=dict(kind=list(kind), crate_types=list(crate_types), name=name),
                mode=mode, features=[], dependencies=[dict(index=d) for d in deps])


class ProfileTests(unittest.TestCase):
    def write(self, directory, name, units, graph=None):
        html = Path(directory) / f'{name}.html'
        html.write_text('<script>\nconst UNIT_DATA = ' + json.dumps(units) + ';\nconst CONCURRENCY_DATA = [];\n</script>')
        path = None
        if graph is not None:
            path = Path(directory) / f'{name}.json'
            path.write_text(json.dumps(dict(version=1, units=graph, roots=[len(graph) - 1])))
        return html, path

    def fixture(self, directory, b_duration=1.0, name='build'):
        # a (lib, rmeta at 0.5) -> b (lib, pipelined) -> c (bin, needs full b); d is independent.
        units = [unit(0, 'a', 0.0, 1.0, rmeta_unblocked=[1], frontend=0.5),
                 unit(1, 'b', 0.5, b_duration, unblocked=[2], frontend=b_duration / 2),
                 unit(2, 'c', 0.5 + b_duration, 0.25, target='c "bin"'),
                 unit(3, 'd', 0.0, 0.5)]
        graph = [node('a', []), node('b', [0]), node('c', [1], kind=('bin',), crate_types=('bin',)), node('d', [])]
        return self.write(directory, name, units, graph)

    def test_pipelined_schedule_matches_cargo_and_critical_path(self):
        with tempfile.TemporaryDirectory() as directory:
            html, graph = self.fixture(directory)
            build = rust_profile.Build(html, graph)
            self.assertTrue(build.rmeta_ok[(0, 1)])
            self.assertFalse(build.rmeta_ok[(1, 2)])
            schedule = rust_profile.simulate(build, jobs=2)
            self.assertAlmostEqual(schedule['start'][1], 0.5)
            self.assertAlmostEqual(schedule['wall'], 1.75)
            path = [step['label'].split()[0] for step in rust_profile.critical_path(build, schedule)]
            self.assertEqual(path, ['a', 'b', 'c'])

    def test_one_job_serializes_by_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            html, graph = self.fixture(directory)
            build = rust_profile.Build(html, graph)
            schedule = rust_profile.simulate(build, jobs=1)
            self.assertAlmostEqual(schedule['wall'], 2.75)
            # 'a' has transitive dependents, so it runs before independent 'd'.
            self.assertLess(schedule['start'][0], schedule['start'][3])

    def test_inferred_graph_and_observed_path(self):
        with tempfile.TemporaryDirectory() as directory:
            html, _ = self.fixture(directory)
            build = rust_profile.Build(html)
            observed = rust_profile.observed_schedule(build)
            self.assertEqual([s['unit'] for s in rust_profile.critical_path(build, observed)], [0, 1, 2])

    def test_diff_attributes_wall_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            base, graph = self.fixture(directory, 1.0, 'base')
            other, _ = self.fixture(directory, 0.5, 'other')
            out = Path(directory) / 'diff.json'
            with contextlib.redirect_stdout(io.StringIO()):
                rust_profile.main(['diff', str(base), str(other), '--unit-graph', str(graph), '--jobs', '2', '--spawn', '0', '--json', str(out)])
            report = json.loads(out.read_text())
            self.assertAlmostEqual(report['simulated']['baseline'] - report['simulated']['baseline_with_candidate_durations'], 0.5)
            self.assertAlmostEqual(report['category_wall_effect']['library'], 0.5)

    def test_calibration_matches_observed_wall(self):
        with tempfile.TemporaryDirectory() as directory:
            units = [unit(i, f'u{i}', 0.0, 0.1) for i in range(4)]
            units = [dict(u, start=0.1 * i + 0.01 * i) for i, u in enumerate(units)]
            html, _ = self.write(directory, 'serial', units)
            build = rust_profile.Build(html)
            spawn = rust_profile.calibrate(build, jobs=1)
            self.assertAlmostEqual(rust_profile.simulate(build, 1, spawn=spawn)['wall'], build.end, places=4)

    def test_rejects_mismatched_unit_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            html, _ = self.fixture(directory)
            _, graph = self.write(directory, 'small', [unit(0, 'a', 0, 1)], [node('a', [])])
            with self.assertRaises(SystemExit):
                rust_profile.Build(html, graph)


if __name__ == '__main__':
    unittest.main()
