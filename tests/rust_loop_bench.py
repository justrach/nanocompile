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

    def test_cargo_argv_includes_package(self):
        argv = BENCH.cargo_argv("check", 0, False, package="ruff")
        self.assertEqual(argv[:4], ["cargo", "check", "-p", "ruff"])
        genome = BENCH.default_genome(package="ruff", loop="check")
        argv = BENCH.genome_argv(genome, "check", None, False, None, None)
        self.assertIn("-p", argv)
        self.assertEqual(argv[argv.index("-p") + 1], "ruff")

    def test_broken_edit_prefers_body_mark_file(self):
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="nano-mark-"))
        first = root / "a.rs"
        first.write_text("fn first() {}\n", encoding="utf-8")
        marked = root / "crates" / "cmd" / "src"
        marked.mkdir(parents=True)
        lib = marked / "lib.rs"
        lib.write_text("// nano-loop-body\nfn is_response_file() {}\n", encoding="utf-8")
        record = BENCH.edit_project(root, "broken")
        self.assertEqual(record[0], lib)
        self.assertIn('let _nano_loop_body: u32 = "nope";', lib.read_text(encoding="utf-8"))
        self.assertEqual(first.read_text(encoding="utf-8"), "fn first() {}\n")
        BENCH.restore_edit(record)
        self.assertEqual(lib.read_text(encoding="utf-8"), "// nano-loop-body\nfn is_response_file() {}\n")

    def test_run_cell_applies_and_reverts_each_edit_run(self):
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="nano-edit-runs-"))
        src = root / "src"
        src.mkdir()
        lib = src / "lib.rs"
        lib.write_text("fn mark() { // nano-loop-body\n}\n", encoding="utf-8")
        seen = []

        def fake_measure(argv, cwd, env, target):
            text = lib.read_text(encoding="utf-8")
            seen.append("_nano_loop_body" in text)
            return {"ms": 1.0, "returncode": 0, "target_bytes": 0, "stderr_tail": "", "stdout_tail": ""}

        original = BENCH.measure_once
        BENCH.measure_once = fake_measure
        try:
            step = type("S", (), {"id": "t", "title": "t"})()
            summary = BENCH.run_cell(step, "check", "body", ["true"], root, {}, root / "target", 0, 3, "body")
        finally:
            BENCH.measure_once = original
        self.assertEqual(summary["ok"], True)
        self.assertEqual(len(summary["samples_ms"]), 3)
        # Timed samples see the edit; restore rebuilds see the original.
        self.assertEqual(seen, [True, False, True, False, True, False])
        self.assertNotIn("_nano_loop_body", lib.read_text(encoding="utf-8"))

    def test_body_clears_compiler_cache_unless_warm_store(self):
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="nano-body-cache-"))
        cache = root / "kache"
        cache.mkdir()
        (cache / "hit").write_text("x", encoding="utf-8")
        lib = root / "lib.rs"
        lib.write_text("fn mark() { // nano-loop-body\n}\n", encoding="utf-8")
        env = {"KACHE_CACHE_DIR": str(cache)}
        original = BENCH.measure_once
        BENCH.measure_once = lambda *a, **k: {
            "ms": 1.0, "returncode": 0, "target_bytes": 0, "stderr_tail": "", "stdout_tail": "",
        }
        try:
            step = type("S", (), {"id": "t", "title": "t"})()
            BENCH.run_cell(step, "check", "body", ["true"], root, env, root / "target", 0, 1, "body")
        finally:
            BENCH.measure_once = original
        self.assertFalse(cache.exists())

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

    def test_kache_env_is_exclusive(self):
        env = BENCH.genome_env(
            BENCH.default_genome(kache=True, incremental=True),
            None, {"kache": "/usr/bin/kache"}, Path("/tmp/sccache"), None,
            Path("/tmp/kache-store"),
        )
        self.assertEqual(env["RUSTC_WRAPPER"], "/usr/bin/kache")
        self.assertEqual(env["KACHE_CACHE_DIR"], "/tmp/kache-store")
        self.assertEqual(env["KACHE_LOCAL_ONLY"], "1")
        self.assertEqual(env["KACHE_SCHEDULER"], "0")
        self.assertEqual(env["CARGO_INCREMENTAL"], "1")
        with self.assertRaises(ValueError):
            BENCH.genome_env(
                BENCH.default_genome(kache=True, sccache=True),
                None, {"kache": "/usr/bin/kache", "sccache": "/usr/bin/sccache"},
                Path("/tmp/sccache"), None, Path("/tmp/kache-store"),
            )
        with self.assertRaises(ValueError):
            BENCH.genome_env(
                BENCH.default_genome(kache=True, wrapper=True),
                "/bin/nano", {"kache": "/usr/bin/kache"},
                Path("/tmp/sccache"), None, Path("/tmp/kache-store"),
            )

    def test_cargo_loop_argv_nextest_and_clippy(self):
        nextest = BENCH.cargo_loop_argv("nextest", 4, True, package="ruff")
        self.assertEqual(nextest[:3], ["cargo", "nextest", "run"])
        self.assertIn("-p", nextest)
        self.assertEqual(nextest[nextest.index("-p") + 1], "ruff")
        self.assertIn("--offline", nextest)
        clippy = BENCH.cargo_loop_argv("clippy", None, False)
        self.assertEqual(clippy[:2], ["cargo", "clippy"])
        nightly = BENCH.genome_argv(
            BENCH.default_genome(share_generics=True, loop="check"),
            "check", None, False, None, None,
        )
        self.assertEqual(nightly[:3], ["cargo", "+nightly", "check"])

    def test_worktree_and_warm_store_cache_state(self):
        cold_empty = BENCH.evaluation_row(
            "mid|worktree", "mid", "worktree",
            BENCH.default_genome(kache=True),
            {"median_ms": 1.0, "stdev_ms": 0.0, "target_bytes": 1, "samples_ms": [1.0]},
            {"agree_on_broken": True, "validate_is_final": True},
            "pinned-hashbrown", "deadbeef",
        )
        self.assertEqual(cold_empty["cache_state"], "empty")
        warm = BENCH.evaluation_row(
            "mid|worktree", "mid", "worktree",
            BENCH.default_genome(kache=True, warm_store=True),
            {"median_ms": 1.0, "stdev_ms": 0.0, "target_bytes": 1, "samples_ms": [1.0]},
            {"agree_on_broken": True, "validate_is_final": True},
            "pinned-hashbrown", "deadbeef",
        )
        self.assertEqual(warm["cache_state"], "warm_compiler_cache")
        noop = BENCH.evaluation_row(
            "mid|noop", "mid", "noop",
            BENCH.default_genome(kache=True, warm_store=True),
            {"median_ms": 1.0, "stdev_ms": 0.0, "target_bytes": 1, "samples_ms": [1.0]},
            {"agree_on_broken": True, "validate_is_final": True},
            "pinned-hashbrown", "deadbeef",
        )
        self.assertIsNone(noop["cache_state"])

    def test_clear_kache_dir(self):
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="nano-kache-"))
        cache = root / "kache"
        cache.mkdir()
        (cache / "hit").write_text("x", encoding="utf-8")
        BENCH._clear_nano_cache({"KACHE_CACHE_DIR": str(cache)})
        self.assertFalse(cache.exists())


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
