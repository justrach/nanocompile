#!/usr/bin/env python3
"""Declared-task helper for a Rust edit-check-validate loop.

The native driver is `nanocompile rust-loop`. This script remains a
compatibility fallback (catalog + spec + run) for environments that have
not rebuilt the binary yet.

Python 3.9+, standard library only. Generates and checks schema-1
specifications for `nanocompile task`, and runs the per-step stamp
wrapper those tasks invoke.

The required graph is always:

    fast-check  ->  cargo check   (skip LLVM codegen)
    validate    ->  cargo test    (real rustc; depends_on fast-check)

A successful fast path is never treated as a release or commit gate.
`check-spec` rejects a graph that omits validate, runs it first, or
asks an experimental compiler to stand in for rustc.

See docs/rust-iteration.md.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

SCHEMA = 1
FAST_CHECK = "fast-check"
VALIDATE = "validate"
STAMP_DIR = ".nanocompile-loop"
FORBIDDEN_VALIDATE = (
    "cranelift",
    "codegen-backend",
    "cg_clif",
    "cargo-clif",
    "rustd",
    "lust",
    "relax",
)
CODEGEN_FLAGS = (
    "codegen-units",
    "incremental",
    "linker",
    "link-arg",
    "debuginfo",
    "split-debuginfo",
    "strip",
)
SOURCE_ROOTS = ("src", "tests", "examples", "benches")
CONFIG_FILES = (
    "Cargo.toml",
    "Cargo.lock",
    "rust-toolchain",
    "rust-toolchain.toml",
    "build.rs",
    ".cargo/config.toml",
    ".cargo/config",
)

# Usable-now recommendations. Commands and flags here were checked against
# current Cargo/rustc documentation or an installed toolchain. Do not add a
# crate or flag that has not been verified.
USABLE_NOW = (
    {
        "id": "fast-check",
        "role": "task",
        "title": "Skip codegen on the edit path",
        "command": ["cargo", "check"],
        "verified": "cargo check --help; rustc emits metadata only",
    },
    {
        "id": "validate",
        "role": "task",
        "title": "Real rustc test/build gate",
        "command": ["cargo", "test"],
        "verified": "cargo test runs rustc with the default LLVM backend",
    },
    {
        "id": "nanocompile-wrapper",
        "role": "recommendation",
        "title": "Cache eligible rustc invocations",
        "command": ["RUSTC_WRAPPER=nanocompile", "CARGO_INCREMENTAL=0", "cargo", "check"],
        "verified": "README RUSTC_WRAPPER protocol; incremental compilations are ineligible",
    },
    {
        "id": "rust-analyzer",
        "role": "recommendation",
        "title": "Editor diagnostics from rust-analyzer",
        "command": ["rust-analyzer"],
        "verified": "https://rust-analyzer.github.io/",
        "url": "https://rust-analyzer.github.io/",
    },
    {
        "id": "bacon",
        "role": "recommendation",
        "title": "Persistent cargo check/test watcher",
        "command": ["bacon"],
        "verified": "https://github.com/Canop/bacon",
        "url": "https://github.com/Canop/bacon",
    },
    {
        "id": "cranelift-dev",
        "role": "recommendation",
        "title": "Cranelift codegen for nightly dev builds",
        "command": [
            "rustup", "component", "add", "rustc-codegen-cranelift-preview",
            "--toolchain", "nightly",
        ],
        "verified": "https://doc.rust-lang.org/cargo/guide/build-performance.html",
        "url": "https://github.com/rust-lang/rustc_codegen_cranelift",
        "nightly": True,
    },
    {
        "id": "fast-linker",
        "role": "recommendation",
        "title": "Faster linker for cargo build",
        "command": ["rustc", "-C", "link-arg=-fuse-ld=lld"],
        "verified": "rustc -C help (link-arg, linker); rust-lld in the sysroot; mold in the Cargo book",
        "url": "https://doc.rust-lang.org/cargo/guide/build-performance.html",
    },
    {
        "id": "sccache",
        "role": "recommendation",
        "title": "Shared compile cache for C or as an alternate rustc wrapper",
        "command": ["sccache"],
        "verified": "https://github.com/mozilla/sccache",
        "url": "https://github.com/mozilla/sccache",
    },
    {
        "id": "crate-shape",
        "role": "recommendation",
        "title": "Split crates and keep codegen-units parallel",
        "command": ["rustc", "-C", "codegen-units=256"],
        "verified": "rustc -C help lists codegen-units",
    },
    {
        "id": "hot-reload",
        "role": "recommendation",
        "title": "Hot-reload a dylib or a Dioxus app",
        "command": ["hot-lib-reloader"],
        "verified": "https://github.com/rksm/hot-lib-reloader-rs; DioxusLabs/dioxus subsecond",
        "url": "https://github.com/rksm/hot-lib-reloader-rs",
    },
    {
        "id": "disk-hygiene",
        "role": "recommendation",
        "title": "Bound target and cache disk use",
        "command": ["nanocompile", "gc"],
        "verified": "nanocompile gc; cargo clean; profile.dev debug = line-tables-only",
        "url": "https://doc.rust-lang.org/cargo/guide/build-performance.html",
    },
)

# Experimental compilers from Charlie Marsh's 21 Oct 2026 thread.
# None of these may appear as the validate command.
EXPERIMENTAL = (
    {
        "id": "rustd",
        "title": "rustd (Jon Kelley / Dioxus Labs)",
        "url": "https://github.com/DioxusLabs/rustd",
        "thread": "https://x.com/jkelleyrtp/status/2110433801071689733",
    },
    {
        "id": "relax",
        "title": "Relax (Rik Arends)",
        "url": "https://x.com/rikarends/status/2112212283934077190",
        "thread": "https://x.com/charliermarsh/status/2112711399512092895",
        "public_repo_verified": False,
    },
    {
        "id": "lust",
        "title": "Lust (Theo)",
        "url": "https://github.com/t3dotgg/lust-lang",
        "thread": "https://x.com/theo/status/2112366051623375234",
    },
    {
        "id": "astral-fork",
        "title": "Astral rustc/cargo/rustfmt/clippy fork",
        "url": "https://x.com/charliermarsh/status/2112711411830804544",
        "open_source": False,
    },
    {
        "id": "upstream-perf",
        "title": "Rust project compiler performance optimizations",
        "url": "https://goals.rust-lang.org/2026/compiler-performance-optimization.html",
        "thread": "https://x.com/charliermarsh/status/2112711419334635917",
    },
)

CHARLIE_THREAD = "https://x.com/charliermarsh/status/2112711387285758250"


def fail(message):
    print("rust-loop: " + message, file=sys.stderr)
    raise SystemExit(2)


def posix(path):
    return Path(path).as_posix()


def which(name):
    found = shutil.which(name)
    if not found:
        fail("required executable not on PATH: " + name)
    return str(Path(found).resolve())


def members(root, directory):
    folder = root / directory
    if not folder.is_dir():
        return []
    result = []
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            continue
        mode = path.stat().st_mode
        if stat.S_ISREG(mode):
            result.append(posix(path.relative_to(root)))
    return result


def workspace_members(text):
    """Conservative [workspace].members reader; not a TOML library."""
    found = []
    section = None
    collecting = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            collecting = False
            continue
        if section != "workspace":
            continue
        if line.startswith("members"):
            collecting = True
            line = line.split("=", 1)[-1].strip()
        if not collecting:
            continue
        if line.startswith("["):
            line = line[1:]
        done = "]" in line
        line = line.split("]", 1)[0]
        for part in line.split(","):
            item = part.strip().strip("\"'")
            if item:
                found.append(item)
        if done:
            collecting = False
    return found


def expand_workspace_member(root, member):
    """Expand one Cargo workspace member, including `crates/*` globs.

    Returns absolute Path objects. Native `nanocompile rust-loop` does the
    same walk in Zig; this is the Python fallback.
    """
    root = Path(root)
    if any(char in member for char in "*?["):
        matches = [
            path.resolve() for path in sorted(root.glob(member))
            if path.is_dir() and (path / "Cargo.toml").is_file()
        ]
        if matches:
            return matches
    path = (root / member).resolve()
    return [path] if path.is_dir() and (path / "Cargo.toml").is_file() else []


def expand_workspace_members(root, patterns):
    """Expand Cargo workspace globs such as crates/* to relative package dirs."""
    root = Path(root)
    found = []
    seen = set()
    for pattern in patterns:
        for path in expand_workspace_member(root, pattern):
            rel = posix(path.resolve().relative_to(root.resolve()))
            if rel in seen:
                continue
            seen.add(rel)
            found.append(rel)
    return found


def discover_inputs(root):
    root = root.resolve()
    cargo = root / "Cargo.toml"
    if not cargo.is_file():
        fail("no Cargo.toml in " + str(root))
    paths = []
    packages = [root]
    for member in expand_workspace_members(root, workspace_members(cargo.read_text(encoding="utf-8"))):
        packages.append((root / member).resolve())
    seen = set()
    for package in packages:
        if not package.is_dir():
            continue
        for name in CONFIG_FILES:
            path = package / name
            if path.is_file() and not path.is_symlink():
                rel = posix(path.relative_to(root)) if path.is_relative_to(root) else posix(path)
                if rel not in seen:
                    seen.add(rel)
                    paths.append(rel)
        for directory in SOURCE_ROOTS:
            for rel in members(package if package == root else root, posix(path_under(root, package, directory))):
                if rel not in seen:
                    seen.add(rel)
                    paths.append(rel)
    return paths


def path_under(root, package, directory):
    if package == root:
        return directory
    return posix((package / directory).relative_to(root))


def rust_loop_script():
    return Path(__file__).resolve()


def validate_tokens(values):
    for value in values:
        lowered = value.lower()
        for banned in FORBIDDEN_VALIDATE:
            if banned in lowered:
                return banned
    return None


def check_spec(spec):
    if spec.get("schema") != SCHEMA:
        fail("specification schema must be 1")
    tasks = spec.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        fail("specification needs a non-empty tasks array")
    names = []
    by_name = {}
    for task in tasks:
        if not isinstance(task, dict):
            fail("each task must be an object")
        name = task.get("name")
        if not name or name in by_name:
            fail("tasks need unique names")
        if not task.get("command") or not task.get("inputs") or not task.get("outputs"):
            fail("task %s needs command, inputs and outputs" % name)
        for dep in task.get("depends_on") or []:
            if dep not in by_name:
                fail("task %s depends on a missing or later task" % name)
        names.append(name)
        by_name[name] = task
    if FAST_CHECK not in by_name or VALIDATE not in by_name:
        fail("a rust-loop specification needs both %s and %s" % (FAST_CHECK, VALIDATE))
    if names.index(FAST_CHECK) > names.index(VALIDATE):
        fail("%s must appear before %s" % (FAST_CHECK, VALIDATE))
    validate = by_name[VALIDATE]
    if FAST_CHECK not in (validate.get("depends_on") or []):
        fail("%s must list depends_on %s" % (VALIDATE, FAST_CHECK))
    banned = validate_tokens([str(part) for part in validate["command"]])
    if banned:
        fail("%s cannot invoke %s; use real rustc/cargo" % (VALIDATE, banned))
    fast = by_name[FAST_CHECK]
    if not any(str(part) == "check" for part in fast["command"]):
        fail("%s must run cargo check" % FAST_CHECK)
    if not any(str(part) == "test" for part in validate["command"]):
        fail("%s must run cargo test" % VALIDATE)
    return by_name


def spec_command(python, script_path, step, stamp, target_dir, offline, wrapper, cargo_subcommand, package=None):
    command = [python, "-I", "-S", "-B", posix(script_path), "run",
               "--step", step, "--stamp", stamp, "--target-dir", target_dir]
    if offline:
        command.append("--offline")
    if wrapper:
        command.extend(["--wrapper", posix(wrapper)])
    command.extend(["--", "cargo", cargo_subcommand])
    if package:
        command.extend(["-p", package])
    return command


def build_spec(root, python, offline, wrapper, target_dir, package=None):
    script = rust_loop_script()
    inputs = discover_inputs(root)
    script_input = posix(os.path.relpath(script, root))
    if script_input not in inputs:
        inputs.insert(0, script_input)
    fast_stamp = STAMP_DIR + "/fast-check.ok"
    validate_stamp = STAMP_DIR + "/validate.ok"
    spec = {
        "schema": SCHEMA,
        "tasks": [
            {
                "name": FAST_CHECK,
                "cwd": ".",
                "command": spec_command(python, script_input, FAST_CHECK, fast_stamp, target_dir,
                                        offline, wrapper, "check", package),
                "inputs": list(inputs),
                "outputs": [fast_stamp],
            },
            {
                "name": VALIDATE,
                "cwd": ".",
                "depends_on": [FAST_CHECK],
                "command": spec_command(python, script_input, VALIDATE, validate_stamp, target_dir,
                                        offline, wrapper, "test", package),
                "inputs": list(inputs) + [fast_stamp],
                "outputs": [validate_stamp],
            },
        ],
    }
    if wrapper:
        cargo = which("cargo")
        rustc = which("rustc")
        for task in spec["tasks"]:
            task["tool_resources"] = [cargo, rustc]
    check_spec(spec)
    return spec


def rustc_help():
    return subprocess.check_output(["rustc", "-C", "help"], text=True, stderr=subprocess.STDOUT)


def rust_lld():
    sysroot = subprocess.check_output(["rustc", "--print", "sysroot"], text=True).strip()
    matches = list(Path(sysroot).glob("lib/rustlib/*/bin/rust-lld"))
    matches += list(Path(sysroot).glob("lib/rustlib/*/bin/rust-lld.exe"))
    return [str(path) for path in matches]


