#!/usr/bin/env python3
"""MAP-Elites archive contract.

Run: python3 tests/map_elites.py [path/to/nanocompile]
The Python tool is enough; the native driver is checked when a binary is given.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "map_elites.py"
CANONICAL = ROOT / "bench" / "map_elites.json"
BINARY = Path(sys.argv.pop(1)).resolve() if __name__ == "__main__" and len(sys.argv) > 1 else None


def genome(**overrides):
    row = {
        "wrapper": False,
        "dev_backend": "llvm",
        "linker": "default",
        "sccache": False,
        "codegen_units": None,
        "incremental": True,
        "debuginfo": "full",
        "fast_check": "cargo-check",
        "loop": "check",
        "jobs": None,
        "offline": True,
    }
    row.update(overrides)
    return row


def evaluation(cell="small|body", fitness=20.0, ok=True, sample="fixture"):
    size, edit = cell.split("|")
    return {
        "cell": cell,
        "size": size,
        "edit": edit,
        "genome": genome(),
        "fitness_ms": fitness,
        "spread_ms": 1.0,
        "disk_bytes": 100,
        "correctness": {"ok": ok, "agree_on_broken": ok, "validate_is_final": ok},
        "sample": sample,
    }


class MapElites(unittest.TestCase):
    def tool(self, args, expected=0):
        result = subprocess.run(
            [sys.executable, str(TOOL), *args],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def test_canonical_archive_validates(self):
        self.tool(["validate", str(CANONICAL)])
        data = json.loads(CANONICAL.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["kind"], "nanocompile.rust-loop.map-elites")
        self.assertEqual(data["axes"]["size"], ["small", "mid", "large"])
        self.assertEqual(data["axes"]["edit"], ["cold", "noop", "body", "sig_dep"])

    def test_merge_keeps_faster_correct_elite(self):
        tmp = tempfile.TemporaryDirectory(prefix="map-elites ")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        into = root / "map_elites.json"
        into.write_text(CANONICAL.read_text(encoding="utf-8"), encoding="utf-8")
        shard = root / "sample.json"
        shard.write_text(json.dumps({
            "schema_version": 1,
            "kind": "nanocompile.rust-loop.map-elites.shard",
            "sample": "fixture",
            "evaluations": [
                evaluation(fitness=20.0),
                evaluation(fitness=19.8),
                evaluation(fitness=15.0),
                evaluation(fitness=10.0, ok=False),
            ],
        }), encoding="utf-8")
        self.tool(["merge", "--into", str(into), str(shard)])
        archive = json.loads(into.read_text(encoding="utf-8"))
        elite = archive["cells"]["small|body"]
        self.assertEqual(elite["fitness_ms"], 15.0)
        self.assertTrue(elite["correctness"]["ok"])
        self.assertGreaterEqual(len(archive["history"]), 2)

    def test_classify_example_is_small(self):
        listed = json.loads(self.tool(["classify", str(ROOT / "examples" / "rust-loop")]).stdout)
        self.assertEqual(listed["size"], "small")
        medium = json.loads(self.tool(["classify", str(ROOT / "examples" / "rust-loop-medium")]).stdout)
        self.assertEqual(medium["size"], "small")
        self.assertLess(medium["loc"], 2000)

    def test_classify_pinned_hashbrown_is_mid(self):
        pinned = ROOT / "examples" / "pinned-hashbrown"
        listed = json.loads(self.tool(["classify", str(pinned)]).stdout)
        self.assertEqual(listed["size"], "mid")
        self.assertGreaterEqual(listed["loc"], 2000)
        self.assertLess(listed["loc"], 50000)

    def test_cranelift_build_genome_ok_test_rejected(self):
        tmp = tempfile.TemporaryDirectory(prefix="map-elites ")
        self.addCleanup(tmp.cleanup)
        good = Path(tmp.name) / "good.json"
        row = evaluation()
        row["genome"]["dev_backend"] = "cranelift"
        row["genome"]["loop"] = "build"
        good.write_text(json.dumps({
            "schema_version": 1,
            "kind": "nanocompile.rust-loop.map-elites.shard",
            "sample": "x",
            "evaluations": [row],
        }), encoding="utf-8")
        self.tool(["validate", str(good)])
        bad = Path(tmp.name) / "bad.json"
        row["genome"]["loop"] = "test"
        bad.write_text(json.dumps({
            "schema_version": 1,
            "kind": "nanocompile.rust-loop.map-elites.shard",
            "sample": "x",
            "evaluations": [row],
        }), encoding="utf-8")
        self.tool(["validate", str(bad)], expected=2)

    def test_touched_sig_dep_requires_dependent_gate(self):
        tmp = tempfile.TemporaryDirectory(prefix="map-elites ")
        self.addCleanup(tmp.cleanup)
        into = Path(tmp.name) / "map_elites.json"
        into.write_text(json.dumps({
            "schema_version": 1,
            "kind": "nanocompile.rust-loop.map-elites",
            "axes": {"size": ["small", "mid", "large"], "edit": ["cold", "noop", "body", "sig_dep"]},
            "fitness": {"metric": "median_ms", "goal": "min", "min_gain_pct": 3.0, "max_non_improving": 4},
            "cells": {},
            "history": [],
            "generalization": {"samples": [], "elites_tested": [], "matrix": []},
            "promoted": {"defaults": None, "sample_specific": []},
        }), encoding="utf-8")
        shard = Path(tmp.name) / "mid.json"
        touched = evaluation("large|sig_dep", fitness=500.0, sample="midsize")
        touched["genome"]["package_scope"] = "touched"
        fallback = evaluation("large|sig_dep", fitness=700.0, sample="midsize")
        fallback["genome"]["debuginfo"] = "line-tables-only"
        shard.write_text(json.dumps({
            "schema_version": 1,
            "kind": "nanocompile.rust-loop.map-elites.shard",
            "sample": "midsize",
            "fitness": {"aggregation": "mean_of_per_sample_medians"},
            "evaluations": [touched],
            "history": [{
                "cell": "large|sig_dep",
                "action": "replace",
                "fitness_ms": 700.0,
                "genome": fallback["genome"],
                "sample": "midsize",
                "reason": "win",
            }],
        }), encoding="utf-8")
        self.tool(["merge", "--into", str(into), str(shard)])
        archive = json.loads(into.read_text(encoding="utf-8"))
        elite = archive["cells"]["large|sig_dep"]
        self.assertEqual(elite["genome"]["debuginfo"], "line-tables-only")
        self.assertNotEqual(elite["genome"].get("package_scope"), "touched")
        self.assertTrue(any("dependents" in (row.get("reason") or "") for row in archive["history"]))

    def test_promote_weights_real_over_fixture(self):
        tmp = tempfile.TemporaryDirectory(prefix="map-elites ")
        self.addCleanup(tmp.cleanup)
        into = Path(tmp.name) / "map_elites.json"
        fixture = evaluation("small|body", fitness=20.0, sample="rust-loop")
        fixture["genome"]["loop"] = "check"
        fixture["genome"]["incremental"] = False
        real = evaluation("large|body", fitness=120.0, sample="midsize")
        real["genome"]["debuginfo"] = "line-tables-only"
        real["sample_class"] = "real"
        into.write_text(json.dumps({
            "schema_version": 1,
            "kind": "nanocompile.rust-loop.map-elites",
            "axes": {"size": ["small", "mid", "large"], "edit": ["cold", "noop", "body", "sig_dep"]},
            "fitness": {"metric": "median_ms", "goal": "min", "min_gain_pct": 3.0, "max_non_improving": 4},
            "cells": {"small|body": fixture, "large|body": real},
            "history": [],
            "generalization": {"samples": [], "elites_tested": [], "matrix": []},
            "promoted": {"defaults": None, "sample_specific": []},
        }), encoding="utf-8")
        self.tool(["promote", "--into", str(into)])
        archive = json.loads(into.read_text(encoding="utf-8"))
        promoted = archive["promoted"]["defaults"]["iteration"]["genome"]
        self.assertEqual(promoted["debuginfo"], "line-tables-only")
        self.assertTrue(any(
            row.get("sample") == "rust-loop" for row in archive["promoted"]["sample_specific"]
        ))

    def test_stacked_wrappers_rejected(self):
        tmp = tempfile.TemporaryDirectory(prefix="map-elites ")
        self.addCleanup(tmp.cleanup)
        bad = Path(tmp.name) / "bad.json"
        bad.write_text(json.dumps({
            "schema_version": 1,
            "kind": "nanocompile.rust-loop.map-elites.shard",
            "sample": "x",
            "evaluations": [evaluation()],
        }), encoding="utf-8")
        data = json.loads(bad.read_text(encoding="utf-8"))
        data["evaluations"][0]["genome"]["wrapper"] = True
        data["evaluations"][0]["genome"]["sccache"] = True
        bad.write_text(json.dumps(data), encoding="utf-8")
        self.tool(["validate", str(bad)], expected=2)


if __name__ == "__main__":
    if BINARY is not None:
        listed = subprocess.run([str(BINARY), "map-elites", "validate", str(CANONICAL)], capture_output=True, text=True)
        if listed.returncode != 0:
            raise SystemExit("native map-elites validate failed:\n" + listed.stderr)
    unittest.main(verbosity=2)
