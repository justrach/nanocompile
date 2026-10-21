#!/usr/bin/env python3
"""Harness helpers: cranelift activation and genome argv."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_bench():
    path = ROOT / "bench" / "rust_loop_bench.py"
    spec = importlib.util.spec_from_file_location("rust_loop_bench", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BENCH = load_bench()


class RustLoopBench(unittest.TestCase):
    def test_cranelift_build_uses_nightly_unstable_flag(self):
        argv = BENCH.genome_argv(
            {"dev_backend": "cranelift", "loop": "build"},
            "check", None, False, None, None,
        )
        self.assertEqual(argv[:3], ["cargo", "+nightly", "build"])
        self.assertIn("-Zcodegen-backend", argv)

    def test_cranelift_check_still_enables_backend_flag(self):
        argv = BENCH.cargo_argv("build", 0, False, "nightly", ["-Zcodegen-backend"])
        self.assertEqual(argv[:2], ["cargo", "+nightly"])
        self.assertIn("-Zcodegen-backend", argv)

    def test_llvm_check_stays_on_default_toolchain(self):
        argv = BENCH.genome_argv(
            {"dev_backend": "llvm", "loop": "check"},
            "check", None, False, None, None,
        )
        self.assertEqual(argv[:2], ["cargo", "check"])
        self.assertNotIn("+nightly", argv)
        self.assertNotIn("-Zcodegen-backend", argv)


if __name__ == "__main__":
    unittest.main(verbosity=2)
