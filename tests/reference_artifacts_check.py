"""Reference bytes survive target mutation and reject damaged evidence."""
from pathlib import Path
import tempfile
from reference_artifacts import digest, retain, verify

with tempfile.TemporaryDirectory(prefix='nano reference evidence ') as temp:
    root = Path(temp)
    target = root / 'target'
    target.mkdir()
    artifact = target / 'product'
    artifact.write_bytes(b'original bytes')
    references = root / 'references'
    retain(target, references, {'product': digest(artifact)})
    artifact.write_bytes(b'changed source')
    assert verify(references) == 1
    artifact.unlink()
    assert verify(references) == 1
    (references / 'product').write_bytes(b'damaged evidence')
    try:
        verify(references)
    except ValueError:
        pass
    else:
        raise AssertionError('Damaged reference accepted')
    try:
        retain(target, root / 'bad', {'../outside': '0' * 64})
    except ValueError:
        pass
    else:
        raise AssertionError('Escaping reference path accepted')
print('PASS: independent reference bytes survive target changes and reject corruption/path escape')
