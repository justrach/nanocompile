"""The loopback task-cache service must not require working DNS to start."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import turbo_cache


class StartupTests(unittest.TestCase):
    def test_startup_with_unavailable_resolver(self):
        with patch('socket.getfqdn', side_effect=RuntimeError('DNS unavailable')):
            server = turbo_cache.Server(('127.0.0.1', 0), turbo_cache.Handler)
            try:
                self.assertGreater(server.server_port, 0)
                self.assertEqual(server.server_name, 'localhost')
            finally:
                server.server_close()


if __name__ == '__main__':
    unittest.main()
