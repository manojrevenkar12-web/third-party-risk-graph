"""CI: the graph pipeline on the development split; exits 1 if it fails the gate."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trg.evals.pipeline import evaluate

if __name__ == "__main__":
    s = evaluate("dev", ["graph-pipeline"])["graph-pipeline"]
    for f in s["gate_failures"]:
        print("FAIL:", f)
    sys.exit(1 if s["gate_failures"] else 0)
