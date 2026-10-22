#!/usr/bin/env python3
"""Correctness and hit/miss tests for the TypeScript worktree cache."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
BIN = os.environ.get("NANOCOMPILE_BIN", str(REPO / "zig-out" / "bin" / "nanocompile"))

FAKE_CHECKER = r"""#!/usr/bin/env python3
import pathlib, sys
root = pathlib.Path.cwd()
errors = []
for p in root.rglob("*.ts"):
    if "node_modules" in p.parts:
        continue
    text = p.read_text(encoding="utf-8")
    if "TYPE_ERROR_INJECT" in text:
        errors.append("%s(1,1): error TS2322: Type 'string' is not assignable to type 'number'." % p)
if errors:
    sys.stderr.write("\n".join(errors) + "\n")
    sys.exit(2)
sys.stdout.write("No type errors in %s\n" % root)
sys.exit(0)
"""


def write_project(root: Path, body: str = "export const n: number = 1;\n"):
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "app.ts").write_text(body, encoding="utf-8")
    (root / "tsconfig.json").write_text(
        '{"compilerOptions":{"strict":true,"noEmit":true,"incremental":true},"include":["src"]}\n',
        encoding="utf-8",
    )


def run_nano(root: Path, store: Path, checker: Path, extra_env=None):
    env = os.environ.copy()
    env["NANOCOMPILE_DIR"] = str(store)
    env["NANOCOMPILE_TSC"] = str(checker)
    env["NANOCOMPILE_TRACE"] = "1"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [BIN, "tsc", "--noEmit"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )


class TypescriptWorktrees(unittest.TestCase):
    def setUp(self):
        if not Path(BIN).exists():
            self.skipTest("nanocompile binary missing; zig build first")
        self.temp = Path(tempfile.mkdtemp(prefix="nano-ts-"))
        self.checker = self.temp / "fake-tsc"
        self.checker.write_text(FAKE_CHECKER, encoding="utf-8")
        self.checker.chmod(0o755)
        self.main = self.temp / "main"
        self.wt = self.temp / "wt-1"
        self.store = self.temp / "store"
        self.main.mkdir()
        write_project(self.main)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_sibling_worktree_hits_shared_store(self):
        first = run_nano(self.main, self.store, self.checker)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("No type errors", first.stdout)
        shutil.copytree(self.main, self.wt)
        second = run_nano(self.wt, self.store, self.checker)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("No type errors", second.stdout)
        stats = subprocess.run(
            [BIN, "stats"],
            env=dict(os.environ, NANOCOMPILE_DIR=str(self.store)),
            capture_output=True,
            text=True,
        )
        self.assertIn("typescript hits: 1", stats.stdout)
        self.assertIn("typescript misses: 1", stats.stdout)

    def test_injected_type_error_is_reported(self):
        run_nano(self.main, self.store, self.checker)
        shutil.copytree(self.main, self.wt)
        app = self.wt / "src" / "app.ts"
        app.write_text("export const n: number = 1; // TYPE_ERROR_INJECT\n", encoding="utf-8")
        bad = run_nano(self.wt, self.store, self.checker)
        self.assertNotEqual(bad.returncode, 0, bad.stdout)
        self.assertIn("TS2322", bad.stderr)
        self.assertNotIn("No type errors", bad.stdout)
        # Clean sibling still hits the zero-error result.
        clean = self.temp / "wt-clean"
        shutil.copytree(self.main, clean)
        ok = run_nano(clean, self.store, self.checker)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("No type errors", ok.stdout)


if __name__ == "__main__":
    unittest.main()
