#!/usr/bin/env python3
"""Real declared-task/Zig-intermediate layering check; no project source edits.

python3 tests/task_layering.py zig-out/bin/nanocompile --runs 3 --output report.json
Requires the repository's supported Zig 0.17.0; uses only Python's stdlib.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess
import tempfile
import time


BUILD = '''const std = @import("std");
pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const stable = b.addObject(.{ .name = "stable", .root_module = b.createModule(.{
        .root_source_file = b.path("stable.zig"), .target = target, .optimize = optimize, .strip = true,
    }) });
    const options = b.addOptions();
    options.addOption([]const u8, "version", b.option([]const u8, "version", "Embedded version") orelse "unset");
    const module = b.createModule(.{
        .root_source_file = b.path("main.zig"), .target = target, .optimize = optimize, .strip = true,
    });
    module.addOptions("options", options);
    module.addObject(stable);
    const exe = b.addExecutable(.{ .name = "layering", .root_module = module });
    b.installArtifact(exe);
}
'''
STABLE = 'export fn answer() u32 { return 42; }\n'
MAIN = '''const std = @import("std");
const options = @import("options");
extern fn answer() u32;
pub fn main() void {
    std.debug.print("task-layering version={s} result={d}\\n", .{ options.version, answer() + BIAS });
}
'''
OVERRIDES = ("ZIG_LIB_DIR", "ZIG_LIBC", "ZIG_LOCAL_PKG_DIR", "CC", "CXX",
             "PKG_CONFIG", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "LIBRARY_PATH",
             "CPATH", "NIX_CFLAGS_COMPILE", "NIX_CFLAGS_LINK", "NIX_LDFLAGS")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(command, *, cwd=None, env=None):
    result = subprocess.run([str(p) for p in command], cwd=cwd, env=env,
                            capture_output=True, timeout=300)
    # Do not copy compiler diagnostics containing local paths into reports/logs.
    require(result.returncode == 0, "subprocess failed (diagnostics withheld; inspect the fixture locally)")
    return result


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resources_under(root, links):
    """Full installed resource tree, including an explicit alias map, no cycles."""
    result, visited = set(), set()

    def visit(path):
        real = path.resolve()
        if path.is_symlink():
            links[str(path)] = str(real)
        if path.is_dir():
            if real in visited:
                return
            visited.add(real)
            for child in sorted(path.iterdir()):
                visit(child)
        elif path.is_file():
            result.add(str(real))
        else:
            require(path.is_symlink() and not path.exists(), "unsupported installed resource")

    visit(root)
    return result


def discover(zig_arg, clean_env):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("NANOCOMPILE_", "R2_", "KACHE_"))}
    if clean_env:
        for name in OVERRIDES:
            env.pop(name, None)
    require(not any(env.get(k) for k in OVERRIDES), "unset compiler/library overrides or pass --clean-env")
    # Explicit directories below replace all ambient cache locations.
    for name in ("ZIG_GLOBAL_CACHE_DIR", "ZIG_LOCAL_CACHE_DIR"):
        env.pop(name, None)
    zig = shutil.which(zig_arg)
    require(zig is not None, "Zig executable not found")
    version = run([zig, "version"], env=env).stdout.decode().strip()
    require(version == "0.17.0", "requires the supported Zig 0.17.0")
    text = run([zig, "env"], env=env).stdout.decode()
    paths = {}
    for name in ("zig_exe", "lib_dir"):
        match = re.search(r'\.' + name + r'\s*=\s*("(?:[^"\\]|\\.)*")', text)
        require(match is not None, "unsupported Zig environment response")
        paths[name] = Path(json.loads(match.group(1))).resolve(strict=True)
    system = platform.system()
    arch = {"arm64": "aarch64", "aarch64": "aarch64", "amd64": "x86_64",
            "x86_64": "x86_64"}.get(platform.machine().lower())
    abi = {"Darwin": "macos", "Linux": "linux-musl", "Windows": "windows-gnu"}.get(system)
    require(arch is not None and abi is not None, "unsupported native host")
    sdk = None
    if system == "Darwin":
        sdk = Path(env.get("SDKROOT") or run(
            ["xcrun", "--sdk", "macosx", "--show-sdk-path"], env=env
        ).stdout.decode().strip()).resolve(strict=True)
    return paths["zig_exe"], paths["lib_dir"], sdk, arch + "-" + abi, env, version


def write_if_changed(path, text):
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def trial(binary, zig_arg, root, iteration, clean_env):
    started = time.perf_counter()
    zig, lib, sdk, target, env, zig_version = discover(zig_arg, clean_env)
    root.mkdir()
    (root / "build.zig").write_text(BUILD)
    (root / "stable.zig").write_text(STABLE)
    env.update(NANOCOMPILE_DIR=str(root / "nano"),
               ZIG_GLOBAL_CACHE_DIR=str(root / "zig-global"),
               ZIG_LOCAL_CACHE_DIR=str(root / "zig-local"))
    output = root / "out" / "bin" / ("layering.exe" if platform.system() == "Windows" else "layering")
    events = root / "nano" / "events"
    rows, references = [], {}
    phases = [
        ("cold", 0, "1.0.0", "empty", "task_miss"),
        ("identical_warm", 0, "1.0.0", "retained", "task_hit"),
        ("source_edit", 1, "1.0.0", "retained", "task_miss"),
        ("version_only", 1, "1.0.1", "retained", "task_miss"),
        ("version_warm", 1, "1.0.1", "retained", "task_hit"),
        ("source_edit_fresh", 1, "1.0.0", "empty", "task_miss"),
        ("version_only_fresh", 1, "1.0.1", "empty", "task_miss"),
    ]
    for phase, bias, version, compiler_state, expected_event in phases:
        if phase != "cold":
            started = time.perf_counter()
        if compiler_state == "empty":
            # Fresh controls evict task entries but retain Nano's installed-tool
            # memos/blobs: the intended comparison changes Zig cache state,
            # rather than also forcing a second full SDK identity hash.
            names = ("nano", "zig-local", "zig-global") if phase == "cold" else ("nano/entries", "zig-local", "zig-global")
            for name in names:
                if (root / name).exists():
                    shutil.rmtree(root / name)
        # Delete the whole installation, not just the executable, before every
        # call. Compiler caches live elsewhere. A Nano hit must restore it.
        if (root / "out").exists():
            shutil.rmtree(root / "out")
        write_if_changed(root / "main.zig", MAIN.replace("BIAS", str(bias)))
        links = {}
        resources = {str(zig)} | resources_under(lib, links)
        if sdk is not None:
            resources |= resources_under(sdk, links)
        write_if_changed(root / "resource-links.json", json.dumps(links, sort_keys=True))
        command = [str(zig), "build", "-j1", "--summary", "all", "-Doptimize=ReleaseFast",
                   "-Dtarget=" + target, "-Dversion=" + version, "--prefix", str(root / "out"),
                   "--cache-dir", str(root / "zig-local")]
        if sdk is not None:
            command += ["--sysroot", str(sdk)]
        spec = {"schema": 1, "tasks": [{
            "name": "task-layering", "cwd": str(root), "command": command,
            "inputs": [str(root / name) for name in ("build.zig", "main.zig", "stable.zig", "resource-links.json")],
            "outputs": [str(output)], "tool_resources": sorted(resources),
        }]}
        (root / "task.json").write_text(json.dumps(spec))
        offset = events.stat().st_size if events.exists() else 0
        setup_done = time.perf_counter()
        result = run([binary, "task", root / "task.json"], cwd=root, env=env)
        process_done = time.perf_counter()
        actual_events = events.read_bytes()[offset:].decode().splitlines()
        require(actual_events == [expected_event], "unexpected task event in " + phase)
        executed = expected_event == "task_miss"
        # A hit replays old diagnostics. NEVER treat a replayed build summary as
        # evidence that Zig ran or its object cache was consulted on this call.
        summary = result.stderr.decode(errors="replace")
        stable_cached = bool(re.search(r"compile obj stable[^\r\n]*\bcached\b", summary)) if executed else None
        if executed:
            require("compile obj stable" in summary, "Zig summary omitted stable object")
            require(stable_cached == (compiler_state == "retained"), "unexpected stable-object cache status in " + phase)
        check = run([output], cwd=root, env=env)
        expected = f"task-layering version={version} result={42 + bias}\n"
        require((check.stdout + check.stderr).decode() == expected, "wrong artifact behavior or embedded version")
        installed = [p for p in (root / "out").rglob("*") if p.is_file()]
        require(installed == [output], "build installed undeclared output sidecars")
        digest, mode = sha(output), output.stat().st_mode
        key = (bias, version)
        matches_retained = None
        if key in references:
            matches_retained = digest == references[key][0]
            require(mode == references[key][1], "restore/fresh build changed permissions")
            if expected_event == "task_hit":
                require(matches_retained, "task restore changed executable bytes")
        else:
            require(digest not in [entry[0] for entry in references.values()], "changed source/version did not change artifact")
            references[key] = (digest, mode)
        verified = time.perf_counter()
        row = {"iteration": iteration, "phase": phase, "task_event": expected_event,
               "compiler_cache_before": compiler_state,
               "task_cache_before": "empty" if phase == "cold" else ("entries_evicted_tools_retained" if compiler_state == "empty" else "retained"),
               "compiler_executed": executed,
               "stable_object_cached_reported_by_zig": stable_cached,
               "setup_seconds": setup_done - started,
               "task_process_seconds": process_done - setup_done,
               "verification_seconds": verified - process_done,
               "total_seconds": verified - started,
               "tool_resource_files": len(resources), "artifact_bytes": output.stat().st_size,
               "artifact_sha256": digest, "matches_retained_sha256": matches_retained,
               "embedded_version": version, "behavior_result": 42 + bias}
        rows.append(row)
        print(json.dumps({k: row[k] for k in ("iteration", "phase", "task_event", "stable_object_cached_reported_by_zig", "total_seconds")}), flush=True)
    return rows, zig_version, target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path, help="existing native nanocompile; never built by this test")
    parser.add_argument("--zig", default="zig")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--clean-env", action="store_true", help="ignore compiler/library overrides for child processes only")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(args.runs > 0, "--runs must be positive")
    binary = args.binary.resolve(strict=True)
    started = time.perf_counter()
    rows = []
    # All generated specs, absolute paths, alias maps, compiler logs and caches
    # remain temporary. The allowlisted report contains none of those details.
    with tempfile.TemporaryDirectory(prefix="nano-task-layering-") as directory:
        for iteration in range(args.runs):
            sample, version, target = trial(binary, args.zig, Path(directory) / str(iteration), iteration, args.clean_env)
            rows.extend(sample)
    report = {
        "schema": 1, "zig_version": version, "target": target, "runs": args.runs,
        "validation_scope": "Results cover this native invocation series only; no hosted workflow or other platform validation is asserted.",
        "method": "One declared whole-build task over Zig build intermediates; stable object plus edited executable; isolated cold caches per trial; retained caches across source and version changes; fresh Zig-cache controls evict Nano task entries but retain its installed-tool memos/blobs and use identical paths, arguments and environment; delete installed outputs before every call; no network or recursive Nano compiler wrapping.",
        "timing_scope": "Each total includes fixture/contract/resource enumeration, output cleanup and applicable cache reset, full Nano process (hashing, identity, lookup/restore, child, revalidation/storage), and runtime/hash verification. Cold also includes tool/SDK discovery and initial fixture creation. Session elapsed additionally includes temporary-directory cleanup. Compiler installation and Nano bootstrap are preconditions, not timed. OS page caches are not flushed.",
        "compiler_evidence": "Zig --summary all explicitly reports compile obj stable cached on source/version task misses; fresh-cache controls must report uncached. No compiler hit counts are inferred from timings or replayed task-hit diagnostics.",
        "limitations": ["Small synthetic fixture, not nanocompile self-build throughput or a general compiler-cache speedup.",
                        "Cold starts with empty Zig/Nano caches; fresh controls empty Zig caches and Nano task entries but retain Nano installed-tool memos/blobs. Neither flushes operating-system caches.",
                        "Sequential fixed phase order, shared host activity and filesystem page caches can bias timings; no speed threshold.",
                        "Zig summaries establish reuse of one stable object only, not reuse inside the changed executable or the build runner.",
                        "Native execution only; compiler installation/SDK and Nano bootstrap time are outside this benchmark.",
                        "Independent fresh compilations need not be byte-identical; their hashes are compared and reported, while runtime behavior/version and permissions must match. Task restores must be byte-identical.",
                        "No cache transport, relocatability, per-invocation Nano compiler interception or new compiler eligibility is implemented."],
        "checks": ["cold task miss", "deleted-output identical warm restore", "source-edit task miss with observed stable-object reuse", "version-only command change misses with observed stable-object reuse", "changed-version restore", "fresh-cache controls have no stable-object hit", "exact runtime behavior and embedded versions", "task restores match artifact SHA-256 and mode", "fresh controls match behavior, version and mode; byte equality reported separately", "only declared executable installed; no sidecars"],
        "rows": rows,
        "median_total_seconds": {phase: statistics.median(row["total_seconds"] for row in rows if row["phase"] == phase)
                                 for phase in dict.fromkeys(row["phase"] for row in rows)},
        "session_elapsed_seconds": time.perf_counter() - started,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print("PASS: declared-task misses retain verified Zig object reuse; fresh controls and versions match")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        # Our RuntimeError messages contain only fixed text and fixture phases.
        raise SystemExit("FAIL: " + str(error))
    except (OSError, subprocess.TimeoutExpired):
        # Keep exception paths/commands/environment out of shareable CI logs.
        raise SystemExit("FAIL: task-layering I/O or subprocess timeout (no report written)")
