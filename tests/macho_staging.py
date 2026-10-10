"""Strict diagnostic comparison for staged Apple thin-LTO executables."""
import struct


def validate_staging_difference(direct, staged):
    """Only LC_UUID and its signed page digest may change; never patch bytes."""
    assert len(direct) == len(staged)
    def ranges(data):
        assert struct.unpack_from('<I', data)[0] == 0xfeedfacf
        count = struct.unpack_from('<I', data, 16)[0]
        offset, uuid, signature = 32, None, None
        for _ in range(count):
            cmd, size = struct.unpack_from('<II', data, offset)
            if cmd == 0x1b:
                uuid = (offset + 8, offset + 24)
            if cmd == 0x1d:
                signature = struct.unpack_from('<II', data, offset + 8)
            offset += size
        assert uuid and signature
        start, length = signature
        magic, size, count = struct.unpack_from('>III', data, start)
        assert magic == 0xfade0cc0 and size <= length
        allowed = [uuid]
        for i in range(count):
            kind, relative = struct.unpack_from('>II', data, start + 12 + i * 8)
            if kind != 0:
                continue
            cd = start + relative
            assert struct.unpack_from('>I', data, cd)[0] == 0xfade0c02
            hash_offset = struct.unpack_from('>I', data, cd + 16)[0]
            slots = struct.unpack_from('>I', data, cd + 28)[0]
            hash_size, page_size = data[cd + 36], 1 << data[cd + 39]
            slot = uuid[0] // page_size
            assert slot < slots and (uuid[1] - 1) // page_size == slot
            digest = cd + hash_offset + slot * hash_size
            allowed.append((digest, digest + hash_size))
        assert len(allowed) == 2
        return allowed
    allowed = ranges(direct)
    assert allowed == ranges(staged)
    changed = [i for i, (x, y) in enumerate(zip(direct, staged)) if x != y]
    assert all(any(lo <= i < hi for lo, hi in allowed) for i in changed), changed
    return {'changed_bytes': len(changed), 'allowed_ranges': allowed,
            'scope': 'LC_UUID and exactly its CodeDirectory page hash; no byte rewriting'}

