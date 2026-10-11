import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from benchmark_host_activity import parse_processes, summarize


class HostActivityTests(unittest.TestCase):
    def test_benchmark_descendants_and_owned_daemon_are_excluded(self):
        rows = parse_processes('1 0 0 launchd\n10 1 1 python3\n11 10 2 cargo\n12 11 700 /private/rustc\n20 1 2 kache\n21 20 100 rustc\n30 1 0 cargo\n31 30 250 /elsewhere/rustc\n40 1 12 /Some App/Helper\n')
        result = summarize(rows, 10, [20])
        self.assertEqual(result['owned_process_count'], 5)
        self.assertEqual(result['owned_cpu_percent'], 805)
        self.assertEqual(result['external_build_process_count'], 2)
        self.assertEqual(result['external_build_cpu_percent'], 250)
        self.assertEqual(result['other_cpu_percent'], 262)
        self.assertNotIn('elsewhere', json.dumps(result))
        self.assertNotIn('Helper', json.dumps(result))

    def test_missing_root_does_not_count_as_a_live_quiet_trial(self):
        self.assertFalse(summarize(parse_processes('1 0 0 launchd\n'), 999)['root_present'])

    def test_invalid_or_missing_observations_fail(self):
        for text in ['', '1 0', '1 0 nan cargo', '1 0 -1 rustc', '1 0 inf rustc', '1 0 1 rustc\n1 0 0 cargo']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_processes(text)

    def test_idle_external_cargo_and_versioned_compilers_remain_visible(self):
        rows = parse_processes('1 0 0 init\n10 1 0 python3\n20 1 0 cargo\n21 20 5 clang-18\n22 20 5 clang++\n23 1 10 swift-frontend\n')
        result = summarize(rows, 10)
        self.assertEqual(result['external_build_process_count'], 4)
        self.assertEqual(result['external_build_cpu_percent'], 20)


if __name__ == '__main__':
    unittest.main()
