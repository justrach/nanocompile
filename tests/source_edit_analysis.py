"""Ensure edit reports retain failures, separate references and reject tampered logs."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from source_edit_analysis import analyze


class SourceEditAnalysis(unittest.TestCase):
    def test_integrity_and_failed_comparisons(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            raw = b'complete private console\n'
            (state / 'build.log').write_bytes(raw)
            record = dict(path='build.log', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            def build(impl, phase, seconds, exit_code=0):
                return dict(implementation=impl, phase=phase, scenario='shared-edit',
                    seconds=seconds, exit_code=exit_code, cli_help_valid=exit_code == 0,
                    events={}, build_log=record, verification=phase == 'empty-cache-reference')
            data = dict(completed=False, builds=[build('nanocompile', 'edit', 12),
                build('kache', 'edit', 10), build('nanocompile', 'empty-cache-reference', 100)])
            report = state / 'report.json'
            report.write_text(json.dumps(data))
            output = state / 'analysis'
            result = analyze(report, state, output)
            self.assertFalse(result['completed'])
            self.assertEqual(len(result['samples']), 3)
            self.assertEqual(result['comparisons'][0]['nano_minus_kache_seconds'], 2)
            self.assertIn('INCOMPLETE', (output / 'next-experiments.md').read_text())
            data['builds'][1]['exit_code'] = 1
            report.write_text(json.dumps(data))
            result = analyze(report, state, output)
            self.assertIsNone(result['comparisons'][0]['nano_minus_kache_seconds'])
            self.assertEqual(result['samples'][1]['exit_code'], 1)
            (state / 'build.log').write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                analyze(report, state, state / 'must-not-exist')
            self.assertFalse((state / 'must-not-exist').exists())

    def test_duplicate_samples_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp)
            (state / 'build.log').write_bytes(b'')
            sample = dict(implementation='nanocompile', phase='edit', scenario='revert',
                seconds=1, exit_code=0, build_log=dict(path='build.log', bytes=0,
                sha256=hashlib.sha256(b'').hexdigest()))
            report = state / 'report.json'
            report.write_text(json.dumps(dict(builds=[sample, sample])))
            with self.assertRaises(ValueError):
                analyze(report, state, state / 'out')


if __name__ == '__main__':
    unittest.main()
