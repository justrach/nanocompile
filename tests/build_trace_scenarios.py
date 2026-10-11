"""Prevent misleading comparisons between different source-edit workloads."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from build_trace import analyze


def sample(tool, scenario, seconds, verification=False):
    return dict(implementation=tool, phase='edit', scenario=scenario,
                verification=verification, trace=dict(requests=[
                    dict(name='harness', kind='rust', seconds=seconds, start_seconds=0)],
                    cargo_units=[], kache_service_events=[]))


class Scenarios(unittest.TestCase):
    def run_analysis(self, builds):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        report = root/'report.json'
        report.write_text(json.dumps(dict(builds=builds)))
        output = root/'analysis'
        result = analyze(report, output)
        return result, output

    def test_missing_counterpart_in_same_scenario_is_unknown(self):
        result, output = self.run_analysis([
            sample('nanocompile', 'leaf-edit', 1), sample('kache', 'shared-edit', 10)])
        self.assertEqual(len(result['comparisons']), 2)
        self.assertTrue(all(r['nano_minus_kache_seconds'] is None for r in result['comparisons']))
        self.assertEqual(json.loads((output/'experiments.json').read_text())['experiments'], [])

    def test_separate_edits_and_fresh_references(self):
        builds = [sample('nanocompile', 'leaf-edit', 1), sample('kache', 'leaf-edit', 2),
                  sample('nanocompile', 'shared-edit', 10), sample('kache', 'shared-edit', 3),
                  sample('nanocompile', 'shared-edit', 100, True),
                  sample('kache', 'shared-edit', 20, True)]
        result, output = self.run_analysis(builds)
        rows = {(r['scenario'], r['verification']): r for r in result['comparisons']}
        self.assertEqual(rows['leaf-edit', False]['nano_minus_kache_seconds'], -1)
        self.assertEqual(rows['shared-edit', False]['nano_minus_kache_seconds'], 7)
        self.assertEqual(rows['shared-edit', True]['nano_minus_kache_seconds'], 80)
        self.assertTrue(all(r['nanocompile']['samples'] == 1 for r in rows.values()))
        experiments = json.loads((output/'experiments.json').read_text())['experiments']
        self.assertEqual(len(experiments), 1)
        self.assertEqual(experiments[0]['observation']['scenario'], 'shared-edit')
        self.assertFalse(experiments[0]['observation']['verification'])
        events = json.loads((output/'trace.json').read_text())['traceEvents']
        names = [e['args']['name'] for e in events if e['ph'] == 'M']
        self.assertIn('verification', names[-1])
        self.assertIn('leaf-edit', names[0])


if __name__ == '__main__':
    unittest.main()
