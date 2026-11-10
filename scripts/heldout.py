"""Once: every design on the held-out split -> reports/heldout.json.

Refuses to run if the world differs from config/heldout.lock, if code or config are not committed, or if it has run
before. What it shows is published and fixed with tests on development data; it is not run again.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trg.evals.pipeline import evaluate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/heldout.json"


def refuse(why: str) -> None:
    print("refusing:", why)
    sys.exit(2)


if __name__ == "__main__":
    if OUT.exists():
        refuse("the held-out split has been run before")
    lock = json.loads((ROOT / "config/heldout.lock").read_text())
    for f, h in lock["sha256"].items():
        if hashlib.sha256((ROOT / f).read_bytes()).hexdigest() != h:
            refuse(f"{f} differs from its pin")
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "src", "config", "scripts"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    if dirty:
        refuse("code or config not committed:\n" + dirty)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    OUT.write_text(json.dumps({"split": "heldout", "commit": commit, "designs": evaluate("heldout")}, indent=1))
