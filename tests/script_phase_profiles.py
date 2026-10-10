"""Verify phase-log integrity, malformed events, missing evidence and safe reports."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from build_trace import Capture, analyze, verify_capture
from script_phase_profiles import collect


class Profiles(unittest.TestCase):
    def test_new_capture_embeds_verified_source_profiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'target'
            stderr = target / 'release/build/example-deadbeef/stderr'
            stderr.parent.mkdir(parents=True)
            stderr.write_text('nanocompile: script-phase restore.total ns=2500000\n')
            log = root / 'build.log'
            log.write_text('whole console\n')
            capture = Capture.__new__(Capture)
            capture.directory = root / 'capture'
            capture.directory.mkdir()
            # Direct mode permits a fixture without compiler frontend records.
            row = dict(implementation='direct')
            capture.finish(row, target, 0, root / 'missing-events', 0, log)
            self.assertEqual(verify_capture(capture.directory)['compiler_records'], 0)
            profiles = row['trace']['script_phase_profiles']
            self.assertEqual(len(profiles), 1)
            self.assertEqual(profiles[0]['median_seconds'], .0025)
            copied = capture.directory / profiles[0]['source_record']
            self.assertEqual(copied.read_bytes(), stderr.read_bytes())
            self.assertEqual(profiles[0]['source_sha256'], hashlib.sha256(copied.read_bytes()).hexdigest())

    def test_verified_private_evidence_and_safe_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture = root / 'capture'
            stderr = capture / 'build-script-outputs/<unsafe>-deadbeef/stderr'
            stderr.parent.mkdir(parents=True)
            raw = ('private-secret-sentinel\n'
                   'nanocompile: script-phase input_snapshot ns=1000000\n'
                   'nanocompile: script-phase input_snapshot ns=3000000\n'
                   'nanocompile: script-phase material.total ns=5000000\n'
                   'nanocompile: script-phase bad ns=-1\n'
                   'nanocompile: script-phase bad ns=9223372036854775808\n'
                   'nanocompile: script-phase bad ns=' + '9'*5000 + '\n'
                   'foreign: script-phase bad ns=5\n').encode()
            stderr.write_bytes(raw)
            name = str(stderr.relative_to(capture))
            manifest = dict(schema=1, compiler_records=0, cargo_units=0,
                            files={name: dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())})
            (capture / 'manifest.json').write_text(json.dumps(manifest))
            rows = collect(capture)
            self.assertEqual(len(rows), 2)
            snapshot = next(row for row in rows if row['stage'] == 'input_snapshot')
            self.assertEqual(snapshot['samples_ns'], [1000000, 3000000])
            self.assertEqual(snapshot['median_seconds'], .002)
            self.assertEqual(snapshot['source_sha256'], manifest['files'][name]['sha256'])
            report = root / 'report.json'
            data = dict(script_profile=True, builds=[dict(implementation='nanocompile', phase='warm',
                        trace=dict(capture_directory=str(capture)))])
            report.write_text(json.dumps(data))
            result = analyze(report, root / 'analysis')
            self.assertEqual(result['script_profile_coverage'][0]['status'], 'verified_private_capture')
            for file in (root / 'analysis').iterdir():
                self.assertNotIn('private-secret-sentinel', file.read_text())
            html = (root / 'analysis/index.html').read_text()
            self.assertIn('&lt;unsafe&gt;', html)
            self.assertNotIn('<unsafe>', html)
            brief = (root / 'analysis/next-experiments.md').read_text()
            self.assertIn('input_snapshot', brief)
            self.assertNotIn('/ material.total:', brief)
            stderr.write_bytes(raw + b'tampered')
            with self.assertRaisesRegex(ValueError, 'differs from manifest'):
                analyze(report, root / 'tampered')
            stderr.unlink()
            with self.assertRaisesRegex(ValueError, 'file set differs'):
                analyze(report, root / 'missing-file')
            del data['builds'][0]['trace']['capture_directory']
            report.write_text(json.dumps(data))
            result = analyze(report, root / 'public-missing')
            self.assertEqual(result['script_profile_coverage'][0]['status'], 'unavailable')
            self.assertEqual(result['script_phase_profiles'], [])
            data['builds'][0]['trace']['script_phase_profiles'] = rows
            report.write_text(json.dumps(data))
            result = analyze(report, root / 'embedded')
            self.assertEqual(result['script_profile_coverage'][0]['status'], 'embedded')
            self.assertEqual(len(result['script_phase_profiles']), 2)
            data['builds'][0]['exit_code'] = 1
            report.write_text(json.dumps(data))
            result = analyze(report, root / 'failed')
            self.assertEqual(result['script_phase_profiles'], [])
            self.assertEqual(len(result['excluded_builds']), 1)


if __name__ == '__main__':
    unittest.main()
