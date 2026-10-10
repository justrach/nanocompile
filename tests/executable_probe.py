"""Record final executable failures without losing the completed build sample."""
import hashlib
import subprocess


def probe_help(path, env):
    try:
        result = subprocess.run([str(path), '--help'], env=env,
                                capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        return dict(cli_help_valid=False, cli_help_error_type=type(error).__name__,
                    cli_help_error=str(error), cli_help_errno=getattr(error, 'errno', None))
    return dict(cli_help_valid=result.returncode == 0 and b'Usage:' in result.stdout,
                cli_help_exit_code=result.returncode,
                cli_help_sha256=hashlib.sha256(result.stdout).hexdigest(),
                cli_help_stderr_sha256=hashlib.sha256(result.stderr).hexdigest())
