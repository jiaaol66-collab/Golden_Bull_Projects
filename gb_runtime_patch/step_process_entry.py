import os
import re
import runpy
import sys
import traceback
from datetime import datetime


def _append_trace(event, **fields):
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        trace_dir = os.path.join(project_root, ".dbg")
        os.makedirs(trace_dir, exist_ok=True)
        trace_path = os.path.join(trace_dir, "async-log-capture.trace")
        parts = [f"ts={datetime.now().isoformat(sep=' ', timespec='seconds')}", f"event={event}"]
        for key, value in fields.items():
            parts.append(f"{key}={value}")
        with open(trace_path, "a", encoding="utf-8") as f:
            f.write(" | ".join(parts) + "\n")
    except Exception:
        pass


def _is_notebook_path(path):
    return os.path.splitext(str(path or ""))[1].lower() == ".ipynb"


def _strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", str(text or ""))


def _normalize_output_text(value):
    if isinstance(value, list):
        return "".join(str(part) for part in value)
    return str(value or "")


def _emit_notebook_output(output):
    output_type = str((output or {}).get("output_type") or "").strip()
    if output_type == "stream":
        text = _normalize_output_text((output or {}).get("text", ""))
        if text:
            sys.stdout.write(text)
            if not text.endswith("\n"):
                sys.stdout.write("\n")
        return

    if output_type in {"execute_result", "display_data"}:
        data = (output or {}).get("data") or {}
        text = (
            data.get("text/plain")
            or data.get("text/markdown")
            or data.get("text/html")
            or ""
        )
        text = _normalize_output_text(text)
        if text:
            sys.stdout.write(text)
            if not text.endswith("\n"):
                sys.stdout.write("\n")
        return

    if output_type == "error":
        traceback_lines = (output or {}).get("traceback") or []
        if traceback_lines:
            text = "\n".join(_strip_ansi(line) for line in traceback_lines)
        else:
            ename = str((output or {}).get("ename") or "Error")
            evalue = str((output or {}).get("evalue") or "")
            text = f"{ename}: {evalue}"
        if text:
            sys.stdout.write(text)
            if not text.endswith("\n"):
                sys.stdout.write("\n")


def _emit_notebook_cell_outputs(cell):
    for output in list((cell or {}).get("outputs") or []):
        _emit_notebook_output(output)
    try:
        sys.stdout.flush()
    except Exception:
        pass


def _emit_notebook_exception(exc):
    text = _strip_ansi(str(exc or "")).strip()
    if not text:
        text = f"{type(exc).__name__}: {exc}"
    sys.stderr.write(text)
    if not text.endswith("\n"):
        sys.stderr.write("\n")
    try:
        sys.stderr.flush()
    except Exception:
        pass


def _run_notebook(notebook_path, extra_args):
    import nbformat
    from nbclient import NotebookClient

    class StreamingNotebookClient(NotebookClient):
        def process_message(self, msg, cell, cell_index):
            output = super().process_message(msg, cell, cell_index)
            if output is not None:
                _emit_notebook_output(output)
                try:
                    sys.stdout.flush()
                except Exception:
                    pass
            return output

    notebook = nbformat.read(notebook_path, as_version=4)
    kernel_name = str((((notebook.metadata or {}).get("kernelspec") or {}).get("name")) or "").strip() or None
    resources = {"metadata": {"path": os.path.dirname(notebook_path) or os.getcwd()}}
    client = StreamingNotebookClient(
        notebook,
        timeout=None,
        allow_errors=False,
        kernel_name=kernel_name,
        resources=resources,
    )

    os.environ["GB_NOTEBOOK_PATH"] = notebook_path
    os.environ["GB_SCRIPT_PATH"] = notebook_path

    original_argv = list(sys.argv)
    try:
        sys.stdout.write(f"[Notebook] 启动全新 kernel 后运行: {notebook_path}\n")
        sys.stdout.flush()
        sys.argv = [notebook_path] + list(extra_args or [])
        with client.setup_kernel():
            for index, cell in enumerate(notebook.cells):
                if str((cell or {}).get("cell_type") or "") != "code":
                    continue
                client.execute_cell(cell, index)
    finally:
        sys.argv = original_argv


def main():
    if len(sys.argv) < 2:
        raise SystemExit("缺少目标脚本路径参数")

    script_arg = sys.argv[1]
    script_path = os.path.abspath(script_arg)
    if not os.path.isfile(script_path):
        raise SystemExit(f"目标脚本不存在: {script_path}")

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    _append_trace(
        "step-entry-start",
        pid=os.getpid(),
        script=script_path,
        shim=os.environ.get("GB_ENABLE_ASYNC_LOG_SHIM", ""),
        pythonpath=os.environ.get("PYTHONPATH", ""),
    )
    import sitecustomize  # noqa: F401
    _append_trace("step-entry-sitecustomize-loaded", pid=os.getpid(), script=script_path)

    original_argv = list(sys.argv)
    original_script_sys_path = None
    try:
        sys.argv = [script_path] + original_argv[2:]
        os.environ["GB_SCRIPT_PATH"] = script_path
        if _is_notebook_path(script_path):
            _append_trace("step-entry-notebook", pid=os.getpid(), script=script_path)
            _run_notebook(script_path, original_argv[2:])
        else:
            original_script_sys_path = list(sys.path)
            sys.path.insert(0, os.path.dirname(script_path))
            runpy.run_path(script_path, run_name="__main__")
    except Exception as exc:
        if _is_notebook_path(script_path):
            _emit_notebook_exception(exc)
            raise SystemExit(1)
        raise
    finally:
        _append_trace("step-entry-finish", pid=os.getpid(), script=script_path)
        if original_script_sys_path is not None:
            sys.path[:] = original_script_sys_path
        sys.argv = original_argv


if __name__ == "__main__":
    main()

