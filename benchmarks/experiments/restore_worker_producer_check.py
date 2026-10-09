#!/usr/bin/env python3
"""Run existing real producer regressions through a live private worker pool."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from restore_worker_pool import Pool


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("worker", type=Path)
    parser.add_argument("front", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--worker-root", type=Path, default=Path("/tmp/nanocompile-restore-worker-service-producers"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    worker, front, baseline = [p.resolve() for p in [args.worker, args.front, args.baseline]]
    tests = Path(__file__).resolve().parents[2] / "tests"
    rows = []
    with Pool(worker, baseline, args.worker_root) as pool:
        for module, extra in [("producer_cache.py", ["--cargo-flags"]), ("executable_cache.py", [])]:
            output = args.output.with_name(args.output.stem + "-" + module.removesuffix(".py") + ".json")
            before = pool.counts()
            subprocess.run([sys.executable, str(tests / module), str(front), *extra, "--output", str(output)], check=True, timeout=300)
            after = pool.counts()
            counts = {k: after[k] - before[k] for k in after}
            assert counts["served"] >= 2, (module, counts)
            rows.append({"test": module, "worker_requests": counts, "report": output.name})
    report = {"scope": "private producer cache-hit worker; compilation and execution remain in accepted wrapper/caller",
              "rows": rows, "binary_sha256": {name: hashlib.sha256(p.read_bytes()).hexdigest()
                                              for name, p in [("worker", worker), ("front", front), ("baseline", baseline)]}}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(rows))


if __name__ == "__main__":
    main()
