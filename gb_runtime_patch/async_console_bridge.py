import argparse
import codecs
import os
import subprocess
import sys
from datetime import datetime


def _write_text(stream, text):
    if not text:
        return
    try:
        stream.write(text)
    except UnicodeEncodeError:
        encoded = text.encode("utf-8", errors="replace")
        target = getattr(stream, "buffer", None)
        if target is not None:
            target.write(encoded)
        else:
            stream.write(encoded.decode("utf-8", errors="replace"))
    stream.flush()


def _append_log(log_handle, text):
    if not log_handle or not text:
        return
    log_handle.write(text)
    log_handle.flush()


def _emit(stream, log_handle, text):
    if not text:
        return
    _write_text(stream, text)
    _append_log(log_handle, text)


def _write_live_carriage(stream, state, text):
    if not text:
        return
    previous_width = int(state.get("live_width", 0) or 0)
    current_width = len(text)
    padding = " " * max(0, previous_width - current_width)
    _write_text(stream, "\r" + text + padding)
    state["live_width"] = max(previous_width, current_width) if padding else current_width
    state["carriage_visible"] = True


def _finalize_live_carriage(stream, log_handle, state, text):
    if not text:
        if state.get("carriage_visible"):
            _write_text(stream, "\r\n")
            state["carriage_visible"] = False
            state["live_width"] = 0
        return
    if state.get("carriage_visible"):
        previous_width = int(state.get("live_width", 0) or 0)
        current_width = len(text)
        padding = " " * max(0, previous_width - current_width)
        _write_text(stream, "\r" + text + padding + "\n")
        _append_log(log_handle, text + "\n")
        state["carriage_visible"] = False
        state["live_width"] = 0
        return
    _emit(stream, log_handle, text + "\n")


def _consume_stream_text(stream, log_handle, state, text):
    if not text:
        return
    pending_cr = bool(state.get("pending_cr"))
    if pending_cr:
        state["pending_cr"] = False
        if text.startswith("\n"):
            line = state["line_buffer"] if state["line_buffer"] else state["carriage_line"]
            _finalize_live_carriage(stream, log_handle, state, line)
            state["line_buffer"] = ""
            state["carriage_line"] = ""
            text = text[1:]
        else:
            state["carriage_line"] = state["line_buffer"] if state["line_buffer"] else state["carriage_line"]
            _write_live_carriage(stream, state, state["carriage_line"])
            state["line_buffer"] = ""

    for ch in text:
        if ch == "\r":
            state["pending_cr"] = True
            continue

        if ch == "\n":
            state["pending_cr"] = False
            line = state["line_buffer"] if state["line_buffer"] else state["carriage_line"]
            _finalize_live_carriage(stream, log_handle, state, line)
            state["line_buffer"] = ""
            state["carriage_line"] = ""
            continue

        if state.get("pending_cr"):
            state["pending_cr"] = False
            state["carriage_line"] = state["line_buffer"] if state["line_buffer"] else state["carriage_line"]
            _write_live_carriage(stream, state, state["carriage_line"])
            state["line_buffer"] = ""

        if state["carriage_line"] and not state["line_buffer"]:
            state["carriage_line"] = ""
        state["line_buffer"] += ch


def _emit_banner(log_handle, script_path, working_dir, log_path, python_path):
    banner_lines = [
        "=" * 60,
        "[OPEN_FILE] 异步脚本启动中",
        f"[OPEN_FILE] 脚本文件: {os.path.basename(script_path)}",
        f"[OPEN_FILE] 启动方式: {os.path.basename(python_path)}",
        f"[OPEN_FILE] 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"[OPEN_FILE] 工作目录: {working_dir}",
        f"[OPEN_FILE] 日志文件: {log_path}",
        "[OPEN_FILE] 正在执行命令，请稍候...",
        "=" * 60,
        "",
    ]
    for line in banner_lines:
        _append_log(log_handle, line + "\n")


def _stream_process_output(process, log_handle):
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    state = {"line_buffer": "", "carriage_line": "", "live_width": 0, "carriage_visible": False, "pending_cr": False}
    stdout = process.stdout
    if stdout is None:
        return

    while True:
        try:
            if hasattr(stdout, "read1"):
                chunk = stdout.read1(1024)
            else:
                chunk = os.read(stdout.fileno(), 1024)
        except OSError:
            break
        if not chunk:
            break
        text = decoder.decode(chunk)
        if not text:
            continue
        _consume_stream_text(sys.stdout, log_handle, state, text)

    tail = decoder.decode(b"", final=True)
    if tail:
        _consume_stream_text(sys.stdout, log_handle, state, tail)
    if state.get("pending_cr") and state.get("line_buffer"):
        state["pending_cr"] = False
        state["carriage_line"] = state["line_buffer"] if state["line_buffer"] else state["carriage_line"]
        _write_live_carriage(sys.stdout, state, state["carriage_line"])
        state["line_buffer"] = ""
    if state["line_buffer"]:
        _finalize_live_carriage(sys.stdout, log_handle, state, state["line_buffer"])
    elif state["carriage_line"]:
        _finalize_live_carriage(sys.stdout, log_handle, state, state["carriage_line"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--script", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--log", required=True)
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.log), exist_ok=True)

    child_env = os.environ.copy()
    child_env["PYTHONUNBUFFERED"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"

    with open(args.log, "w", encoding="utf-8", newline="\n") as log_handle:
        _emit_banner(log_handle, args.script, args.cwd, args.log, args.python)
        process = subprocess.Popen(
            [args.python, args.script],
            cwd=args.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=child_env,
            bufsize=0,
        )
        try:
            _stream_process_output(process, log_handle)
        finally:
            return_code = process.wait()
        if return_code != 0:
            _emit(
                sys.stdout,
                log_handle,
                f"\n[OPEN_FILE] 脚本执行失败，退出码: {return_code}\n",
            )
        return return_code


if __name__ == "__main__":
    raise SystemExit(main())
