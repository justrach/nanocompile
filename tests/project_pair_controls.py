"""Regression checks for the declared versus executed benchmark intervention."""
import argparse
import contextlib
import io
import unittest

from project_pair_comparison import build_environment, runtime_comparison


class RuntimeControlTests(unittest.TestCase):
    def parse(self, values, hashes=None):
        return runtime_comparison(argparse.ArgumentParser(), values,
                                  hashes or {'baseline': 'same', 'candidate': 'same'})

    def test_only_one_recorded_control_changes_measured_builds(self):
        control = self.parse(['NANOCOMPILE_PRODUCER_GRAPH_WORKERS', '0', '4'])
        common = {'NANOCOMPILE_DIR': '/private/cache', 'RUSTC_WRAPPER': '/private/wrapper'}
        original = dict(common)
        for phase in ('prime', 'cold', 'warm'):
            baseline = build_environment(common, 'baseline', phase, control, None)
            candidate = build_environment(common, 'candidate', phase, control, None)
            self.assertEqual({k for k in baseline if baseline[k] != candidate[k]}, {control['name']})
            for mode, env in [('baseline', baseline), ('candidate', candidate)]:
                self.assertEqual(env[control['name']], control['values'][mode])
                self.assertNotIn('NANOCOMPILE_TRACE', env)
        self.assertEqual(common, original)

    def test_activation_trace_cannot_leak_into_measured_builds(self):
        control = self.parse(['NANOCOMPILE_PRODUCER_GRAPH_WORKERS', '0', '4'])
        common = {'NANOCOMPILE_DIR': '/private/cache'}
        for phase in ('prime', 'cold', 'warm'):
            for mode in ('baseline', 'candidate'):
                env = build_environment(common, mode, phase, control, 'graph: parallel producer roots')
                self.assertEqual(env.get('NANOCOMPILE_TRACE') == '1',
                                 phase == 'prime' and mode == 'candidate')
        self.assertNotIn('NANOCOMPILE_TRACE', common)

    def test_reject_confounded_or_unsafe_interventions(self):
        cases = [
            (['NANOCOMPILE_PRODUCER_GRAPH_WORKERS', '0', '4'], {'baseline': 'one', 'candidate': 'two'}),
            (['NANOCOMPILE_PRODUCER_GRAPH_WORKERS', '4', '4'], None),
            (['NANOCOMPILE_PRODUCER_GRAPH_WORKERS', '0', '400'], None),
            (['NANOCOMPILE_DIR', '0', '1'], None),
            (['R2_SECRET_ACCESS_KEY', '0', '1'], None),
            (['NANOCOMPILE_UNKNOWN_EXPERIMENT', '0', '1'], None),
        ]
        for values, hashes in cases:
            with self.subTest(control=values), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    self.parse(values, hashes)
                self.assertEqual(error.exception.code, 2)

    def test_ordinary_two_binary_mode_keeps_its_environment(self):
        self.assertIsNone(self.parse(None, {'baseline': 'one', 'candidate': 'two'}))
        common = {'NANOCOMPILE_DIR': '/private/cache'}
        self.assertEqual(build_environment(common, 'candidate', 'prime', None, None), common)


if __name__ == '__main__':
    unittest.main()
