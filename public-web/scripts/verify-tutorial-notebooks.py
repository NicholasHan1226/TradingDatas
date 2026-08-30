"""Validate generated notebook structure and execute all Python cells in order.

Standard-library runner, not a Jupyter UI/kernel integration test. No artifacts
are rewritten and notebooks need no network or third-party computation packages.
"""
import json
from pathlib import Path
import sys


def verify_notebook(path):
    notebook = json.loads(path.read_text())
    assert notebook["nbformat"] == 4 and notebook["nbformat_minor"] == 5
    assert notebook["metadata"]["kernelspec"]["name"] == "python3"
    namespace = {"__name__": "__main__"}
    identifiers = set()
    code_count = 0
    for cell in notebook["cells"]:
        assert cell["id"] not in identifiers
        identifiers.add(cell["id"])
        assert isinstance(cell["metadata"], dict)
        source = cell["source"]
        assert isinstance(source, list) and all(isinstance(line, str) for line in source)
        if cell["cell_type"] == "code":
            assert cell["execution_count"] is None and cell["outputs"] == []
            exec(compile("".join(source), f"{path.name}:{cell['id']}", "exec"), namespace)
            code_count += 1
        else:
            assert cell["cell_type"] == "markdown"
    assert code_count == 4
    assert namespace["result"] == namespace["expected"]
    return code_count


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent / "dist/client/downloads/research"
    paths = [Path(value) for value in sys.argv[1:]] or sorted(root.glob("*/tutorial-*.ipynb"))
    assert len(paths) > 0, "Build download files first"
    for notebook_path in paths:
        count = verify_notebook(notebook_path)
        print(f"PASS {notebook_path.parent.name}/{notebook_path.name}: {count} code cells")
    print(f"Validated and executed {len(paths)} notebooks")
