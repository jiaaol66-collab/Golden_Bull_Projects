from __future__ import annotations

import datetime as dt
import json
import multiprocessing as mp
import os
import queue
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = 1
DEFAULT_COMMAND_QUEUE_SIZE = 32
DEFAULT_SNAPSHOT_QUEUE_SIZE = 4
DEFAULT_SNAPSHOT_INTERVAL_MS = 400
MAX_LOG_LINES_PER_WORKSPACE = 160
MAX_TIMELINE_ENTRIES_PER_WORKSPACE = 240


def _json_payload(value: Any) -> Any:
    """Return a detached JSON-safe copy or raise a useful TypeError."""

    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _put_latest(target_queue: Any, payload: dict[str, Any]) -> bool:
    """Publish without ever blocking Tk; evict an obsolete snapshot if full."""

    safe_payload = _json_payload(payload)
    try:
        target_queue.put_nowait(safe_payload)
        return True
    except queue.Full:
        pass

    try:
        target_queue.get_nowait()
    except queue.Empty:
        # multiprocessing.Queue's feeder thread can briefly report Full and
        # Empty at the same time.  The next scheduled snapshot will retry.
        return False
    try:
        target_queue.put_nowait(safe_payload)
        return True
    except queue.Full:
        return False


def _iso(value: Any) -> str:
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ", timespec="milliseconds")
    return str(value or "")


def _normal_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return os.path.normcase(os.path.abspath(text))


