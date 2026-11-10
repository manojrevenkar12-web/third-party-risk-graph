"""Nothing that serves reads the truth: the graph package never imports the world, the simulation or the evaluation."""

import ast
from pathlib import Path

SERVING = Path(__file__).resolve().parents[1] / "src/trg/graph"


def test_graph_package_imports_nothing_from_the_world():
    for f in SERVING.glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.ImportFrom):
                mod = ("." * node.level) + (node.module or "")
                assert not any(x in mod for x in ("world", "sim", "evals")), f"{f.name} imports {mod}"
        assert "data/truth" not in f.read_text(), f.name
