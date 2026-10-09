"""Experimental R2 snapshot transport; compilation and validation remain in Zig.

Install boto3 separately. Credentials are read from a mode-0600 JSON file
outside the repository, or R2_* environment variables. Never log credentials.
Only entries and blobs are transported, never locks or toolchain metadata.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tarfile
import tempfile
import time


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def valid_member(name):
    return bool(re.fullmatch(r"entries/[0-9a-f]{64}|blobs/([0-9a-f]{2})/\1[0-9a-f]{62}", name))


def client(config=None):
    import boto3
    from botocore.config import Config
    if config:
        path = Path(config)
        if path.stat().st_mode & 0o077:
            raise ValueError("credential file must have mode 0600")
        data = json.loads(path.read_text())
    else:
        data = {k: os.environ["R2_" + k.upper()] for k in
                ("endpoint", "bucket", "access_key_id", "secret_access_key")}
    if not data["endpoint"].startswith("https://"):
        raise ValueError("R2 endpoint must use HTTPS")
    return boto3.client("s3", endpoint_url=data["endpoint"], region_name="auto",
                        aws_access_key_id=data["access_key_id"],
                        aws_secret_access_key=data["secret_access_key"],
                        config=Config(retries={"max_attempts": 3},
                                      request_checksum_calculation="when_required",
                                      response_checksum_validation="when_required")), data["bucket"]


@contextlib.contextmanager
def maintenance(root):
    (root / "locks").mkdir(parents=True, exist_ok=True)
    with open(root / "locks/maintenance", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def transfer(action, root, snapshot, config=None, max_bytes=20 * 1024**3):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", snapshot):
        raise ValueError("snapshot must be a simple name")
    root = Path(root).resolve()
    s3, bucket = client(config)
    prefix = "nanocompile/snapshots-v1/"
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="nanocompile-r2-") as temp:
        archive = Path(temp) / "cache.tar.gz"
        if action == "push":
            count = 0
            size = 0
            with maintenance(root), tarfile.open(archive, "w:gz", compresslevel=1) as tar:
                for sub in ("entries", "blobs"):
                    for path in sorted((root / sub).rglob("*")):
                        relative = path.relative_to(root).as_posix()
                        if path.is_symlink():
                            raise ValueError("cache symlinks are not supported")
                        if path.is_file():
                            if not valid_member(relative):
                                raise ValueError("unexpected cache file")
                            size += path.stat().st_size
                            if size > max_bytes:
                                raise ValueError("snapshot exceeds unpacked size limit")
                            info = tar.gettarinfo(str(path), relative)
                            info.uid = info.gid = 0
                            info.uname = info.gname = ""
                            info.mode = 0o600
                            with path.open("rb") as f:
                                tar.addfile(info, f)
                            count += 1
            sha = digest(archive)
            key = prefix + "objects/" + sha + ".tar.gz"
            s3.upload_file(str(archive), bucket, key)
            index = {"schema": 1, "sha256": sha, "bytes": archive.stat().st_size,
                     "unpacked_bytes": size, "files": count}
            # Publish the pointer only after the immutable archive is uploaded.
            s3.put_object(Bucket=bucket, Key=prefix + snapshot + ".json",
                          Body=json.dumps(index).encode(), ContentType="application/json")
        else:
            response = s3.get_object(Bucket=bucket, Key=prefix + snapshot + ".json")
            body = response["Body"]
            try:
                raw = body.read(16385)
            finally:
                body.close()
            if len(raw) > 16384:
                raise ValueError("snapshot index too large")
            index = json.loads(raw)
            if (index.get("schema") != 1 or not re.fullmatch(r"[0-9a-f]{64}", index.get("sha256", ""))
                    or not isinstance(index.get("bytes"), int) or not 0 <= index["bytes"] <= max_bytes
                    or not isinstance(index.get("unpacked_bytes"), int)
                    or not 0 <= index["unpacked_bytes"] <= max_bytes):
                raise ValueError("invalid snapshot index")
            # Bound the download even if the object or index is malformed.
            response = s3.get_object(Bucket=bucket, Key=prefix + "objects/" + index["sha256"] + ".tar.gz")
            body = response["Body"]
            try:
                with archive.open("wb") as f:
                    total = 0
                    while block := body.read(1024 * 1024):
                        total += len(block)
                        if total > index["bytes"]:
                            raise ValueError("snapshot exceeds declared size")
                        f.write(block)
            finally:
                body.close()
            if archive.stat().st_size != index["bytes"] or digest(archive) != index["sha256"]:
                raise ValueError("snapshot checksum mismatch")
            staged = Path(temp) / "staged"
            names = set()
            size = 0
            with tarfile.open(archive, "r:gz") as tar:
                for member in tar:
                    if not member.isfile() or not valid_member(member.name) or member.name in names:
                        raise ValueError("unsafe archive member")
                    names.add(member.name)
                    size += member.size
                    if member.size < 0 or size > max_bytes:
                        raise ValueError("archive exceeds unpacked size limit")
                    path = staged / member.name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    # Never use tar.extract: reject links and traversal explicitly.
                    with tar.extractfile(member) as source, path.open("xb") as dest:
                        while block := source.read(1024 * 1024):
                            dest.write(block)
                    path.chmod(0o600)
            if len(names) != index["files"] or size != index["unpacked_bytes"]:
                raise ValueError("snapshot inventory mismatch")
            with maintenance(root):
                # Merge: no unrelated entries are deleted. Each file replaces atomically.
                for name in sorted(names):
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if path.parent.is_symlink() or path.parent.parent.is_symlink():
                        raise ValueError("cache directories must not be symlinks")
                    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as dest:
                        tmp = Path(dest.name)
                        try:
                            with (staged / name).open("rb") as source:
                                while block := source.read(1024 * 1024):
                                    dest.write(block)
                            dest.close()
                            os.replace(tmp, path)
                        finally:
                            tmp.unlink(missing_ok=True)
    return {"action": action, "snapshot": snapshot, "seconds": time.monotonic() - start,
            "archive_bytes": index["bytes"], "unpacked_bytes": index["unpacked_bytes"],
            "files": index["files"], "sha256": index["sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("push", "pull"))
    parser.add_argument("--cache", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--config", help="private mode-0600 credential JSON file")
    args = parser.parse_args()
    try:
        print(json.dumps(transfer(args.action, args.cache, args.snapshot, args.config), indent=2))
    except Exception as exc:
        # SDK exceptions can contain endpoint/request context. Do not print them.
        raise SystemExit("R2 transfer failed: " + type(exc).__name__)


if __name__ == "__main__":
    main()