class _LegacyBridgeMixin:
    """Observation and command adapter mixed into the unchanged Terminal.

    The concrete class is created inside the spawned process so importing this
    module in the modern shell does not import CustomTkinter or ``terminal.py``.
    Scheduler actions deliberately call the legacy implementation via
    ``super()``; this class does not contain a second scheduler.
    """

    def __init__(
        self,
        command_queue: Any,
        snapshot_queue: Any,
        stop_event: Any,
        *,
        snapshot_interval_ms: int = DEFAULT_SNAPSHOT_INTERVAL_MS,
        initially_visible: bool = False,
    ) -> None:
        self._bridge_command_queue = command_queue
        self._bridge_snapshot_queue = snapshot_queue
        self._bridge_stop_event = stop_event
        self._bridge_snapshot_interval_ms = max(150, int(snapshot_interval_ms))
        self._bridge_revision = 0
        self._bridge_visible = bool(initially_visible)
        self._bridge_close_started = False
        self._bridge_last_command: dict[str, Any] = {}
        self._bridge_logs: dict[str, deque[str]] = defaultdict(
            lambda: deque(maxlen=MAX_LOG_LINES_PER_WORKSPACE)
        )
        self._bridge_logs_lock = threading.Lock()
        self._bridge_last_error: dict[str, Any] = {
            "tab_id": "",
            "file": "",
            "message": "",
            "captured_at": "",
        }

        super().__init__()

        if not self._bridge_visible:
            try:
                self.withdraw()
            except Exception:
                pass
        self.safe_after(0, self._bridge_poll_commands)
        self.safe_after(0, self._bridge_publish_snapshot)

    # Observation hooks only.  The legacy implementation remains authoritative.
    def log_msg(self, tab_id: str, msg: Any, raw: bool = False, overwrite_last: bool = False) -> None:
        super().log_msg(tab_id, msg, raw=raw, overwrite_last=overwrite_last)
        if overwrite_last:
            return
        line = str(msg or "")
        if not raw:
            line = f"[{dt.datetime.now().strftime('%H:%M:%S')}] {line}"
        self._bridge_record_log(tab_id, line)

    def queue_runtime_log(self, tab_id: str, line: Any) -> None:
        super().queue_runtime_log(tab_id, line)
        self._bridge_record_log(tab_id, str(line or ""))

    def show_script_error_popup(self, script_path: Any, error_message: Any) -> None:
        self._bridge_last_error = {
            "tab_id": self._bridge_active_tab_id(),
            "file": os.path.abspath(str(script_path or "")) if script_path else "",
            "message": str(error_message or ""),
            "captured_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
        self._bridge_publish_snapshot()
        super().show_script_error_popup(script_path, error_message)

    def on_app_close(self) -> None:
        if self._bridge_close_started:
            return
        self._bridge_close_started = True
        try:
            self._bridge_last_command = {
                "ok": True,
                "action": "shutdown",
                "message": "旧版调度进程正在安全关闭。",
                "completed_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
            self._bridge_publish_snapshot(lifecycle="closing")
        finally:
            self._bridge_stop_event.set()
            super().on_app_close()

    def _bridge_record_log(self, tab_id: str, line: str) -> None:
        if not tab_id or not line:
            return
        with self._bridge_logs_lock:
            self._bridge_logs[tab_id].append(line)

    def _bridge_poll_commands(self) -> None:
        if self._bridge_close_started or getattr(self, "app_closing", False):
            return
        if self._bridge_stop_event.is_set():
            self.on_app_close()
            return

        for _ in range(24):
            try:
                command = self._bridge_command_queue.get_nowait()
            except queue.Empty:
                break
            self._bridge_execute_command(command)
            if self._bridge_close_started:
                return
        self.safe_after(80, self._bridge_poll_commands)

    def _bridge_execute_command(self, raw_command: Any) -> None:
        request_id = ""
        action = ""
        try:
            if not isinstance(raw_command, dict):
                raise ValueError("命令必须是 JSON 对象。")
            version = int(raw_command.get("version", PROTOCOL_VERSION))
            if version != PROTOCOL_VERSION:
                raise ValueError(f"不支持的桥接协议版本: {version}")
            request_id = str(raw_command.get("request_id") or "")
            action = str(raw_command.get("action") or "").strip().lower()
            payload = raw_command.get("payload") or {}
            if not isinstance(payload, dict):
                raise ValueError("命令 payload 必须是 JSON 对象。")

            handlers = {
                "activate": self._bridge_command_activate,
                "mount": self._bridge_command_mount,
                "start": self._bridge_command_start,
                "run_manual_code": self._bridge_command_run_manual_code,
                "open_file_structure": self._bridge_command_open_file_structure,
                "open_config_editor": self._bridge_command_open_config_editor,
                "open_resource_settings": self._bridge_command_open_resource_settings,
                "initialize_award_workspace": self._bridge_command_initialize_award_workspace,
                "pause": self._bridge_command_pause,
                "open_legacy_ui": self._bridge_command_open_legacy_ui,
                "shutdown": self._bridge_command_shutdown,
            }
            handler = handlers.get(action)
            if handler is None:
                raise ValueError(f"未知命令: {action or '<empty>'}")
            result = handler(payload) or {}
            self._bridge_last_command = {
                "request_id": request_id,
                "action": action,
                "ok": bool(result.get("ok", True)),
                "message": str(result.get("message") or ""),
                "data": result.get("data") or {},
                "completed_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
        except Exception as exc:
            self._bridge_last_command = {
                "request_id": request_id,
                "action": action,
                "ok": False,
                "message": f"{type(exc).__name__}: {exc}",
                "data": {},
                "completed_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
        self._bridge_publish_snapshot()

    def _bridge_resolve_workspace(self, payload: dict[str, Any]) -> dict[str, str]:
        nested = payload.get("workspace")
        values = dict(nested) if isinstance(nested, dict) else {}
        values.update({key: value for key, value in payload.items() if key != "workspace"})
        requested_id = str(values.get("workspace_id") or values.get("id") or "").strip()
        requested_root = _normal_path(values.get("workspace_root"))
        requested_award = str(values.get("award") or "").strip()
        requested_name = str(values.get("workspace_name") or values.get("name") or "").strip()
        requested_year = str(values.get("year") or "").strip()

        if values.get("tab_id") in self.active_tabs_data:
            tab_id = str(values["tab_id"])
            tab_data = self.active_tabs_data[tab_id]
            manifest = tab_data.get("manifest", {})
            return {
                "tab_id": tab_id,
                "award": str(tab_data.get("award") or ""),
                "workspace_name": os.path.basename(str(manifest.get("workspace_root") or "")),
                "workspace_root": str(manifest.get("workspace_root") or ""),
                "year": self.get_workspace_year(os.path.basename(str(manifest.get("workspace_root") or ""))),
            }

        from award_config import get_award_folder, get_award_labels

        matches: list[dict[str, str]] = []
        for award in get_award_labels():
            if requested_award and award != requested_award:
                continue
            for workspace_name in self.scan_workspaces(award):
                workspace_root = os.path.abspath(os.path.join(get_award_folder(award), workspace_name))
                if requested_root and _normal_path(workspace_root) != requested_root:
                    continue
                if requested_name and workspace_name != requested_name:
                    # The request may contain the user-facing alias.
                    stub = {"workspace_root": workspace_root, "award": award}
                    if self.get_workspace_display_name(stub) != requested_name:
                        continue
                if requested_year and self.get_workspace_year(workspace_name) != requested_year:
                    continue
                if requested_id:
                    meta_path = os.path.join(workspace_root, ".gb_workspace.json")
                    try:
                        with open(meta_path, "r", encoding="utf-8-sig") as handle:
                            metadata = json.load(handle)
                    except (OSError, ValueError, TypeError):
                        metadata = {}
                    if str(metadata.get("workspace_id") or "") != requested_id:
                        continue
                matches.append(
                    {
                        "tab_id": f"{award}-{workspace_name}",
                        "award": award,
                        "workspace_name": workspace_name,
                        "workspace_root": workspace_root,
                        "year": self.get_workspace_year(workspace_name),
                    }
                )

        if not matches and not any((requested_id, requested_root, requested_award, requested_name)):
            active_tab_id = self._bridge_active_tab_id()
            if active_tab_id in self.active_tabs_data:
                return self._bridge_resolve_workspace({"tab_id": active_tab_id})
        if not matches:
            raise ValueError("未找到对应工作区；请传 workspace_id、workspace_root，或 award + workspace_name。")
        if len(matches) > 1:
            raise ValueError("工作区条件不唯一；请补充 workspace_id 或 workspace_root。")
        return matches[0]

    def _bridge_mount_resolved(self, resolved: dict[str, str]) -> str:
        tab_id = resolved["tab_id"]
        if tab_id in self.active_tabs_data:
            self.tabview.set(tab_id)
            return tab_id

        award = resolved["award"]
        year = resolved["year"]
        workspace_name = resolved["workspace_name"]
        self.award_menu.set(award)
        self.update_year_menu(award, selected_year=year, selected_workspace=workspace_name)
        reverse_map = self.workspace_menu_reverse_map.get((award, year), {})
        self.workspace_menu.set(reverse_map.get(workspace_name, workspace_name))
        super().mount_workspace()
        if tab_id not in self.active_tabs_data:
            raise RuntimeError("旧版 Terminal 未能挂载工作区。")
        return tab_id

    def _bridge_command_activate(self, payload: dict[str, Any]) -> dict[str, Any]:
        resolved = self._bridge_resolve_workspace(payload)
        tab_id = self._bridge_mount_resolved(resolved) if payload.get("mount") else resolved["tab_id"]
        if tab_id not in self.active_tabs_data:
            raise ValueError("工作区尚未挂载；请先发送 mount，或设置 mount=true。")
        self.tabview.set(tab_id)
        if payload.get("show", True):
            self._bridge_show_legacy_window()
        return {"ok": True, "message": "已激活工作区。", "data": {"tab_id": tab_id}}

    def _bridge_command_mount(self, payload: dict[str, Any]) -> dict[str, Any]:
        resolved = self._bridge_resolve_workspace(payload)
        tab_id = self._bridge_mount_resolved(resolved)
        return {"ok": True, "message": "工作区已挂载。", "data": {"tab_id": tab_id}}

    def _bridge_command_start(self, payload: dict[str, Any]) -> dict[str, Any]:
        resolved = self._bridge_resolve_workspace(payload)
        tab_id = self._bridge_mount_resolved(resolved)
        tab_data = self.active_tabs_data[tab_id]
        if self.is_workspace_tab_running(tab_id):
            raise RuntimeError("该工作区已有任务正在运行。")

        requested_orders = payload.get("selected_orders")
        if requested_orders is not None:
            if not isinstance(requested_orders, list):
                raise ValueError("selected_orders 必须是运行顺序数组。")
            selected_orders: set[int] = set()
            for raw_order in requested_orders:
                try:
                    selected_orders.add(int(raw_order))
                except (TypeError, ValueError):
                    raise ValueError(f"无效运行顺序: {raw_order}") from None
            valid_orders = set(self.get_valid_manifest_step_orders(tab_data.get("manifest", {})))
            unknown_orders = selected_orders - valid_orders
            if unknown_orders:
                raise ValueError(f"工作区不存在运行顺序: {sorted(unknown_orders)}")
            for order, variable in tab_data.get("step_vars", {}).items():
                variable.set("1" if order in selected_orders else "0")

        super().start_batch_run(tab_id)
        started = bool(tab_data.get("attempt_active") or self.is_workspace_tab_running(tab_id))
        if not started:
            raise RuntimeError("旧版调度器未启动任务；请检查步骤选择与运行顺序。")
        return {
            "ok": True,
            "message": "已由旧版调度内核开始运行。",
            "data": {"tab_id": tab_id, "session_id": tab_data.get("timeline_batch_session_id", "")},
        }

    def _bridge_manual_code_items(self, manifest: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in manifest.get("other_root_codes", []) or []:
            items.append({**dict(item), "group": "工具代码"})
        try:
            fixed_backup = self.get_fixed_backup_code_item(os.path.abspath(str(manifest.get("workspace_root") or "")))
        except Exception:
            fixed_backup = {}
        if fixed_backup and fixed_backup.get("exists"):
            items.append({**dict(fixed_backup), "group": "工具代码"})
        for folder in manifest.get("step_code_folders", []) or []:
            group = str(folder.get("display_label") or folder.get("folder_rel_path") or "辅助代码")
            for item in folder.get("async_files", []) or []:
                items.append({**dict(item), "group": group})

        unique: dict[str, dict[str, Any]] = {}
        workspace_root = os.path.abspath(str(manifest.get("workspace_root") or ""))
        for item in items:
            rel_path = str(item.get("rel_path") or "").replace("\\", "/").strip("/")
            if not rel_path or os.path.splitext(rel_path.lower())[1] not in {".py", ".ipynb"}:
                continue
            abs_path = os.path.abspath(os.path.join(workspace_root, rel_path))
            try:
                if os.path.normcase(os.path.commonpath([workspace_root, abs_path])) != os.path.normcase(workspace_root):
                    continue
            except ValueError:
                continue
            unique[os.path.normcase(rel_path)] = {
                **item,
                "id": rel_path,
                "rel_path": rel_path,
                "abs_path": abs_path,
                "label": str(item.get("display_label") or item.get("name") or os.path.basename(rel_path)),
                "exists": os.path.isfile(abs_path),
                "group": str(item.get("group") or "辅助代码"),
            }
        return sorted(unique.values(), key=lambda item: (item["group"], item["label"], item["rel_path"]))

    def _bridge_command_run_manual_code(self, payload: dict[str, Any]) -> dict[str, Any]:
        resolved = self._bridge_resolve_workspace(payload)
        tab_id = self._bridge_mount_resolved(resolved)
        tab_data = self.active_tabs_data[tab_id]
        if self.is_workspace_tab_running(tab_id):
            raise RuntimeError("该工作区已有任务正在运行。")
        code_id = str(payload.get("code_id") or "").replace("\\", "/").strip("/")
        allowed = {
            item["id"]: item
            for item in self._bridge_manual_code_items(tab_data.get("manifest", {}) or {})
            if item.get("exists")
        }
        item = allowed.get(code_id)
        if item is None:
            raise ValueError("所选代码不在当前工作区的未编排代码白名单中。")
        super().run_code_item(tab_id, item)
        return {
            "ok": True,
            "message": f"已由旧调度内核运行：{item['label']}",
            "data": {"tab_id": tab_id, "code_id": code_id, "rel_path": item["rel_path"]},
        }

    def _bridge_command_open_file_structure(self, payload: dict[str, Any]) -> dict[str, Any]:
        resolved = self._bridge_resolve_workspace(payload)
        tab_id = self._bridge_mount_resolved(resolved)
        tab_data = self.active_tabs_data[tab_id]
        blueprint_path = os.path.abspath(str(tab_data.get("bp_path") or ""))
        if not blueprint_path or not os.path.isfile(blueprint_path):
            raise FileNotFoundError("当前工作区未找到 文件结构.xlsx。")
        editor = super().open_file_structure_editor_for_tab(tab_id)
        if editor is None:
            raise RuntimeError("文件结构编辑器未能打开。")
        return {
            "ok": True,
            "message": "已打开当前工作区的文件结构编辑器。",
            "data": {"tab_id": tab_id, "blueprint_path": blueprint_path, "target_surface": "file_structure_editor"},
        }

    def _bridge_command_open_config_editor(self, payload: dict[str, Any]) -> dict[str, Any]:
        resolved = self._bridge_resolve_workspace(payload)
        tab_id = self._bridge_mount_resolved(resolved)
        config_path = os.path.abspath(str(self.get_sidebar_award_config_path(resolved["award"]) or ""))
        if not config_path or not os.path.isfile(config_path):
            raise FileNotFoundError("当前奖项没有已接入的 configs 配置文件。")
        editor = self._ensure_sidebar_config_editor(resolved["award"], resolved["year"])
        if editor is None:
            raise RuntimeError("configs 编辑器未能打开。")
        return {
            "ok": True,
            "message": "已打开当前奖项与年份的 configs 编辑器。",
            "data": {"tab_id": tab_id, "config_path": config_path, "target_surface": "config_editor"},
        }

    def _bridge_command_open_resource_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        resolved = self._bridge_resolve_workspace(payload)
        tab_id = self._bridge_mount_resolved(resolved)
        self.refresh_sidebar_resource_browser(resolved["award"], resolved["year"])
        self._bridge_show_legacy_window()
        return {
            "ok": True,
            "message": "已打开并定位到当前奖项、年份和工作区；请在左侧“资料浏览”选择原始数据集和评奖规则后点击确定。",
            "data": {"tab_id": tab_id, "target_surface": "legacy_resource_settings", "pending_user_action": True},
        }

    def _bridge_command_initialize_award_workspace(self, payload: dict[str, Any]) -> dict[str, Any]:
        resolved = self._bridge_resolve_workspace(payload)
        self._bridge_mount_resolved(resolved)
        award_root = self.get_sidebar_award_root(resolved["award"])
        script_path = self.get_award_initialize_script_path(award_root)
        if not script_path or not os.path.isfile(script_path):
            raise FileNotFoundError("当前奖项根目录没有 initialize.py。")
        super().on_sidebar_initialize_click()
        context = getattr(self, "sidebar_initialize_context", {}) or {}
        if not context.get("active"):
            raise RuntimeError("旧 Terminal 未能启动奖项工作区初始化。")
        return {
            "ok": True,
            "message": "已启动当前奖项与年份的工作区初始化流程。",
            "data": {
                "target_surface": "award_workspace_initializer",
                "pending_user_action": True,
                "script_path": os.path.abspath(script_path),
            },
        }

    def _bridge_command_pause(self, payload: dict[str, Any]) -> dict[str, Any]:
        resolved = self._bridge_resolve_workspace(payload)
        tab_id = resolved["tab_id"]
        if tab_id not in self.active_tabs_data:
            raise ValueError("工作区尚未挂载。")
        tab_data = self.active_tabs_data[tab_id]
        if not self.is_workspace_tab_running(tab_id):
            return {"ok": False, "message": "当前没有正在运行的进程。", "data": {"tab_id": tab_id}}

        # A modern UI may do its own explicit confirmation and send confirmed.
        # Otherwise each command is one click in the legacy 3-click safeguard.
        calls = 3 if payload.get("confirmed") else 1
        for _ in range(calls):
            if self.is_workspace_tab_running(tab_id):
                super().request_pause(tab_id)
        still_running = self.is_workspace_tab_running(tab_id)
        return {
            "ok": True,
            "message": "暂停确认已记录。" if still_running else "运行已由旧版调度器停止。",
            "data": {
                "tab_id": tab_id,
                "still_running": still_running,
                "confirmation_count": int(tab_data.get("pause_click_count", 0) or 0),
                "confirmation_required": 3,
            },
        }

    def _bridge_show_legacy_window(self) -> None:
        self._bridge_visible = True
        self.deiconify()
        try:
            self.state("zoomed")
        except Exception:
            pass
        self.lift()
        try:
            self.focus_force()
        except Exception:
            pass

    def _bridge_command_open_legacy_ui(self, _payload: dict[str, Any]) -> dict[str, Any]:
        self._bridge_show_legacy_window()
        return {"ok": True, "message": "已打开旧版 Terminal 窗口。"}

    def _bridge_command_shutdown(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload.get("confirmed"):
            raise ValueError("关闭桥接进程必须传 confirmed=true。")
        self._bridge_last_command = {
            "ok": True,
            "action": "shutdown",
            "message": "正在关闭旧版调度进程。",
        }
        self.safe_after(0, self.on_app_close)
        return {"ok": True, "message": "正在安全关闭。"}

    def _bridge_active_tab_id(self) -> str:
        try:
            tab_id = str(self.tabview.get() or "")
        except Exception:
            tab_id = ""
        return tab_id if tab_id in self.active_tabs_data else ""

    def _bridge_step_payload(self, step: dict[str, Any], state: str = "") -> dict[str, Any]:
        return {
            "order": step.get("order"),
            "label": str(step.get("display_label") or step.get("script_name") or ""),
            "script_name": str(step.get("script_name") or ""),
            "rel_path": str(step.get("rel_path") or "").replace("\\", "/"),
            "state": state,
        }

    def _bridge_timeline(self, tab_id: str, tab_data: dict[str, Any]) -> list[dict[str, Any]]:
        session_id = str(tab_data.get("timeline_batch_session_id") or tab_data.get("attempt_selected_session_id") or "")
        entries = self.get_time_record_entries(
            tab_id,
            session_id=session_id,
            max_items=MAX_TIMELINE_ENTRIES_PER_WORKSPACE,
            reference_now=dt.datetime.now(),
        )
        result: list[dict[str, Any]] = []
        for index, entry in enumerate(entries, start=1):
            serialized = self.serialize_attempt_record_entry(entry)
            serialized["order"] = entry.get("order", index)
            serialized["source"] = str(entry.get("source") or "")
            serialized["pid"] = entry.get("pid")
            result.append(serialized)
        return result

    def _bridge_workspace_snapshot(self, tab_id: str) -> dict[str, Any]:
        tab_data = self.active_tabs_data.get(tab_id, {})
        manifest = tab_data.get("manifest", {}) or {}
        workspace_meta = self.load_workspace_metadata(manifest)
        workspace_root = str(manifest.get("workspace_root") or "")
        steps = list(self.get_ordered_manifest_steps(manifest))
        step_states = tab_data.get("step_states", {}) or {}
        configured_selected_orders = [
            step.get("order")
            for step in steps
            if step.get("order") in tab_data.get("step_vars", {})
            and tab_data["step_vars"][step.get("order")].get() == "1"
        ]
        execution_selected_orders = list(configured_selected_orders)
        if tab_data.get("workspace_stepper_snapshot_active"):
            execution_selected_orders = list(
                tab_data.get("workspace_stepper_selected_orders_snapshot") or execution_selected_orders
            )

        all_steps = [
            self._bridge_step_payload(step, step_states.get(step.get("order"), "pending"))
            for step in steps
        ]
        execution_selected_set = set(execution_selected_orders)
        selected = [item for item in all_steps if item.get("order") in execution_selected_set]
        finished_states = {"success", "error", "skip", "missing"}
        finished = [item for item in selected if item["state"] in finished_states]

        current_step_id = tab_data.get("current_step_id")
        current_step = next((step for step in steps if step.get("order") == current_step_id), None)
        current_run_info = tab_data.get("current_run_info") or {}
        if current_step is None and current_run_info:
            current_step = current_run_info
        current_payload = self._bridge_step_payload(
            current_step or {},
            "running" if current_step else "",
        )

        main_running = self.is_main_process_running(tab_id)
        async_pids = list(self.get_live_async_pids(tab_id))
        is_running = bool(main_running or async_pids or tab_data.get("attempt_active"))
        attempt_status = str(tab_data.get("attempt_status") or "").lower()
        if is_running:
            status = "running"
        elif attempt_status in {"failed", "error"} or tab_data.get("run_timer_failed"):
            status = "failed"
        elif attempt_status == "cancelled":
            status = "paused"
        elif attempt_status in {"success", "done", "completed"}:
            status = "done"
        elif selected and len(finished) == len(selected) and all(item["state"] == "success" for item in finished):
            status = "done"
        else:
            status = "idle"

        now_epoch = time.time()
        try:
            attempt_started_at = float(tab_data.get("attempt_started_at_epoch") or 0.0)
        except (TypeError, ValueError):
            attempt_started_at = 0.0
        attempt_seconds = max(0.0, now_epoch - attempt_started_at) if is_running and attempt_started_at else self.get_live_main_timer_seconds(tab_data)
        try:
            current_started_at = float(current_run_info.get("timeline_started_at") or 0.0)
        except (TypeError, ValueError):
            current_started_at = 0.0
        current_step_seconds = max(0.0, now_epoch - current_started_at) if current_started_at else 0.0

        timeline = self._bridge_timeline(tab_id, tab_data)
        async_seconds = sum(
            max(0.0, float(item.get("duration_seconds") or 0.0))
            for item in timeline
            if item.get("axis") == "async"
        )
        with self._bridge_logs_lock:
            logs = list(self._bridge_logs.get(tab_id, ()))

        popup_error = self._bridge_last_error if self._bridge_last_error.get("tab_id") == tab_id else {}
        error = {
            "file": str(tab_data.get("error_file_rel_path") or popup_error.get("file") or "").replace("\\", "/"),
            "folder": str(tab_data.get("error_folder_rel_path") or "").replace("\\", "/"),
            "message": str(tab_data.get("attempt_error_excerpt") or popup_error.get("message") or ""),
            "log_path": str(tab_data.get("attempt_error_log_path") or ""),
        }
        return {
            "tab_id": tab_id,
            "workspace": {
                "id": str(workspace_meta.get("workspace_id") or ""),
                "award": str(tab_data.get("award") or workspace_meta.get("award") or ""),
                "name": str(workspace_meta.get("workspace_name") or os.path.basename(workspace_root)),
                "display_name": str(self.get_workspace_display_name(manifest) or os.path.basename(workspace_root)),
                "year": self.get_workspace_year(os.path.basename(workspace_root)),
                "workspace_root": workspace_root,
            },
            "session_id": str(tab_data.get("timeline_batch_session_id") or tab_data.get("attempt_selected_session_id") or ""),
            "status": status,
            "current_step": current_payload,
            "steps": all_steps,
            "selected_orders": configured_selected_orders,
            "execution_selected_orders": execution_selected_orders,
            "selected": selected,
            "finished": finished,
            "progress": {
                "selected_total": len(selected),
                "finished_total": len(finished),
                "percent": round(100.0 * len(finished) / len(selected), 1) if selected else 0.0,
            },
            "timers": {
                "attempt_seconds": round(attempt_seconds, 3),
                "main_seconds": round(self.get_live_main_timer_seconds(tab_data), 3),
                "current_step_seconds": round(current_step_seconds, 3),
                "async_seconds": round(async_seconds, 3),
            },
            "processes": {
                "main_running": main_running,
                "async_running": bool(async_pids),
                "async_pids": async_pids,
                "workspace_lock_held": is_running,
            },
            "can_start": not is_running,
            "latest_log": logs[-1] if logs else "",
            "logs": logs,
            "error": error,
            "timeline": timeline,
            "manual_codes": self._bridge_manual_code_items(manifest),
        }

    def _bridge_build_snapshot(self, lifecycle: str = "ready") -> dict[str, Any]:
        self._bridge_revision += 1
        active_tab_id = self._bridge_active_tab_id()
        workspace_snapshots = [
            self._bridge_workspace_snapshot(tab_id)
            for tab_id in list(self.active_tabs_data.keys())
        ]
        active = next((item for item in workspace_snapshots if item["tab_id"] == active_tab_id), None)
        empty = {
            "workspace": None,
            "session_id": "",
            "status": "idle",
            "current_step": {},
            "steps": [],
            "selected_orders": [],
            "execution_selected_orders": [],
            "selected": [],
            "finished": [],
            "progress": {"selected_total": 0, "finished_total": 0, "percent": 0.0},
            "timers": {"attempt_seconds": 0.0, "main_seconds": 0.0, "current_step_seconds": 0.0, "async_seconds": 0.0},
            "processes": {"main_running": False, "async_running": False, "async_pids": []},
            "latest_log": "",
            "logs": [],
            "error": {"file": "", "folder": "", "message": "", "log_path": ""},
            "timeline": [],
        }
        active = active or empty
        return {
            "version": PROTOCOL_VERSION,
            "type": "legacy_terminal_snapshot",
            "revision": self._bridge_revision,
            "captured_at": dt.datetime.now().isoformat(timespec="milliseconds"),
            "lifecycle": lifecycle,
            "legacy": {
                "pid": os.getpid(),
                "visible": self._bridge_visible,
                "scheduler": "terminal.GoldenBullTerminal",
            },
            "capabilities": {
                "activate": True,
                "mount": True,
                "start": True,
                "run_manual_code": True,
                "open_file_structure": True,
                "open_config_editor": True,
                "open_resource_settings": True,
                "initialize_award_workspace": True,
                "pause": True,
                "pause_confirmation_required": 3,
                "open_legacy_ui": True,
                # The unchanged scheduler keeps process/timer registries under
                # each tab_id and already rejects a second run for that tab.
                "parallel_workspace_runs": True,
                "workspace_run_mutex": True,
                "scheduler_reimplemented": False,
            },
            "active_tab_id": active_tab_id,
            "workspace": active["workspace"],
            "session_id": active["session_id"],
            "status": active["status"],
            "current_step": active["current_step"],
            "steps": active.get("steps", []),
            "selected_orders": active.get("selected_orders", []),
            "execution_selected_orders": active.get("execution_selected_orders", []),
            "selected": active["selected"],
            "finished": active["finished"],
            "progress": active["progress"],
            "timers": active["timers"],
            "processes": active["processes"],
            "latest_log": active["latest_log"],
            "logs": active["logs"],
            "error": active["error"],
            "timeline": active["timeline"],
            "manual_codes": active.get("manual_codes", []),
            "workspaces": workspace_snapshots,
            "loaded_workspaces_state": {
                "schema_version": 1,
                "revision": self._bridge_revision,
                "active_tab_id": active_tab_id,
                "items": workspace_snapshots,
                "parallel_capability": {
                    "supported": True,
                    "scope": "different_workspaces",
                    "same_workspace": False,
                    "shared_resource_warning": "不同工作区共享的数据文件或外部资源仍可能互相影响。",
                },
            },
            "last_command": self._bridge_last_command,
        }

    def _bridge_publish_snapshot(self, lifecycle: str = "ready") -> None:
        if self._bridge_close_started and lifecycle != "closing":
            return
        try:
            _put_latest(self._bridge_snapshot_queue, self._bridge_build_snapshot(lifecycle=lifecycle))
        except Exception as exc:
            fallback = {
                "version": PROTOCOL_VERSION,
                "type": "legacy_terminal_snapshot",
                "revision": self._bridge_revision,
                "captured_at": dt.datetime.now().isoformat(timespec="milliseconds"),
                "lifecycle": "snapshot_error",
                "status": "error",
                "error": {"file": __file__, "folder": "", "message": f"{type(exc).__name__}: {exc}", "log_path": ""},
            }
            _put_latest(self._bridge_snapshot_queue, fallback)
        if not self._bridge_close_started and not getattr(self, "app_closing", False):
            self.safe_after(self._bridge_snapshot_interval_ms, self._bridge_publish_snapshot)


def _legacy_process_entry(
    project_root: str,
    command_queue: Any,
    snapshot_queue: Any,
    ready_event: Any,
    stop_event: Any,
    snapshot_interval_ms: int,
    initially_visible: bool,
) -> None:
    """Spawn target.  All Tk construction and access lives in this process."""

    root = str(Path(project_root).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    os.chdir(root)
    try:
        from terminal import GoldenBullTerminal

        class BridgedGoldenBullTerminal(_LegacyBridgeMixin, GoldenBullTerminal):
            pass

        app = BridgedGoldenBullTerminal(
            command_queue,
            snapshot_queue,
            stop_event,
            snapshot_interval_ms=snapshot_interval_ms,
            initially_visible=initially_visible,
        )
        ready_event.set()
        app.mainloop()
    except BaseException as exc:
        _put_latest(
            snapshot_queue,
            {
                "version": PROTOCOL_VERSION,
                "type": "legacy_terminal_snapshot",
                "revision": 0,
                "captured_at": dt.datetime.now().isoformat(timespec="milliseconds"),
                "lifecycle": "fatal",
                "status": "error",
                "error": {
                    "file": __file__,
                    "folder": "",
                    "message": f"{type(exc).__name__}: {exc}",
                    "log_path": "",
                },
            },
        )
        ready_event.set()
        raise
    finally:
        stop_event.set()


class LegacyBridgeController:
    """Parent-side lifecycle and IPC facade for the legacy scheduler process.

    On Windows, call :meth:`start` below an ``if __name__ == '__main__'`` guard.
    ``stop()`` asks the legacy window to run its normal cleanup path and does
    not force-kill by default, preventing accidental orphaning of task trees.
    """

    def __init__(
        self,
        project_root: str | os.PathLike[str],
        *,
        snapshot_interval_ms: int = DEFAULT_SNAPSHOT_INTERVAL_MS,
        initially_visible: bool = False,
        command_queue_size: int = DEFAULT_COMMAND_QUEUE_SIZE,
        snapshot_queue_size: int = DEFAULT_SNAPSHOT_QUEUE_SIZE,
        context: str = "spawn",
    ) -> None:
        self.project_root = str(Path(project_root).resolve())
        self.snapshot_interval_ms = max(150, int(snapshot_interval_ms))
        self.initially_visible = bool(initially_visible)
        self._context = mp.get_context(context)
        self.command_queue = self._context.Queue(maxsize=max(4, int(command_queue_size)))
        self.snapshot_queue = self._context.Queue(maxsize=max(2, int(snapshot_queue_size)))
        self.ready_event = self._context.Event()
        self.stop_event = self._context.Event()
        self.process: mp.Process | None = None
        self._send_lock = threading.Lock()

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process else None

    def is_running(self) -> bool:
        return bool(self.process and self.process.is_alive())

    def start(self, *, wait: bool = True, timeout: float = 25.0) -> "LegacyBridgeController":
        if self.is_running():
            return self
        if self.process is not None:
            raise RuntimeError("桥接进程已经结束；请创建新的 LegacyBridgeController。")
        self.process = self._context.Process(
            name="GoldenBullLegacyBridge",
            target=_legacy_process_entry,
            args=(
                self.project_root,
                self.command_queue,
                self.snapshot_queue,
                self.ready_event,
                self.stop_event,
                self.snapshot_interval_ms,
                self.initially_visible,
            ),
            daemon=False,
        )
        self.process.start()
        if wait and not self.ready_event.wait(max(0.1, float(timeout))):
            raise TimeoutError("等待旧版 Terminal 桥接进程启动超时。")
        if wait and self.process.exitcode is not None:
            snapshot = self.get_snapshot(timeout=0.2)
            message = ((snapshot or {}).get("error") or {}).get("message") or f"退出码 {self.process.exitcode}"
            raise RuntimeError(f"旧版 Terminal 桥接进程启动失败：{message}")
        return self

    def send(self, action: str, payload: dict[str, Any] | None = None, *, timeout: float = 1.0) -> str:
        if not self.is_running():
            raise RuntimeError("旧版 Terminal 桥接进程尚未运行。")
        request_id = uuid.uuid4().hex
        command = _json_payload(
            {
                "version": PROTOCOL_VERSION,
                "request_id": request_id,
                "action": str(action or ""),
                "payload": payload or {},
            }
        )
        with self._send_lock:
            self.command_queue.put(command, timeout=max(0.05, float(timeout)))
        return request_id

    def activate(self, workspace: dict[str, Any] | None = None, *, show: bool = True, mount: bool = False) -> str:
        payload = dict(workspace or {})
        payload.update({"show": bool(show), "mount": bool(mount)})
        return self.send("activate", payload)

    def mount(self, workspace: dict[str, Any]) -> str:
        return self.send("mount", dict(workspace))

    def start_run(self, workspace: dict[str, Any] | None = None, selected_orders: list[int] | None = None) -> str:
        payload = dict(workspace or {})
        if selected_orders is not None:
            payload["selected_orders"] = list(selected_orders)
        return self.send("start", payload)

    def run_manual_code(self, workspace: dict[str, Any], code_id: str) -> str:
        payload = dict(workspace or {})
        payload["code_id"] = str(code_id or "")
        return self.send("run_manual_code", payload)

    def open_file_structure(self, workspace: dict[str, Any]) -> str:
        return self.send("open_file_structure", dict(workspace or {}))

    def open_config_editor(self, workspace: dict[str, Any]) -> str:
        return self.send("open_config_editor", dict(workspace or {}))

    def open_resource_settings(self, workspace: dict[str, Any]) -> str:
        return self.send("open_resource_settings", dict(workspace or {}))

    def initialize_award_workspace(self, workspace: dict[str, Any]) -> str:
        return self.send("initialize_award_workspace", dict(workspace or {}))

    def pause(self, workspace: dict[str, Any] | None = None, *, confirmed: bool = False) -> str:
        payload = dict(workspace or {})
        payload["confirmed"] = bool(confirmed)
        return self.send("pause", payload)

    def open_legacy_ui(self) -> str:
        return self.send("open_legacy_ui")

    def get_snapshot(self, *, timeout: float = 0.0, latest: bool = True) -> dict[str, Any] | None:
        try:
            if timeout and timeout > 0:
                snapshot = self.snapshot_queue.get(timeout=float(timeout))
            else:
                snapshot = self.snapshot_queue.get_nowait()
        except queue.Empty:
            return None
        if latest:
            while True:
                try:
                    snapshot = self.snapshot_queue.get_nowait()
                except queue.Empty:
                    break
        return snapshot if isinstance(snapshot, dict) else None

    def wait_for_command(self, request_id: str, *, timeout: float = 8.0) -> dict[str, Any] | None:
        deadline = time.monotonic() + max(0.0, float(timeout))
        latest: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            remaining = max(0.01, deadline - time.monotonic())
            snapshot = self.get_snapshot(timeout=min(0.25, remaining), latest=False)
            if snapshot is None:
                if not self.is_running():
                    return latest
                continue
            latest = snapshot
            if str((snapshot.get("last_command") or {}).get("request_id") or "") == request_id:
                return snapshot
        return latest

    def stop(self, *, timeout: float = 12.0, force: bool = False) -> bool:
        process = self.process
        if process is None:
            return True
        if process.is_alive():
            try:
                self.send("shutdown", {"confirmed": True}, timeout=0.5)
            except (RuntimeError, queue.Full, OSError):
                self.stop_event.set()
            process.join(max(0.1, float(timeout)))
        if process.is_alive() and force:
            # Explicit opt-in only.  Normal shutdown is preferred because the
            # legacy on_app_close path also cleans up its child processes.
            process.terminate()
            process.join(3.0)
        return not process.is_alive()

    def close_queues(self) -> None:
        if self.is_running():
            raise RuntimeError("桥接进程仍在运行，不能关闭 IPC 队列。")
        for ipc_queue in (self.command_queue, self.snapshot_queue):
            try:
                ipc_queue.close()
                ipc_queue.join_thread()
            except (OSError, ValueError):
                pass

    def __enter__(self) -> "LegacyBridgeController":
        return self.start()

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.stop()


__all__ = [
    "DEFAULT_COMMAND_QUEUE_SIZE",
    "DEFAULT_SNAPSHOT_INTERVAL_MS",
    "DEFAULT_SNAPSHOT_QUEUE_SIZE",
    "LegacyBridgeController",
    "PROTOCOL_VERSION",
]
