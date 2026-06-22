import os
import runpy
import sys
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
    try:
        sys.argv = [script_path] + original_argv[2:]
        runpy.run_path(script_path, run_name="__main__")
    finally:
        _append_trace("step-entry-finish", pid=os.getpid(), script=script_path)
        sys.argv = original_argv


if __name__ == "__main__":
    main()
