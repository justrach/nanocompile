"""Real executable probe success, exit failure and permission failure."""
import os
from pathlib import Path
import tempfile
from executable_probe import probe_help

with tempfile.TemporaryDirectory() as temporary:
    app = Path(temporary) / 'app'
    app.write_text('#!/bin/sh\necho "Usage: app"\n')
    app.chmod(0o755)
    assert probe_help(app, os.environ)['cli_help_valid']
    app.write_text('#!/bin/sh\necho "Usage: app"\nexit 3\n')
    failed = probe_help(app, os.environ)
    assert not failed['cli_help_valid'] and failed['cli_help_exit_code'] == 3
    app.chmod(0o644)
    failed = probe_help(app, os.environ)
    assert not failed['cli_help_valid'] and failed['cli_help_error_type'] == 'PermissionError'
    assert failed['cli_help_errno'] == 13
    app.unlink()
    assert probe_help(app, os.environ)['cli_help_error_type'] == 'FileNotFoundError'
print('PASS: executable probe failures are reportable')
