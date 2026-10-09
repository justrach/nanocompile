"""Probe proc-macro producer inputs using real rustc and linker dependency reports.

Diagnostic fixture only: this does not enable producer caching. A native
archive changes while producer sources, explicit externs and dep-info remain
unchanged. The macro is loaded by rustc and its expansion is executed.
"""
import argparse
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def darwin_dependencies(data):
    records = []
    offset = 0
    while offset < len(data):
        opcode = data[offset]
        end = data.find(b"\0", offset + 1)
        if end < 0 or opcode not in (0, 0x10, 0x11, 0x40):
            raise ValueError("unknown or truncated linker dependency report")
        value = data[offset + 1:end].decode()
        if not value or (not records and opcode != 0) or (records and opcode == 0):
            raise ValueError("invalid linker dependency header or path")
        records.append((opcode, value))
        offset = end + 1
    if not records or not any(op == 0x40 for op, _ in records):
        raise ValueError("missing linker version or output")
    return {"inputs": [value for op, value in records if op == 0x10],
            "missing": [value for op, value in records if op == 0x11]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--toolchain", default="1.97.1")
    p.add_argument("--decoder", type=Path, help="optional Zig link-report inspector")
    p.add_argument("--observer", type=Path, help="nanocompile binary to observe the actual final linker")
    args = p.parse_args()
    decoder = args.decoder.resolve() if args.decoder else None
    observer = args.observer.resolve() if args.observer else None
    if sys.platform not in ("darwin", "linux"):
        p.error("this probe requires macOS or Linux")
    root = args.state.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    out = root / "out"
    out.mkdir()
    preferred = root / "preferred-native"
    preferred.mkdir()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("R2_", "KACHE_", "NANOCOMPILE_"))
           and k not in ("RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "RUSTC_BOOTSTRAP")}
    env["RUSTUP_TOOLCHAIN"] = args.toolchain
    cc = shutil.which("cc", path=env.get("PATH"))
    if cc is None:
        raise RuntimeError("cc is required")
    linker = root / "linker"
    cfg = root / "linker.json"
    linker.write_text("#!/usr/bin/env python3\n"
                      "import json,pathlib,subprocess,sys\n"
                      "cfg=json.loads((pathlib.Path(__file__).parent/'linker.json').read_text())\n"
                      "sys.exit(subprocess.call([cfg['cc'],*sys.argv[1:],cfg['report_flag']]))\n")
    if observer:
        linker.write_text("#!/usr/bin/env python3\n"
                          "import json,pathlib,subprocess,sys\n"
                          "root=pathlib.Path(__file__).parent\n"
                          "cfg=json.loads((root/'linker.json').read_text())\n"
                          "sys.exit(subprocess.call([cfg['observer'],'internal-linker',str(root/'observer.json'),*sys.argv[1:]]))\n")
    linker.chmod(0o700)

    def run(command, name):
        proc = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=120)
        (root / (name + ".log")).write_bytes(proc.stdout + proc.stderr)
        if proc.returncode:
            raise RuntimeError("probe command failed; see private log " + name)
        return proc.stdout

    (root / "leaf.rs").write_text(
        '#[link(name="probe_native",kind="static",modifiers="-bundle")]\n'
        'extern "C" { fn probe_value() -> u32; }\n'
        'pub fn answer() -> u32 { unsafe { probe_value() } }\n')
    (root / "middle.rs").write_text('pub fn answer() -> u32 { leaf::answer() }\n')
    (root / "producer.rs").write_text(
        'extern crate proc_macro;\n'
        '#[proc_macro] pub fn answer(_: proc_macro::TokenStream) -> proc_macro::TokenStream {\n'
        'middle::answer().to_string().parse().unwrap() }\n')
    (root / "consumer.rs").write_text('fn main() { println!("{}", producer::answer!()); }\n')
    rust = ["rustc", "--edition=2021"]
    run([*rust, "leaf.rs", "--crate-name", "leaf", "--crate-type", "rlib",
         "--emit=dep-info,metadata,link", "--out-dir", str(out)], "leaf")
    run([*rust, "middle.rs", "--crate-name", "middle", "--crate-type", "rlib",
         "--emit=dep-info,metadata,link", "--out-dir", str(out),
         "--extern", "leaf=" + str(out / "libleaf.rlib"),
         "-L", "dependency=" + str(out)], "middle")
    dylib = out / ("libproducer.dylib" if sys.platform == "darwin" else "libproducer.so")
    native = out / "libprobe_native.a"
    reference = {str(path.relative_to(root)): sha(path) for path in
                 [root / "producer.rs", root / "leaf.rs", root / "middle.rs",
                  out / "libmiddle.rlib", out / "libleaf.rlib"]}
    phases = []
    metadata_texts = []
    original_stamp = None
    for value in (12, 13, 14):
        if value == 14:
            # A newly appearing higher-priority archive changes resolution
            # without changing the previously selected archive at all.
            native = preferred / "libprobe_native.a"
        (root / "native.c").write_text("unsigned probe_value(void) { return " + str(value) + "; }\n")
        run([cc, "-fPIC", "-c", "native.c", "-o", str(root / "native.o")], "native-" + str(value))
        native.unlink(missing_ok=True)
        run(["ar", "crs", str(native), str(root / "native.o")], "archive-" + str(value))
        if original_stamp is None:
            original_stamp = native.stat()
        else:
            os.utime(native, ns=(original_stamp.st_atime_ns, original_stamp.st_mtime_ns))
        report = root / ("link-" + str(value) + ".deps")
        flag = ("-Wl,-dependency_info," + str(report) if sys.platform == "darwin"
                else "-Wl,--dependency-file=" + str(report))
        cfg.write_text(json.dumps({"cc": cc, "report_flag": flag}))
        invocation = root / ("invocation-" + str(value) + ".json")
        if observer:
            cfg.write_text(json.dumps({"observer": str(observer)}))
            (root / "observer.json").write_text(json.dumps({"driver": str(Path(cc).absolute()),
                                "format": "darwin" if sys.platform == "darwin" else "make",
                                "report": str(report), "invocation": str(invocation)}))
        run([*rust, "producer.rs", "--crate-name", "producer", "--crate-type", "proc-macro",
             "--emit=dep-info,link", "--out-dir", str(out),
             "--extern", "middle=" + str(out / "libmiddle.rlib"), "--extern", "proc_macro",
             "-L", "dependency=" + str(out), "-L", "native=" + str(preferred),
             "-L", "native=" + str(out),
             "-C", "linker=" + str(linker)], "producer-" + str(value))
        diagnostic = subprocess.run(["rustc", "-Zls=root", str(dylib)], cwd=root,
                                    env=dict(env, RUSTC_BOOTSTRAP="1"), capture_output=True, timeout=120)
        if diagnostic.returncode:
            raise RuntimeError("producer metadata query failed")
        text = diagnostic.stdout.decode()
        metadata_texts.append(text)
        assert "proc_macro true\n" in text
        assert text.split("=External Dependencies=\n", 1)[1].strip() == ""
        if sys.platform == "darwin":
            deps = darwin_dependencies(report.read_bytes())
        else:
            # Diagnostic paths generated by this fixture contain no newlines.
            contents = report.read_text().replace("\\\n", "")
            deps = {"inputs": shlex.split(contents.split(": ", 1)[1].split("\n\n", 1)[0]),
                    "missing": []}
        assert str(native) in deps["inputs"], deps
        assert any("libleaf" in path for path in deps["inputs"]), deps
        assert any("libmiddle" in path for path in deps["inputs"]), deps
        invocation_verified = False
        if observer:
            record = invocation.read_bytes()
            seal, payload = record.split(b"\n", 1)
            # Check envelope structure and captured fields here. The producer
            # parent must also validate the BLAKE3 seal before using the record.
            assert len(seal) == 64 and all(chr(c) in "0123456789abcdef" for c in seal)
            captured = json.loads(payload)
            assert captured["driver"] == str(Path(cc).absolute())
            assert Path(captured["cwd"]).resolve() == root
            assert str(dylib) in captured["args"]
            assert "env" not in captured
            invocation_verified = True
        zig_report = None
        if decoder:
            zig_report = json.loads(run([str(decoder), "darwin" if sys.platform == "darwin" else "make",
                                         str(report)], "zig-report-" + str(value)))
            assert str(native) in zig_report["inputs"], zig_report
            assert any("libleaf" in path for path in zig_report["inputs"]), zig_report
            assert any("libmiddle" in path for path in zig_report["inputs"]), zig_report
            assert zig_report["outputs"] == [str(dylib)], zig_report
            if sys.platform == "darwin":
                assert zig_report["inputs"] == deps["inputs"]
                assert zig_report["missing"] == deps["missing"]
        run([*rust, "consumer.rs", "--extern", "producer=" + str(dylib),
             "-o", str(root / "consumer")], "consumer-" + str(value))
        actual = run([str(root / "consumer")], "execute-" + str(value)).decode().strip()
        assert actual == str(value), actual
        assert all(sha(root / name) == digest for name, digest in reference.items())
        phases.append({"native_value": value, "consumer_output": actual,
                       "native_sha256": sha(native), "native_bytes": native.stat().st_size,
                       "native_mtime_ns": native.stat().st_mtime_ns,
                       "selected_native_path": str(native),
                       "fallback_native_sha256": sha(out / "libprobe_native.a"),
                       "preferred_candidate_reported_missing": str(preferred / "libprobe_native.a") in deps["missing"],
                       "producer_sha256": sha(dylib),
                       "producer_dep_info_sha256": sha(out / "producer.d"),
                       "zig_report_verified": zig_report is not None,
                       "zig_observer_invocation_verified": invocation_verified,
                       "linker_inputs": deps["inputs"], "linker_missing": deps["missing"],
                       "source_and_explicit_externs_unchanged": True,
                       "producer_external_metadata_dependencies": []})
    assert phases[0]["producer_dep_info_sha256"] == phases[1]["producer_dep_info_sha256"]
    assert phases[0]["producer_sha256"] != phases[1]["producer_sha256"]
    assert phases[0]["native_sha256"] != phases[1]["native_sha256"]
    assert phases[0]["native_mtime_ns"] == phases[1]["native_mtime_ns"]
    assert phases[1]["fallback_native_sha256"] == phases[2]["fallback_native_sha256"]
    assert phases[1]["producer_dep_info_sha256"] == phases[2]["producer_dep_info_sha256"]
    assert phases[1]["producer_sha256"] != phases[2]["producer_sha256"]
    result = {"platform": platform.platform(),
              "rustc": run(["rustc", "-vV"], "version").decode(),
              "method": "real compiler and final native linker; three macro producer builds; native archive changed with preserved mtime, then a higher-priority archive appears while fallback archive remains unchanged; unchanged source files and explicit Rust externs; unchanged producer dep-info; load macro in rustc and run expanded consumer",
              "fixture_hashes": reference, "phases": phases,
              "producer_metadata": metadata_texts,
              "zig_decoder_sha256": sha(decoder) if decoder else None,
              "zig_observer_sha256": sha(observer) if observer else None,
              "conclusion": "Producer metadata and source dep-info alone do not describe final linker inputs. Linker reports include transitive Rust archives and selected native archives. Higher-priority candidates can be resolved by rustc before the final linker; explicit native search membership still needs guards."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"native_values": [p["consumer_output"] for p in phases],
                      "metadata_dependencies_empty": True,
                      "source_externs_and_dep_info_unchanged": True,
                      "native_mtime_preserved": True,
                      "new_candidate_changes_resolution": True,
                      "linker_tracks_native_archive": True}))


if __name__ == "__main__":
    main()
