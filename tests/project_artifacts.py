"""Distinguish installed execution shims from compiler-produced script binaries."""
import hashlib


def compiled_scripts(target):
    hashes = {}
    for launcher in sorted((target / 'release/build').glob('*/build-script-build')):
        if not launcher.is_file():
            continue
        originals = sorted(launcher.parent.glob('*.nano-real'))
        assert len(originals) <= 1, f'Ambiguous original script executables: {originals}'
        original = originals[0] if originals else launcher
        hashes[str(launcher.relative_to(target))] = hashlib.sha256(original.read_bytes()).hexdigest()
    return hashes
