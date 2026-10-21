#!/usr/bin/env python3
"""Unit tests for the agent-worktrees harness helpers."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bench"))
import agent_worktrees as aw  # noqa: E402


class CargoCmd(unittest.TestCase):
    def test_uses_nightly(self):
        self.assertEqual(aw.cargo_cmd("check", None)[:2], ["cargo", "+nightly"])
        self.assertIn("--offline", aw.cargo_cmd("test", "ruff"))


class StatsDelta(unittest.TestCase):
    def test_parse_and_delta(self):
        text = "hits: 10\nmisses: 4\nbuild-script hits: 2\nbuild-script misses: 1\n"
        parsed = aw.parse_stats_text(text)
        compiled, restored = aw.stats_compiled({"hits": 1, "misses": 1, "build-script misses": 0, "build-script hits": 0}, parsed)
        self.assertEqual(compiled, 4)
        self.assertEqual(restored, 11)


class ParseCompiled(unittest.TestCase):
    def test_compiling_and_checking(self):
        text = (
            "    Checking libc v0.2.0\n"
            "   Compiling axum v0.8.4\n"
            "    Dirty serde v1.0.0\n"
            "    Finished `dev` profile [unoptimized + debuginfo] target(s)\n"
        )
        self.assertEqual(aw.parse_compiled(text), ["libc", "axum", "serde"])


class DiskOnce(unittest.TestCase):
    def test_hardlink_counted_once(self):
        root = Path(tempfile.mkdtemp(prefix="nano-wt-disk-"))
        try:
            a = root / "store" / "blob"
            b = root / "target-a" / "blob"
            a.parent.mkdir(parents=True)
            b.parent.mkdir(parents=True)
            a.write_bytes(b"x" * 4096)
            os.link(a, b)
            self.assertEqual(aw.unique_disk_bytes([root / "store", root / "target-a"]), 4096)
            self.assertGreater(a.stat().st_nlink, 1)
        finally:
            shutil.rmtree(root)


class Edits(unittest.TestCase):
    def test_body_sig_large_restore(self):
        root = Path(tempfile.mkdtemp(prefix="nano-wt-edit-"))
        try:
            src = root / "src"
            src.mkdir()
            (src / "lib.rs").write_text("pub fn f() {}\n", encoding="utf-8")
            rec = aw.apply_agent_edit(root, "body")
            self.assertTrue(rec)
            self.assertIn("_nano_agent_body", (src / "lib.rs").read_text(encoding="utf-8"))
            aw.restore_records(rec)
            self.assertEqual((src / "lib.rs").read_text(encoding="utf-8"), "pub fn f() {}\n")
            rec = aw.apply_agent_edit(root, "large")
            self.assertGreaterEqual(len(rec), 1)
            aw.restore_records(rec)
        finally:
            shutil.rmtree(root)


class Climb(unittest.TestCase):
    def test_keep_three_percent(self):
        rows = [
            {"split": "train", "lever": "none", "mode": "sequential", "ok": True,
             "crates_compiled_mean": 10, "wall_ms": 1000, "disk_bytes": 100, "loop": "check", "sample": "axum"},
            {"split": "train", "lever": "l0_nano_best", "mode": "sequential", "ok": True,
             "crates_compiled_mean": 4, "wall_ms": 400, "disk_bytes": 80, "loop": "check", "sample": "axum"},
            {"split": "train", "lever": "l1_script_cache", "mode": "sequential", "ok": True,
             "crates_compiled_mean": 3, "wall_ms": 380, "disk_bytes": 80, "loop": "check", "sample": "axum"},
            {"split": "train", "lever": "l2_test_bins", "mode": "sequential", "ok": True,
             "crates_compiled_mean": 3, "wall_ms": 379, "disk_bytes": 80, "loop": "test", "sample": "axum"},
        ]
        result = aw.hill_climb(rows)
        self.assertIn("l0_nano_best", result["kept"])
        self.assertIn("l1_script_cache", result["kept"])
        self.assertNotIn("l2_test_bins", result["kept"])

    def test_survival_fraction(self):
        train = [
            {"lever": "none", "ok": True, "crates_compiled_mean": 10, "wall_ms": 1000, "disk_bytes": 100},
            {"lever": "l1_script_cache", "ok": True, "crates_compiled_mean": 4, "wall_ms": 400, "disk_bytes": 80},
        ]
        held = [
            {"sample": "bhumi", "approach": "none", "ok": True, "n_worktrees": 4, "from_older": False,
             "variant": {"edit_kind": "mixed", "from_older": False},
             "crates_compiled_mean": 10, "wall_ms": 1000, "disk_bytes": 100},
            {"sample": "bhumi", "approach": "nanocompile", "lever": "frozen", "ok": True, "n_worktrees": 4,
             "variant": {"edit_kind": "mixed", "from_older": False},
             "crates_compiled_mean": 5, "wall_ms": 500, "disk_bytes": 90},
        ]
        surv = aw.survival(train, held, "l1_script_cache")
        self.assertIsNotNone(surv["per_metric"]["wall_ms"]["survived_fraction"])
        self.assertGreater(surv["per_metric"]["wall_ms"]["survived_fraction"], 0.5)


class Docs(unittest.TestCase):
    def test_render_contains_setup(self):
        text = aw.render_docs({
            "hill_climb": {"log": [], "frozen_lever": "l1_script_cache", "frozen_env": aw.NANO_SCRIPT},
            "survival": {"per_metric": {}, "general": ["bhumi"], "repo_specific": []},
            "train": [],
            "breakdown": [],
        })
        self.assertIn("worktree init", text)
        self.assertIn("NANOCOMPILE_BUILD_SCRIPT_CACHE", text)


if __name__ == "__main__":
    unittest.main()
