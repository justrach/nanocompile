#!/usr/bin/env python3
"""Workspace-glob coverage for rust-loop input discovery.

Large Cargo workspaces write `members = ["crates/*"]`. The helper must expand
that glob so crate sources participate in the declared-task contract.

Run: python3 tests/rust_loop_workspace_glob.py
"""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import rust_loop  # noqa: E402


class WorkspaceGlob(unittest.TestCase):
    def test_expand_crates_star(self):
        with tempfile.TemporaryDirectory(prefix="nano rust loop ws ") as tmp:
            root = Path(tmp)
            (root / "Cargo.toml").write_text(
                '[workspace]\nmembers = ["crates/*"]\n', encoding="utf-8"
            )
            leaf = root / "crates" / "leaf"
            hub = root / "crates" / "hub"
            for package in (leaf, hub):
                (package / "src").mkdir(parents=True)
                (package / "Cargo.toml").write_text(
                    '[package]\nname = "%s"\nversion = "0.1.0"\nedition = "2021"\n'
                    % package.name,
                    encoding="utf-8",
                )
                (package / "src" / "lib.rs").write_text("pub fn x() {}\n", encoding="utf-8")
            self.assertEqual(
                rust_loop.workspace_members((root / "Cargo.toml").read_text(encoding="utf-8")),
                ["crates/*"],
            )
            expanded = rust_loop.expand_workspace_member(root, "crates/*")
            self.assertEqual({path.name for path in expanded}, {"hub", "leaf"})
            self.assertEqual(
                set(rust_loop.expand_workspace_members(root, ["crates/*"])),
                {"crates/hub", "crates/leaf"},
            )
            inputs = rust_loop.discover_inputs(root)
            self.assertIn("crates/leaf/src/lib.rs", inputs)
            self.assertIn("crates/hub/src/lib.rs", inputs)
            self.assertIn("crates/leaf/Cargo.toml", inputs)


if __name__ == "__main__":
    unittest.main()
