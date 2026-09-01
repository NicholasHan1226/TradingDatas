"""Optional actual-kernel acceptance; never writes outputs into shipped notebooks.

Run with an isolated Python containing nbformat, nbclient and ipykernel.
The kernel uses that exact interpreter, with connection files in a temp directory.
No global kernel registration, provider access or persistent environment changes.
"""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

try:
    import nbformat
    from nbclient import NotebookClient
    from jupyter_client import KernelManager
except ImportError:
    raise SystemExit("Optional Jupyter acceptance needs nbformat, nbclient and ipykernel in the selected isolated Python.")


def verify(path):
    notebook = nbformat.read(path, as_version=4)
    nbformat.validate(notebook)
    assert all(cell.get("execution_count") is None and not cell.get("outputs") for cell in notebook.cells)
    with TemporaryDirectory(prefix="td-notebook-kernel-") as directory:
        manager = KernelManager(kernel_name="python3", transport="ipc", ip=str(Path(directory) / "ipc"), connection_file=str(Path(directory) / "connection.json"))
        manager.kernel_spec.argv = [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"]
        try:
            executed = NotebookClient(notebook, km=manager, timeout=30, allow_errors=False).execute(cwd=directory)
        finally:
            if manager.has_kernel:
                manager.shutdown_kernel(now=True)
            manager.cleanup_resources()
    cells = [cell for cell in executed.cells if cell.cell_type == "code"]
    assert [cell.execution_count for cell in cells] == [1, 2, 3, 4]
    assert not any(output.output_type == "error" for cell in cells for output in cell.outputs)
    assert any("Passed:" in output.get("text", "") or "通过：" in output.get("text", "") for output in cells[-1].outputs)
    print(f"PASS {path.parent.name}/{path.name}: actual kernel, four code cells")


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent / "dist/client/downloads/research"
    paths = [Path(value) for value in sys.argv[1:]] or sorted(root.glob("*/tutorial-*.ipynb"))
    assert paths, "Build download files first"
    for path in paths:
        verify(path)
    print(f"Executed {len(paths)} notebooks in isolated Jupyter kernels; shipped files unchanged.")
