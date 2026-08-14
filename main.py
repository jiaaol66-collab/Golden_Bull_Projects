from __future__ import annotations

import argparse
import functools
import http.server
import json
import multiprocessing
import socketserver
import sys
import webbrowser
from pathlib import Path

from modern_terminal import TerminalBridge


PROJECT_ROOT = Path(__file__).resolve().parent
UI_ROOT = PROJECT_ROOT / "modern_terminal" / "ui"


def build_ui_url(floating: bool = False) -> str:
    """Build a WebView-safe local URL without changing the file path."""
    url = (UI_ROOT / "index.html").resolve().as_uri()
    return f"{url}#view=floating" if floating else url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="金牛奖 Terminal 新界面")
    parser.add_argument("--floating", action="store_true", help="启动始终置顶的运行监视器")
    parser.add_argument("--workspace", default="", help="默认工作区 ID")
    parser.add_argument("--debug", action="store_true", help="启用 WebView 调试模式")
    parser.add_argument("--browser", action="store_true", help="在系统浏览器中预览静态界面")
    parser.add_argument("--smoke-test", action="store_true", help="只验证状态读取与依赖，不打开窗口")
    parser.add_argument("--without-legacy-bridge", action="store_true", help="仅预览界面，不启动旧调度内核桥")
    return parser


def run_smoke_test(bridge: TerminalBridge) -> int:
    payload = bridge.diagnostics()
    payload["ui_exists"] = (UI_ROOT / "index.html").is_file()
    try:
        import webview  # noqa: F401

        payload["pywebview_available"] = True
    except ImportError:
        payload["pywebview_available"] = False
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] and payload["ui_exists"] else 1


def run_browser_preview() -> int:
    if not (UI_ROOT / "index.html").is_file():
        print(f"未找到界面文件：{UI_ROOT / 'index.html'}", file=sys.stderr)
        return 1

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(UI_ROOT))
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = int(server.server_address[1])
    url = f"http://127.0.0.1:{port}/index.html?preview=1"
    print(f"静态预览已启动：{url}")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def run_webview(bridge: TerminalBridge, floating: bool, debug: bool) -> int:
    try:
        import webview
    except ModuleNotFoundError as exc:
        if exc.name != "webview":
            raise
        print(
            "缺少 pywebview。请先执行：\n"
            "  run.bat -m pip install -r modern_terminal\\requirements.txt\n"
            "也可以执行 `python main.py --browser` 预览静态界面。",
            file=sys.stderr,
        )
        return 2

    index_path = (UI_ROOT / "index.html").resolve()
    if not index_path.is_file():
        print(f"未找到界面文件：{index_path}", file=sys.stderr)
        return 1

    url = build_ui_url(floating=floating)
    window_options = {
        "title": "运行监视器" if floating else "金牛奖 Terminal",
        "url": url,
        "js_api": bridge,
        "background_color": "#F1F8F3",
    }
    if floating:
        window_options.update(
            {
                "width": 300,
                "height": 132,
                "resizable": False,
                "frameless": True,
                "easy_drag": True,
                "shadow": True,
                "transparent": True,
                "on_top": True,
            }
        )
    else:
        window_options.update({"width": 1380, "height": 860, "min_size": (1040, 680)})

    window = webview.create_window(**window_options)
    bridge.attach_window(window)
    try:
        webview.start(debug=debug)
    finally:
        bridge.stop_legacy_bridge()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mode = "floating" if args.floating else "main"
    bridge = TerminalBridge(PROJECT_ROOT, mode=mode, workspace_id=args.workspace)
    if args.smoke_test:
        return run_smoke_test(bridge)
    if args.browser:
        return run_browser_preview()
    if not args.floating and not args.without_legacy_bridge:
        bridge_result = bridge.start_legacy_bridge()
        if not bridge_result.get("ok"):
            print(f"旧内核实时桥启动失败，将使用只读日志状态：{bridge_result.get('message', '')}", file=sys.stderr)
    return run_webview(bridge, floating=args.floating, debug=args.debug)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