def verify_toolchain():
    help_text = rustc_help()
    missing = [flag for flag in CODEGEN_FLAGS if flag not in help_text]
    if missing:
        fail("rustc -C help is missing " + ", ".join(missing))
    check = subprocess.run(["cargo", "check", "--help"], check=True, capture_output=True, text=True)
    if "Check a local package" not in check.stdout:
        fail("cargo check --help did not describe check")
    test = subprocess.run(["cargo", "test", "--help"], check=True, capture_output=True, text=True)
    if "unit and integration tests" not in test.stdout.lower() and "run the tests" not in test.stdout.lower():
        fail("cargo test --help did not describe test")
    if not rust_lld():
        fail("rust-lld is not present in the rustc sysroot")
    return {
        "rustc_codegen_flags": list(CODEGEN_FLAGS),
        "rust_lld": rust_lld(),
        "cargo_check": True,
        "cargo_test": True,
    }


def run_step(step, stamp, target_dir, offline, wrapper, cargo_argv):
    if step not in (FAST_CHECK, VALIDATE):
        fail("unknown step " + step)
    if not cargo_argv:
        fail("missing cargo command after --")
    if step == VALIDATE:
        banned = validate_tokens(cargo_argv + [os.environ.get(name, "") for name in os.environ
                                              if "CODEGEN_BACKEND" in name])
        if banned:
            fail("validate refuses %s; the gate must be real rustc" % banned)
        for name, value in list(os.environ.items()):
            if name.endswith("CODEGEN_BACKEND") and value.lower() == "cranelift":
                fail("validate refuses a cranelift codegen backend")
    env = dict(os.environ)
    env["CARGO_TARGET_DIR"] = str(Path(target_dir).resolve())
    env.pop("CARGO_PROFILE_DEV_CODEGEN_BACKEND", None)
    env.pop("CARGO_PROFILE_TEST_CODEGEN_BACKEND", None)
    if wrapper:
        env["RUSTC_WRAPPER"] = str(Path(wrapper).resolve())
        env["CARGO_INCREMENTAL"] = "0"
    elif step == VALIDATE:
        env.pop("RUSTC_WRAPPER", None)
        env.pop("RUSTC_WORKSPACE_WRAPPER", None)
    argv = list(cargo_argv)
    if offline and "--offline" not in argv:
        argv.append("--offline")
    completed = subprocess.run(argv, env=env)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    destination = Path(stamp)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(step + "\n", encoding="utf-8")
    return 0


