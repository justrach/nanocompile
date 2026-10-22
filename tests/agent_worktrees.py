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

    def test_regression_blocks_keep(self):
        summary = {
            "crates_compiled_mean": {"gain": 0.2, "keep": True},
            "wall_ms": {"gain": 0.1, "keep": True},
            "disk_bytes": {"gain": -0.4, "keep": False},
            "store_bytes": {"gain": 0.0, "keep": False},
        }
        self.assertFalse(aw.keep_decision(summary))
        summary["disk_bytes"] = {"gain": -0.02, "keep": False}
        self.assertTrue(aw.keep_decision(summary))

    def test_pareto_non_dominated(self):
        rows = [
            {"sample": "axum", "approach": "none", "lever": "none", "ok": True, "n_worktrees": 4,
             "mode": "sequential", "edit_kind": "mixed",
             "crates_compiled_mean": 50, "wall_ms": 20000, "disk_bytes": 800, "store_bytes": 0},
            {"sample": "axum", "approach": "shared_target", "lever": "shared_target", "ok": True, "n_worktrees": 4,
             "mode": "sequential", "edit_kind": "mixed",
             "crates_compiled_mean": 1, "wall_ms": 3000, "disk_bytes": 160, "store_bytes": 0},
            {"sample": "axum", "approach": "nanocompile", "lever": "l0_nano_best", "ok": True, "n_worktrees": 4,
             "mode": "sequential", "edit_kind": "mixed",
             "crates_compiled_mean": 2, "wall_ms": 4000, "disk_bytes": 150, "store_bytes": 40},
            {"sample": "axum", "approach": "kache", "lever": "kache", "ok": True, "n_worktrees": 4,
             "mode": "sequential", "edit_kind": "mixed",
             "crates_compiled_mean": 1, "wall_ms": 5000, "disk_bytes": 600, "store_bytes": 200},
        ]
        front = aw.pareto_frontier(rows)
        approaches = {r["approach"] for r in front}
        self.assertIn("shared_target", approaches)
        self.assertIn("nanocompile", approaches)
        info = aw.pareto_by_repo(rows, "train")["axum"]
        self.assertTrue(info["nano_on_frontier"])

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
        self.assertIn("NANOCOMPILE_EXECUTABLE_PRODUCERS", text)
        self.assertIn("NANOCOMPILE_HARDLINK_TARGET", text)

    def test_climb_notes_stay_in_table(self):
        text = aw.render_docs({
            "hill_climb": {
                "log": [{
                    "lever": "l14_slim_graph",
                    "vs": "l12_no_variants",
                    "keep": True,
                    "metrics": {},
                    "note": "Skip empty -L prefix guards",
                }],
                "frozen_lever": "frozen",
                "frozen_env": aw.NANO_FRONTIER,
            },
            "survival": {"per_metric": {}, "general": [], "repo_specific": []},
            "train": [],
            "breakdown": [],
        })
        self.assertIn("NANOCOMPILE_REMAP_PATHS", text)
        self.assertIn("NANOCOMPILE_TS_INCREMENTAL", text)
        self.assertIn("| `l14_slim_graph` |", text)
        self.assertIn("Skip empty -L prefix guards", text)
        climb = text.split("## Hill-climb")[1].split("## Generalization")[0]
        rows = [line for line in climb.splitlines() if line.startswith("| `")]
        self.assertEqual(len(rows), 1)
        self.assertTrue(all(line.startswith("|") for line in climb.splitlines() if "l14_slim_graph" in line))


if __name__ == "__main__":
    unittest.main()
