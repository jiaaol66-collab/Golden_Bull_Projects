from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import json
import os
import zipfile
from pathlib import Path
from typing import Any, Iterable

import award_config


STATUS_LABELS = {
    "idle": "空闲",
    "pending": "等待中",
    "running": "运行中",
    "done": "已完成",
    "success": "已完成",
    "failed": "运行失败",
    "error": "运行失败",
    "cancelled": "已取消",
    "stale": "已中断",
}


def _read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return default


def _parse_datetime(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def _seconds_between(start: Any, end: Any = None) -> float:
    started_at = _parse_datetime(start)
    ended_at = _parse_datetime(end) if end else dt.datetime.now()
    if not started_at or not ended_at:
        return 0.0
    return max(0.0, (ended_at - started_at).total_seconds())


def _relative_display(path_text: Any) -> str:
    return str(path_text or "").replace("\\", "/")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _manifest_text(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text in {".", "None"} else text


def _manifest_order(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value == value and value.is_integer() else None
    text = _manifest_text(value)
    if text.isdigit():
        return int(text)
    if text and text.replace(".", "", 1).isdigit():
        number = float(text)
        return int(number) if number.is_integer() else None
    return None


def _datetime_sort_value(value: Any) -> float:
    parsed = _parse_datetime(value)
    if parsed is None:
        return 0.0
    try:
        return parsed.timestamp()
    except (OSError, OverflowError, ValueError):
        return 0.0


class TerminalStateReader:
    """Read-only projection of the legacy Terminal's persisted runtime state.

    The existing scheduler owns all writes.  This reader only consumes the
    workspace metadata, attempt summaries, structured timeline and run logs.
    """

    def __init__(self, project_root: str | os.PathLike[str]):
        self.project_root = Path(project_root).resolve()
        self.logs_root = self.project_root / "logs"
        self.sidebar_state_path = self.project_root / ".terminal_sidebar_state.json"
        self._revision = 0
        self._award_config_mtime_ns = 0

    @staticmethod
    def _stable_workspace_id(workspace_root: Path) -> str:
        root_key = os.path.normcase(str(workspace_root.resolve()))
        return f"ws_{hashlib.sha1(root_key.encode('utf-8')).hexdigest()[:12]}"

    @staticmethod
    def _workspace_created_at(
        workspace_root: Path,
        workspace_metadata: dict[str, Any] | None = None,
        log_metadata: dict[str, Any] | None = None,
    ) -> str:
        """Return the workspace establishment time, never a run/update time."""

        for metadata in (workspace_metadata or {}, log_metadata or {}):
            created_at = _clean_text(metadata.get("created_at"))
            if created_at:
                return created_at
        try:
            return dt.datetime.fromtimestamp(workspace_root.stat().st_ctime).isoformat(timespec="seconds")
        except (OSError, OverflowError, ValueError):
            return ""

    def read_sidebar_selection(self) -> dict[str, Any]:
        """Read the legacy four-field sidebar preference without treating it as loaded state."""

        path = self.sidebar_state_path
        if not path.is_file():
            payload: dict[str, Any] = {}
            read_status = "missing"
        else:
            try:
                raw = _read_json(path, None)
                if not isinstance(raw, dict):
                    raise ValueError("sidebar state is not an object")
                payload = raw
                read_status = "ok"
            except (TypeError, ValueError):
                payload = {}
                read_status = "invalid"

        nested = payload.get("selection_context")
        selection = {**payload, **nested} if isinstance(nested, dict) else payload
        workspace_value = selection.get("workspace")
        workspace_object = workspace_value if isinstance(workspace_value, dict) else {}
        award = _clean_text(selection.get("award") or selection.get("award_name"))
        year = _clean_text(selection.get("year") or selection.get("year_text"))
        workspace_name = _clean_text(
            workspace_object.get("name")
            or workspace_object.get("workspace_name")
            or (workspace_value if not isinstance(workspace_value, dict) else "")
            or selection.get("workspace_name")
            or selection.get("active_workspace")
        )
        workspace_id = _clean_text(selection.get("workspace_id") or workspace_object.get("id"))

        matched = None
        for workspace in self.discover_workspaces():
            if workspace_id and workspace_id not in {
                _clean_text(workspace.get("id")),
                _clean_text(workspace.get("legacy_workspace_id")),
            }:
                continue
            if award and award not in {
                _clean_text(workspace.get("award")),
                _clean_text(workspace.get("award_dir_name")),
            }:
                continue
            if year and year != self._workspace_year(workspace.get("name")):
                continue
            if workspace_name and workspace_name not in {
                _clean_text(workspace.get("name")),
                _clean_text(workspace.get("display_name")),
            }:
                continue
            if any((workspace_id, award, year, workspace_name)):
                matched = workspace
                break

        if read_status == "ok" and matched is None and any((workspace_id, award, year, workspace_name)):
            read_status = "not_found"
        return {
            "schema_version": 1,
            "source": path.name,
            "read_status": read_status,
            "award": award,
            "year": year,
            "workspace": workspace_name,
            "workspace_id": _clean_text((matched or {}).get("id")),
            "resolved": matched is not None,
            "saved_at": _clean_text(payload.get("saved_at")),
        }

    def persist_sidebar_selection(self, workspace: dict[str, Any]) -> dict[str, Any]:
        """Update legacy selection keys while preserving unknown/forward-compatible fields."""

        current = _read_json(self.sidebar_state_path, {})
        payload = dict(current) if isinstance(current, dict) else {}
        payload.update(
            {
                "award": _clean_text(workspace.get("award")),
                "year": self._workspace_year(workspace.get("name")),
                "workspace": _clean_text(workspace.get("name")),
                "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
        )
        temp_path = self.sidebar_state_path.with_name(f".{self.sidebar_state_path.name}.{os.getpid()}.tmp")
        try:
            self.sidebar_state_path.parent.mkdir(parents=True, exist_ok=True)
            with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.sidebar_state_path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
        return self.read_sidebar_selection()

    @staticmethod
    def _workspace_year(value: Any) -> str:
        import re

        match = re.search(r"(?:19|20)\d{2}", _clean_text(value))
        return match.group(0) if match else ""

    def discover_workspaces(self) -> list[dict[str, Any]]:
        by_root: dict[str, dict[str, Any]] = {}

        metadata_paths = self.logs_root.glob("*/ws_*/workspace.json") if self.logs_root.is_dir() else []
        for metadata_path in metadata_paths:
            payload = _read_json(metadata_path, {})
            if not isinstance(payload, dict):
                continue
            legacy_workspace_id = str(payload.get("workspace_id") or metadata_path.parent.name)
            run_root = Path(payload.get("run_root") or metadata_path.parent / "run")
            index = _read_json(run_root / "index.json", [])
            latest_attempt = index[-1] if isinstance(index, list) and index else {}
            workspace_root = Path(payload.get("workspace_root") or "")
            if workspace_root and not workspace_root.is_absolute():
                workspace_root = self.project_root / workspace_root
            try:
                workspace_root = workspace_root.resolve()
            except OSError:
                continue
            # Logs are historical evidence, not the workspace registry.  Do
            # not resurrect a workspace whose directory has been removed.
            if not workspace_root.is_dir():
                continue
            workspace_meta = _read_json(workspace_root / ".gb_workspace.json", {})
            if not isinstance(workspace_meta, dict):
                workspace_meta = {}
            display_name = str(
                payload.get("workspace_display_name")
                or payload.get("workspace_name")
                or metadata_path.parent.name
            )
            updated_at = str(
                latest_attempt.get("ended_at")
                or latest_attempt.get("started_at")
                or payload.get("updated_at")
                or ""
            )
            by_root[os.path.normcase(str(workspace_root))] = {
                    "id": self._stable_workspace_id(workspace_root),
                    "legacy_workspace_id": legacy_workspace_id,
                    "award": str(latest_attempt.get("award") or payload.get("award") or payload.get("award_dir_name") or ""),
                    "award_dir_name": str(payload.get("award_dir_name") or metadata_path.parent.parent.name),
                    "name": str(payload.get("workspace_name") or display_name),
                    "display_name": display_name,
                    "workspace_root": str(workspace_root),
                    "log_root": str(metadata_path.parent.resolve()),
                    "run_root": str(run_root.resolve()),
                    "created_at": self._workspace_created_at(workspace_root, workspace_meta, payload),
                    "updated_at": updated_at,
                    "latest_status": str(latest_attempt.get("status") or "idle"),
                }

        # The filesystem and award registry are authoritative for workspace
        # discovery.  This also finds newly created workspaces before their
        # first run has produced log metadata.
        award_config_path = self.project_root / "award_config.py"
        try:
            config_mtime_ns = award_config_path.stat().st_mtime_ns
        except OSError:
            config_mtime_ns = 0
        if config_mtime_ns and config_mtime_ns != self._award_config_mtime_ns:
            importlib.reload(award_config)
            self._award_config_mtime_ns = config_mtime_ns

        for award_label in award_config.get_award_labels():
            relative_award_root = award_config.get_award_folder(award_label)
            if not relative_award_root:
                continue
            award_root = (self.project_root / relative_award_root).resolve()
            if not award_root.is_dir():
                continue
            try:
                candidates = list(award_root.iterdir())
            except OSError:
                continue
            for candidate in candidates:
                if not candidate.is_dir():
                    continue
                blueprint_paths = (
                    candidate / "资料" / "代码" / "工作区设置" / "文件结构.xlsx",
                    candidate / "工作区设置" / "文件结构.xlsx",
                )
                if not any(path.is_file() for path in blueprint_paths):
                    continue
                resolved_root = candidate.resolve()
                root_key = os.path.normcase(str(resolved_root))
                existing = by_root.get(root_key)
                if existing:
                    existing["award"] = award_label
                    existing["award_dir_name"] = str(relative_award_root).replace("\\", "/")
                    workspace_meta = _read_json(resolved_root / ".gb_workspace.json", {})
                    if not isinstance(workspace_meta, dict):
                        workspace_meta = {}
                    existing["created_at"] = self._workspace_created_at(
                        resolved_root,
                        workspace_meta,
                        {"created_at": existing.get("created_at")},
                    )
                    continue

                workspace_meta = _read_json(resolved_root / ".gb_workspace.json", {})
                if not isinstance(workspace_meta, dict):
                    workspace_meta = {}
                legacy_workspace_id = str(workspace_meta.get("workspace_id") or "")
                workspace_id = self._stable_workspace_id(resolved_root)
                log_folder_id = legacy_workspace_id or workspace_id
                log_root = self.logs_root / Path(relative_award_root).name / log_folder_id
                run_root = log_root / "run"
                index = _read_json(run_root / "index.json", [])
                latest_attempt = index[-1] if isinstance(index, list) and index else {}
                display_name = str(
                    workspace_meta.get("workspace_display_name")
                    or workspace_meta.get("display_name")
                    or candidate.name
                )
                by_root[root_key] = {
                    "id": workspace_id,
                    "legacy_workspace_id": legacy_workspace_id,
                    "award": award_label,
                    "award_dir_name": str(relative_award_root).replace("\\", "/"),
                    "name": candidate.name,
                    "display_name": display_name,
                    "workspace_root": str(resolved_root),
                    "log_root": str(log_root.resolve()),
                    "run_root": str(run_root.resolve()),
                    "created_at": self._workspace_created_at(resolved_root, workspace_meta),
                    "updated_at": str(
                        latest_attempt.get("ended_at")
                        or latest_attempt.get("started_at")
                        or workspace_meta.get("updated_at")
                        or ""
                    ),
                    "latest_status": str(latest_attempt.get("status") or "idle"),
                }

        workspaces = list(by_root.values())
        workspaces.sort(
            key=lambda item: (
                _datetime_sort_value(item.get("created_at")),
                _clean_text(item.get("display_name")),
            ),
            reverse=True,
        )
        return workspaces

    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        for workspace in self.discover_workspaces():
            if workspace["id"] == workspace_id or workspace.get("legacy_workspace_id") == workspace_id:
                return workspace
        return None

    def _attempts(self, workspace: dict[str, Any]) -> list[dict[str, Any]]:
        index = _read_json(Path(workspace["run_root"]) / "index.json", [])
        if not isinstance(index, list):
            return []
        attempts = [dict(item) for item in index if isinstance(item, dict)]
        attempts.reverse()
        return attempts

    @staticmethod
    def _workspace_blueprint(workspace_root: Path) -> Path | None:
        for candidate in (
            workspace_root / "资料" / "代码" / "工作区设置" / "文件结构.xlsx",
            workspace_root / "工作区设置" / "文件结构.xlsx",
        ):
            if candidate.is_file():
                return candidate
        return None

    def _manifest_steps(self, workspace: dict[str, Any]) -> list[dict[str, Any]]:
        """Read the complete canonical run order without importing the Tk scheduler."""

        workspace_root = Path(str(workspace.get("workspace_root") or ""))
        blueprint = self._workspace_blueprint(workspace_root)
        if blueprint is None:
            return []
        try:
            from openpyxl import load_workbook

            workbook = load_workbook(blueprint, data_only=True, read_only=True)
            try:
                sheet = workbook["工作区"]
                rows = sheet.iter_rows(values_only=True)
                header = list(next(rows))
                columns = {str(name): index for index, name in enumerate(header) if name is not None}
                required = {"工作区名", "步骤", "工作区文件夹", "运行顺序", "相应代码和说明文件", "代码/说明"}
                if not required.issubset(columns):
                    return []
                target_award = _manifest_text(award_config.get_manifest_award(str(workspace.get("award") or "")))
                current_award = ""
                candidates: list[tuple[str, list[Any]]] = []
                for values in rows:
                    row = list(values)
                    award_value = _manifest_text(row[columns["工作区名"]])
                    if award_value:
                        current_award = award_value
                    order = _manifest_order(row[columns["运行顺序"]])
                    script = _manifest_text(row[columns["相应代码和说明文件"]])
                    item_type = _manifest_text(row[columns["代码/说明"]])
                    if order is None or item_type != "代码" or Path(script).suffix.lower() not in {".py", ".ipynb"}:
                        continue
                    candidates.append((current_award, row))
            finally:
                workbook.close()
        except (ImportError, OSError, KeyError, StopIteration, TypeError, ValueError, zipfile.BadZipFile):
            return []

        matching = [row for award_name, row in candidates if target_award and award_name == target_award]
        if matching:
            selected_rows = matching
        else:
            distinct_awards = {award_name for award_name, _row in candidates if award_name}
            selected_rows = [row for _award_name, row in candidates] if len(distinct_awards) <= 1 else []

        steps: list[dict[str, Any]] = []
        for row in selected_rows:
            order = _manifest_order(row[columns["运行顺序"]])
            step_value = _manifest_text(row[columns["步骤"]])
            folder_name = _manifest_text(row[columns["工作区文件夹"]])
            script = _manifest_text(row[columns["相应代码和说明文件"]])
            if order is None or not script:
                continue
            if step_value and step_value.replace("_", "").isdigit():
                preferred = f"step_{step_value}_{folder_name}"
                legacy = f"step_{step_value} {folder_name}"
                folder = preferred if (workspace_root / preferred).is_dir() else legacy if (workspace_root / legacy).is_dir() else preferred
            else:
                folder = folder_name
            subdirs = [
                _manifest_text(row[columns[name]])
                for name in ("子文件夹1", "子文件夹2", "子文件夹3", "子文件夹4")
                if name in columns
            ]
            rel_path = Path(folder, *(part for part in subdirs if part), script)
            abs_path = workspace_root / rel_path
            script_stem = Path(script).stem or "unnamed"
            steps.append(
                {
                    "order": order,
                    "step_value": step_value,
                    "script_name": script,
                    "label": f"{order}_step_{step_value or 'unknown'}_{script_stem}",
                    "rel_path": _relative_display(rel_path),
                    "exists": abs_path.is_file(),
                    "runnable": Path(script).suffix.lower() in {".py", ".ipynb"},
                }
            )
        gui_state = _read_json(workspace_root / "参评信息" / "gui_state.json", {})
        saved_states = gui_state.get("step_states") if isinstance(gui_state, dict) else {}
        saved_states = saved_states if isinstance(saved_states, dict) else {}
        status_map = {"success": "done", "error": "failed", "pending": "waiting"}
        for item in steps:
            raw_state = str(saved_states.get(str(item["order"]), saved_states.get(item["order"], "pending")))
            item["status"] = status_map.get(raw_state, raw_state)
        return sorted(steps, key=lambda item: int(item["order"]))

    @staticmethod
    def _configured_step_orders(workspace_root: Path, steps: list[dict[str, Any]]) -> list[int]:
        gui_state = _read_json(workspace_root / "参评信息" / "gui_state.json", {})
        valid_orders = {int(item["order"]) for item in steps if item.get("order") is not None}
        if isinstance(gui_state, dict) and "selected_step_orders" in gui_state:
            result: list[int] = []
            for value in gui_state.get("selected_step_orders") or []:
                order = _manifest_order(value)
                if order in valid_orders and order not in result:
                    result.append(order)
            return result
        return [
            int(item["order"])
            for item in steps
            if item.get("order") is not None and item.get("exists") and item.get("runnable", True)
        ]

    def _timeline_entries(self, timeline_path: Path, session_id: str = "") -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        try:
            lines = timeline_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            return events
        for line in lines:
            marker = "GB_TIMELINE "
            if marker not in line:
                continue
            try:
                payload = json.loads(line.split(marker, 1)[1])
            except (ValueError, TypeError):
                continue
            if isinstance(payload, dict):
                if session_id and str(payload.get("session_id") or "") != session_id:
                    continue
                events.append(payload)

        entries: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for event in events:
            run_id = str(event.get("run_id") or "")
            if not run_id:
                continue
            if run_id not in entries:
                entries[run_id] = {
                    "run_id": run_id,
                    "session_id": str(event.get("session_id") or ""),
                    "rel_path": _relative_display(event.get("rel_path")),
                    "label": Path(str(event.get("rel_path") or "未命名步骤")).stem,
                    "axis": str(event.get("axis") or "main"),
                    "kind": str(event.get("axis") or "main"),
                    "status": "running",
                    "started_at": "",
                    "ended_at": "",
                    "duration_seconds": 0.0,
                    "pid": event.get("pid"),
                }
                order.append(run_id)
            entry = entries[run_id]
            if event.get("event") == "start":
                entry["started_at"] = str(event.get("ts") or "")
                entry["status"] = "running"
                entry["pid"] = event.get("pid")
            elif event.get("event") == "end":
                status = str(event.get("status") or "done")
                entry["status"] = "done" if status == "success" else status
                entry["ended_at"] = str(event.get("ts") or "")
                try:
                    entry["duration_seconds"] = float(event.get("duration") or 0.0)
                except (TypeError, ValueError):
                    entry["duration_seconds"] = 0.0
        return [entries[key] for key in order]

    def _records(self, attempt_dir: Path, workspace_root: Path, session_id: str) -> list[dict[str, Any]]:
        records = _read_json(attempt_dir / "records_summary.json", [])
        if isinstance(records, list) and records:
            return [dict(item) for item in records if isinstance(item, dict)]
        archived = self._timeline_entries(attempt_dir / "timeline.log", session_id=session_id)
        if archived:
            return archived
        for name in ("时间记录.log", "时间记录.txt"):
            live_path = workspace_root / "参评信息" / name
            live = self._timeline_entries(live_path, session_id=session_id)
            if live:
                return live
        return []

    def _is_pid_running(self, pid: Any) -> bool:
        try:
            pid_number = int(pid)
        except (TypeError, ValueError):
            return False
        if pid_number <= 0:
            return False
        try:
            import psutil

            return psutil.pid_exists(pid_number) and psutil.Process(pid_number).is_running()
        except Exception:
            return False

    def _normalize_entries(self, entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for index, raw in enumerate(entries, start=1):
            item = dict(raw)
            status = str(item.get("status") or "pending").lower()
            if status == "success":
                status = "done"
            if status == "running" and not self._is_pid_running(item.get("pid")):
                # A final summary is authoritative; an unfinished timeline with
                # no live PID is presented as interrupted instead of running.
                status = "stale"
            item.update(
                {
                    "order": index,
                    "rel_path": _relative_display(item.get("rel_path")),
                    "label": str(item.get("label") or Path(str(item.get("rel_path") or f"步骤 {index}")).stem),
                    "axis": str(item.get("axis") or "main"),
                    "status": status,
                    "status_label": STATUS_LABELS.get(status, status),
                    "started_at": str(item.get("started_at") or ""),
                    "ended_at": str(item.get("ended_at") or ""),
                }
            )
            try:
                duration = float(item.get("duration_seconds") or 0.0)
            except (TypeError, ValueError):
                duration = 0.0
            if status == "running" and not duration:
                duration = _seconds_between(item.get("started_at"))
            item["duration_seconds"] = duration
            normalized.append(item)
        return normalized

    def _latest_log_lines(self, attempt_dir: Path, limit: int = 160) -> list[str]:
        candidates = []
        for folder_name in ("main", "async"):
            folder = attempt_dir / folder_name
            if folder.is_dir():
                candidates.extend(path for path in folder.glob("*.log") if path.is_file())
        candidates.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
        if not candidates:
            return []
        try:
            lines = candidates[0].read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            return []
        return lines[-max(1, int(limit)) :]

    def snapshot(
        self,
        workspace_id: str | None = None,
        log_limit: int = 160,
        attempt_id: str | None = None,
    ) -> dict[str, Any]:
        self._revision += 1
        captured_at = dt.datetime.now().isoformat(timespec="seconds")
        workspaces = self.discover_workspaces()
        workspace = None
        if workspace_id:
            workspace = next((item for item in workspaces if item["id"] == workspace_id), None)
        if workspace is None and workspaces:
            workspace = workspaces[0]
        if workspace is None:
            return self.empty_snapshot()

        attempts = self._attempts(workspace)
        attempt = (
            next((item for item in attempts if str(item.get("session_id") or "") == attempt_id), {})
            if attempt_id
            else (attempts[0] if attempts else {})
        )
        session_id = str(attempt.get("session_id") or "")
        attempt_dir = Path(workspace["run_root"]) / session_id if session_id else Path(workspace["run_root"])
        disk_summary = _read_json(attempt_dir / "summary.json", {}) if session_id else {}
        if isinstance(disk_summary, dict) and disk_summary:
            attempt = {**attempt, **disk_summary}
        workspace_root = Path(workspace["workspace_root"])
        entries = self._normalize_entries(self._records(attempt_dir, workspace_root, session_id)) if session_id else []
        manifest_steps = self._manifest_steps(workspace)
        configured_step_orders = self._configured_step_orders(workspace_root, manifest_steps)

        live_entries = [item for item in entries if item["status"] == "running"]
        stale_entries = [item for item in entries if item["status"] == "stale"]
        failed_entries = [item for item in entries if item["status"] in {"failed", "error", "cancelled"}]
        done_entries = [item for item in entries if item["status"] == "done"]
        current_entry = (live_entries or failed_entries[-1:] or stale_entries[-1:] or entries[-1:])
        current_entry = current_entry[0] if current_entry else {}

        raw_status = str(attempt.get("status") or "idle").lower()
        if raw_status == "running" and not live_entries:
            status = "stale"
        elif raw_status == "success":
            status = "done"
        else:
            status = raw_status

        selected_total = int(attempt.get("selected_step_total") or len([item for item in entries if item["axis"] == "main"]) or 0)
        done_total = len([item for item in done_entries if item["axis"] == "main"])
        completed_for_progress = done_total + len([item for item in failed_entries if item["axis"] == "main"])
        progress = round((completed_for_progress / selected_total) * 100, 1) if selected_total else 0.0

        started_at = str(attempt.get("started_at") or "")
        ended_at = str(attempt.get("ended_at") or "")
        if status == "running":
            attempt_seconds = _seconds_between(started_at)
            main_seconds = attempt_seconds
        else:
            attempt_seconds = _seconds_between(started_at, ended_at)
            try:
                main_seconds = float(attempt.get("main_timer_seconds") or 0.0)
            except (TypeError, ValueError):
                main_seconds = 0.0
        current_step_seconds = _seconds_between(current_entry.get("started_at")) if current_entry.get("status") == "running" else float(current_entry.get("duration_seconds") or 0.0)
        async_seconds = sum(
            _seconds_between(item.get("started_at"))
            if item.get("status") == "running"
            else float(item.get("duration_seconds") or 0.0)
            for item in entries
            if item.get("axis") == "async"
        )

        history = []
        for item in attempts[:30]:
            history.append(
                {
                    "session_id": str(item.get("session_id") or ""),
                    "name": str(item.get("attempt_name") or item.get("started_at") or "未命名尝试"),
                    "status": str(item.get("status") or "idle"),
                    "status_label": str(item.get("status_label") or STATUS_LABELS.get(str(item.get("status") or "idle"), "空闲")),
                    "started_at": str(item.get("started_at") or ""),
                    "ended_at": str(item.get("ended_at") or ""),
                    "main_timer_seconds": float(item.get("main_timer_seconds") or 0.0),
                }
            )

        return {
            "schema_version": 1,
            "revision": self._revision,
            "captured_at": captured_at,
            "workspace": workspace,
            "status": status,
            "status_label": STATUS_LABELS.get(status, str(attempt.get("status_label") or status)),
            "session_id": session_id,
            "attempt": attempt,
            "current_step": current_entry,
            "entries": entries,
            "manifest_steps": manifest_steps,
            "configured_step_orders": configured_step_orders,
            "history": history,
            "timers": {
                "attempt_seconds": attempt_seconds,
                "main_seconds": main_seconds,
                "current_step_seconds": current_step_seconds,
                "async_seconds": async_seconds,
            },
            "progress": {
                "selected_total": selected_total,
                "done_total": done_total,
                "percent": progress,
            },
            "logs": self._latest_log_lines(attempt_dir, limit=log_limit) if session_id else [],
            "error": {
                "file": _relative_display(attempt.get("error_file_rel_path")),
                "folder": _relative_display(attempt.get("error_folder_rel_path")),
                "message": str(attempt.get("error_excerpt") or ""),
                "log_path": str(attempt.get("error_log_path") or ""),
            },
            "refreshed_at": captured_at,
        }

    @staticmethod
    def empty_snapshot() -> dict[str, Any]:
        captured_at = dt.datetime.now().isoformat(timespec="seconds")
        return {
            "schema_version": 1,
            "revision": 0,
            "captured_at": captured_at,
            "workspace": None,
            "status": "idle",
            "status_label": "空闲",
            "session_id": "",
            "attempt": {},
            "current_step": {},
            "entries": [],
            "manifest_steps": [],
            "configured_step_orders": [],
            "history": [],
            "timers": {"attempt_seconds": 0.0, "main_seconds": 0.0, "current_step_seconds": 0.0, "async_seconds": 0.0},
            "progress": {"selected_total": 0, "done_total": 0, "percent": 0.0},
            "logs": [],
            "error": {"file": "", "folder": "", "message": "", "log_path": ""},
            "refreshed_at": captured_at,
        }