def print_catalog():
    print(json.dumps({
        "schema": SCHEMA,
        "attribution": CHARLIE_THREAD,
        "usable_now": list(USABLE_NOW),
        "experimental": list(EXPERIMENTAL),
        "required_tasks": [FAST_CHECK, VALIDATE],
    }, indent=2))
    print()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    spec = sub.add_parser("spec", help="write a schema-1 rust-loop task specification")
    spec.add_argument("--manifest", default="Cargo.toml")
    spec.add_argument("--write", default="-")
    spec.add_argument("--python", default=sys.executable)
    spec.add_argument("--wrapper")
    spec.add_argument("--target-dir", default="target")
    spec.add_argument("--package", help="cargo -p PACKAGE for fast-check and validate")
    spec.add_argument("--offline", action="store_true")

    check = sub.add_parser("check-spec", help="reject a spec that skips the rustc gate")
    check.add_argument("specification")

    run = sub.add_parser("run", help="execute one rust-loop step and write its stamp")
    run.add_argument("--step", required=True, choices=(FAST_CHECK, VALIDATE))
    run.add_argument("--stamp", required=True)
    run.add_argument("--target-dir", default="target")
    run.add_argument("--offline", action="store_true")
    run.add_argument("--wrapper")
    run.add_argument("command", nargs=argparse.REMAINDER)

    sub.add_parser("list", help="print the usable-now and experimental catalogs")
    sub.add_parser("verify-flags", help="confirm documented rustc/cargo flags exist")

    args = parser.parse_args(argv)
    if args.action == "list":
        print_catalog()
        return 0
    if args.action == "verify-flags":
        print(json.dumps(verify_toolchain(), indent=2))
        print()
        return 0
    if args.action == "check-spec":
        check_spec(json.loads(Path(args.specification).read_text(encoding="utf-8")))
        print("PASS: rust-loop specification keeps %s before %s" % (FAST_CHECK, VALIDATE))
        return 0
    if args.action == "spec":
        root = Path(args.manifest).resolve().parent
        document = build_spec(root, args.python, args.offline, args.wrapper, args.target_dir, args.package)
        encoded = json.dumps(document, indent=2) + "\n"
        if args.write == "-":
            sys.stdout.write(encoded)
        else:
            Path(args.write).write_text(encoded, encoding="utf-8")
        return 0
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    return run_step(args.step, args.stamp, args.target_dir, args.offline, args.wrapper, command)


if __name__ == "__main__":
    raise SystemExit(main())
