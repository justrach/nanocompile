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
        self.assertEqual(argv[:4], ["cargo", "+nightly", "-Zcodegen-backend", "build"])

    def test_cranelift_check_still_enables_backend_flag(self):
        argv = BENCH.cargo_argv("build", 0, False, "nightly", ["-Zcodegen-backend"])
        self.assertEqual(argv[:4], ["cargo", "+nightly", "-Zcodegen-backend", "build"])

    def test_cargo_z_flags_precede_subcommand(self):
        argv = BENCH.cargo_argv("test", 0, True, "nightly", ["-Zcodegen-backend", "--no-run"])
        self.assertEqual(argv[:4], ["cargo", "+nightly", "-Zcodegen-backend", "test"])
        self.assertIn("--no-run", argv)
        self.assertLess(argv.index("-Zcodegen-backend"), argv.index("test"))
        self.assertGreater(argv.index("--no-run"), argv.index("test"))

    def test_nightly_llvm_control_has_no_cranelift_flag(self):
        argv = BENCH.cargo_argv("build", 0, False, "nightly")
        self.assertEqual(argv[:3], ["cargo", "+nightly", "build"])
        self.assertNotIn("-Zcodegen-backend", argv)

    def test_cranelift_uses_rustc_flag_not_cargo_profile_env(self):
        env = BENCH.genome_env(
            {"dev_backend": "cranelift", "loop": "build"},
            None, {"sccache": False}, Path("/tmp/sccache"), None,
        )
        self.assertNotIn("CARGO_PROFILE_DEV_CODEGEN_BACKEND", env)
        self.assertNotIn("CARGO_PROFILE_TEST_CODEGEN_BACKEND", env)
        self.assertIn("-Zcodegen-backend=cranelift", env.get("RUSTFLAGS", ""))

    def test_llvm_check_stays_on_default_toolchain(self):
        argv = BENCH.genome_argv(
            {"dev_backend": "llvm", "loop": "check"},
            "check", None, False, None, None,
        )
        self.assertEqual(argv[:2], ["cargo", "check"])
        self.assertNotIn("+nightly", argv)
        self.assertNotIn("-Zcodegen-backend", argv)

    def test_evaluation_row_marks_from_samples_held_out(self):
        row = BENCH.evaluation_row(
            "mid|cold", "mid", "cold",
            BENCH.default_genome(),
            {"median_ms": 1.0, "stdev_ms": 0.0, "target_bytes": 1, "samples_ms": [1.0]},
            {"agree_on_broken": True, "validate_is_final": True},
            "hashbrown-from-rach-repos",
            "deadbeef",
        )
        self.assertTrue(row["held_out"])
        named = BENCH.evaluation_row(
            "mid|cold", "mid", "cold",
            BENCH.default_genome(),
            {"median_ms": 1.0, "stdev_ms": 0.0, "target_bytes": 1, "samples_ms": [1.0]},
            {"agree_on_broken": True, "validate_is_final": True},
            "pinned-hashbrown-held-out",
            "deadbeef",
        )
        self.assertTrue(named["held_out"])
        occupy = BENCH.evaluation_row(
            "mid|cold", "mid", "cold",
            BENCH.default_genome(),
            {"median_ms": 1.0, "stdev_ms": 0.0, "target_bytes": 1, "samples_ms": [1.0]},
            {"agree_on_broken": True, "validate_is_final": True},
            "pinned-hashbrown",
            "deadbeef",
        )
        self.assertFalse(occupy["held_out"])

    def test_cold_clears_sccache_dir(self):
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="nano-sccache-"))
        cache = root / "sccache"
        cache.mkdir()
        (cache / "hit").write_text("x", encoding="utf-8")
        BENCH._clear_nano_cache({"SCCACHE_DIR": str(cache)})
        self.assertFalse(cache.exists())

    def test_seed_genomes_measure_check_before_test(self):
        seeds = BENCH.seed_genomes("/bin/true", {"sccache": True, "mold": True, "cranelift": True})
        loops = [row["loop"] for row in seeds]
        first_test = next(i for i, loop in enumerate(loops) if loop in ("test", "graph"))
        self.assertIn("check", loops[:first_test])
        self.assertIn("build", loops[:first_test])


class NightlyPair(unittest.TestCase):
    def test_pair_argv_isolates_backend_from_runner(self):
        path = ROOT / "bench" / "nightly_pair.py"
        spec = importlib.util.spec_from_file_location("nightly_pair", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        llvm = module.pair_argv("test", False, None, True)
        cranelift = module.pair_argv("test", True, None, True)
        self.assertEqual(llvm[:3], ["cargo", "+nightly", "test"])
        self.assertIn("--no-run", llvm)
        self.assertNotIn("-Zcodegen-backend", llvm)
        self.assertEqual(cranelift[:4], ["cargo", "+nightly", "-Zcodegen-backend", "test"])
        self.assertIn("--no-run", cranelift)
        self.assertLess(cranelift.index("-Zcodegen-backend"), cranelift.index("test"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
