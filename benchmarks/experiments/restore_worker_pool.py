"""Private process pool for the cache-hit worker experiment."""
from pathlib import Path
import shutil
import subprocess
import time


class Pool:
    def __init__(self, worker, baseline, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=False)
        shutil.copy2(baseline, self.root / "baseline")
        self.processes = []
        self.logs = []
        try:
            for i in range(4):
                lock = self.root / f"{i}.lock"
                lock.write_bytes(b"")
                lock.chmod(0o600)
                log = (self.root / f"{i}.log").open("wb")
                self.logs.append(log)
                self.processes.append(subprocess.Popen([str(worker), str(self.root / f"{i}.sock")],
                                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log))
            deadline = time.monotonic() + 10
            while not all((self.root / f"{i}.sock").exists() for i in range(4)):
                assert time.monotonic() < deadline and all(p.poll() is None for p in self.processes), "worker startup failed"
                time.sleep(0.02)
        except BaseException:
            self.close()
            raise

    def close(self):
        for p in self.processes:
            if p.poll() is None:
                p.terminate()
        for p in self.processes:
            p.wait(timeout=10)
        for log in self.logs:
            log.close()

    def counts(self):
        data = "".join((self.root / f"{i}.log").read_text() for i in range(4))
        return {"served": data.count("restore worker result: 0\n"),
                "fallback": data.count("restore worker result: 200\n")}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
