from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
import hashlib
import datetime as dt
import time
from pathlib import Path
from typing import Any

from award_config import (
    get_award_config_file,
    get_award_config_label,
    get_award_folder,
    get_award_labels,
)

from .state_reader import TerminalStateReader


LOADED_WORKSPACES_SCHEMA_VERSION = 1
MODERN_SESSION_ENV = "GOLDEN_BULL_MODERN_SESSION_ID"


class TerminalBridge:
    """Narrow bridge between the HTML shell and the existing Terminal.

    Scheduling remains in the legacy kernel.  The HTML shell only adapts its
    commands and owns lightweight UI concerns such as resource pickers.
    """

    def __init__(self, project_root: str | os.PathLike[str], mode: str = "main", workspace_id: str = ""):
        self.project_root = Path(project_root).resolve()
        self.mode = mode
        self.reader = TerminalStateReader(self.project_root)
        explicit_workspace = self.reader.get_workspace(workspace_id) if workspace_id else None
        self._selected_workspace_id = str((explicit_workspace or {}).get("id") or "")
        self._selected_attempt_id = ""
        self._legacy_process: subprocess.Popen[Any] | None = None
        self._floating_process: subprocess.Popen[Any] | None = None
        self._lock = threading.RLock()
        self._selected_orders: set[int] = set()
        self._selected_orders_by_workspace: dict[str, set[int]] = {}
        self._legacy_controller: Any = None
        self._legacy_snapshot: dict[str, Any] | None = None
        self._legacy_bridge_error = ""
        self._log_streams: dict[tuple[str, str], dict[str, Any]] = {}
        self._window: Any = None
        self._selection_context = self.reader.read_sidebar_selection()
        self._loaded_workspace_ids: set[str] = set()
        self._loaded_revision = 0
        self._live_workspace_summaries: dict[str, dict[str, Any]] = {}
        self._shared_workspace_summaries: dict[str, dict[str, Any]] = {}
        self._last_shared_write_at = 0.0
        root_digest = hashlib.sha1(os.path.normcase(str(self.project_root)).encode("utf-8")).hexdigest()[:12]
        self._session_state_path = Path(tempfile.gettempdir()) / "golden_bull_modern_terminal" / f"{root_digest}.json"
        inherited_session = str(os.environ.get(MODERN_SESSION_ENV) or "").strip()
        self._session_id = inherited_session if mode == "floating" and inherited_session else uuid.uuid4().hex
        if mode == "floating":
            self._refresh_shared_loaded_state(require_session=bool(inherited_session))

    def attach_window(self, window: Any) -> None:
        self._window = window

    def _read_shared_loaded_state(self) -> dict[str, Any]:
        try:
            with self._session_state_path.open("r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
        except (OSError, ValueError, TypeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _refresh_shared_loaded_state(self, *, require_session: bool = True) -> None:
        if self.mode != "floating":
            return
        payload = self._read_shared_loaded_state()
        if int(payload.get("schema_version") or 0) != LOADED_WORKSPACES_SCHEMA_VERSION:
            return
        session_id = str(payload.get("session_id") or "")
        if require_session and session_id != self._session_id:
            return
        owner_pid = payload.get("owner_pid")
        if not self.reader._is_pid_running(owner_pid):
            return
        if not self._session_id or not require_session:
            self._session_id = session_id or self._session_id
        valid_ids = {
            str(workspace.get("id") or "")
            for workspace_id in payload.get("loaded_workspace_ids") or []
            if (workspace := self.reader.get_workspace(str(workspace_id or "")))
        }
        self._loaded_workspace_ids = {value for value in valid_ids if value}
        summaries = payload.get("workspace_summaries") or []
        self._shared_workspace_summaries = {
            str(item.get("id") or ""): dict(item)
            for item in summaries
            if isinstance(item, dict) and str(item.get("id") or "") in self._loaded_workspace_ids
        }
        self._loaded_revision = max(self._loaded_revision, int(payload.get("revision") or 0))

    def _write_shared_loaded_state(self, *, force: bool = True) -> None:
        if self.mode == "floating":
            return
        now = time.monotonic()
        if not force and now - self._last_shared_write_at < 0.35:
            return
        payload = {
            "schema_version": LOADED_WORKSPACES_SCHEMA_VERSION,
            "session_id": self._session_id,
            "revision": self._loaded_revision,
            "owner_pid": os.getpid(),
            "active_workspace_id": self._selected_workspace_id,
            "loaded_workspace_ids": sorted(self._loaded_workspace_ids),
            "workspace_summaries": [
                self._live_workspace_summaries[workspace_id]
                for workspace_id in sorted(self._loaded_workspace_ids)
                if workspace_id in self._live_workspace_summaries
            ],
            "updated_at": dt.datetime.now().isoformat(timespec="milliseconds"),
        }
        self._session_state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._session_state_path.with_name(
            f".{self._session_state_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._session_state_path)
            self._last_shared_write_at = now
        except OSError:
            pass
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _record_loaded_workspaces(
        self,
        workspace_ids: list[str] | set[str],
        *,
        validate: bool = True,
    ) -> None:
        before = set(self._loaded_workspace_ids)
        for workspace_id in workspace_ids:
            if validate:
                workspace = self.reader.get_workspace(str(workspace_id or ""))
                if workspace:
                    self._loaded_workspace_ids.add(str(workspace.get("id") or ""))
            elif workspace_id:
                self._loaded_workspace_ids.add(str(workspace_id))
        self._loaded_workspace_ids.discard("")
        if self._loaded_workspace_ids != before:
            self._loaded_revision += 1
            self._write_shared_loaded_state()

    def existing_legacy_pids(self) -> list[int]:
        target = (self.project_root / "terminal.py").resolve()
        found: list[int] = []
        try:
            import psutil

            for process in psutil.process_iter(["pid", "cmdline"]):
                try:
                    args = list(process.info.get("cmdline") or [])
                    script_args = [Path(value).resolve() for value in args[1:] if str(value).lower().endswith("terminal.py")]
                    if target in script_args:
                        found.append(int(process.info["pid"]))
                except (OSError, ValueError, TypeError, psutil.Error):
                    continue
        except ImportError:
            return []
        return sorted(set(found))

    @staticmethod
    def _focus_legacy_window() -> bool:
        try:
            import win32con
            import win32gui

            matches: list[int] = []

            def collect(hwnd: int, _extra: Any) -> None:
                if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == "金牛奖终端中控台":
                    matches.append(hwnd)

            win32gui.EnumWindows(collect, None)
            if not matches:
                return False
            hwnd = matches[-1]
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            return False

    def start_legacy_bridge(self) -> dict[str, Any]:
        if self.mode == "floating":
            return {"ok": False, "message": "悬浮窗不会重复启动调度内核。"}
        with self._lock:
            if self._legacy_controller and self._legacy_controller.is_running():
                return {"ok": True, "pid": self._legacy_controller.pid}
            existing = self.existing_legacy_pids()
            if existing:
                self._legacy_bridge_error = f"检测到现有 Terminal 进程 {existing}，为避免冲突已保持只读监视。"
                return {"ok": False, "existing": True, "pids": existing, "message": self._legacy_bridge_error}
            try:
                from .legacy_bridge import LegacyBridgeController

                controller = LegacyBridgeController(self.project_root, initially_visible=False)
                controller.start(wait=True)
                self._legacy_controller = controller
                self._legacy_snapshot = controller.get_snapshot(timeout=1.0)
                self._legacy_bridge_error = ""
                return {"ok": True, "pid": controller.pid}
            except Exception as exc:
                self._legacy_bridge_error = f"{type(exc).__name__}: {exc}"
                self._legacy_controller = None
                return {"ok": False, "message": self._legacy_bridge_error}

    def stop_legacy_bridge(self) -> bool:
        with self._lock:
            controller = self._legacy_controller
            self._legacy_controller = None
        if not controller:
            return True
        try:
            stopped = controller.stop()
            if stopped:
                controller.close_queues()
            return stopped
        except Exception:
            return False

    def _poll_legacy_snapshot(self) -> dict[str, Any] | None:
        controller = self._legacy_controller
        if controller and controller.is_running():
            snapshot = controller.get_snapshot(latest=True)
            if snapshot:
                self._legacy_snapshot = snapshot
        return self._legacy_snapshot

    def _selected_id(self) -> str:
        if self._selected_workspace_id and self.reader.get_workspace(self._selected_workspace_id):
            return self._selected_workspace_id
        self._selected_workspace_id = ""
        return self._selected_workspace_id

    def _legacy_workspace_payload(self, workspace_id: str = "") -> dict[str, Any]:
        workspace = self.reader.get_workspace(workspace_id or self._selected_id())
        if not workspace:
            raise ValueError("未找到对应工作区。")
        return {
            "workspace_root": workspace.get("workspace_root") or "",
            "award": workspace.get("award") or "",
            "workspace_name": workspace.get("name") or "",
            "year": self._workspace_year(workspace.get("name") or ""),
        }

    def _frontend_logs(
        self,
        raw_lines: list[Any],
        workspace_id: str,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Attach stable cursors so clearing the view survives full-tail polling."""
        messages = [str(item.get("message") if isinstance(item, dict) else item) for item in raw_lines]
        key = (workspace_id, session_id)
        with self._lock:
            previous = self._log_streams.get(key)
            generation = int((previous or {}).get("generation") or 1)
            previous_lines = list((previous or {}).get("lines") or [])
            previous_next = int((previous or {}).get("next_cursor") or 1)

            overlap = 0
            for size in range(min(len(previous_lines), len(messages)), 0, -1):
                if previous_lines[-size:] == messages[:size]:
                    overlap = size
                    break

            if previous and previous_lines and messages and overlap == 0:
                generation += 1
                start_cursor = 1
            elif previous:
                start_cursor = max(1, previous_next - overlap)
            else:
                start_cursor = 1

            next_cursor = start_cursor + len(messages)
            self._log_streams[key] = {
                "generation": generation,
                "lines": messages,
                "next_cursor": next_cursor,
            }

        stream_id = f"{workspace_id}:{session_id}:{generation}"
        result = []
        for index, text in enumerate(messages):
            lowered = text.lower()
            level = "error" if any(token in lowered for token in ("error", "exception", "报错", "失败")) else "info"
            result.append(
                {
                    "ts": "",
                    "level": level,
                    "source": "runtime",
                    "message": text,
                    "stream_id": stream_id,
                    "cursor": start_cursor + index,
                }
            )
        return result

    def _workspace_resources(self, workspace: dict[str, Any]) -> list[dict[str, Any]]:
        award = str(workspace.get("award") or "")
        year = self._workspace_year(workspace.get("name") or "")
        award_folder = get_award_folder(award)
        award_root = (self.project_root / award_folder).resolve() if award_folder else Path()
        config_path = award_root / "奖项资料配置.json" if award_folder else Path()
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.is_file() else {}
        except (OSError, ValueError, TypeError):
            payload = {}
        year_payload = ((payload.get("years") or {}).get(year) or {}) if isinstance(payload, dict) else {}
        dataset_path = str(year_payload.get("dataset_path") or "")
        rule_path = str(year_payload.get("rule_path") or "")
        config_file = get_award_config_file(award, project_root=str(self.project_root))
        return [
            {
                "title": "原始数据集",
                "description": "运行脚本通过 Terminal 读取的年度数据源目录",
                "path": dataset_path or "尚未指定",
                "status": "已连接" if dataset_path and Path(dataset_path).is_dir() else "未配置",
                "action": "select-dataset",
            },
            {
                "title": "评奖规则 / 方案文件",
                "description": "绑定供查看的年度规则文件；计算参数由 configs 单独管理",
                "path": rule_path or "尚未指定",
                "status": "已绑定" if rule_path and Path(rule_path).is_file() else "未配置",
                "action": "select-rule",
            },
            {
                "title": get_award_config_label(award) or "configs",
                "description": "当前奖项的年度计算参数配置",
                "path": str(config_file or "尚未接入配置文件"),
                "status": "可编辑" if config_file and Path(config_file).is_file() else "未接入",
                "action": "open-configs",
            },
        ]

    def _resource_context(self, workspace_id: str) -> tuple[dict[str, Any], str, str, Path, dict[str, Any]]:
        workspace = self.reader.get_workspace(workspace_id or self._selected_id())
        if not workspace:
            raise ValueError("未找到对应工作区。")
        award = str(workspace.get("award") or "")
        year = self._workspace_year(workspace.get("name") or "")
        award_folder = get_award_folder(award)
        if not award_folder or not year:
            raise ValueError("当前工作区缺少奖项或年份信息。")
        config_path = (self.project_root / award_folder / "奖项资料配置.json").resolve()
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.is_file() else {}
        except (OSError, ValueError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return workspace, award, year, config_path, payload

    def get_resource_config(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            workspace, award, year, config_path, config = self._resource_context(
                str((payload or {}).get("workspace_id") or self._selected_id())
            )
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}
        year_payload = ((config.get("years") or {}).get(year) or {})
        return {
            "ok": True,
            "workspace_id": workspace.get("id") or "",
            "award": award,
            "year": year,
            "dataset_path": str(year_payload.get("dataset_path") or ""),
            "rule_path": str(year_payload.get("rule_path") or ""),
            "config_path": str(config_path),
        }

    def choose_resource(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        kind = str(payload.get("kind") or "")
        if kind not in {"dataset", "rule"}:
            return {"ok": False, "message": "未知资源类型。"}
        try:
            workspace, award, year, config_path, config = self._resource_context(
                str(payload.get("workspace_id") or self._selected_id())
            )
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}
        if self._window is None:
            return {"ok": False, "message": "当前窗口无法打开系统选择器。"}

        years = config.get("years") if isinstance(config.get("years"), dict) else {}
        year_payload = years.get(year) if isinstance(years.get(year), dict) else {}
        key = "dataset_path" if kind == "dataset" else "rule_path"
        current = str(year_payload.get(key) or "")
        award_root = config_path.parent
        initial_dir = Path(current) if kind == "dataset" else Path(current).parent
        if not initial_dir.is_dir():
            initial_dir = award_root
        try:
            import webview

            dialog_types = getattr(webview, "FileDialog", None)
            folder_dialog = dialog_types.FOLDER if dialog_types else webview.FOLDER_DIALOG
            open_dialog = dialog_types.OPEN if dialog_types else webview.OPEN_DIALOG
            if kind == "dataset":
                selected = self._window.create_file_dialog(folder_dialog, directory=str(initial_dir))
            else:
                selected = self._window.create_file_dialog(
                    open_dialog,
                    directory=str(initial_dir),
                    file_types=("规则与方案文件 (*.docx;*.doc;*.pdf;*.md;*.txt)", "全部文件 (*.*)"),
                )
        except Exception as exc:
            return {"ok": False, "message": f"打开系统选择器失败：{exc}"}
        if not selected:
            return {"ok": False, "cancelled": True, "message": "已取消选择。"}

        selected_value = selected[0] if isinstance(selected, (list, tuple)) else selected
        selected_path = Path(str(selected_value)).resolve()
        valid = selected_path.is_dir() if kind == "dataset" else selected_path.is_file()
        if not valid:
            return {"ok": False, "message": "所选数据集必须是现存目录。" if kind == "dataset" else "所选规则必须是现存文件。"}

        # The dialog can stay open for a long time.  Reload immediately before
        # saving so another editor's changes are merged instead of overwritten.
        if config_path.is_file():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError, TypeError) as exc:
                return {"ok": False, "message": f"奖项资料配置无法读取，已停止保存以保护原文件：{exc}"}
            if not isinstance(config, dict):
                return {"ok": False, "message": "奖项资料配置格式错误，已停止保存以保护原文件。"}
        else:
            config = {}
        years = config.get("years")
        if not isinstance(years, dict):
            years = {}
        year_payload = years.get(year)
        if not isinstance(year_payload, dict):
            year_payload = {}
        year_payload[key] = str(selected_path)
        year_payload["updated_at"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")
        years[year] = year_payload
        config.update({"version": 1, "updated_at": year_payload["updated_at"], "years": years})
        temp_path: Path | None = None
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=config_path.parent,
                prefix=f".{config_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                json.dump(config, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            os.replace(temp_path, config_path)
        except OSError as exc:
            return {"ok": False, "message": f"保存奖项资料配置失败：{exc}"}
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
        self._selected_workspace_id = str(workspace.get("id") or self._selected_workspace_id)
        updated_config = self.get_resource_config({"workspace_id": workspace.get("id") or ""})
        return {
            **updated_config,
            "completed": True,
            "resource_config": updated_config,
            "snapshot": self.get_state(),
            "message": "原始数据集已更新。" if kind == "dataset" else "评奖规则 / 方案文件已更新。",
        }

    def _match_discovered_workspace(
        self,
        raw_workspace: dict[str, Any],
        discovered: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        discovered = discovered if discovered is not None else self.reader.discover_workspaces()
        raw_root = str(raw_workspace.get("workspace_root") or raw_workspace.get("path") or "").strip()
        normal_root = os.path.normcase(os.path.abspath(raw_root)) if raw_root else ""
        raw_ids = {
            str(raw_workspace.get("id") or ""),
            str(raw_workspace.get("workspace_id") or ""),
            str(raw_workspace.get("legacy_workspace_id") or ""),
        }
        raw_ids.discard("")
        for workspace in discovered:
            candidate_root = os.path.normcase(os.path.abspath(str(workspace.get("workspace_root") or "")))
            if normal_root and candidate_root == normal_root:
                return workspace
            candidate_ids = {
                str(workspace.get("id") or ""),
                str(workspace.get("legacy_workspace_id") or ""),
            }
            if raw_ids & candidate_ids:
                return workspace
        return None

    def _project_legacy_workspaces(self, legacy: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(legacy, dict):
            return []
        discovered = self.reader.discover_workspaces()
        loaded_state = legacy.get("loaded_workspaces_state")
        raw_items = loaded_state.get("items") if isinstance(loaded_state, dict) else legacy.get("workspaces")
        raw_items = list(raw_items or [])
        if not raw_items and isinstance(legacy.get("workspace"), dict) and legacy.get("workspace"):
            raw_items = [legacy]

        projected: list[dict[str, Any]] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            raw_workspace = raw_item.get("workspace") if isinstance(raw_item.get("workspace"), dict) else raw_item
            matched = self._match_discovered_workspace(raw_workspace, discovered)
            if not matched:
                continue
            legacy_workspace_id = str(
                raw_workspace.get("id")
                or raw_workspace.get("workspace_id")
                or matched.get("legacy_workspace_id")
                or ""
            )
            normalized_workspace = {
                **matched,
                **raw_workspace,
                "id": str(matched.get("id") or ""),
                "legacy_workspace_id": legacy_workspace_id,
                "year": self._workspace_year(matched.get("name") or raw_workspace.get("name")),
                "path": str(matched.get("workspace_root") or raw_workspace.get("workspace_root") or ""),
            }
            projected.append({**raw_item, "workspace": normalized_workspace})
        self._live_workspace_summaries = {
            str((item.get("workspace") or {}).get("id") or ""): self._legacy_workspace_summary(item)
            for item in projected
            if str((item.get("workspace") or {}).get("id") or "")
        }
        self._record_loaded_workspaces(
            set(self._live_workspace_summaries),
            validate=False,
        )
        self._write_shared_loaded_state(force=False)
        return projected

    def _disk_workspace_summary(self, workspace: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.reader.snapshot(str(workspace.get("id") or ""), log_limit=1)
        timers = snapshot.get("timers") or {}
        progress = snapshot.get("progress") or {}
        current_step = snapshot.get("current_step") or {}
        status = str(snapshot.get("status") or workspace.get("latest_status") or "idle")
        if status == "stale":
            status = "cancelled"
        return {
            **workspace,
            "year": self._workspace_year(workspace.get("name")),
            "path": str(workspace.get("workspace_root") or ""),
            "status": status,
            "running": status == "running",
            "session_id": str(snapshot.get("session_id") or ""),
            "current_step": current_step,
            "progress": progress,
            "timers": timers,
            "latest_log": str((snapshot.get("logs") or [""])[-1]),
            "processes": {
                "main_running": status == "running" and current_step.get("axis") == "main",
                "async_running": False,
                "async_pids": [],
            },
            "runtime_source": "disk",
        }

    def _legacy_workspace_summary(self, item: dict[str, Any]) -> dict[str, Any]:
        workspace = item.get("workspace") or {}
        status = str(item.get("status") or "idle")
        processes = item.get("processes") or {}
        running = bool(
            status == "running"
            or processes.get("main_running")
            or processes.get("async_running")
        )
        return {
            **workspace,
            "status": status,
            "running": running,
            "session_id": str(item.get("session_id") or ""),
            "current_step": item.get("current_step") or {},
            "progress": item.get("progress") or {},
            "timers": item.get("timers") or {},
            "latest_log": str(item.get("latest_log") or ""),
            "processes": processes,
            "runtime_source": "legacy_bridge",
        }

    def _loaded_workspaces_contract(
        self,
        legacy: dict[str, Any] | None = None,
        *,
        projected: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if self.mode == "floating":
            self._refresh_shared_loaded_state(require_session=bool(os.environ.get(MODERN_SESSION_ENV)))
        projected = projected if projected is not None else self._project_legacy_workspaces(legacy)
        live_by_id = {
            str((item.get("workspace") or {}).get("id") or ""): self._legacy_workspace_summary(item)
            for item in projected
        }
        if self.mode == "floating":
            live_by_id = {**self._shared_workspace_summaries, **live_by_id}
        discovered_by_id = {
            str(workspace.get("id") or ""): workspace
            for workspace in self.reader.discover_workspaces()
        }
        summaries: list[dict[str, Any]] = []
        for workspace_id in self._loaded_workspace_ids:
            workspace = discovered_by_id.get(workspace_id)
            if not workspace:
                continue
            summary = live_by_id.get(workspace_id) or self._disk_workspace_summary(workspace)
            if workspace_id in self._shared_workspace_summaries and workspace_id not in {
                str((item.get("workspace") or {}).get("id") or "") for item in projected
            }:
                summary = {**summary, "runtime_source": "shared_legacy_bridge"}
            running = bool(summary.get("running"))
            summaries.append(
                {
                    **summary,
                    "loaded": True,
                    "active": workspace_id == self._selected_id(),
                    "can_start": not running,
                    "workspace_lock": {
                        "scope": "workspace",
                        "held": running,
                        "reason": "running" if running else "available",
                    },
                }
            )
        summaries.sort(
            key=lambda item: (
                str(item.get("created_at") or ""),
                str(item.get("display_name") or item.get("name") or ""),
            ),
            reverse=True,
        )
        capabilities = (legacy or {}).get("capabilities") or {}
        connected = bool(self._legacy_controller and self._legacy_controller.is_running())
        parallel_available = bool(connected and capabilities.get("parallel_workspace_runs"))
        parallel_capability = {
            "supported": parallel_available,
            "scope": "different_workspaces",
            "same_workspace": False,
            "shared_resource_warning": (
                "旧内核按工作区互锁；不同工作区可并行，但共享数据文件或外部资源仍可能互相影响。"
                if parallel_available
                else "当前未连接可确认并行能力的旧调度内核。"
            ),
        }
        return {
            "schema_version": LOADED_WORKSPACES_SCHEMA_VERSION,
            "revision": self._loaded_revision,
            "session_id": self._session_id,
            "active_workspace_id": self._selected_id(),
            "items": summaries,
            "parallel": {
                "available": parallel_available,
                "source": "legacy_kernel" if parallel_available else "unavailable",
                "scope": "workspace",
                "same_workspace_interlock": True,
            },
            "parallel_capability": parallel_capability,
        }

    def _decorate_workspace_state(
        self,
        payload: dict[str, Any],
        legacy: dict[str, Any] | None = None,
        *,
        projected: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        loaded_state = self._loaded_workspaces_contract(legacy, projected=projected)
        payload["selection_context"] = dict(self._selection_context)
        payload["loaded_workspaces_state"] = loaded_state
        payload["loaded_workspaces"] = loaded_state["items"]
        payload["workspace_summaries"] = loaded_state["items"]
        payload["parallel_capability"] = loaded_state["parallel_capability"]
        payload["capabilities"] = {
            **(payload.get("capabilities") or {}),
            "parallel_workspace_runs": loaded_state["parallel"]["available"],
            "workspace_run_mutex": True,
        }
        return payload

    def get_bootstrap_state(self) -> dict[str, Any]:
        selected_id = self._selected_id()
        snapshot = self.reader.snapshot(selected_id) if selected_id else self.reader.empty_snapshot()
        result = {
            "app": {
                "title": "金牛奖 Terminal",
                "mode": self.mode,
                "theme": "mint-light",
                "project_root": str(self.project_root),
            },
            "awards": get_award_labels(),
            "workspaces": self.reader.discover_workspaces(),
            "selected_workspace_id": selected_id,
            "selection_context": dict(self._selection_context),
            "snapshot": snapshot,
            "capabilities": {
                "read_runtime_state": True,
                "timeline": True,
                "logs": True,
                "history": True,
                "floating_monitor": True,
                "legacy_scheduler": True,
                "native_scheduler_controls": False,
            },
        }
        loaded_state = self._loaded_workspaces_contract(self._poll_legacy_snapshot())
        result["loaded_workspaces_state"] = loaded_state
        result["loaded_workspaces"] = loaded_state["items"]
        result["workspace_summaries"] = loaded_state["items"]
        result["parallel_capability"] = loaded_state["parallel_capability"]
        result["capabilities"]["parallel_workspace_runs"] = loaded_state["parallel"]["available"]
        result["capabilities"]["workspace_run_mutex"] = True
        return result

    def _frontend_snapshot(self, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        if snapshot is None:
            selected_id = self._selected_id()
            snapshot = self.reader.snapshot(selected_id) if selected_id else self.reader.empty_snapshot()
        workspace = snapshot.get("workspace") or {}
        timers = snapshot.get("timers") or {}
        progress = snapshot.get("progress") or {}
        entries = list(snapshot.get("entries") or [])
        main_entries = [item for item in entries if item.get("axis") == "main"]
        async_entries = [item for item in entries if item.get("axis") == "async"]
        manifest_steps = list(snapshot.get("manifest_steps") or [])
        workspace_id = str(workspace.get("id") or "")
        cached_orders = self._selected_orders_by_workspace.get(workspace_id)
        if cached_orders is not None:
            selected_orders = set(cached_orders)
        elif manifest_steps:
            selected_orders = {
                int(value)
                for value in snapshot.get("configured_step_orders") or []
                if str(value).lstrip("-").isdigit()
            }
        else:
            selected_orders = {
                int(item.get("order")) for item in main_entries if item.get("order") is not None
            }

        starts = [str(item.get("started_at") or "") for item in entries if item.get("started_at")]
        timeline_origin = min(starts) if starts else ""
        try:
            origin_dt = __import__("datetime").datetime.fromisoformat(timeline_origin) if timeline_origin else None
        except ValueError:
            origin_dt = None

        timeline = []
        for item in entries:
            try:
                start_dt = __import__("datetime").datetime.fromisoformat(str(item.get("started_at") or ""))
                start_seconds = max(0.0, (start_dt - origin_dt).total_seconds()) if origin_dt else 0.0
            except ValueError:
                start_seconds = 0.0
            timeline.append(
                {
                    **item,
                    "start": start_seconds,
                    "duration": float(item.get("duration_seconds") or 0.0),
                }
            )

        log_lines = self._frontend_logs(
            list(snapshot.get("logs") or []),
            str(workspace.get("id") or ""),
            str(snapshot.get("session_id") or ""),
        )

        workspaces = []
        for item in self.reader.discover_workspaces():
            workspaces.append(
                {
                    **item,
                    "year": self._workspace_year(item.get("name", "")),
                    "path": item.get("workspace_root", ""),
                }
            )

        status = str(snapshot.get("status") or "idle")
        if status == "stale":
            status = "cancelled"
        records_by_path = {
            str(item.get("rel_path") or "").replace("\\", "/").lower(): item
            for item in main_entries
            if item.get("rel_path")
        }
        steps = []
        for item in manifest_steps or main_entries:
            raw_order = item.get("order")
            order = int(raw_order if raw_order is not None else len(steps) + 1)
            record = records_by_path.get(str(item.get("rel_path") or "").replace("\\", "/").lower(), {})
            steps.append(
                {
                    **item,
                    **(
                        {
                            "status": record.get("status"),
                            "duration_seconds": record.get("duration_seconds", 0.0),
                        }
                        if record
                        else {}
                    ),
                    "order": order,
                    "name": item.get("label") or f"步骤 {order}",
                    "path": item.get("rel_path") or "",
                    "selected": order in selected_orders,
                }
            )

        attempts = []
        for item in snapshot.get("history") or []:
            attempts.append(
                {
                    **item,
                    "id": item.get("session_id") or "",
                    "duration_seconds": float(item.get("main_timer_seconds") or 0.0),
                    "main_steps": 0,
                    "async_steps": 0,
                    "archived": item.get("status") != "running",
                }
            )

        workspace_root = str(workspace.get("workspace_root") or "")
        current = snapshot.get("current_step") or {}
        result = {
            "schema_version": snapshot.get("schema_version", 1),
            "revision": snapshot.get("revision", 0),
            "mode": self.mode,
            "updated_at": snapshot.get("captured_at") or snapshot.get("refreshed_at"),
            "awards": get_award_labels(),
            "years": sorted({self._workspace_year(item.get("name", "")) for item in workspaces if self._workspace_year(item.get("name", ""))}, reverse=True),
            "workspaces": workspaces,
            "active_workspace_id": workspace.get("id") or "",
            "workspace": {
                **workspace,
                "year": self._workspace_year(workspace.get("name", "")),
                "path": workspace_root,
            },
            "run": {
                "status": status,
                "attempt_id": snapshot.get("session_id") or "",
                "attempt_name": (snapshot.get("attempt") or {}).get("attempt_name") or "本轮尝试",
                "total_elapsed_seconds": float(timers.get("attempt_seconds") or 0.0),
                "main_elapsed_seconds": float(timers.get("main_seconds") or 0.0),
                "current_step_elapsed_seconds": float(timers.get("current_step_seconds") or 0.0),
                "completed_steps": int(progress.get("done_total") or 0),
                "total_steps": int(progress.get("selected_total") or 0),
                "async_running": len([item for item in async_entries if item.get("status") == "running"]),
                "async_total": len(async_entries),
                "timer_running": {
                    "total": status == "running",
                    "main": any(item.get("status") == "running" for item in main_entries),
                    "current_step": bool(current and current.get("axis") == "main" and current.get("status") == "running"),
                    "async": any(item.get("status") == "running" for item in async_entries),
                },
            },
            "steps": steps,
            "current_step": current,
            "timeline": timeline,
            "logs": log_lines,
            "files": {"output": [], "processed": [], "important": [], "database": []},
            "resources": self._workspace_resources(workspace),
            "results": [],
            "attempts": attempts,
            "manual_codes": [],
            "error": snapshot.get("error") or {},
            "bridge": {
                "connected": bool(self._legacy_controller and self._legacy_controller.is_running()),
                "error": self._legacy_bridge_error,
            },
        }
        return self._decorate_workspace_state(result)

    def _frontend_from_legacy(self, legacy: dict[str, Any]) -> dict[str, Any]:
        projected_workspaces = self._project_legacy_workspaces(legacy)
        selected_id = self._selected_id()
        target_item = next(
            (
                item
                for item in projected_workspaces
                if str((item.get("workspace") or {}).get("id") or "") == selected_id
            ),
            None,
        )
        if target_item is None:
            active_tab_id = str(legacy.get("active_tab_id") or "")
            target_item = next(
                (item for item in projected_workspaces if str(item.get("tab_id") or "") == active_tab_id),
                projected_workspaces[0] if projected_workspaces else None,
            )
        if target_item:
            legacy = {
                **legacy,
                **{
                    key: value
                    for key, value in target_item.items()
                    if key not in {"tab_id"}
                },
            }
            workspace = target_item.get("workspace") or {}
            if not selected_id:
                self._selected_workspace_id = str(workspace.get("id") or "")
                self._loaded_revision += 1
                self._write_shared_loaded_state()
        else:
            workspace = legacy.get("workspace") or {}
        if not workspace:
            return self._frontend_snapshot()
        matched_workspace = self._match_discovered_workspace(workspace)
        legacy_workspace_id = str(workspace.get("legacy_workspace_id") or workspace.get("id") or "")
        stable_workspace_id = str((matched_workspace or {}).get("id") or workspace.get("id") or "")
        workspace = {
            **(matched_workspace or {}),
            **workspace,
            "id": stable_workspace_id,
            "legacy_workspace_id": legacy_workspace_id,
        }
        timers = legacy.get("timers") or {}
        progress = legacy.get("progress") or {}
        execution_selected = list(legacy.get("selected") or [])
        all_steps = list(legacy.get("steps") or execution_selected)
        raw_timeline = list(legacy.get("timeline") or [])

        starts = [str(item.get("started_at") or "") for item in raw_timeline if item.get("started_at")]
        origin_text = min(starts) if starts else ""
        try:
            import datetime

            origin = datetime.datetime.fromisoformat(origin_text) if origin_text else None
        except ValueError:
            origin = None
        timeline = []
        for item in raw_timeline:
            try:
                start_dt = datetime.datetime.fromisoformat(str(item.get("started_at") or ""))
                start = max(0.0, (start_dt - origin).total_seconds()) if origin else 0.0
            except (ValueError, UnboundLocalError):
                start = 0.0
            timeline.append({**item, "start": start, "duration": float(item.get("duration_seconds") or 0.0)})

        configured_raw = legacy.get("selected_orders")
        if isinstance(configured_raw, list):
            configured_orders = {
                int(value) for value in configured_raw if str(value).lstrip("-").isdigit()
            }
        else:
            configured_orders = {
                int(item.get("order"))
                for item in execution_selected
                if item.get("order") is not None
            }
        cached_orders = self._selected_orders_by_workspace.get(stable_workspace_id)
        if cached_orders is not None:
            configured_orders = set(cached_orders)

        steps = []
        for index, item in enumerate(all_steps, start=1):
            order = item.get("order") if item.get("order") is not None else index
            raw_state = str(item.get("state") or "pending")
            status = {"success": "done", "error": "failed", "pending": "waiting"}.get(raw_state, raw_state)
            duration = next(
                (float(row.get("duration_seconds") or 0.0) for row in raw_timeline if row.get("rel_path") == item.get("rel_path")),
                0.0,
            )
            steps.append(
                {
                    **item,
                    "order": order,
                    "name": item.get("label") or item.get("script_name") or f"步骤 {order}",
                    "path": item.get("rel_path") or "",
                    "status": status,
                    "selected": order in configured_orders,
                    "duration_seconds": duration,
                }
            )

        status = str(legacy.get("status") or "idle")
        if status == "paused":
            status = "cancelled"
        current_workspace_id = stable_workspace_id
        logs = self._frontend_logs(
            list(legacy.get("logs") or []),
            current_workspace_id,
            str(legacy.get("session_id") or ""),
        )
        disk_snapshot = self._frontend_snapshot(self.reader.snapshot(current_workspace_id)) if current_workspace_id else self._frontend_snapshot()
        result = {
            **disk_snapshot,
            "revision": legacy.get("revision", 0),
            "updated_at": legacy.get("captured_at") or "",
            "active_workspace_id": current_workspace_id,
            "workspace": {**workspace, "path": workspace.get("workspace_root") or ""},
            "run": {
                "status": status,
                "attempt_id": legacy.get("session_id") or "",
                "attempt_name": "本轮尝试",
                "total_elapsed_seconds": float(timers.get("attempt_seconds") or 0.0),
                "main_elapsed_seconds": float(timers.get("main_seconds") or 0.0),
                "current_step_elapsed_seconds": float(timers.get("current_step_seconds") or 0.0),
                "completed_steps": int(progress.get("finished_total") or 0),
                "total_steps": int(progress.get("selected_total") or len(execution_selected)),
                "async_running": 1 if (legacy.get("processes") or {}).get("async_running") else 0,
                "async_total": len([item for item in timeline if item.get("axis") == "async"]),
                "timer_running": {
                    "total": status == "running",
                    "main": bool((legacy.get("processes") or {}).get("main_running")),
                    "current_step": bool(
                        (legacy.get("processes") or {}).get("main_running")
                        and (legacy.get("current_step") or {})
                    ),
                    "async": bool((legacy.get("processes") or {}).get("async_running")),
                },
            },
            "steps": steps,
            "current_step": legacy.get("current_step") or {},
            "timeline": timeline,
            "logs": logs or disk_snapshot.get("logs", []),
            "manual_codes": list(legacy.get("manual_codes") or []),
            "error": legacy.get("error") or {},
            "bridge": {
                "connected": True,
                "pid": (legacy.get("legacy") or {}).get("pid"),
                "last_command": legacy.get("last_command") or {},
            },
        }
        return self._decorate_workspace_state(result, legacy, projected=projected_workspaces)

    @staticmethod
    def _workspace_year(name: Any) -> str:
        import re

        match = re.search(r"(?:19|20)\d{2}", str(name or ""))
        return match.group(0) if match else ""

    # API names below intentionally match the dependency-free HTML shell.
    def bootstrap(self) -> dict[str, Any]:
        if self._selected_attempt_id:
            snapshot = self._frontend_snapshot(
                self.reader.snapshot(self._selected_id(), attempt_id=self._selected_attempt_id)
            )
            snapshot["bridge"] = {
                **(snapshot.get("bridge") or {}),
                "connected": bool(self._legacy_controller and self._legacy_controller.is_running()),
                "error": self._legacy_bridge_error,
            }
            return snapshot
        legacy = self._poll_legacy_snapshot()
        has_loaded = bool(
            legacy
            and (
                legacy.get("workspace")
                or legacy.get("workspaces")
                or (legacy.get("loaded_workspaces_state") or {}).get("items")
            )
        )
        snapshot = self._frontend_from_legacy(legacy) if has_loaded else self._frontend_snapshot()
        snapshot["bridge"] = {
            **(snapshot.get("bridge") or {}),
            "connected": bool(self._legacy_controller and self._legacy_controller.is_running()),
            "error": self._legacy_bridge_error,
        }
        return snapshot

    def get_state(self) -> dict[str, Any]:
        if self._selected_attempt_id:
            return self._frontend_snapshot(
                self.reader.snapshot(self._selected_id(), attempt_id=self._selected_attempt_id)
            )
        legacy = self._poll_legacy_snapshot()
        has_loaded = bool(
            legacy
            and (
                legacy.get("workspace")
                or legacy.get("workspaces")
                or (legacy.get("loaded_workspaces_state") or {}).get("items")
            )
        )
        return self._frontend_from_legacy(legacy) if has_loaded else self._frontend_snapshot()

    def refresh_state(self, workspace_id: str = "") -> dict[str, Any]:
        if workspace_id:
            workspace = self.reader.get_workspace(workspace_id)
            self._selected_workspace_id = str((workspace or {}).get("id") or "")
        selected_id = self._selected_id()
        return self.reader.snapshot(selected_id) if selected_id else self.reader.empty_snapshot()

    def select_workspace(self, workspace_id: str) -> dict[str, Any]:
        workspace = self.reader.get_workspace(workspace_id)
        if not workspace:
            return {"ok": False, "message": "未找到对应工作区。"}
        self._selected_workspace_id = str(workspace.get("id") or "")
        self._write_shared_loaded_state()
        return {"ok": True, "snapshot": self.reader.snapshot(self._selected_workspace_id)}

    def set_active_workspace(self, payload: dict[str, Any]) -> dict[str, Any]:
        workspace_id = str((payload or {}).get("workspace_id") or "")
        previous_workspace_id = self._selected_workspace_id
        result = self.select_workspace(workspace_id)
        if not result.get("ok"):
            return result
        workspace_id = self._selected_workspace_id
        self._selected_attempt_id = ""
        controller = self._legacy_controller
        if controller and controller.is_running():
            try:
                self._project_legacy_workspaces(self._poll_legacy_snapshot())
                workspace_payload = self._legacy_workspace_payload(workspace_id)
                if workspace_id in self._loaded_workspace_ids and hasattr(controller, "activate"):
                    request_id = controller.activate(workspace_payload, show=False, mount=False)
                else:
                    request_id = controller.mount(workspace_payload)
                legacy = controller.wait_for_command(request_id)
                if legacy:
                    self._legacy_snapshot = legacy
                    if (legacy.get("last_command") or {}).get("ok"):
                        self._project_legacy_workspaces(legacy)
                        self._record_loaded_workspaces({workspace_id})
                        self._selection_context = self.reader.persist_sidebar_selection(
                            self.reader.get_workspace(workspace_id) or {}
                        )
                        self._write_shared_loaded_state()
                        snapshot = self._frontend_from_legacy(legacy)
                        snapshot["load_result"] = {
                            "ok": True,
                            "loaded": True,
                            "workspace_id": workspace_id,
                        }
                        return snapshot
                    self._legacy_bridge_error = str((legacy.get("last_command") or {}).get("message") or "")
                    self._selected_workspace_id = previous_workspace_id
                    self._write_shared_loaded_state()
                    return {"ok": False, "message": self._legacy_bridge_error or "旧调度内核未能挂载工作区。"}
                raise TimeoutError("等待旧调度内核挂载结果超时。")
            except Exception as exc:
                self._legacy_bridge_error = f"{type(exc).__name__}: {exc}"
                self._selected_workspace_id = previous_workspace_id
                self._write_shared_loaded_state()
                return {"ok": False, "message": f"挂载工作区失败：{exc}"}
        self._selection_context = self.reader.persist_sidebar_selection(
            self.reader.get_workspace(workspace_id) or {}
        )
        self._write_shared_loaded_state()
        snapshot = self._frontend_snapshot(result["snapshot"])
        snapshot["load_result"] = {
            "ok": True,
            "loaded": False,
            "workspace_id": workspace_id,
            "reason": "legacy_bridge_unavailable",
        }
        return snapshot

    def set_workspace_filter(self, payload: dict[str, Any]) -> dict[str, Any]:
        award = str((payload or {}).get("award") or "")
        year = str((payload or {}).get("year") or "")
        workspaces = self.reader.discover_workspaces()
        filtered = [
            item
            for item in workspaces
            if (not award or str(item.get("award") or "") == award)
            and (not year or self._workspace_year(item.get("name") or "") == year)
        ]
        return {
            "ok": True,
            "award": award,
            "year": year,
            "workspaces": filtered,
            "latest_workspace_id": str((filtered[0] if filtered else {}).get("id") or ""),
            "latest_basis": "created_at",
        }

    def set_selected_steps(self, payload: dict[str, Any]) -> dict[str, Any]:
        workspace_id = str((payload or {}).get("workspace_id") or self._selected_id())
        workspace = self.reader.get_workspace(workspace_id) if workspace_id else None
        stable_workspace_id = str((workspace or {}).get("id") or workspace_id)
        orders = (payload or {}).get("orders") or []
        self._selected_orders = {int(value) for value in orders if str(value).lstrip("-").isdigit()}
        if stable_workspace_id:
            self._selected_orders_by_workspace[stable_workspace_id] = set(self._selected_orders)
        return {
            "ok": True,
            "workspace_id": stable_workspace_id,
            "orders": sorted(self._selected_orders),
        }

    def list_workspaces(self) -> list[dict[str, Any]]:
        return self.reader.discover_workspaces()

    def get_logs(self, workspace_id: str = "", limit: int = 200) -> dict[str, Any]:
        selected_id = str((self.reader.get_workspace(workspace_id) or {}).get("id") or "") if workspace_id else self._selected_id()
        snapshot = (
            self.reader.snapshot(selected_id, log_limit=max(20, min(int(limit), 1000)))
            if selected_id
            else self.reader.empty_snapshot()
        )
        return {"ok": True, "session_id": snapshot["session_id"], "logs": snapshot["logs"]}

    def _launch(
        self,
        command: list[str],
        *,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.Popen[Any]:
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        env = None
        if extra_env:
            env = os.environ.copy()
            env.update({str(key): str(value) for key, value in extra_env.items()})
        return subprocess.Popen(command, cwd=str(self.project_root), creationflags=creationflags, env=env)

    def launch_legacy_terminal(self) -> dict[str, Any]:
        controller = self._legacy_controller
        if controller and controller.is_running():
            try:
                request_id = controller.open_legacy_ui()
                legacy = controller.wait_for_command(request_id)
                if legacy:
                    self._legacy_snapshot = legacy
                return {
                    "ok": bool((legacy or {}).get("last_command", {}).get("ok", True)),
                    "message": str((legacy or {}).get("last_command", {}).get("message") or "已打开现有调度内核。"),
                    "pid": controller.pid,
                }
            except Exception as exc:
                return {"ok": False, "message": f"打开旧版 Terminal 失败：{exc}"}
        existing = self.existing_legacy_pids()
        if existing:
            focused = self._focus_legacy_window()
            return {
                "ok": True,
                "message": "已定位当前 Terminal 窗口。" if focused else "检测到当前 Terminal 已在运行，请切换到旧窗口继续操作。",
                "pids": existing,
            }
        with self._lock:
            if self._legacy_process and self._legacy_process.poll() is None:
                return {"ok": True, "message": "旧版 Terminal 已经打开。", "pid": self._legacy_process.pid}
            terminal_path = self.project_root / "terminal.py"
            if not terminal_path.is_file():
                return {"ok": False, "message": "未找到 terminal.py。"}
            try:
                self._legacy_process = self._launch([sys.executable, str(terminal_path)])
            except OSError as exc:
                return {"ok": False, "message": f"启动旧版 Terminal 失败：{exc}"}
            return {"ok": True, "message": "已打开现有调度内核。", "pid": self._legacy_process.pid}

    def request_scheduler_action(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        controller = self._legacy_controller
        payload = dict(payload or {})
        workspace_id = str(payload.get("workspace_id") or self._selected_id())
        if controller and controller.is_running() and action in {"start", "pause"}:
            try:
                workspace_payload = self._legacy_workspace_payload(workspace_id)
                if action == "start":
                    request_id = controller.start_run(workspace_payload, payload.get("selected_orders"))
                else:
                    request_id = controller.pause(workspace_payload, confirmed=bool(payload.get("confirmed")))
                legacy = controller.wait_for_command(request_id)
                if legacy:
                    self._legacy_snapshot = legacy
                command_result = (legacy or {}).get("last_command") or {}
                if legacy:
                    self._project_legacy_workspaces(legacy)
                if command_result.get("ok"):
                    workspace = self.reader.get_workspace(workspace_id)
                    if workspace:
                        workspace_id = str(workspace.get("id") or "")
                        self._selected_workspace_id = workspace_id
                        self._record_loaded_workspaces({workspace_id})
                        self._selection_context = self.reader.persist_sidebar_selection(workspace)
                        self._write_shared_loaded_state()
                loaded_state = self._loaded_workspaces_contract(legacy)
                return {
                    "ok": bool(command_result.get("ok")),
                    "delegated": False,
                    "action": action,
                    "message": str(command_result.get("message") or "调度命令已发送。"),
                    "loaded_workspaces_state": loaded_state,
                    "parallel_capability": loaded_state["parallel_capability"],
                }
            except Exception as exc:
                return {"ok": False, "action": action, "message": f"调度命令失败：{exc}"}
        result = self.launch_legacy_terminal()
        result.update(
            {
                "delegated": True,
                "action": str(action or ""),
                "message": "现阶段该操作由现有 Terminal 执行；已为你打开旧版调度窗口。",
            }
        )
        return result

    def open_path(self, path_text: Any) -> dict[str, Any]:
        if isinstance(path_text, dict):
            kind = str(path_text.get("kind") or "")
            path_id = str(path_text.get("path_id") or "")
            if kind == "workspace" or path_id == "workspace":
                return self.open_workspace()
            if kind == "logs" or path_id == "logs":
                return self.open_logs()
            workspace = self.reader.get_workspace(self._selected_id())
            if kind == "attempt" and workspace and path_id:
                return self.open_path(str(Path(workspace["run_root"]) / path_id))
            return {"ok": False, "message": "当前路径入口尚未生成。"}
        raw_path = Path(str(path_text or ""))
        candidate = raw_path if raw_path.is_absolute() else self.project_root / raw_path
        try:
            candidate = candidate.resolve()
            candidate.relative_to(self.project_root)
        except (OSError, ValueError):
            return {"ok": False, "message": "只能打开项目目录内的路径。"}
        if not candidate.exists():
            return {"ok": False, "message": "目标路径不存在。"}
        try:
            os.startfile(str(candidate))
        except OSError as exc:
            return {"ok": False, "message": f"打开路径失败：{exc}"}
        return {"ok": True, "message": "已打开。"}

    def open_workspace(self, workspace_id: str = "") -> dict[str, Any]:
        workspace = self.reader.get_workspace(workspace_id or self._selected_id())
        if not workspace:
            return {"ok": False, "message": "未找到工作区。"}
        return self.open_path(workspace["workspace_root"])

    def open_logs(self, workspace_id: str = "") -> dict[str, Any]:
        workspace = self.reader.get_workspace(workspace_id or self._selected_id())
        if not workspace:
            return {"ok": False, "message": "未找到工作区日志。"}
        return self.open_path(workspace["log_root"])

    def toggle_floating_monitor(self, workspace_id: str = "") -> dict[str, Any]:
        with self._lock:
            if self.mode == "floating":
                return {"ok": True, "message": "当前已经是悬浮监视器。"}
            if self._floating_process and self._floating_process.poll() is None:
                self._floating_process.terminate()
                self._floating_process = None
                return {"ok": True, "visible": False, "message": "悬浮监视器已关闭。"}
            main_path = self.project_root / "main.py"
            selected_id = workspace_id or self._selected_id()
            command = [sys.executable, str(main_path), "--floating"]
            if selected_id:
                command.extend(["--workspace", selected_id])
            try:
                self._floating_process = self._launch(
                    command,
                    extra_env={MODERN_SESSION_ENV: self._session_id},
                )
            except OSError as exc:
                return {"ok": False, "message": f"启动悬浮监视器失败：{exc}"}
            return {
                "ok": True,
                "visible": True,
                "pid": self._floating_process.pid,
                "message": "悬浮监视器已打开。",
            }

    def show_floating_monitor(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        visible = bool((payload or {}).get("visible", True))
        monitor_workspace_id = str((payload or {}).get("workspace_id") or self._selected_id())
        with self._lock:
            is_running = bool(self._floating_process and self._floating_process.poll() is None)
            if visible and is_running:
                return {"ok": True, "visible": True, "message": "悬浮监视器已经打开。"}
            if not visible and is_running:
                self._floating_process.terminate()
                self._floating_process = None
                return {"ok": True, "visible": False, "message": "悬浮监视器已关闭。"}
            if not visible:
                return {"ok": True, "visible": False}
        return self.toggle_floating_monitor(monitor_workspace_id)

    def start_run(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self._selected_attempt_id = ""
        return self.request_scheduler_action("start", payload)

    def pause_run(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request_scheduler_action("pause", payload)

    def run_manual_code(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        workspace_id = str(payload.get("workspace_id") or self._selected_id())
        code_id = str(payload.get("code_id") or "")
        if not code_id:
            return {"ok": False, "message": "请选择要运行的代码。"}
        controller = self._legacy_controller
        if not controller or not controller.is_running():
            return {
                "ok": False,
                "completed": False,
                "pending_user_action": True,
                "message": "当前为只读监视，无法从现代界面启动代码；请关闭重复的旧 Terminal 后重试。",
            }
        try:
            request_id = controller.run_manual_code(self._legacy_workspace_payload(workspace_id), code_id)
            legacy = controller.wait_for_command(request_id)
            if legacy:
                self._legacy_snapshot = legacy
            result = (legacy or {}).get("last_command") or {}
            return {
                "ok": bool(result.get("ok")),
                "completed": bool(result.get("ok")),
                "message": str(result.get("message") or "未编排代码运行失败。"),
                "data": result.get("data") or {},
            }
        except Exception as exc:
            return {"ok": False, "completed": False, "message": f"运行未编排代码失败：{exc}"}

    def _open_legacy_surface(self, method_name: str, workspace_id: str) -> dict[str, Any]:
        controller = self._legacy_controller
        if not controller or not controller.is_running():
            launched = self.launch_legacy_terminal()
            return {
                **launched,
                "completed": False,
                "opened": bool(launched.get("ok")),
                "pending_user_action": True,
                "message": "当前为只读监视，已打开旧 Terminal；请在旧窗口完成该操作。" if launched.get("ok") else launched.get("message", "打开失败。"),
            }
        try:
            request_id = getattr(controller, method_name)(self._legacy_workspace_payload(workspace_id))
            legacy = controller.wait_for_command(request_id)
            if legacy:
                self._legacy_snapshot = legacy
            result = (legacy or {}).get("last_command") or {}
            data = result.get("data") or {}
            return {
                "ok": bool(result.get("ok")),
                "completed": False,
                "opened": bool(result.get("ok")),
                "pending_user_action": bool(data.get("pending_user_action", True)),
                "target_surface": data.get("target_surface") or "legacy_terminal",
                "message": str(result.get("message") or "目标界面未能打开。"),
                "data": data,
            }
        except Exception as exc:
            return {"ok": False, "completed": False, "opened": False, "message": f"打开功能失败：{exc}"}

    def management_action(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        action = str(payload.get("action") or "")
        workspace_id = str(payload.get("workspace_id") or self._selected_id())
        if action == "run-unarranged-code":
            requested_workspace = self.reader.get_workspace(workspace_id)
            if not requested_workspace:
                return {"ok": False, "message": "未找到当前工作区，无法读取代码清单。"}
            snapshot = self.get_state()
            if str((snapshot.get("workspace") or {}).get("id") or "") != str(requested_workspace.get("id") or ""):
                return {"ok": False, "message": "当前工作区尚未在调度内核中挂载，请重新选择工作区后再试。"}
            manual_codes = [item for item in snapshot.get("manual_codes") or [] if item.get("exists", True)]
            if not manual_codes:
                return {"ok": False, "message": "当前工作区没有识别到可单独运行的未编排代码，或调度内核仍处于只读监视状态。"}
            return {
                "ok": True,
                "requires_selection": True,
                "manual_codes": manual_codes,
                "message": "请选择要运行的代码。",
            }
        if action == "create-workspace":
            script_path = self.project_root / "scripts" / "create_award_workspace_template.py"
            if not script_path.is_file():
                return {"ok": False, "completed": False, "message": "未找到新建奖项工作区向导。"}
            try:
                process = self._launch([sys.executable, str(script_path)])
            except OSError as exc:
                return {"ok": False, "completed": False, "message": f"打开新建向导失败：{exc}"}
            return {
                "ok": True,
                "completed": False,
                "opened": True,
                "pending_user_action": True,
                "target_surface": "create_award_workspace_wizard",
                "pid": process.pid,
                "message": "已打开“新建奖项＋首个工作区”向导；从现有工作区创建下一工作区，请使用“运行未编排代码”里的 inherit.py。",
            }
        if action == "initialize-workspace":
            return self._open_legacy_surface("initialize_award_workspace", workspace_id)
        if action == "edit-file-structure":
            return self._open_legacy_surface("open_file_structure", workspace_id)
        if action == "configure-resources":
            resource_config = self.get_resource_config({"workspace_id": workspace_id})
            if not resource_config.get("ok"):
                return resource_config
            return {
                "ok": True,
                "completed": False,
                "requires_resource_config": True,
                "resource_config": resource_config,
                "message": "请选择要更新的资源。",
            }
        if action in {"select-dataset", "select-rule"}:
            return self.choose_resource(
                {
                    "workspace_id": workspace_id,
                    "kind": "dataset" if action == "select-dataset" else "rule",
                }
            )
        if action == "open-configs":
            workspace = self.reader.get_workspace(workspace_id)
            if not workspace:
                return {"ok": False, "completed": False, "message": "请先选择工作区，以确定奖项和年份。"}
            config_file = get_award_config_file(str(workspace.get("award") or ""), project_root=str(self.project_root))
            if not config_file or not Path(config_file).is_file():
                return {"ok": False, "completed": False, "message": "当前奖项没有接入 configs 配置文件。"}
            if str(workspace.get("award") or "") not in {"私募金牛奖", "分析师金牛奖", "券商资管金牛奖"}:
                opened = self.open_path(config_file)
                return {
                    **opened,
                    "completed": bool(opened.get("ok")),
                    "opened": bool(opened.get("ok")),
                    "target_surface": "config_source_file",
                    "message": "当前奖项没有专用表单，已打开真实 configs 源文件。" if opened.get("ok") else opened.get("message", "打开失败。"),
                }
            return self._open_legacy_surface("open_config_editor", workspace_id)
        return {
            "ok": False,
            "completed": False,
            "message": f"入口尚未接通：{action or '未知动作'}。",
        }

    def get_panel_data(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        snapshot = self.get_state()
        panel = str((payload or {}).get("panel") or "")
        keys = {"timeline": "timeline", "data": "files", "resources": "resources", "results": "results", "attempts": "attempts"}
        key = keys.get(panel)
        return {key: snapshot.get(key)} if key else {"ok": False, "message": "未知面板。"}

    def select_attempt(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        attempt_id = str((payload or {}).get("attempt_id") or "")
        if not attempt_id:
            self._selected_attempt_id = ""
            return self.get_state()

        workspace_id = self._selected_id()
        if not workspace_id:
            return {"ok": False, "message": "尚未加载工作区。"}
        current = self.reader.snapshot(workspace_id)
        known_ids = {
            str(item.get("session_id") or "")
            for item in current.get("history") or []
            if item.get("session_id")
        }
        if attempt_id not in known_ids:
            return {"ok": False, "message": "未找到对应的运行尝试。"}

        if attempt_id == str(current.get("session_id") or ""):
            self._selected_attempt_id = ""
            return self.get_state()

        self._selected_attempt_id = attempt_id
        return self._frontend_snapshot(
            self.reader.snapshot(workspace_id, attempt_id=attempt_id)
        )

    def set_attempt_scope(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"ok": True}

    def set_floating_mode(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        mode = str((_payload or {}).get("mode") or "mini")
        if mode not in {"mini", "expanded"}:
            return {"ok": False, "message": "未知的悬浮窗模式。"}
        window = self._window
        if self.mode == "floating" and window is not None:
            try:
                width, height = (300, 132) if mode == "mini" else (330, 314)
                window.resize(width, height)
            except Exception as exc:
                return {"ok": False, "message": f"调整悬浮窗失败：{exc}"}
        return {"ok": True, "mode": mode}

    def save_floating_position(self, _payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"ok": True}

    def close_floating_monitor(self) -> dict[str, Any]:
        window = self._window
        if self.mode != "floating" or window is None:
            return {"ok": True, "message": "悬浮监视器未单独运行。"}
        try:
            window.destroy()
            return {"ok": True, "message": "悬浮监视器已关闭，运行任务不受影响。"}
        except Exception as exc:
            return {"ok": False, "message": f"关闭悬浮窗失败：{exc}"}

    def focus_main_window(self) -> dict[str, Any]:
        try:
            import win32con
            import win32gui

            matches: list[int] = []

            def collect(hwnd: int, _extra: Any) -> None:
                if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == "金牛奖 Terminal":
                    matches.append(hwnd)

            win32gui.EnumWindows(collect, None)
            if matches:
                hwnd = matches[-1]
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                return {"ok": True, "message": "已切换到主界面。"}
        except Exception:
            pass

        try:
            self._launch([sys.executable, str(self.project_root / "main.py"), "--without-legacy-bridge"])
        except OSError as exc:
            return {"ok": False, "message": f"打开主界面失败：{exc}"}
        return {"ok": True, "message": "已打开主界面。"}

    def diagnostics(self) -> dict[str, Any]:
        workspaces = self.reader.discover_workspaces()
        selected_id = self._selected_id()
        snapshot = self.reader.snapshot(selected_id) if selected_id else self.reader.empty_snapshot()
        return {
            "ok": True,
            "mode": self.mode,
            "project_root": str(self.project_root),
            "workspace_count": len(workspaces),
            "selected_workspace_id": selected_id,
            "snapshot_status": snapshot.get("status"),
            "entry_count": len(snapshot.get("entries") or []),
            "json_serializable": bool(json.dumps(snapshot, ensure_ascii=False)),
        }
