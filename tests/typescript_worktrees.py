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
for p in root.rglob("*"):
    if p.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
        continue
    if "node_modules" in p.parts:
        continue
    text = p.read_text(encoding="utf-8")
    if "TYPE_ERROR_INJECT" in text or "_nano_ts_error" in text or "_nano_undefined_ident" in text:
        errors.append("%s(1,1): error TS2322: Type 'string' is not assignable to type 'number'. _nano_ts_error" % p)
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
        self.assertTrue(info["nano_won"])
        self.assertEqual(info["nano_dominated_by"], [])

    def test_files_better_wall_worse_is_not_won(self):
        none = {"approach": "none", "ok": True, "correctness_ok": True, "wall_ms": 100, "files_rechecked": 100, "store_bytes": 0, "disk_bytes": 100, "rss_kb": 100}
        nano = {"approach": "nanocompile", "lever": "l2_seed_buildinfo", "ok": True, "correctness_ok": True, "wall_ms": 140, "files_rechecked": 1, "store_bytes": 10, "disk_bytes": 80, "rss_kb": 80}
        self.assertFalse(tw.honestly_won(nano, none))
        self.assertFalse(tw.cell_summary([none, nano])["nano_won"])


class CorrectnessGate(unittest.TestCase):
    def test_generic_ts2304_is_not_an_inject(self):
        self.assertFalse(tw.inject_reported({"stderr": "error TS2304: Cannot find name 'foo'.", "stdout": ""}))
        self.assertFalse(tw.inject_reported({"stderr": "error TS2322: Type 'string' is not assignable.", "stdout": ""}))
        self.assertTrue(tw.inject_reported({"stderr": "const _nano_ts_error: never", "stdout": ""}))

    def test_nodenext_keeps_matching_resolution(self):
        root = Path(tempfile.mkdtemp(prefix="nano-ts-nn-"))
        try:
            (root / "tsconfig.json").write_text(
                '{"compilerOptions":{"module":"NodeNext","checkJs":true,"allowJs":true,"noEmit":true}}\n',
                encoding="utf-8",
            )
            tw.compat_tsconfig_for_checker(root, "tsgo")
            text = (root / "tsconfig.json").read_text(encoding="utf-8")
            self.assertIn("nodenext", text.lower())
            self.assertNotIn("bundler", text)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_extends_node10_sets_bundler(self):
        root = Path(tempfile.mkdtemp(prefix="nano-ts-ext-"))
        try:
            (root / "tsconfig.json").write_text(
                '{"extends":"./base.json","compilerOptions":{"strict":true}}\n',
                encoding="utf-8",
            )
            tw.compat_tsconfig_for_checker(root, "tsgo")
            self.assertIn("bundler", (root / "tsconfig.json").read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_classify_skips_tsconfig_exclude(self):
        root = Path(tempfile.mkdtemp(prefix="nano-ts-ex-"))
        try:
            write_project(root)
            (root / "src" / "excluded.js").write_text("export const excluded = 1;\n", encoding="utf-8")
            (root / "tsconfig.json").write_text(
                '{"compilerOptions":{"strict":true,"noEmit":true},"include":["src"],"exclude":["src/excluded.js"]}\n',
                encoding="utf-8",
            )
            kinds = tw.classify_sources(root)
            self.assertNotIn("src/excluded.js", kinds["import_counts"])
            self.assertIn("src/app.ts", kinds["import_counts"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


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
        self.assertIn("NANOCOMPILE_TS_DIRTY_SCOPE", env)
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
        self.assertTrue(bad["error_seen"])
        clean = tw.run_check(self.main, checker, "l0_result_cache", self.store, Path(BIN), {}, ["--noEmit"])
        self.assertTrue(clean["ok"])
        self.assertFalse(clean["error_seen"])

    def test_failure_result_is_cached(self):
        (self.main / "src" / "app.ts").write_text(
            "const _nano_ts_error: never = true;\n", encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(self.main), "add", "-A"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(self.main), "-c", "user.email=nano@local", "-c", "user.name=nano", "commit", "-qm", "broken"],
            check=True, capture_output=True,
        )
        subprocess.run([BIN, "worktree", "init", "--store", str(self.store), str(self.main)], check=True, capture_output=True)
        checker = {"id": "tsc", "bin_env": "NANOCOMPILE_TSC", "exe": str(self.checker)}
        first = tw.run_check(self.main, checker, "l0_result_cache", self.store, Path(BIN), {}, ["--noEmit"])
        self.assertFalse(first["ok"])
        self.assertEqual(first["returncode"], 2)
        wt = self.temp / "wt-fail"
        tw.add_git_worktree(self.main, wt)
        subprocess.run([BIN, "worktree", "init", "--store", str(self.store), str(wt)], check=True, capture_output=True)
        second = tw.run_check(wt, checker, "l0_result_cache", self.store, Path(BIN), {}, ["--noEmit"])
        self.assertFalse(second["ok"], second["stderr"])
        self.assertGreaterEqual(second["hits"], 1)
        self.assertEqual(second["returncode"], 2)
        self.assertIn("TS2322", second["stderr"])

    def test_nodenext_checkjs_inject_is_reported(self):
        shutil.rmtree(self.main)
        self.main.mkdir()
        (self.main / "src").mkdir()
        (self.main / "src" / "app.js").write_text("export const n = 1;\n", encoding="utf-8")
        (self.main / "tsconfig.json").write_text(
            '{"compilerOptions":{"allowJs":true,"checkJs":true,"noEmit":true,"module":"NodeNext","strict":true},"include":["src"]}\n',
            encoding="utf-8",
        )
        subprocess.run(["git", "init"], cwd=self.main, check=True, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=self.main, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.email=nano@local", "-c", "user.name=nano", "commit", "-qm", "js"],
            cwd=self.main, check=True, capture_output=True,
        )
        tw.compat_tsconfig_for_checker(self.main, "tsgo")
        self.assertIn("nodenext", (self.main / "tsconfig.json").read_text(encoding="utf-8").lower())
        subprocess.run([BIN, "worktree", "init", "--store", str(self.store), str(self.main)], check=True, capture_output=True)
        checker = {"id": "tsc", "bin_env": "NANOCOMPILE_TSC", "exe": str(self.checker)}
        rec = tw.edit_file(self.main / "src" / "app.js", "error")
        bad = tw.run_check(self.main, checker, "l0_result_cache", self.store, Path(BIN), {}, ["--noEmit"])
        tw.restore_edit(rec)
        self.assertTrue(bad["error_seen"], bad["stderr"])
        self.assertIn("_nano_ts_error", bad["stderr"])

    def test_exit0_with_errors_still_reports_inject(self):
        exit0 = self.temp / "fake-exit0"
        exit0.write_text(
            r"""#!/usr/bin/env python3
import pathlib, sys
root = pathlib.Path.cwd()
blob = ""
for p in root.rglob("*"):
    if p.suffix in {".ts", ".js"} and "node_modules" not in p.parts:
        blob += p.read_text(encoding="utf-8")
sys.stderr.write("error TS2304: Cannot find name 'preexisting'.\n")
if "_nano_ts_error" in blob or "_nano_undefined_ident" in blob:
    sys.stderr.write("%s(1,1): error TS2322: Type 'string' is not assignable to type 'number'. _nano_ts_error\n" % root)
sys.exit(0)
""",
            encoding="utf-8",
        )
        exit0.chmod(0o755)
        os.environ["NANOCOMPILE_TSC"] = str(exit0)
        subprocess.run([BIN, "worktree", "init", "--store", str(self.store), str(self.main)], check=True, capture_output=True)
        checker = {"id": "tsc", "bin_env": "NANOCOMPILE_TSC", "exe": str(exit0)}
        rec = tw.edit_file(self.main / "src" / "app.ts", "error")
        bad = tw.run_check(self.main, checker, "l0_result_cache", self.store, Path(BIN), extra_env={"NANOCOMPILE_TSC": str(exit0)}, args=["--noEmit"])
        tw.restore_edit(rec)
        self.assertTrue(bad["ok"])
        self.assertTrue(bad["error_seen"], bad["stderr"])
        self.assertTrue(tw.inject_reported(bad))


if __name__ == "__main__":
    unittest.main()
