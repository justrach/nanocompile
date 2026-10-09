"""Verify the private linker observer's environment, streams and exit status."""
import argparse
import json
import os
from pathlib import Path
import subprocess
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
                          "import os,sys\n"
                          "assert os.environ['NANO_OBSERVER_TEST_MARKER']=='unchanged'\n"
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
    print("PASS: observer environment, streams, nonzero exit, signal and configuration")


if __name__ == "__main__":
    main()

