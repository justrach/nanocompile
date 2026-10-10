#!/usr/bin/env python3
"""Verify early compiler notifications and byte-exact dual-stream capture."""
import os
import selectors
import subprocess
import sys
import tempfile
from pathlib import Path

probe = str(Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory(prefix='nano-stream-') as tmp:
    root = Path(tmp)
    gate = root / 'gate'
    script = root / 'child.py'
    script.write_text('''import os, sys, time
from pathlib import Path
assert os.read(0, 1) == b''
assert os.environ['STREAM_ENV_PROBE'] == 'preserved'
os.write(2, b'{"artifact":"metadata"}\\n')
while not Path(sys.argv[1]).exists(): time.sleep(.005)
payload = bytes(range(256)) * 8192
os.write(1, payload)
os.write(2, payload)
sys.exit(int(sys.argv[2]))
''')
    for code in (0, 7):
        gate.unlink(missing_ok=True)
        env = dict(os.environ, STREAM_ENV_PROBE='preserved', PROBE_CAPTURE_OUT=str(root / 'out'), PROBE_CAPTURE_ERR=str(root / 'err'))
        child = subprocess.Popen([probe, sys.executable, str(script), str(gate), str(code)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with selectors.DefaultSelector() as sel:
                sel.register(child.stderr, selectors.EVENT_READ)
                assert sel.select(10), 'metadata was buffered while compiler waited for Cargo'
            first = child.stderr.readline()
            assert first == b'{"artifact":"metadata"}\n', first
            assert child.poll() is None, 'compiler exited before notification handshake'
            gate.touch()
            out, err = child.communicate(timeout=30)
            payload = bytes(range(256)) * 8192
            assert child.returncode == code, child.returncode
            assert out == payload
            assert first + err == first + payload
            assert (root / 'out').read_bytes() == out
            assert (root / 'err').read_bytes() == first + err
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()
    child = subprocess.run([probe, sys.executable, '-c', 'import os,signal; os.kill(os.getpid(),signal.SIGTERM)'], capture_output=True, timeout=10)
    assert child.returncode == 143, child.returncode
print('PASS early metadata, 2 MiB binary dual streams, exact capture, failure and signal status')
