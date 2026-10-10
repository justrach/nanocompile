"""Inject disk failures and verify prior benchmark evidence survives."""
import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark_storage import require_space, save_report


class StorageTests(unittest.TestCase):
    def test_failed_write_flush_and_replace_preserve_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'report.json'
            save_report(output, {'builds': [1], 'completed': False})
            original = output.read_bytes()
            for stage in ('json.dump', 'os.fsync', 'os.replace'):
                with self.subTest(stage=stage):
                    with patch('benchmark_storage.' + stage,
                               side_effect=OSError(errno.ENOSPC, 'disk full')):
                        with self.assertRaises(OSError):
                            save_report(output, {'builds': [1, 2]})
                    self.assertEqual(output.read_bytes(), original)
                    self.assertEqual(list(Path(directory).iterdir()), [output])
            save_report(output, {'builds': [1, 2], 'completed': True})
            self.assertEqual(json.loads(output.read_text())['builds'], [1, 2])

    def test_space_gate_for_new_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'new' / 'state'
            usage = type('Usage', (), {'free': 1024**3})()
            with patch('benchmark_storage.shutil.disk_usage', return_value=usage):
                with self.assertRaisesRegex(OSError, 'Insufficient benchmark storage'):
                    require_space(state, 32)
                self.assertEqual(require_space(state, .5), 1024**3)
            self.assertFalse(state.exists())


if __name__ == '__main__':
    unittest.main()
