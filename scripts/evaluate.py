"""Every design on the development split -> reports/dev.json (about ten minutes)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trg.evals.pipeline import evaluate

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    out = {"split": "dev", "designs": evaluate("dev", sys.argv[1:] or None)}
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/dev.json").write_text(json.dumps(out, indent=1))
