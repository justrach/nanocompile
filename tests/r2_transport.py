"""Transport round-trip and malformed snapshot checks without credentials/network."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import r2_cache


class Store:
    def __init__(self):
        self.objects = {}

    def upload_file(self, path, bucket, key):
        self.objects[key] = Path(path).read_bytes()

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}


class TransportTests(unittest.TestCase):
    def test_roundtrip_and_corruption_preserves_existing_cache(self):
        store = Store()
        with tempfile.TemporaryDirectory() as tmp, patch.object(r2_cache, "client", return_value=(store, "test")):
            root, restored = Path(tmp) / "source", Path(tmp) / "restored"
            entry = "entries/" + "a" * 64
            blob = "blobs/bb/" + "b" * 64
            for name, content in ((entry, b"entry"), (blob, b"blob")):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            (root / "toolchains").mkdir()
            (root / "toolchains/private").write_text("do not transport")
            index = r2_cache.transfer("push", root, "test")
            r2_cache.transfer("pull", restored, "test")
            self.assertEqual((restored / entry).read_bytes(), b"entry")
            self.assertEqual((restored / blob).read_bytes(), b"blob")
            self.assertFalse((restored / "toolchains").exists())
            key = "nanocompile/snapshots-v1/objects/" + index["sha256"] + ".tar.gz"
            store.objects[key] = b"corrupted"
            with self.assertRaises(ValueError):
                r2_cache.transfer("pull", restored, "test")
            self.assertEqual((restored / entry).read_bytes(), b"entry")

    def test_traversal_links_duplicates_and_limits_rejected(self):
        for name, kind in (("../escape", tarfile.REGTYPE),
                           ("entries/" + "a" * 64, tarfile.SYMTYPE)):
            with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as tmp:
                store = Store()
                data = io.BytesIO()
                with tarfile.open(fileobj=data, mode="w:gz") as tar:
                    info = tarfile.TarInfo(name)
                    info.type = kind
                    info.size = 0
                    tar.addfile(info)
                raw = data.getvalue()
                sha = hashlib.sha256(raw).hexdigest()
                store.objects["nanocompile/snapshots-v1/objects/" + sha + ".tar.gz"] = raw
                store.objects["nanocompile/snapshots-v1/test.json"] = json.dumps({
                    "schema": 1, "sha256": sha, "bytes": len(raw), "unpacked_bytes": 0, "files": 1}).encode()
                with patch.object(r2_cache, "client", return_value=(store, "test")), self.assertRaises(ValueError):
                    r2_cache.transfer("pull", Path(tmp) / "cache", "test")
                self.assertFalse((Path(tmp) / "escape").exists())
        self.assertFalse(r2_cache.valid_member("entries/" + "g" * 64))
        self.assertFalse(r2_cache.valid_member("blobs/aa/" + "b" * 64))


if __name__ == "__main__":
    unittest.main()
