"""Verify request phase coverage, nested timing semantics and safe extraction."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from compiler_phase_profiles import collect
from build_trace import analyze, Capture, verify_capture


class CompilerPhases(unittest.TestCase):
    def test_observed_stages_and_untrusted_streams(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'manifest.json').write_text('{"schema":1}')
            (root/'one.json').write_text(json.dumps(dict(exit_code=0,args=['rustc','--crate-name','harness'])))
            raw = b'private-secret\nnanocompile: compiler-phase producer.total ns=900000000\nnanocompile: compiler-phase restore.total ns=800000000\nnanocompile: compiler-phase restore.total ns=600000000\nnanocompile: compiler-phase invalid ns=-1\nnanocompile: compiler-phase overflow ns=9223372036854775808\nnanocompile: compiler-phase trailing ns=3 junk\n'
            (root/'one.stderr').write_bytes(raw)
            (root/'failed.json').write_text(json.dumps(dict(exit_code=1,args=['rustc','--crate-name','broken'])))
            (root/'failed.stderr').write_text('nanocompile: compiler-phase producer.total ns=9999999999\n')
            result = collect(root)
            self.assertEqual(len(result),2)
            stage = {row['stage']:row for row in result}
            self.assertEqual(stage['restore.total']['samples_ns'],[800000000,600000000])
            self.assertEqual(stage['restore.total']['median_seconds'],.7)
            self.assertEqual(stage['producer.total']['median_seconds'],.9)
            self.assertEqual(stage['restore.total']['source_sha256'],hashlib.sha256(raw).hexdigest())
            self.assertEqual(stage['restore.total']['source_bytes'],len(raw))
            self.assertNotIn('private-secret',json.dumps(result))
            self.assertTrue(all(row['request']=='harness' for row in result))
            # Keep nested observations separate; no combined savings/total row.
            self.assertEqual(set(stage),{'producer.total','restore.total'})

    def test_verified_capture_backfill_and_missing_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);directory=root/'capture';directory.mkdir()
            record=dict(args=['rustc','--crate-name','<unsafe>'],exit_code=0,start_ns=0,end_ns=3,user_us=0,system_us=0)
            (directory/'request.json').write_text(json.dumps(record))
            raw=b'private-secret\nnanocompile: compiler-phase producer.restore ns=700000000\n'
            (directory/'request.stderr').write_bytes(raw);(directory/'request.stdout').write_bytes(b'')
            capture=Capture.__new__(Capture);capture.directory=directory
            build=dict(implementation='nanocompile',phase='warm')
            capture.finish(build,root/'target',0,root/'missing',0)
            self.assertEqual(verify_capture(directory)['compiler_records'],1)
            self.assertEqual(len(build['trace']['compiler_phase_profiles']),1)
            # Backfill uses every manifest file, not just the phase stream.
            del build['trace']['compiler_phase_profiles']
            data=dict(compiler_profile=True,builds=[build]);report=root/'report.json';report.write_text(json.dumps(data))
            result=analyze(report,root/'analysis')
            self.assertEqual(result['compiler_profile_coverage'][0]['status'],'verified_private_capture')
            self.assertEqual(result['compiler_phase_profiles'][0]['median_seconds'],.7)
            self.assertIn('&lt;unsafe&gt;', (root/'analysis/index.html').read_text())
            for file in (root/'analysis').iterdir():self.assertNotIn('private-secret',file.read_text())
            (directory/'request.stderr').write_bytes(raw+b'tampered')
            with self.assertRaisesRegex(ValueError,'differs from manifest'):analyze(report,root/'tampered')
            del build['trace']['capture_directory'];report.write_text(json.dumps(data))
            result=analyze(report,root/'unavailable')
            self.assertEqual(result['compiler_profile_coverage'][0]['status'],'unavailable')
            self.assertEqual(result['compiler_phase_profiles'],[])
            build['exit_code']=1;report.write_text(json.dumps(data))
            result=analyze(report,root/'failed')
            self.assertEqual(len(result['excluded_builds']),1)
            self.assertEqual(result['compiler_phase_profiles'],[])

    def test_missing_stream_is_not_zero_cost(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'request.json').write_text(json.dumps(dict(exit_code=0,args=['rustc'])))
            with self.assertRaises(FileNotFoundError):collect(root)


if __name__=='__main__':unittest.main()
