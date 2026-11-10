import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_world_matches_its_pin():
    lock = json.loads((ROOT / "config/heldout.lock").read_text())
    for f, h in lock["sha256"].items():
        assert hashlib.sha256((ROOT / f).read_bytes()).hexdigest() == h, f
