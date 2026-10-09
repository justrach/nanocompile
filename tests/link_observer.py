"""Verify the private linker observer's environment, streams and exit status."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("binary", type=Path)
    args = p.parse_args()
    binary = args.binary.resolve()
    with tempfile.TemporaryDirectory(prefix="nano observer, ") as directory:
        root = Path(directory)
        config = root / "config.json"
        record = root / "record.json"
        driver = root / "driver"
        driver.write_text("#!/usr/bin/env python3\n"
                          "import os,sys,pathlib\n"
                          "assert os.environ['NANO_OBSERVER_TEST_MARKER']=='unchanged'\n"
                          "if os.environ.get('NANO_OBSERVER_RESPONSE_TO_CHANGE'): pathlib.Path(os.environ['NANO_OBSERVER_RESPONSE_TO_CHANGE']).write_text('changed')\n"
                          "if os.environ.get('NANO_OBSERVER_RESPONSE_TO_RESTORE'):\n"
                          " p=pathlib.Path(os.environ['NANO_OBSERVER_RESPONSE_TO_RESTORE']); original=p.read_bytes(); st=p.stat(); p.write_bytes(b'modified'); p.write_bytes(original); os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns))\n"
                          "sys.stdout.write('native stdout\\n')\n"
                          "sys.stderr.write('native stderr\\n')\n"
                          "sys.exit(7)\n")
        driver.chmod(0o700)
        config.write_text(json.dumps({"driver": str(driver), "format": "darwin",
                                    "report": str(root / "report"), "invocation": str(record)}))
        env = dict(os.environ, NANO_OBSERVER_TEST_MARKER="unchanged",
                   NANOCOMPILE_DIR=str(root / "cache"))
        command = [str(binary), "internal-linker", str(config), "object with, spaces.o"]
        result = subprocess.run(command, env=env, capture_output=True, timeout=20)
        assert result.returncode == 7, result
        assert result.stdout == b"native stdout\n", result
        assert result.stderr == b"native stderr\n", result
        payload = json.loads(record.read_bytes().split(b"\n", 1)[1])
        assert payload["args"] == ["object with, spaces.o"], payload
        assert "env" not in payload, payload
        assert payload["capture_valid"] and payload["expanded_args"] == payload["args"]
        inner = root / "inner response.rsp"
        outer = root / "outer response.rsp"
        inner.write_text("'nested object, with spaces.o' -L \"library with spaces\"")
        outer.write_text("@'inner response.rsp' -o out.so")
        response_command = [str(binary), "internal-linker", str(config), "@outer response.rsp"]
        result = subprocess.run(response_command, cwd=root, env=env, capture_output=True, timeout=20)
        assert result.returncode == 7, result
        payload = json.loads(record.read_bytes().split(b"\n", 1)[1])
        assert payload["capture_valid"], payload
        assert payload["expanded_args"] == ["nested object, with spaces.o", "-L", "library with spaces", "-o", "out.so"]
        assert len(payload["responses"]) == 2 and all(r["unchanged"] for r in payload["responses"])
        changed_env = dict(env, NANO_OBSERVER_RESPONSE_TO_CHANGE=str(inner))
        result = subprocess.run(response_command, cwd=root, env=changed_env, capture_output=True, timeout=20)
        assert result.returncode == 7, result
        payload = json.loads(record.read_bytes().split(b"\n", 1)[1])
        assert not payload["capture_valid"] and any(not r["unchanged"] for r in payload["responses"])
        restored_env = dict(env, NANO_OBSERVER_RESPONSE_TO_RESTORE=str(inner))
        original = inner.read_bytes()
        original_mtime = inner.stat().st_mtime_ns
        result = subprocess.run(response_command, cwd=root, env=restored_env, capture_output=True, timeout=20)
        assert result.returncode == 7, result
        assert inner.read_bytes() == original and inner.stat().st_mtime_ns == original_mtime
        payload = json.loads(record.read_bytes().split(b"\n", 1)[1])
        assert not payload["capture_valid"] and any(not r["unchanged"] for r in payload["responses"])
        inner.write_text("@'outer response.rsp'")
        result = subprocess.run(response_command, cwd=root, env=env, capture_output=True, timeout=20)
        assert result.returncode == 7, result
        payload = json.loads(record.read_bytes().split(b"\n", 1)[1])
        assert not payload["capture_valid"] and payload["capture_error"] == "RecursiveResponse"
        outer.write_text("'unterminated")
        result = subprocess.run(response_command, cwd=root, env=env, capture_output=True, timeout=20)
        assert result.returncode == 7, result
        payload = json.loads(record.read_bytes().split(b"\n", 1)[1])
        assert not payload["capture_valid"] and payload["capture_error"] == "TruncatedResponse"
        # Verify expansion against an actual compiler driver, not just the spy.
        cc = shutil.which("cc")
        assert cc
        (root / "source.c").write_text("int answer(void) { return 42; }\n")
        subprocess.run([cc, "-fPIC", "-c", "source.c", "-o", "object, with spaces.o"],
                       cwd=root, env=env, capture_output=True, check=True, timeout=20)
        library = root / ("library, with spaces.dylib" if sys.platform == "darwin" else "library, with spaces.so")
        inner.write_text(("-dynamiclib" if sys.platform == "darwin" else "-shared") + " 'object, with spaces.o'")
        outer.write_text("@'inner response.rsp' -o '" + library.name + "'")
        config.write_text(json.dumps({"driver": str(Path(cc).absolute()), "format": "darwin" if sys.platform == "darwin" else "make",
                                    "report": str(root / "report"), "invocation": str(record)}))
        result = subprocess.run(response_command, cwd=root, env=env, capture_output=True, timeout=30)
        assert result.returncode == 0, result
        assert ctypes.CDLL(str(library)).answer() == 42
        payload = json.loads(record.read_bytes().split(b"\n", 1)[1])
        assert payload["capture_valid"] and all(r["unchanged"] for r in payload["responses"])
        assert library.name in payload["expanded_args"]
        assert (root / "report").exists()
        # Ownership is captured before control returns to rustc, which may
        # immediately delete its scratch files. A symlink to a foreign object
        # remains persistent even when the link spelling is inside the job.
        owned_out = root / 'private output'
        owned_out.mkdir(mode=0o700)
        owned_object = owned_out / 'generated, object'
        subprocess.run([cc, '-fPIC', '-c', 'source.c', '-o', str(owned_object)],
                       cwd=root, env=env, capture_output=True, check=True, timeout=20)
        (root / 'foreign.c').write_text('int persistent(void) { return 7; }\n')
        foreign = root / 'persistent.o'
        subprocess.run([cc, '-fPIC', '-c', 'foreign.c', '-o', str(foreign)],
                       cwd=root, env=env, capture_output=True, check=True, timeout=20)
        alias = owned_out / 'foreign alias.o'
        alias.symlink_to(foreign)
        owned_library = owned_out / library.name
        ownership = {'out': str(owned_out), 'canonical_out': str(owned_out.resolve()),
                     'output': str(owned_library)}
        config.write_text(json.dumps({'driver': str(Path(cc).absolute()),
            'format': 'darwin' if sys.platform == 'darwin' else 'make',
            'report': str(root / 'report'), 'invocation': str(record),
            'capture_id': 'owned-job', 'ownership': ownership}))
        owned_command = [str(binary), 'internal-linker', str(config),
                         '-dynamiclib' if sys.platform == 'darwin' else '-shared',
                         str(owned_object), str(alias), '-o', str(owned_library)]
        result = subprocess.run(owned_command, cwd=root, env=env, capture_output=True, timeout=30)
        assert result.returncode == 0, result
        assert ctypes.CDLL(str(owned_library)).answer() == 42
        payload = json.loads(record.read_bytes().split(b'\n', 1)[1])
        assert payload['capture_valid'], payload
        inputs = payload['link']['inputs']
        assert any(p['owned'] and p['path'] == str(owned_object.resolve()) for p in inputs), payload
        assert any(not p['owned'] and p['path'] == str(foreign.resolve()) for p in inputs), payload
        assert payload['link']['ownership'] == ownership
        owned_object.unlink()
        assert any(p['owned'] for p in inputs)  # durable capture outlives scratch
        # A successful driver that writes no new report cannot adopt the prior
        # link's report. Discovery failure must still retain native exit zero.
        driver.write_text('#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n')
        cfg = json.loads(config.read_text())
        cfg['driver'] = str(driver)
        config.write_text(json.dumps(cfg))
        result = subprocess.run(owned_command, cwd=root, env=env, capture_output=True, timeout=20)
        assert result.returncode == 0, result
        payload = json.loads(record.read_bytes().split(b'\n', 1)[1])
        assert not payload['capture_valid'] and payload['link'] is None, payload
        assert not (root / 'report').exists()
        config.write_text(json.dumps({"driver": str(driver), "format": "darwin",
                                    "report": str(root / "report"), "invocation": str(record)}))
        driver.write_text("#!/usr/bin/env python3\n"
                          "import os,signal\n"
                          "os.kill(os.getpid(),signal.SIGTERM)\n")
        result = subprocess.run(command, env=env, capture_output=True, timeout=20)
        assert result.returncode == 143, result
        record.unlink()
        config.write_text(json.dumps({"driver": str(driver), "format": "darwin",
                                    "report": str(config), "invocation": str(record)}))
        result = subprocess.run(command, env=env, capture_output=True, timeout=20)
        assert result.returncode == 1 and not record.exists(), result
    print("PASS: observer environment, streams, exits, response capture/invalidation and real nested-response linking")


if __name__ == "__main__":
    main()
