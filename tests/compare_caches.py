#!/usr/bin/env python3
import unittest
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bench"))
import compare_caches as caches  # noqa: E402


class CompareCaches(unittest.TestCase):
    def test_parse_nano_stats_and_delta(self):
        before = caches.parse_nano_stats(
            "hits: 1\nmisses: 2\nbypasses: 3\nlogical bytes: 10\n"
            "restore ns total: 1000\nrestore ns samples: 1\n"
            "restore reflink: 0\nrestore hardlink: 1\nrestore copy: 2\n"
        )
        after = caches.parse_nano_stats(
            "hits: 4\nmisses: 3\nbypasses: 3\nlogical bytes: 40\n"
            "restore ns total: 4000\nrestore ns samples: 3\n"
            "restore reflink: 1\nrestore hardlink: 2\nrestore copy: 2\n"
        )
        delta = caches.delta_stats(before, after)
        self.assertEqual(delta["hits"], 3)
        self.assertEqual(delta["misses"], 1)
        self.assertAlmostEqual(delta["hit_rate"], 0.75)
        self.assertEqual(delta["store_bytes"], 40)
        self.assertEqual(delta["restore_hardlink"], 1)
        self.assertAlmostEqual(delta["restore_ms"], 0.0015)

    def test_catalog_covers_requested_samples(self):
        for name in (
            "rust-loop", "hashbrown", "serde_derive", "axum", "nalgebra",
            "ripgrep", "ruff", "bhumi", "emergentDB",
        ):
            self.assertIn(name, caches.SAMPLE_CATALOG)


if __name__ == "__main__":
    unittest.main()
