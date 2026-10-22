#!/usr/bin/env python3
"""Correctness and git-worktree tests for the TypeScript shared store."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bench"))
import ts_worktrees as tw  # noqa: E402

BIN = os.environ.get("NANOCOMPILE_BIN", str(REPO / "zig-out" / "bin" / "nanocompile"))

FAKE_CHECKER = r"""#!/usr/bin/env python3
import pathlib, sys
root = pathlib.Path.cwd()
errors = []
for p in root.rglob("*.ts"):
    if "node_modules" in p.parts:
        continue
    text = p.read_text(encoding="utf-8")
    if "TYPE_ERROR_INJECT" in text or "_nano_ts_error" in text or "_nano_undefined_ident" in text:
        errors.append("%s(1,1): error TS2322: Type 'string' is not assignable to type 'number'." % p)
if errors:
    sys.stderr.write("\n".join(errors) + "\n")
    sys.exit(2)
sys.stdout.write("No type errors in %s\n" % root)
sys.exit(0)
"""


def write_project(root: Path):
    (root / "src").mkdir(parents=True)
    (root / "src" / "types.ts").write_text("export type N = number;\n", encoding="utf-8")
    (root / "src" / "app.ts").write_text("import type { N } from './types'; export const n: N = 1;\n", encoding="utf-8")
    (root / "src" / "leaf.ts").write_text("export const leaf = 1;\n", encoding="utf-8")
    (root / "tsconfig.json").write_text(
        '{"compilerOptions":{"strict":true,"noEmit":true},"include":["src"]}\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=nano@local", "-c", "user.name=nano", "commit", "-qm", "init"],
        cwd=root, check=True, capture_output=True,
    )


class Classify(unittest.TestCase):
    def test_leaf_vs_shared(self):
        root = Path(tempfile.mkdtemp(prefix="nano-ts-cls-"))
        try:
            write_project(root)
            kinds = tw.classify_sources(root)
            self.assertEqual(kinds["n_sources"], 3)
            self.assertTrue(str(kinds["shared"]).endswith("types.ts"))
            self.assertIn(kinds["leaf"].name, {"leaf.ts", "app.ts"})
            self.assertNotEqual(kinds["leaf"], kinds["shared"])
            self.assertTrue(kinds["tsconfig"].name == "tsconfig.json")
        finally:
            shutil.rmtree(root, ignore_errors=True)


class FilesFor(unittest.TestCase):
    def test_nano_miss_is_project_grain(self):
        hit = {"hits": 1, "misses": 0}
        miss = {"hits": 0, "misses": 1}
        self.assertEqual(tw.files_for(hit, 126, "l0_result_cache"), 0)
        self.assertEqual(tw.files_for(miss, 126, "l2_seed_buildinfo"), 1)
        self.assertEqual(tw.files_for(miss, 126, "none"), 126)


class Pareto(unittest.TestCase):
    def test_nano_not_dominated_on_disk(self):
        rows = [
            {"approach": "none", "ok": True, "correctness_ok": True, "wall_ms": 400, "files_rechecked": 100, "store_bytes": 0, "disk_bytes": 800, "rss_kb": 200},
            {"approach": "nanocompile", "lever": "l0_result_cache", "ok": True, "correctness_ok": True, "wall_ms": 5, "files_rechecked": 0, "store_bytes": 10, "disk_bytes": 50, "rss_kb": 20},
        ]
        info = tw.cell_summary(rows)
        self.assertTrue(info["nano_on_frontier"])
        self.assertEqual(info["nano_dominated_by"], [])


class GitWorktrees(unittest.TestCase):
    def setUp(self):
        if not Path(BIN).exists():
            self.skipTest("nanocompile binary missing")
        self.temp = Path(tempfile.mkdtemp(prefix="nano-ts-wt-"))
        self.checker = self.temp / "fake-tsc"
        self.checker.write_text(FAKE_CHECKER, encoding="utf-8")
        self.checker.chmod(0o755)
        self.main = self.temp / "main"
        self.store = self.temp / "store"
        self.main.mkdir()
        write_project(self.main)
        os.environ["NANOCOMPILE_TSC"] = str(self.checker)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_init_writes_ts_shims(self):
        subprocess.run([BIN, "worktree", "init", "--store", str(self.store), str(self.main)], check=True, capture_output=True)
        env = (self.main / ".nanocompile" / "env").read_text(encoding="utf-8")
        self.assertIn("NANOCOMPILE_DIR=", env)
        self.assertIn("NANOCOMPILE_TS_INCREMENTAL", env)
        shim = self.main / ".nanocompile" / "bin" / "tsc"
        self.assertTrue(shim.exists())
        self.assertTrue(os.access(shim, os.X_OK))
        self.assertIn("tsc", shim.read_text(encoding="utf-8"))

    def test_git_worktree_hit_and_injected_error(self):
        subprocess.run([BIN, "worktree", "init", "--store", str(self.store), str(self.main)], check=True, capture_output=True)
        checker = {"id": "tsc", "bin_env": "NANOCOMPILE_TSC", "exe": str(self.checker)}
        first = tw.run_check(self.main, checker, "l0_result_cache", self.store, Path(BIN), {}, ["--noEmit"])
        self.assertTrue(first["ok"], first["stderr"])
        wt = self.temp / "wt-1"
        tw.add_git_worktree(self.main, wt)
        subprocess.run([BIN, "worktree", "init", "--store", str(self.store), str(wt)], check=True, capture_output=True)
        second = tw.run_check(wt, checker, "l0_result_cache", self.store, Path(BIN), {}, ["--noEmit"])
        self.assertTrue(second["ok"], second["stderr"])
        self.assertGreaterEqual(second["hits"], 1)
        rec = tw.edit_file(wt / "src" / "app.ts", "error")
        bad = tw.run_check(wt, checker, "l0_result_cache", self.store, Path(BIN), {}, ["--noEmit"])
        tw.restore_edit(rec)
        self.assertFalse(bad["ok"])
        self.assertIn("TS2322", bad["stderr"])
        clean = tw.run_check(self.main, checker, "l0_result_cache", self.store, Path(BIN), {}, ["--noEmit"])
        self.assertTrue(clean["ok"])


if __name__ == "__main__":
    unittest.main()
