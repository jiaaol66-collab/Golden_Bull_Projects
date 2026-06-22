import builtins
import os
import subprocess
import sys
import threading
from datetime import datetime


_PATCHED_MODULES = set()
_ORIGINAL_IMPORT = builtins.__import__


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


def _patch_userlib_tools():
    _append_trace("sitecustomize-patch-attempt", pid=os.getpid(), shim=os.environ.get("GB_ENABLE_ASYNC_LOG_SHIM", ""), loaded="userlib.tools" in sys.modules)
    if os.environ.get("GB_ENABLE_ASYNC_LOG_SHIM") != "1":
        return

    tools = sys.modules.get("userlib.tools")
    if tools is None:
        return
    if getattr(tools, "_gb_async_log_shim_applied", False):
        return

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bridge_script = os.path.join(project_root, "gb_runtime_patch", "async_console_bridge.py")
    if not os.path.isfile(bridge_script):
        return

    def _patched_open_python_async(file_path):
        _append_trace("patched-open-python-async", pid=os.getpid(), file=file_path)
        print("open_python_async被调用")
        try:
            abs_file_path = os.path.abspath(file_path)
            if not os.path.exists(abs_file_path):
                script_dir = os.path.dirname(os.path.abspath(tools.__file__))
                abs_file_path = os.path.normpath(os.path.join(script_dir, "..", file_path))

            if not os.path.exists(abs_file_path):
                print(f"错误：Python脚本不存在 -> {abs_file_path}")
                return

            file_dir = os.path.dirname(abs_file_path)
            venv_python = os.path.join(project_root, "myenv", "Scripts", "python.exe")
            python_executable = venv_python if os.path.exists(venv_python) else sys.executable
            log_path = tools._build_async_log_path(abs_file_path)
            if not log_path:
                fallback_name = os.path.basename(abs_file_path) + ".log"
                log_path = os.path.join(file_dir, fallback_name)

            child_env = os.environ.copy()
            workspace_root = tools._get_env_text("GB_TIMELINE_WORKSPACE_ROOT")
            if workspace_root:
                workspace_root = os.path.abspath(workspace_root)
            child_env["GB_TIMELINE_WORKSPACE_ROOT"] = workspace_root or ""
            child_env["GB_TIMELINE_SESSION_ID"] = tools._get_env_text("GB_TIMELINE_SESSION_ID") or tools._make_timeline_id("session")
            child_env["GB_TIMELINE_RUN_ID"] = tools._make_timeline_id("run")
            child_env["GB_TIMELINE_PARENT_REL"] = tools._get_env_text("GB_TIMELINE_REL_PATH")
            child_env["GB_TIMELINE_PARENT_RUN_ID"] = tools._get_env_text("GB_TIMELINE_RUN_ID")
            child_env["GB_TIMELINE_AXIS"] = "async"
            child_env["GB_TIMELINE_SOURCE"] = "async_open"
            child_env["GB_TIMELINE_REL_PATH"] = tools._compute_timeline_rel_path(abs_file_path, workspace_root)
            child_env["PYTHONUNBUFFERED"] = "1"
            child_env["PYTHONIOENCODING"] = "utf-8"
            child_env["PYTHONUTF8"] = "1"
            child_env["GB_ENABLE_ASYNC_LOG_SHIM"] = "1"

            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)

            tools._debug_report_open_file(
                "shim-A",
                "gb_runtime_patch.sitecustomize:_patched_open_python_async",
                "[DEBUG] runtime shim resolved launch inputs",
                {
                    "abs_file_path": abs_file_path,
                    "bridge_script": bridge_script,
                    "python_executable": python_executable,
                    "log_path": log_path,
                    "creationflags": creationflags,
                },
            )

            bridge_cmd = (
                f"& {tools._ps_quote(python_executable)} "
                f"{tools._ps_quote(bridge_script)} "
                f"--python {tools._ps_quote(python_executable)} "
                f"--script {tools._ps_quote(abs_file_path)} "
                f"--cwd {tools._ps_quote(file_dir)} "
                f"--log {tools._ps_quote(log_path)}"
            )
            ps_command = tools._build_async_ps_command(
                file_dir,
                bridge_cmd,
                script_name=os.path.basename(abs_file_path),
                launch_mode="python.exe + bridge",
                log_path="",
                pause_on_failure=True,
            )

            proc = subprocess.Popen(
                ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
                cwd=file_dir,
                creationflags=creationflags,
                env=child_env,
            )

            tools._register_async_pid(proc.pid)
            threading.Thread(
                target=tools._watch_async_process,
                args=(proc, None, abs_file_path),
                daemon=True,
            ).start()
            print(f"[DEBUG] 异步子进程 PID: {proc.pid}")
        except Exception as exc:
            tools._debug_report_open_file(
                "shim-E",
                "gb_runtime_patch.sitecustomize:_patched_open_python_async",
                "[DEBUG] runtime shim raised exception",
                {
                    "file_path": file_path,
                    "error": str(exc),
                },
            )
            print(f"异步启动Python脚本失败: {str(exc)}")

    def _patched_open_file(file_path):
        _append_trace("patched-open-file", pid=os.getpid(), file=file_path)
        print("open_file被调用")
        try:
            abs_file_path = os.path.abspath(file_path)
            if not os.path.exists(abs_file_path):
                print(f"错误：文件不存在 -> {abs_file_path}")
                script_dir = os.path.dirname(os.path.abspath(tools.__file__))
                abs_file_path = os.path.normpath(os.path.join(script_dir, "..", file_path))

            file_extension = os.path.splitext(abs_file_path)[1].lower()
            tools._debug_report_open_file(
                "F-shim",
                "gb_runtime_patch.sitecustomize:_patched_open_file",
                "[DEBUG] runtime shim open_file resolved target path",
                {
                    "input_path": file_path,
                    "abs_file_path": abs_file_path,
                    "exists": os.path.exists(abs_file_path),
                    "file_extension": file_extension,
                },
            )

            if file_extension == ".py":
                return _patched_open_python_async(abs_file_path)

            print(f"执行默认打开逻辑: {abs_file_path}")
            if sys.platform == "win32":
                os.startfile(abs_file_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", abs_file_path], check=True)
            else:
                subprocess.run(["xdg-open", abs_file_path], check=True)
            print(f"成功发起打开请求: {os.path.basename(abs_file_path)}")
        except Exception as exc:
            print(f"打开文件失败: {str(exc)}")

    tools._gb_original_open_python_async = getattr(tools, "open_python_async", None)
    tools._gb_original_open_file = getattr(tools, "open_file", None)
    tools.open_python_async = _patched_open_python_async
    tools.open_file = _patched_open_file
    try:
        if getattr(tools._gb_original_open_file, "__globals__", None) is not None:
            tools._gb_original_open_file.__globals__["open_python_async"] = _patched_open_python_async
            tools._gb_original_open_file.__globals__["open_file"] = _patched_open_file
    except Exception:
        pass
    tools._gb_async_log_shim_applied = True
    _PATCHED_MODULES.add("userlib.tools")
    _append_trace(
        "sitecustomize-patch-applied",
        pid=os.getpid(),
        module="userlib.tools",
        open_python_async_id=id(tools.open_python_async),
        open_file_id=id(tools.open_file),
    )


def _shim_import(name, globals=None, locals=None, fromlist=(), level=0):
    module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    fromlist = fromlist or ()
    if name == "userlib.tools" or (name == "userlib" and "tools" in fromlist):
        _patch_userlib_tools()
    elif "userlib.tools" in sys.modules and "userlib.tools" not in _PATCHED_MODULES:
        _patch_userlib_tools()
    return module


builtins.__import__ = _shim_import
_append_trace("sitecustomize-loaded", pid=os.getpid(), shim=os.environ.get("GB_ENABLE_ASYNC_LOG_SHIM", ""))
_patch_userlib_tools()
