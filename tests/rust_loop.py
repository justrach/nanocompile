#!/usr/bin/env python3
"""Rust edit-check-validate declared-task checks.

Run: python3 tests/rust_loop.py /path/to/nanocompile
Exercises the native `nanocompile rust-loop` driver. The Python helper remains
only as a catalog/cross-check fallback.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools" / "rust_loop.py"
DOCS = ROOT / "docs" / "rust-iteration.md"
EXAMPLE = ROOT / "examples" / "rust-loop"
BINARY = Path(sys.argv.pop(1)).resolve() if __name__ == "__main__" else None
CRATE = """[package]
name = "nano-rust-loop-fixture"
version = "0.1.0"
edition = "2021"
"""
LIB = """pub fn add(left: i32, right: i32) -> i32 {
    left + right
}

#[cfg(test)]
mod tests {
    use super::add;

    #[test]
    fn adds_two_numbers() {
        assert_eq!(add(2, 2), 4);
    }
}
"""


def load_helper():
    sys.path.insert(0, str(HELPER.parent))
    import rust_loop
    return rust_loop


class RustLoop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = load_helper()
        cls.docs = DOCS.read_text(encoding="utf-8")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="nano rust loop ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        self.project = self.root / "crate"
        self.project.mkdir()
        (self.project / "src").mkdir()
        (self.project / "Cargo.toml").write_text(CRATE, encoding="utf-8")
        (self.project / "src" / "lib.rs").write_text(LIB, encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith("NANOCOMPILE_")
                    and k not in ("RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER")}
        self.env["NANOCOMPILE_DIR"] = str(self.cache)
        self.serial = 0

    def helper_run(self, args, cwd=None, env=None, expected=0):
        result = subprocess.run(
            [str(BINARY), "rust-loop", *args],
            cwd=self.project if cwd is None else cwd,
            env=self.env if env is None else env,
            capture_output=True, text=True, timeout=90,
        )
        self.assertEqual(result.returncode, expected, result.stderr)
        return result

    def write_spec(self, **kwargs):
        destination = self.project / "nanocompile.tasks.json"
        args = ["spec", "--manifest", str(self.project / "Cargo.toml"),
                "--write", str(destination), "--offline"]
        if kwargs.get("wrapper"):
            args.extend(["--wrapper", str(kwargs["wrapper"])])
        self.helper_run(args)
        return json.loads(destination.read_text(encoding="utf-8"))

    def run_task(self, spec_name="nanocompile.tasks.json", expected=0):
        self.serial += 1
        report = self.root / ("report-%d.json" % self.serial)
        env = dict(self.env)
        env["NANOCOMPILE_TASK_REPORT"] = str(report)
        result = subprocess.run(
            [str(BINARY), "task", spec_name],
            cwd=self.project, env=env, capture_output=True, timeout=120,
        )
        self.assertEqual(result.returncode, expected, result.stderr.decode(errors="replace"))
        data = json.loads(report.read_text()) if report.exists() else None
        return result, data

    def test_catalog_matches_docs_and_thread(self):
        listed = self.helper_run(["list"], cwd=self.root)
        catalog = json.loads(listed.stdout)
        self.assertEqual(catalog["attribution"], self.helper.CHARLIE_THREAD)
        self.assertIn(catalog["attribution"], self.docs)
        ids = [row["id"] for row in catalog["usable_now"]]
        self.assertEqual(ids, [row["id"] for row in self.helper.USABLE_NOW])
        self.assertEqual(ids[0], "fast-check")
        self.assertEqual(ids[1], "validate")
        for row in catalog["usable_now"] + catalog["experimental"]:
            self.assertIn(row["id"], self.docs, row["id"])
            if row.get("url"):
                self.assertIn(row["url"], self.docs, row["url"])
        self.assertFalse(next(row for row in catalog["experimental"] if row["id"] == "relax")
                         .get("public_repo_verified", True))
        self.assertFalse(next(row for row in catalog["experimental"] if row["id"] == "astral-fork")
                         .get("open_source", True))

    def test_documented_rustc_and_cargo_flags_exist(self):
        verified = json.loads(self.helper_run(["verify-flags"], cwd=self.root).stdout)
        for flag in ("codegen-units", "linker", "link-arg", "incremental", "debuginfo"):
            self.assertIn(flag, verified["rustc_codegen_flags"])
        self.assertTrue(verified["rust_lld"])
        self.assertTrue(verified["cargo_check"])
        self.assertTrue(verified["cargo_test"])
        help_text = subprocess.check_output(["rustc", "-C", "help"], text=True)
        self.assertIn("line-tables-only", help_text)

    def test_spec_requires_validate_after_fast_check(self):
        spec = self.write_spec()
        self.helper.check_spec(spec)
        self.assertEqual([task["name"] for task in spec["tasks"]], ["fast-check", "validate"])
        self.assertEqual(spec["tasks"][1]["depends_on"], ["fast-check"])
        bad = json.loads(json.dumps(spec))
        bad["tasks"] = [bad["tasks"][0]]
        with self.assertRaises(SystemExit):
            self.helper.check_spec(bad)
        swapped = json.loads(json.dumps(spec))
        swapped["tasks"] = list(reversed(swapped["tasks"]))
        swapped["tasks"][0]["depends_on"] = []
        swapped["tasks"][1]["depends_on"] = ["validate"]
        with self.assertRaises(SystemExit):
            self.helper.check_spec(swapped)
        cranelift = json.loads(json.dumps(spec))
        cranelift["tasks"][1]["command"] = ["cargo", "test", "-Zcodegen-backend"]
        with self.assertRaises(SystemExit):
            self.helper.check_spec(cranelift)
        rustd = json.loads(json.dumps(spec))
        rustd["tasks"][1]["command"] = ["cargo", "rustd", "test"]
        with self.assertRaises(SystemExit):
            self.helper.check_spec(rustd)

    def test_validate_run_refuses_cranelift_backend(self):
        env = dict(self.env)
        env["CARGO_PROFILE_DEV_CODEGEN_BACKEND"] = "cranelift"
        result = self.helper_run(
            ["run", "--step", "validate", "--stamp", "out.ok", "--", "cargo", "test"],
            env=env, expected=2,
        )
        self.assertIn("cranelift", result.stderr)

    def test_task_graph_check_then_real_rustc_test(self):
        spec = self.write_spec(wrapper=BINARY)
        self.assertTrue(spec["tasks"][0]["command"][-1] == "check")
        self.assertTrue(spec["tasks"][1]["command"][-1] == "test")
        self.assertIn(str(BINARY), spec["tasks"][0]["command"])
        cold, report = self.run_task()
        self.assertEqual([row["outcome"] for row in report["tasks"]], ["miss", "miss"])
        self.assertIn("fast-check", (self.project / ".nanocompile-loop" / "fast-check.ok").read_text())
        self.assertIn("validate", (self.project / ".nanocompile-loop" / "validate.ok").read_text())
        events = [line for line in (self.cache / "events").read_text().splitlines()
                  if line.startswith("task_")]
        self.assertEqual(events, ["task_miss", "task_miss"])
        for stamp in spec["tasks"][0]["outputs"] + spec["tasks"][1]["outputs"]:
            (self.project / stamp).unlink()
        warm, report = self.run_task()
        self.assertEqual([row["outcome"] for row in report["tasks"]], ["hit", "hit"])
        self.assertEqual(
            [line for line in (self.cache / "events").read_text().splitlines() if line.startswith("task_")],
            ["task_miss", "task_miss", "task_hit", "task_hit"],
        )
        self.assertEqual(cold.stdout, warm.stdout)
        source = self.project / "src" / "lib.rs"
        source.write_text("fn broken(\n", encoding="utf-8")
        self.write_spec(wrapper=BINARY)
        for stamp in spec["tasks"][0]["outputs"] + spec["tasks"][1]["outputs"]:
            (self.project / stamp).unlink(missing_ok=True)
        broken, report = self.run_task(expected=101)
        self.assertEqual(report["tasks"][0]["outcome"], "failed")
        self.assertEqual(len(report["tasks"]), 1)
        self.assertFalse((self.project / ".nanocompile-loop" / "validate.ok").exists())
        self.assertIn(b"error", broken.stderr.lower() + broken.stdout.lower())

    def test_discover_inputs_expands_crates_glob(self):
        (self.project / "Cargo.toml").write_text("[workspace]\nmembers = [\"crates/*\"]\n", encoding="utf-8")
        (self.project / "src" / "lib.rs").unlink()
        (self.project / "src").rmdir()
        core = self.project / "crates" / "core"
        (core / "src").mkdir(parents=True)
        (core / "Cargo.toml").write_text(
            "[package]\nname = \"core\"\nversion = \"0.1.0\"\nedition = \"2021\"\n",
            encoding="utf-8",
        )
        (core / "src" / "lib.rs").write_text("pub fn answer() -> u8 { 1 }\n", encoding="utf-8")
        skipped = self.helper.workspace_members((self.project / "Cargo.toml").read_text(encoding="utf-8"))
        self.assertEqual(skipped, ["crates/*"])
        self.assertEqual(self.helper.expand_workspace_members(self.project, skipped), ["crates/core"])
        inputs = self.helper.discover_inputs(self.project)
        self.assertIn("crates/core/src/lib.rs", inputs)
        self.assertIn("crates/core/Cargo.toml", inputs)

    def test_graph_noop_sees_workspace_glob_edits(self):
        (self.project / "Cargo.toml").write_text("[workspace]\nmembers = [\"crates/*\"]\n", encoding="utf-8")
        (self.project / "src" / "lib.rs").unlink()
        (self.project / "src").rmdir()
        core = self.project / "crates" / "core"
        (core / "src").mkdir(parents=True)
        (core / "Cargo.toml").write_text(
            "[package]\nname = \"core\"\nversion = \"0.1.0\"\nedition = \"2021\"\n",
            encoding="utf-8",
        )
        source = core / "src" / "lib.rs"
        source.write_text("pub fn answer() -> u8 { 1 }\n", encoding="utf-8")
        spec = self.write_spec(wrapper=BINARY)
        self.assertIn("crates/core/src/lib.rs", spec["tasks"][0]["inputs"])
        _, report = self.run_task()
        self.assertEqual([row["outcome"] for row in report["tasks"]], ["miss", "miss"])
        _, warm = self.run_task()
        self.assertEqual([row["outcome"] for row in warm["tasks"]], ["hit", "hit"])
        source.write_text("pub fn answer() -> u8 { 2 }\n", encoding="utf-8")
        _, edited = self.run_task()
        self.assertEqual(edited["tasks"][0]["outcome"], "miss")

    def test_example_specification_is_a_valid_rust_loop(self):
        spec_path = EXAMPLE / "nanocompile.tasks.json"
        self.helper_run(["check-spec", str(spec_path)], cwd=EXAMPLE)
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        self.assertEqual(spec["tasks"][0]["name"], "fast-check")
        self.assertEqual(spec["tasks"][1]["depends_on"], ["fast-check"])
        self.assertTrue((EXAMPLE / "Cargo.toml").is_file())
        self.assertTrue((EXAMPLE / "src" / "lib.rs").is_file())
        self.assertIn("Charlie Marsh", self.docs)


if __name__ == "__main__":
    if BINARY is None:
        raise SystemExit("usage: python3 tests/rust_loop.py /path/to/nanocompile")
    unittest.main(verbosity=2)
