"""Generate the world and pin it: data/sources, data/truth and config/heldout.lock (sha256 of every file)."""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trg.world.generate import build_all  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    files = build_all()
    lock = {"heldout": "the supplier batch marked heldout in data/sources/suppliers.json, every source dated after "
            "dev_cutoff, and every question with split heldout",
            "sha256": {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(files)}}
    (ROOT / "config/heldout.lock").write_text(json.dumps(lock, indent=1) + "\n")
    print(f"{len(files)} files pinned")


if __name__ == "__main__":
    main()
