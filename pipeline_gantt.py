import datetime
import json
import os
import re
import time
import tkinter as tk
import uuid

import customtkinter as ctk

from style_config import *


def _clean_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in (".", "None") else text


def _top_step_folder(rel_path):
    text = _clean_text(rel_path).replace("/", os.sep).replace("\\", os.sep)
    if not text:
        return ""
    first_part = text.split(os.sep, 1)[0]
    return first_part if first_part.lower().startswith("step_") else ""


def _norm_rel(path):
    text = _clean_text(path).replace("/", os.sep).replace("\\", os.sep)
    if not text:
        return ""
    return os.path.normcase(os.path.normpath(text))


class PipelineGanttMixin:
    def get_workspace_view_name(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return "主界面"
        workspace_view_tabview = tab_data.get("workspace_view_tabview")
        if workspace_view_tabview and workspace_view_tabview.winfo_exists():
            try:
                view_name = workspace_view_tabview.get()
                tab_data["workspace_view_preferred"] = view_name
                return view_name
            except Exception:
                pass
        return tab_data.get("workspace_view_preferred", "主界面")

    def get_time_record_path(self, manifest):
        workspace_root = manifest.get("workspace_root", "")
        if not workspace_root:
            return ""
        log_path = os.path.join(workspace_root, "参评信息", "时间记录.log")
        legacy_path = os.path.join(workspace_root, "参评信息", "时间记录.txt")
        if os.path.isfile(log_path):
            return log_path
        if os.path.isfile(legacy_path):
            return legacy_path
        return log_path

    def get_legacy_time_record_path(self, manifest):
        workspace_root = manifest.get("workspace_root", "")
        if not workspace_root:
            return ""
        return os.path.join(workspace_root, "参评信息", "时间记录.txt")

    def get_workspace_meta_path(self, manifest):
        workspace_root = manifest.get("workspace_root", "") if isinstance(manifest, dict) else str(manifest or "")
        if not workspace_root:
            return ""
        return os.path.join(workspace_root, ".gb_workspace.json")

    def load_workspace_metadata(self, manifest):
        meta_path = self.get_workspace_meta_path(manifest)
        if not meta_path or not os.path.isfile(meta_path):
            return {}
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def ensure_workspace_metadata(self, manifest):
        workspace_root = manifest.get("workspace_root", "") if isinstance(manifest, dict) else ""
        if not workspace_root:
            return {}
        workspace_root = os.path.abspath(workspace_root)
        award_dir_name = os.path.basename(os.path.dirname(workspace_root)) or _clean_text((manifest or {}).get("award")) or "未分类"
        workspace_name = os.path.basename(workspace_root) or workspace_root
        payload = self.load_workspace_metadata({"workspace_root": workspace_root})
        workspace_id = _clean_text(payload.get("workspace_id"))
        now_text = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")
        if not workspace_id:
            workspace_id = f"ws_{uuid.uuid4().hex[:8]}"
        normalized_payload = dict(payload)
        normalized_payload.update({
            "workspace_id": workspace_id,
            "award": _clean_text((manifest or {}).get("award")),
            "award_dir_name": award_dir_name,
            "workspace_name": workspace_name,
            "workspace_display_name": _clean_text(payload.get("workspace_display_name")),
            "workspace_root": workspace_root,
            "updated_at": now_text,
        })
        if not _clean_text(normalized_payload.get("created_at")):
            normalized_payload["created_at"] = now_text
        meta_path = self.get_workspace_meta_path({"workspace_root": workspace_root})
        if meta_path:
            try:
                os.makedirs(os.path.dirname(meta_path), exist_ok=True)
                old_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                new_text = json.dumps(normalized_payload, ensure_ascii=False, sort_keys=True)
                if old_text != new_text:
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(normalized_payload, f, ensure_ascii=False, indent=2)
            except OSError:
                pass
        return normalized_payload

    def get_workspace_id(self, manifest):
        return _clean_text(self.ensure_workspace_metadata(manifest).get("workspace_id"))

    def get_workspace_display_name(self, manifest):
        metadata = self.ensure_workspace_metadata(manifest)
        display_name = _clean_text(metadata.get("workspace_display_name"))
        workspace_name = _clean_text(metadata.get("workspace_name"))
        return display_name or workspace_name or os.path.basename(_clean_text((manifest or {}).get("workspace_root")))

    def save_workspace_display_name(self, manifest, display_name):
        metadata = self.ensure_workspace_metadata(manifest)
        if not metadata:
            return {}
        display_name = _clean_text(display_name)
        metadata["workspace_display_name"] = display_name
        metadata["updated_at"] = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")
        meta_path = self.get_workspace_meta_path(manifest)
        if meta_path:
            try:
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, ensure_ascii=False, indent=2)
            except OSError:
                return {}
        self.sync_workspace_archive_metadata(manifest)
        return metadata

    def get_logs_root(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

    def get_workspace_logs_root(self, manifest):
        metadata = self.ensure_workspace_metadata(manifest)
        workspace_id = _clean_text(metadata.get("workspace_id"))
        award_dir_name = _clean_text(metadata.get("award_dir_name")) or "未分类"
        if not workspace_id:
            return ""
        return os.path.join(self.get_logs_root(), award_dir_name, workspace_id)

    def get_workspace_log_manifest_path(self, manifest):
        workspace_logs_root = self.get_workspace_logs_root(manifest)
        if not workspace_logs_root:
            return ""
        return os.path.join(workspace_logs_root, "workspace.json")

    def sync_workspace_archive_metadata(self, manifest):
        metadata = self.ensure_workspace_metadata(manifest)
        workspace_logs_root = self.get_workspace_logs_root(manifest)
        if not metadata or not workspace_logs_root:
            return metadata
        archive_payload = dict(metadata)
        archive_payload["log_root"] = workspace_logs_root
        archive_payload["meta_path"] = self.get_workspace_meta_path(manifest)
        archive_payload["run_root"] = os.path.join(workspace_logs_root, "run")
        archive_payload["runtime_root"] = os.path.join(workspace_logs_root, "runtime")
        try:
            os.makedirs(workspace_logs_root, exist_ok=True)
            with open(self.get_workspace_log_manifest_path(manifest), "w", encoding="utf-8") as f:
                json.dump(archive_payload, f, ensure_ascii=False, indent=2)
        except OSError:
            pass
        return archive_payload

    def get_workspace_runtime_root(self, manifest):
        workspace_logs_root = self.get_workspace_logs_root(manifest)
        if not workspace_logs_root:
            return ""
        return os.path.join(workspace_logs_root, "runtime")

    def get_attempts_root(self, manifest):
        workspace_logs_root = self.get_workspace_logs_root(manifest)
        if not workspace_logs_root:
            return ""
        return os.path.join(workspace_logs_root, "run")

    def get_attempt_index_path(self, manifest):
        attempts_root = self.get_attempts_root(manifest)
        if not attempts_root:
            return ""
        return os.path.join(attempts_root, "index.json")

    def get_attempt_dir(self, manifest, session_id):
        attempts_root = self.get_attempts_root(manifest)
        session_id = _clean_text(session_id)
        if not attempts_root or not session_id:
            return ""
        return os.path.join(attempts_root, session_id)

    def get_attempt_summary_path(self, manifest, session_id):
        attempt_dir = self.get_attempt_dir(manifest, session_id)
        if not attempt_dir:
            return ""
        return os.path.join(attempt_dir, "summary.json")

    def get_attempt_timeline_path(self, manifest, session_id):
        attempt_dir = self.get_attempt_dir(manifest, session_id)
        if not attempt_dir:
            return ""
        return os.path.join(attempt_dir, "timeline.log")

    def get_attempt_records_summary_path(self, manifest, session_id):
        attempt_dir = self.get_attempt_dir(manifest, session_id)
        if not attempt_dir:
            return ""
        return os.path.join(attempt_dir, "records_summary.json")

    def get_attempt_main_logs_dir(self, manifest, session_id):
        attempt_dir = self.get_attempt_dir(manifest, session_id)
        if not attempt_dir:
            return ""
        return os.path.join(attempt_dir, "main")

    def get_attempt_async_logs_dir(self, manifest, session_id):
        attempt_dir = self.get_attempt_dir(manifest, session_id)
        if not attempt_dir:
            return ""
        return os.path.join(attempt_dir, "async")

    def load_attempt_index(self, manifest):
        index_path = self.get_attempt_index_path(manifest)
        if not index_path or not os.path.isfile(index_path):
            return []
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        raw_items = [item for item in payload if isinstance(item, dict) and _clean_text(item.get("session_id"))]
        items = []
        changed = False
        for item in raw_items:
            normalized_item, item_changed = self.normalize_stale_attempt_summary(item)
            items.append(normalized_item)
            changed = changed or item_changed
        if changed:
            self.write_json_file(index_path, items)
        items.sort(key=lambda item: _clean_text(item.get("started_at")) or _clean_text(item.get("ended_at")), reverse=True)
        return items

    def normalize_stale_attempt_summary(self, summary):
        payload = dict(summary or {})
        status = _clean_text(payload.get("status")).lower()
        running_total = payload.get("running_entry_total", 0)
        try:
            running_total = int(running_total)
        except (TypeError, ValueError):
            running_total = 0
        if status != "running" or running_total > 0:
            return payload, False
        ended_at = _clean_text(payload.get("ended_at"))
        is_final = bool(payload.get("is_final"))
        if ended_at and is_final:
            return payload, False
        note = _clean_text(payload.get("note"))
        error_excerpt = _clean_text(payload.get("error_excerpt"))
        failed_total = payload.get("failed_entry_total", 0)
        try:
            failed_total = int(failed_total)
        except (TypeError, ValueError):
            failed_total = 0
        if "用户手动终止" in note:
            final_status = "cancelled"
        elif failed_total > 0 or error_excerpt:
            final_status = "failed"
        else:
            final_status = "success"
        payload["status"] = final_status
        payload["status_label"] = self.get_attempt_status_label(final_status)
        payload["ended_at"] = ended_at or _clean_text(payload.get("archived_at"))
        payload["is_final"] = True
        return payload, True

    def load_attempt_summary(self, manifest, session_id):
        session_id = _clean_text(session_id)
        if not session_id:
            return {}
        summary_path = self.get_attempt_summary_path(manifest, session_id)
        if summary_path and os.path.isfile(summary_path):
            try:
                with open(summary_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if isinstance(payload, dict):
                    normalized_payload, changed = self.normalize_stale_attempt_summary(payload)
                    if changed:
                        self.write_json_file(summary_path, normalized_payload)
                        self.upsert_attempt_index(manifest, normalized_payload)
                    return normalized_payload
            except (OSError, json.JSONDecodeError):
                pass
        for item in self.load_attempt_index(manifest):
            if _clean_text(item.get("session_id")) == session_id:
                return item
        return {}

    def save_attempt_display_name(self, manifest, session_id, attempt_name):
        session_id = _clean_text(session_id)
        if not session_id:
            return {}
        summary = self.load_attempt_summary(manifest, session_id)
        if not summary:
            return {}
        summary["attempt_name"] = _clean_text(attempt_name)
        summary["archived_at"] = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")
        summary_path = self.get_attempt_summary_path(manifest, session_id)
        if summary_path:
            try:
                os.makedirs(os.path.dirname(summary_path), exist_ok=True)
                with open(summary_path, "w", encoding="utf-8") as f:
                    json.dump(summary, f, ensure_ascii=False, indent=2)
            except OSError:
                return {}
        self.upsert_attempt_index(manifest, summary)
        return summary

    def load_attempt_records_summary(self, manifest, session_id):
        summary_path = self.get_attempt_records_summary_path(manifest, session_id)
        if not summary_path or not os.path.isfile(summary_path):
            return []
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []
        return payload if isinstance(payload, list) else []

    def get_attempt_status_label(self, status):
        return {
            "running": "进行中",
            "success": "成功",
            "done": "成功",
            "failed": "失败",
            "error": "失败",
            "cancelled": "已取消",
        }.get(_clean_text(status).lower(), "未知")

    def build_attempt_display_label(self, summary):
        session_id = _clean_text(summary.get("session_id"))
        attempt_name = _clean_text(summary.get("attempt_name"))
        stamp_dt = self.parse_time_record_datetime(summary.get("started_at"))
        stamp_text = stamp_dt.strftime("%m-%d %H:%M") if stamp_dt else (session_id[-10:] if session_id else "未命名")
        timer_seconds = summary.get("main_timer_seconds", 0.0)
        try:
            timer_seconds = float(timer_seconds)
        except (TypeError, ValueError):
            timer_seconds = 0.0
        title = attempt_name or stamp_text
        return f"{title} | {self.get_attempt_status_label(summary.get('status'))} | {self.format_elapsed_time(timer_seconds)}"

    def get_attempt_selector_state(self, tab_id, manifest):
        tab_data = self.active_tabs_data.get(tab_id)
        summaries = self.load_attempt_index(manifest)
        display_map = {}
        values = []
        used = set()
        for summary in summaries:
            session_id = _clean_text(summary.get("session_id"))
            if not session_id:
                continue
            label = self.build_attempt_display_label(summary)
            if label in used:
                label = f"{label} | {session_id[-4:]}"
            used.add(label)
            values.append(label)
            display_map[label] = session_id

        selected_session_id = _clean_text((tab_data or {}).get("attempt_selected_session_id"))
        available_sessions = {session_id for session_id in display_map.values()}
        current_session_id = _clean_text((tab_data or {}).get("timeline_batch_session_id"))
        if current_session_id and current_session_id in available_sessions and not selected_session_id:
            selected_session_id = current_session_id
        if selected_session_id not in available_sessions:
            selected_session_id = next(iter(display_map.values()), "")
        selected_label = next((label for label, session_id in display_map.items() if session_id == selected_session_id), "")
        if tab_data is not None:
            tab_data["attempt_display_map"] = display_map
            if selected_session_id:
                tab_data["attempt_selected_session_id"] = selected_session_id
        return summaries, display_map, values, selected_session_id, selected_label

    def parse_time_record_datetime(self, text):
        stamp_text = _clean_text(text)
        if not stamp_text:
            return None
        try:
            return datetime.datetime.fromisoformat(stamp_text)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                try:
                    return datetime.datetime.strptime(stamp_text, fmt)
                except ValueError:
                    continue
        return None

    def build_time_record_code_index(self, manifest):
        index = {}

        def upsert(rel_path, label, folder_rel_path="", order=None, kind="root", priority=9):
            norm_rel = _norm_rel(rel_path)
            if not norm_rel:
                return
            old = index.get(norm_rel)
            if old and old.get("priority", 99) <= priority:
                return
            index[norm_rel] = {
                "label": label or os.path.splitext(os.path.basename(rel_path))[0] or rel_path,
                "folder_rel_path": folder_rel_path or _top_step_folder(rel_path),
                "order": order,
                "kind": kind,
                "axis": "async" if kind == "step_async" else kind,
                "priority": priority,
            }

        for step in manifest.get("steps", []):
            upsert(
                step.get("rel_path", ""),
                step.get("display_label") or step.get("script_name", ""),
                step.get("folder_rel_path", ""),
                step.get("order"),
                kind="main",
                priority=0,
            )

        for folder in manifest.get("step_code_folders", []):
            folder_rel_path = folder.get("folder_rel_path", "")
            for item in folder.get("main_steps", []):
                upsert(
                    item.get("rel_path", ""),
                    item.get("display_label") or item.get("name", ""),
                    folder_rel_path or item.get("folder_rel_path", ""),
                    item.get("order"),
                    kind="main",
                    priority=1,
                )
            for item in folder.get("async_files", []):
                upsert(
                    item.get("rel_path", ""),
                    item.get("display_label") or item.get("name", ""),
                    folder_rel_path or item.get("folder_rel_path", ""),
                    item.get("order"),
                    kind="step_async",
                    priority=2,
                )

        for item in manifest.get("other_root_codes", []):
            upsert(
                item.get("rel_path", ""),
                item.get("display_label") or item.get("name", ""),
                "",
                None,
                kind="root",
                priority=3,
            )

        rel_path = manifest.get("default_update_rel_path", "")
        if rel_path:
            upsert(rel_path, "更新代码", "", None, kind="root", priority=1)
        return index

    def build_time_record_entry(self, code_index, rel_path, start_at, end_at, duration_seconds, status, meta=None):
        rel_path = _clean_text(rel_path).replace("/", os.sep).replace("\\", os.sep)
        merged_meta = dict(code_index.get(_norm_rel(rel_path), {}))
        if meta:
            merged_meta.update({k: v for k, v in meta.items() if v not in (None, "")})
        label = merged_meta.get("label") or os.path.splitext(os.path.basename(rel_path))[0] or rel_path
        duration_seconds = max(0.0, float(duration_seconds or 0.0))
        axis = _clean_text(merged_meta.get("axis"))
        if not axis:
            kind = _clean_text(merged_meta.get("kind"))
            axis = "async" if kind == "step_async" else (kind or "root")
        if axis == "step_async":
            axis = "async"
        return {
            "rel_path": rel_path,
            "label": label,
            "folder_rel_path": merged_meta.get("folder_rel_path") or _top_step_folder(rel_path),
            "order": merged_meta.get("order"),
            "kind": merged_meta.get("kind", "root"),
            "axis": axis or "root",
            "start_at": start_at,
            "end_at": end_at,
            "duration_seconds": duration_seconds,
            "status": status,
            "sort_at": start_at or end_at,
            "run_id": _clean_text(merged_meta.get("run_id")),
            "session_id": _clean_text(merged_meta.get("session_id")),
            "parent_rel": _clean_text(merged_meta.get("parent_rel")),
            "parent_run_id": _clean_text(merged_meta.get("parent_run_id")),
            "source": _clean_text(merged_meta.get("source")),
            "pid": merged_meta.get("pid"),
            "data_scope": _clean_text(merged_meta.get("data_scope")),
        }

    def parse_legacy_time_record_entries(self, tab_id, code_index, time_record_path, reference_now=None):
        start_pattern = re.compile(r"代码运行(?:\((?P<scope>[^)]*)\))?:(?P<rel>.+?)--\((?P<ts>.+?)\)\s*$")
        success_pattern = re.compile(r"成功运行(?:\((?P<scope>[^)]*)\))?:(?P<rel>.+?),\s*用时(?P<dur>[0-9.]+)秒--\((?P<ts>.+?)\)\s*$")
        pending = {}
        entries = []

        try:
            with open(time_record_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except OSError:
            return []

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            matched_start = start_pattern.search(line)
            if matched_start:
                rel_path = matched_start.group("rel").strip()
                start_at = self.parse_time_record_datetime(matched_start.group("ts"))
                pending.setdefault(_norm_rel(rel_path), []).append({
                    "rel_path": rel_path,
                    "start_at": start_at,
                    "data_scope": _clean_text(matched_start.group("scope")),
                })
                continue

            matched_success = success_pattern.search(line)
            if not matched_success:
                continue
            rel_path = matched_success.group("rel").strip()
            norm_rel = _norm_rel(rel_path)
            end_at = self.parse_time_record_datetime(matched_success.group("ts"))
            try:
                duration_seconds = float(matched_success.group("dur"))
            except ValueError:
                duration_seconds = 0.0
            start_at = None
            pending_info = {}
            pending_items = pending.get(norm_rel) or []
            if pending_items:
                pending_info = pending_items.pop(0)
                rel_path = pending_info.get("rel_path", rel_path)
                start_at = pending_info.get("start_at")
            meta = {
                "data_scope": _clean_text(matched_success.group("scope")) or _clean_text(pending_info.get("data_scope")),
            }
            if start_at is None and end_at is not None:
                start_at = end_at - datetime.timedelta(seconds=duration_seconds)
            entries.append(self.build_time_record_entry(code_index, rel_path, start_at, end_at, duration_seconds, "done", meta=meta))

        now_dt = reference_now or datetime.datetime.now()
        has_running_process = self.is_main_process_running(tab_id) or self.has_async_processes(tab_id)
        for pending_items in pending.values():
            for pending_info in pending_items:
                rel_path = pending_info.get("rel_path", "")
                start_at = pending_info.get("start_at") or now_dt
                duration_seconds = max(0.0, (now_dt - start_at).total_seconds())
                is_recent = duration_seconds < 6 * 3600
                status = "running" if has_running_process and is_recent else "unfinished"
                display_end_at = now_dt if status == "running" else (start_at + datetime.timedelta(seconds=min(duration_seconds, 1.0)))
                display_duration_seconds = duration_seconds if status == "running" else min(duration_seconds, 1.0)
                entries.append(
                    self.build_time_record_entry(
                        code_index,
                        rel_path,
                        start_at,
                        display_end_at,
                        display_duration_seconds,
                        status,
                        meta={"data_scope": _clean_text(pending_info.get("data_scope"))},
                    )
                )

        entries.sort(key=lambda item: item.get("sort_at") or datetime.datetime.min)
        return entries[-60:]

    def parse_structured_time_record_entries(self, tab_id, code_index, time_record_path, session_id="", max_items=None, reference_now=None):
        pending = {}
        entries = []
        timeline_prefix = "GB_TIMELINE "
        try:
            with open(time_record_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except OSError:
            return []

        for raw_line in lines:
            line = raw_line.strip()
            if not line or not line.startswith(timeline_prefix):
                continue
            try:
                payload = json.loads(line[len(timeline_prefix):])
            except json.JSONDecodeError:
                continue
            event = _clean_text(payload.get("event"))
            run_id = _clean_text(payload.get("run_id"))
            ts = self.parse_time_record_datetime(payload.get("ts"))
            if not run_id or not event:
                continue
            if event == "start":
                pending[run_id] = payload
                continue
            if event != "end":
                continue
            start_payload = pending.pop(run_id, None)
            rel_path = _clean_text(payload.get("rel_path") or (start_payload or {}).get("rel_path"))
            duration_seconds = payload.get("duration")
            try:
                duration_seconds = float(duration_seconds)
            except (TypeError, ValueError):
                duration_seconds = 0.0
            start_at = self.parse_time_record_datetime((start_payload or {}).get("ts"))
            end_at = ts
            if start_at is None and end_at is not None and duration_seconds:
                start_at = end_at - datetime.timedelta(seconds=duration_seconds)
            entries.append(
                self.build_time_record_entry(
                    code_index,
                    rel_path,
                    start_at,
                    end_at,
                    duration_seconds,
                    {"success": "done", "completed": "done"}.get(_clean_text(payload.get("status")).lower(), _clean_text(payload.get("status")).lower() or "done"),
                    meta={
                        "run_id": run_id,
                        "session_id": _clean_text(payload.get("session_id") or (start_payload or {}).get("session_id")),
                        "parent_rel": _clean_text(payload.get("parent_rel") or (start_payload or {}).get("parent_rel")),
                        "parent_run_id": _clean_text(payload.get("parent_run_id") or (start_payload or {}).get("parent_run_id")),
                        "source": _clean_text(payload.get("source") or (start_payload or {}).get("source")),
                        "axis": _clean_text(payload.get("axis") or (start_payload or {}).get("axis")),
                        "pid": payload.get("pid") or (start_payload or {}).get("pid"),
                        "data_scope": _clean_text(payload.get("data_scope") or (start_payload or {}).get("data_scope")),
                    },
                )
            )

        now_dt = reference_now or datetime.datetime.now()
        has_running_process = self.is_main_process_running(tab_id) or self.has_async_processes(tab_id)
        for run_id, start_payload in pending.items():
            start_at = self.parse_time_record_datetime(start_payload.get("ts")) or now_dt
            duration_seconds = max(0.0, (now_dt - start_at).total_seconds())
            is_recent = duration_seconds < 6 * 3600
            status = "running" if has_running_process and is_recent else "unfinished"
            display_end_at = now_dt if status == "running" else (start_at + datetime.timedelta(seconds=min(duration_seconds, 1.0)))
            display_duration_seconds = duration_seconds if status == "running" else min(duration_seconds, 1.0)
            entries.append(
                self.build_time_record_entry(
                    code_index,
                    _clean_text(start_payload.get("rel_path")),
                    start_at,
                    display_end_at,
                    display_duration_seconds,
                    status,
                    meta={
                        "run_id": run_id,
                        "session_id": _clean_text(start_payload.get("session_id")),
                        "parent_rel": _clean_text(start_payload.get("parent_rel")),
                        "parent_run_id": _clean_text(start_payload.get("parent_run_id")),
                        "source": _clean_text(start_payload.get("source")),
                        "axis": _clean_text(start_payload.get("axis")),
                        "pid": start_payload.get("pid"),
                        "data_scope": _clean_text(start_payload.get("data_scope")),
                    },
                )
            )

        entries.sort(key=lambda item: item.get("sort_at") or datetime.datetime.min)
        session_id = _clean_text(session_id)
        if session_id:
            entries = [item for item in entries if _clean_text(item.get("session_id")) == session_id]
        else:
            session_entries = [item for item in entries if item.get("session_id")]
            if session_entries:
                latest_session_id = max(session_entries, key=lambda item: item.get("sort_at") or datetime.datetime.min).get("session_id")
                entries = [item for item in entries if item.get("session_id") == latest_session_id]
        if max_items is not None:
            return entries[-max_items:]
        return entries

    def get_time_record_entries(self, tab_id, session_id="", time_record_path="", max_items=60, reference_now=None):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return []
        manifest = tab_data.get("manifest", {})
        time_record_path = time_record_path or self.get_time_record_path(manifest)
        legacy_time_record_path = self.get_legacy_time_record_path(manifest)
        code_index = self.build_time_record_code_index(manifest)
        if time_record_path.lower().endswith(".log") and os.path.isfile(time_record_path):
            entries = self.parse_structured_time_record_entries(
                tab_id,
                code_index,
                time_record_path,
                session_id=session_id,
                max_items=max_items,
                reference_now=reference_now,
            )
            if entries:
                return entries
            if session_id:
                return []
        if legacy_time_record_path and os.path.isfile(legacy_time_record_path):
            entries = self.parse_legacy_time_record_entries(tab_id, code_index, legacy_time_record_path, reference_now=reference_now)
            if max_items is not None:
                return entries[-max_items:]
            return entries
        return []

    def get_gantt_bar_color(self, entry):
        status = entry.get("status")
        if status == "unfinished":
            return DANGER
        if status == "running":
            return ACCENT
        if status in {"error", "failed", "cancelled"}:
            return DANGER
        kind = entry.get("kind")
        if kind == "step_async":
            return WARNING
        if kind == "root":
            return SUCCESS
        return ACCENT_HOVER

    def get_timeline_scale_config(self, total_seconds, is_running):
        total_seconds = max(1.0, float(total_seconds or 1.0))
        if is_running:
            tick_seconds = TIMELINE_RUNNING_TICK_SECONDS
        else:
            candidates = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1200, 1800, 3600]
            best = candidates[0]
            best_score = None
            for candidate in candidates:
                tick_count = total_seconds / candidate
                score = abs(tick_count - TIMELINE_TARGET_TICK_COUNT)
                if TIMELINE_MIN_TICK_COUNT <= tick_count <= TIMELINE_MAX_TICK_COUNT:
                    best = candidate
                    best_score = score
                    break
                if best_score is None or score < best_score:
                    best = candidate
                    best_score = score
            tick_seconds = best
        pixels_per_second = TIMELINE_TICK_PIXELS / float(tick_seconds)
        tick_count = max(1, int(total_seconds / float(tick_seconds)) + 1)
        body_height = max(TIMELINE_MIN_BODY_HEIGHT, tick_count * TIMELINE_TICK_PIXELS + 28)
        return {
            "tick_seconds": tick_seconds,
            "pixels_per_second": pixels_per_second,
            "body_height": body_height,
        }

    def get_timeline_entry_end(self, entry, fallback_now=None):
        fallback_now = fallback_now or datetime.datetime.now()
        return entry.get("end_at") or fallback_now

    def build_async_lanes(self, entries, fallback_now=None):
        fallback_now = fallback_now or datetime.datetime.now()
        lanes = []
        sorted_entries = sorted(
            entries,
            key=lambda item: (
                item.get("start_at") or fallback_now,
                self.get_timeline_entry_end(item, fallback_now),
                item.get("label", ""),
            ),
        )
        for entry in sorted_entries:
            start_at = entry.get("start_at") or fallback_now
            placed = False
            for lane in lanes:
                last_entry = lane[-1]
                last_end = self.get_timeline_entry_end(last_entry, fallback_now)
                if last_end <= start_at:
                    lane.append(entry)
                    placed = True
                    break
            if not placed:
                lanes.append([entry])
        return lanes

    def build_timeline_lane_groups(self, entries):
        fallback_now = datetime.datetime.now()
        main_entries = []
        async_entries = []
        for entry in entries:
            axis = entry.get("axis")
            if axis == "main":
                main_entries.append(entry)
            else:
                async_entries.append(entry)
        main_entries.sort(key=lambda item: (item.get("start_at") or fallback_now, item.get("order") or 9999, item.get("label", "")))
        return main_entries, self.build_async_lanes(async_entries, fallback_now)

    def get_timeline_block_text(self, entry):
        label = entry.get("label") or os.path.splitext(os.path.basename(entry.get("rel_path", "")))[0]
        duration = f"{entry.get('duration_seconds', 0.0):.1f}s"
        parent_rel = _clean_text(entry.get("parent_rel"))
        if parent_rel:
            parent_label = os.path.splitext(os.path.basename(parent_rel))[0]
            return f"{label}\n{duration} | <- {parent_label}"
        return f"{label}\n{duration}"

    def resolve_timeline_entry_code_path(self, manifest, entry):
        workspace_root = _clean_text((manifest or {}).get("workspace_root"))
        rel_path = _clean_text(entry.get("rel_path")).replace("/", os.sep).replace("\\", os.sep)
        if not workspace_root or not rel_path:
            return ""

        candidates = []
        if os.path.isabs(rel_path):
            candidates.append(os.path.normpath(rel_path))
        else:
            candidates.append(os.path.normpath(os.path.abspath(os.path.join(workspace_root, rel_path))))
            trimmed_parts = [part for part in rel_path.split(os.sep) if part not in {"", "."}]
            while trimmed_parts and trimmed_parts[0] == "..":
                trimmed_parts.pop(0)
            if trimmed_parts:
                candidates.append(os.path.normpath(os.path.abspath(os.path.join(workspace_root, *trimmed_parts))))
            parent_rel = _clean_text(entry.get("parent_rel")).replace("/", os.sep).replace("\\", os.sep)
            if parent_rel:
                parent_abs = os.path.normpath(os.path.abspath(os.path.join(workspace_root, parent_rel)))
                parent_dir = os.path.dirname(parent_abs)
                candidates.append(os.path.normpath(os.path.abspath(os.path.join(parent_dir, rel_path))))

        seen = set()
        fallback = ""
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            if not fallback:
                fallback = candidate
            if os.path.isfile(candidate):
                return candidate
        return fallback

    def get_timeline_entry_log_path(self, manifest, entry):
        session_id = _clean_text(entry.get("session_id"))
        run_id = _clean_text(entry.get("run_id"))
        axis = _clean_text(entry.get("axis"))
        if not run_id:
            return ""

        candidate_dirs = []
        if session_id:
            if axis == "main":
                candidate_dirs.append(self.get_attempt_main_logs_dir(manifest, session_id))
            else:
                candidate_dirs.append(self.get_attempt_async_logs_dir(manifest, session_id))
        runtime_root = self.get_workspace_runtime_root(manifest)
        if runtime_root:
            candidate_dirs.append(runtime_root)
            candidate_dirs.append(os.path.join(runtime_root, "async"))

        rel_path = _clean_text(entry.get("rel_path")).replace("/", os.sep).replace("\\", os.sep)
        basename = os.path.basename(rel_path)
        safe_basename = re.sub(r'[<>:"/\\\\|?*]+', "_", basename) if basename else ""
        label = _clean_text(entry.get("label"))
        safe_label = re.sub(r'[<>:"/\\\\|?*]+', "_", label) if label else ""
        run_stamp_match = re.match(r"run_(\d{8}_\d{6})", run_id)
        run_stamp_prefix = f"{run_stamp_match.group(1)}_" if run_stamp_match else ""

        for base_dir in candidate_dirs:
            if not base_dir or not os.path.isdir(base_dir):
                continue
            try:
                file_names = [name for name in os.listdir(base_dir) if name.lower().endswith(".log")]
            except OSError:
                continue

            for name in file_names:
                if name.startswith(f"{run_id}_"):
                    return os.path.join(base_dir, name)

            fuzzy_matches = []
            for name in file_names:
                score = 0
                if run_stamp_prefix and name.startswith(run_stamp_prefix):
                    score += 4
                if safe_basename and safe_basename in name:
                    score += 3
                if safe_label and safe_label in name:
                    score += 2
                if label and label in name:
                    score += 1
                if score > 0:
                    fuzzy_matches.append((score, name))
            if fuzzy_matches:
                fuzzy_matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
                return os.path.join(base_dir, fuzzy_matches[0][1])
        return ""

    def bind_timeline_item_open(self, canvas, tag, workspace_root, entry):
        manifest = {"workspace_root": workspace_root}
        abs_path = self.resolve_timeline_entry_code_path(manifest, entry)
        if not abs_path:
            return
        canvas.tag_bind(tag, "<Button-1>", lambda _event, p=abs_path: self.open_file(p))

    def draw_timeline_grid(self, canvas, min_start, total_seconds, total_width, body_height, lane_layout, scale_config):
        tick_step = scale_config["tick_seconds"]
        pixels_per_second = scale_config["pixels_per_second"]
        time_x2 = lane_layout[0]["x2"]
        compact_label = tick_step <= 15
        for second in range(0, int(total_seconds) + tick_step, tick_step):
            y = lane_layout[0]["body_y"] + int(second * pixels_per_second)
            canvas.create_line(0, y, total_width, y, fill=TIMELINE_GRID, width=1)
            stamp = min_start + datetime.timedelta(seconds=second)
            canvas.create_text(
                time_x2 - 8,
                y + (10 if compact_label else 2),
                text=stamp.strftime("%H:%M:%S") if compact_label else f"{stamp.strftime('%H:%M:%S')}",
                anchor="ne",
                fill=TEXT_MUTED,
                font=("Segoe UI", 11),
            )
            if not compact_label:
                canvas.create_text(
                    time_x2 - 8,
                    y + 16,
                    text=f"+{second}s",
                    anchor="ne",
                    fill=TEXT_MUTED,
                    font=("Segoe UI", 9),
                )
        end_y = lane_layout[0]["body_y"] + body_height
        canvas.create_line(0, end_y, total_width, end_y, fill=TIMELINE_GRID, width=1)

    def draw_timeline_lane_backgrounds(self, canvas, total_width, total_height, lane_layout):
        for lane in lane_layout:
            canvas.create_rectangle(lane["x1"], 0, lane["x2"], TIMELINE_HEADER_HEIGHT, fill=lane["bg"], outline="")
            canvas.create_rectangle(lane["x1"], TIMELINE_HEADER_HEIGHT, lane["x2"], total_height, fill=lane["body_bg"], outline="")
            canvas.create_line(lane["x1"], 0, lane["x1"], total_height, fill=TIMELINE_GRID, width=1)
            canvas.create_text(
                lane["x1"] + 10,
                TIMELINE_HEADER_HEIGHT / 2,
                text=lane["title"],
                anchor="w",
                fill=TEXT_PRIMARY,
                font=("Segoe UI", 12, "bold"),
            )
        canvas.create_line(total_width - 1, 0, total_width - 1, total_height, fill=TIMELINE_GRID, width=1)
        canvas.create_line(0, TIMELINE_HEADER_HEIGHT, total_width, TIMELINE_HEADER_HEIGHT, fill=TIMELINE_GRID, width=1)

    def draw_timeline_entry_block(self, canvas, lane, entry, min_start, workspace_root, scale_config):
        start_at = entry.get("start_at") or min_start
        end_at = self.get_timeline_entry_end(entry)
        offset_seconds = max(0.0, (start_at - min_start).total_seconds())
        length_seconds = max(0.0, (end_at - start_at).total_seconds())
        pixels_per_second = scale_config["pixels_per_second"]
        y1 = lane["body_y"] + int(offset_seconds * pixels_per_second) + 4
        height = max(TIMELINE_BLOCK_MIN_HEIGHT, int(length_seconds * pixels_per_second))
        y2 = y1 + height
        x1 = lane["x1"] + TIMELINE_BLOCK_PAD_X
        x2 = lane["x2"] - TIMELINE_BLOCK_PAD_X
        tag = f"timeline_{entry.get('run_id') or id(entry)}"
        fill_color = self.get_gantt_bar_color(entry)
        outline_color = ACCENT_DEEP if entry.get("axis") == "main" else SECONDARY
        canvas.create_rectangle(x1, y1, x2, y2, fill=fill_color, outline=outline_color, width=1, tags=(tag,))
        canvas.create_text(
            x1 + 8,
            y1 + 8,
            text=self.get_timeline_block_text(entry),
            anchor="nw",
            fill=TEXT_INVERSE if fill_color in {ACCENT, ACCENT_HOVER, ACCENT_DEEP, DANGER, SUCCESS, SECONDARY} else TEXT_PRIMARY,
            font=("Segoe UI", 10, "bold"),
            width=max(40, x2 - x1 - 16),
            tags=(tag,),
        )
        self.bind_timeline_item_open(canvas, tag, workspace_root, entry)

    def render_timeline_swimlane(self, parent, tab_id, entries, manifest, is_running=False):
        workspace_root = manifest.get("workspace_root", "")
        main_entries, async_lanes = self.build_timeline_lane_groups(entries)
        async_lane_count = max(1, len(async_lanes))
        panel_width = parent.winfo_width() if parent.winfo_exists() else 0
        available_width = max(860, panel_width - 24 if panel_width > 120 else 980)
        remaining_width = max(360, available_width - TIMELINE_TIME_COL_WIDTH - TIMELINE_MAIN_COL_WIDTH)
        if async_lane_count * TIMELINE_ASYNC_COL_MIN_WIDTH <= remaining_width:
            async_col_width = TIMELINE_ASYNC_COL_MIN_WIDTH
        else:
            async_col_width = max(110, int(remaining_width / async_lane_count))
        total_width = TIMELINE_TIME_COL_WIDTH + TIMELINE_MAIN_COL_WIDTH + async_lane_count * async_col_width

        now_dt = datetime.datetime.now()
        valid_starts = [entry["start_at"] for entry in entries if entry.get("start_at")]
        valid_ends = [self.get_timeline_entry_end(entry, now_dt) for entry in entries if entry.get("start_at")]
        min_start = min(valid_starts) if valid_starts else now_dt
        max_end = max(valid_ends) if valid_ends else now_dt
        total_seconds = max(1, int((max_end - min_start).total_seconds()))
        scale_config = self.get_timeline_scale_config(total_seconds, is_running)
        body_height = scale_config["body_height"]
        total_height = TIMELINE_HEADER_HEIGHT + body_height

        lane_layout = [
            {
                "title": "时间轴",
                "x1": 0,
                "x2": TIMELINE_TIME_COL_WIDTH,
                "bg": TIMELINE_TIME_BG,
                "body_bg": TIMELINE_TIME_BG,
                "body_y": TIMELINE_HEADER_HEIGHT,
            },
            {
                "title": "顺序代码主轴",
                "x1": TIMELINE_TIME_COL_WIDTH,
                "x2": TIMELINE_TIME_COL_WIDTH + TIMELINE_MAIN_COL_WIDTH,
                "bg": TIMELINE_MAIN_BG,
                "body_bg": SURFACE_BG,
                "body_y": TIMELINE_HEADER_HEIGHT,
            },
        ]
        async_offset = TIMELINE_TIME_COL_WIDTH + TIMELINE_MAIN_COL_WIDTH
        for index in range(async_lane_count):
            lane_layout.append(
                {
                    "title": f"异步/工具 {index + 1}",
                    "x1": async_offset + index * async_col_width,
                    "x2": async_offset + (index + 1) * async_col_width,
                    "bg": TIMELINE_ASYNC_BG,
                    "body_bg": SURFACE_BG,
                    "body_y": TIMELINE_HEADER_HEIGHT,
                }
            )

        swimlane_card = ctk.CTkFrame(parent, **panel_card_style())
        swimlane_card.pack(fill="x", padx=10, pady=(0, 10))
        card_head = ctk.CTkFrame(swimlane_card, fg_color="transparent")
        card_head.pack(fill="x", padx=10, pady=(10, 6))
        ctk.CTkLabel(card_head, text="纵向泳道图", text_color=TEXT_PRIMARY, font=ui_font(14, "bold")).pack(side="left")
        ctk.CTkLabel(
            card_head,
            text=f"主轴 1 列 | 异步/工具 {len(async_lanes)} 列 | 刻度 {scale_config['tick_seconds']}s | 点击色块可打开代码文件",
            text_color=TEXT_MUTED,
        ).pack(side="right")

        canvas = tk.Canvas(
            swimlane_card,
            height=total_height,
            bg=SURFACE_BG,
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        canvas.pack(fill="x", padx=10, pady=(0, 10))
        canvas.configure(width=total_width)

        self.draw_timeline_lane_backgrounds(canvas, total_width, total_height, lane_layout)
        self.draw_timeline_grid(canvas, min_start, total_seconds, total_width, body_height, lane_layout, scale_config)

        main_lane = lane_layout[1]
        for entry in main_entries:
            self.draw_timeline_entry_block(canvas, main_lane, entry, min_start, workspace_root, scale_config)

        if async_lanes:
            for lane_index, lane_entries in enumerate(async_lanes, start=2):
                current_lane = lane_layout[lane_index]
                for entry in lane_entries:
                    self.draw_timeline_entry_block(canvas, current_lane, entry, min_start, workspace_root, scale_config)

        detail_card = ctk.CTkFrame(parent, **panel_card_style())
        detail_card.pack(fill="x", padx=10, pady=(0, 10))
        all_entries = sorted(entries, key=lambda item: item.get("sort_at") or datetime.datetime.min)
        ctk.CTkLabel(
            detail_card,
            text=f"本次全部记录 ({len(all_entries)} 条)",
            text_color=TEXT_PRIMARY,
            font=ui_font(14, "bold"),
        ).pack(anchor="w", padx=10, pady=(10, 4))
        ctk.CTkLabel(
            detail_card,
            text="上方色块打开代码文件，下方记录打开对应日志",
            text_color=TEXT_MUTED,
            font=ui_font(11),
        ).pack(anchor="w", padx=10, pady=(0, 6))
        for entry in all_entries:
            status_label = {
                "done": "已完成",
                "running": "运行中",
                "unfinished": "未完成",
                "error": "失败",
                "failed": "失败",
                "cancelled": "已取消",
            }.get(entry.get("status"), "未知")
            axis_label = "顺序代码" if entry.get("axis") == "main" else "异步/工具"
            extra = f" <- {os.path.splitext(os.path.basename(entry['parent_rel']))[0]}" if entry.get("parent_rel") else ""
            summary = f"{axis_label} | {entry.get('label')} | {status_label} | {entry.get('duration_seconds', 0.0):.1f}秒{extra}"
            log_path = self.get_timeline_entry_log_path(manifest, entry)
            if log_path and os.path.isfile(log_path):
                ctk.CTkButton(
                    detail_card,
                    text=summary,
                    anchor="w",
                    fg_color="transparent",
                    hover_color=ACCENT_SEGMENT_BG,
                    text_color=self.get_gantt_bar_color(entry),
                    corner_radius=RADIUS_SM,
                    height=30,
                    command=lambda p=log_path: self.open_file(p),
                ).pack(fill="x", padx=6, pady=(0, 3))
            else:
                ctk.CTkLabel(
                    detail_card,
                    text=summary,
                    text_color=self.get_gantt_bar_color(entry),
                    wraplength=WRAP_PANEL_LG,
                    justify="left",
                ).pack(anchor="w", padx=10, pady=(0, 4))
        ctk.CTkLabel(detail_card, text="", text_color=TEXT_MUTED).pack(anchor="w", padx=10, pady=(0, 6))

    def set_selected_attempt(self, tab_id, selected_label):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        session_id = _clean_text(tab_data.get("attempt_display_map", {}).get(selected_label))
        if not session_id:
            return
        tab_data["attempt_selected_session_id"] = session_id
        self.schedule_gui_state_save(tab_id)
        self.render_gantt_tab(tab_id)

    def render_gantt_tab(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        gantt_header = tab_data.get("gantt_header")
        gantt_panel = tab_data.get("gantt_panel")
        manifest = tab_data.get("manifest", {})
        if not gantt_header or not gantt_panel:
            return
        restore_scroll = self.get_scroll_fraction(gantt_panel)
        tab_data["gantt_scroll_fraction"] = restore_scroll
        tab_data["gantt_last_refresh"] = time.monotonic()
        for widget in gantt_header.winfo_children():
            widget.destroy()
        for widget in gantt_panel.winfo_children():
            widget.destroy()

        time_record_path = self.get_time_record_path(manifest)
        _, _, attempt_values, selected_session_id, selected_label = self.get_attempt_selector_state(tab_id, manifest)
        active_attempt = bool(tab_data.get("attempt_active")) and selected_session_id == _clean_text(tab_data.get("timeline_batch_session_id"))
        selected_summary = self.load_attempt_summary(manifest, selected_session_id)
        reference_now = None
        if active_attempt or not selected_session_id:
            entries = self.get_time_record_entries(tab_id, session_id=selected_session_id, max_items=None)
            active_timer_seconds = tab_data.get("run_timer_elapsed", 0.0)
            if tab_data.get("run_timer_running") and tab_data.get("run_timer_started_at") is not None:
                active_timer_seconds = time.monotonic() - tab_data["run_timer_started_at"]
            timer_seconds = active_timer_seconds
            selected_timeline_path = time_record_path
        else:
            selected_timeline_path = self.get_attempt_timeline_path(manifest, selected_session_id)
            reference_now = self.parse_time_record_datetime((selected_summary or {}).get("ended_at"))
            entries = self.get_time_record_entries(
                tab_id,
                session_id=selected_session_id,
                time_record_path=selected_timeline_path,
                max_items=None,
                reference_now=reference_now,
            )
            timer_seconds = selected_summary.get("main_timer_seconds", 0.0) if selected_summary else 0.0
        try:
            timer_seconds = float(timer_seconds)
        except (TypeError, ValueError):
            timer_seconds = 0.0

        title_row = ctk.CTkFrame(gantt_header, fg_color="transparent")
        title_row.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(title_row, text="步骤流水线", text_color=TEXT_PRIMARY, font=ui_font(18, "bold")).pack(side="left")
        ctk.CTkLabel(title_row, text="本次所选", text_color=TEXT_MUTED, font=ui_font(12)).pack(side="left", padx=(10, 0))
        attempt_row = ctk.CTkFrame(gantt_header, fg_color="transparent")
        attempt_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(attempt_row, text="尝试", text_color=TEXT_PRIMARY, font=ui_font(13, "bold")).pack(side="left", padx=(0, 8))
        if attempt_values:
            ctk.CTkOptionMenu(
                attempt_row,
                values=attempt_values,
                width=WIDTH_ATTEMPT_MENU,
                height=HEIGHT_BUTTON_SM,
                corner_radius=RADIUS_MD,
                fg_color=ACCENT_SEGMENT_BG,
                button_color=ACCENT,
                button_hover_color=ACCENT_HOVER,
                text_color=TEXT_PRIMARY,
                dropdown_fg_color=SURFACE_BG,
                dropdown_hover_color=ITEM_HOVER,
                dropdown_text_color=TEXT_PRIMARY,
                command=lambda value, tid=tab_id: self.set_selected_attempt(tid, value),
            ).pack(side="left")
            if selected_label:
                attempt_menu = attempt_row.winfo_children()[-1]
                try:
                    attempt_menu.set(selected_label)
                except Exception:
                    pass
        else:
            ctk.CTkLabel(attempt_row, text="暂无尝试记录", text_color=TEXT_MUTED).pack(side="left")
        attempt_dir = self.get_attempt_dir(manifest, selected_session_id) if selected_session_id else self.get_attempts_root(manifest)
        if attempt_dir:
            ctk.CTkButton(
                attempt_row,
                text="打开尝试目录",
                width=WIDTH_OPEN_INFO_BUTTON,
                height=HEIGHT_BUTTON_SM,
                corner_radius=RADIUS_MD,
                command=lambda p=attempt_dir: self.open_path(p, ensure_dir=True),
                **button_secondary_style(),
            ).pack(side="right")
        if selected_session_id:
            ctk.CTkButton(
                attempt_row,
                text="重命名尝试",
                width=WIDTH_OPEN_INFO_BUTTON,
                height=HEIGHT_BUTTON_SM,
                corner_radius=RADIUS_MD,
                command=lambda tid=tab_id: self.rename_attempt_display_name(tid),
                **button_secondary_style(),
            ).pack(side="right", padx=(0, 6))
        records_summary_path = self.get_attempt_records_summary_path(manifest, selected_session_id) if selected_session_id else ""
        ctk.CTkButton(
            title_row,
            text="刷新流水线",
            width=WIDTH_ACTION_BUTTON,
            height=HEIGHT_BUTTON_SM,
            corner_radius=RADIUS_MD,
            command=lambda tid=tab_id: self.render_gantt_tab(tid),
            **button_secondary_style(),
        ).pack(side="right")

        if time_record_path and os.path.exists(time_record_path):
            ctk.CTkButton(
                title_row,
                text="打开时间记录",
                width=WIDTH_OPEN_INFO_BUTTON,
                height=HEIGHT_BUTTON_SM,
                corner_radius=RADIUS_MD,
                command=lambda p=time_record_path: self.open_file(p),
                **button_primary_style(),
            ).pack(side="right", padx=(0, 6))

        selected_status_label = self.get_attempt_status_label(selected_summary.get("status")) if selected_summary else ("进行中" if active_attempt else "未开始")
        main_status = "运行中" if active_attempt and self.is_main_process_running(tab_id) else ("已结束" if selected_session_id else "空闲")
        async_status = "运行中" if active_attempt and self.has_async_processes(tab_id) else ("已结束" if selected_session_id else "空闲")
        ctk.CTkLabel(
            gantt_header,
            text=f"主步骤链计时: {self.format_elapsed_time(timer_seconds)} | 当前尝试: {selected_status_label} | 主进程: {main_status} | 异步: {async_status}",
            text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=(0, 2))
        # ctk.CTkLabel(
        #     gantt_header,
        #     text="主计时器只记录主步骤链，不计入单独运行的异步/辅助代码；运行中暂按 300 秒刻度展示，结束后按 5 秒倍数自适应重绘。",
        #     text_color=TEXT_MUTED,
        #     wraplength=WRAP_PANEL_LG,
        #     justify="left",
        # ).pack(anchor="w", pady=(0, 8))

        summary_card = ctk.CTkFrame(gantt_panel, **panel_card_style())
        summary_card.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(summary_card, text="时间记录文件", text_color=TEXT_PRIMARY, font=ui_font(14, "bold")).pack(anchor="w", padx=10, pady=(10, 2))
        ctk.CTkLabel(
            summary_card,
            text=selected_timeline_path if selected_timeline_path else "当前工作区尚未定位到 时间记录.log。",
            text_color=TEXT_MUTED,
            wraplength=WRAP_PANEL_LG,
            justify="left",
        ).pack(anchor="w", padx=10, pady=(0, 8))
        if selected_summary:
            start_text = _clean_text(selected_summary.get("started_at")) or "-"
            end_text = _clean_text(selected_summary.get("ended_at")) or ("进行中" if active_attempt else "-")
            ctk.CTkLabel(
                summary_card,
                text=f"尝试区间: {start_text} -> {end_text}",
                text_color=TEXT_MUTED,
                wraplength=WRAP_PANEL_LG,
                justify="left",
            ).pack(anchor="w", padx=10, pady=(0, 8))
            error_excerpt = _clean_text(selected_summary.get("error_excerpt"))
            if error_excerpt:
                ctk.CTkLabel(summary_card, text="失败摘要", text_color=DANGER, font=ui_font(13, "bold")).pack(anchor="w", padx=10, pady=(0, 2))
                ctk.CTkLabel(
                    summary_card,
                    text=error_excerpt,
                    text_color=DANGER,
                    wraplength=WRAP_PANEL_LG,
                    justify="left",
                ).pack(anchor="w", padx=10, pady=(0, 6))
                error_log_path = _clean_text(selected_summary.get("error_log_path"))
                if error_log_path and os.path.exists(error_log_path):
                    ctk.CTkButton(
                        summary_card,
                        text="打开错误日志",
                        width=WIDTH_OPEN_INFO_BUTTON,
                        height=HEIGHT_BUTTON_SM,
                        corner_radius=RADIUS_MD,
                        command=lambda p=error_log_path: self.open_file(p),
                        **button_danger_style(),
                    ).pack(anchor="w", padx=10, pady=(0, 8))
            if records_summary_path and os.path.exists(records_summary_path):
                ctk.CTkButton(
                    summary_card,
                    text="打开摘要归档",
                    width=WIDTH_OPEN_INFO_BUTTON,
                    height=HEIGHT_BUTTON_SM,
                    corner_radius=RADIUS_MD,
                    command=lambda p=records_summary_path: self.open_file(p),
                    **button_secondary_style(),
                ).pack(anchor="w", padx=10, pady=(0, 8))

        if not entries:
            ctk.CTkLabel(
                summary_card,
                text="当前尝试暂未解析到可展示的时间记录。请先运行带 `insert_bookmark()` 的代码，或确认 `参评信息/时间记录.log` / `尝试记录/timeline.log` 已生成。",
                text_color=TEXT_MUTED,
                wraplength=WRAP_PANEL_LG,
                justify="left",
            ).pack(anchor="w", padx=10, pady=(0, 10))
            self.safe_after_idle(self.set_scroll_fraction, gantt_panel, restore_scroll)
            return

        valid_starts = [entry["start_at"] for entry in entries if entry.get("start_at")]
        valid_ends = [entry["end_at"] or datetime.datetime.now() for entry in entries if entry.get("start_at")]
        min_start = min(valid_starts) if valid_starts else datetime.datetime.now()
        max_end = max(valid_ends) if valid_ends else datetime.datetime.now()
        total_seconds = max(1.0, (max_end - min_start).total_seconds())
        ctk.CTkLabel(
            summary_card,
            text=f"展示最近 {len(entries)} 条记录 | 时间范围: {min_start.strftime('%m-%d %H:%M:%S')} -> {max_end.strftime('%m-%d %H:%M:%S')}",
            text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=10, pady=(0, 10))
        selected_status = _clean_text((selected_summary or {}).get("status")).lower()
        swimlane_running = bool(
            active_attempt
            or selected_status in {"running", "pending"}
        )
        self.render_timeline_swimlane(gantt_panel, tab_id, entries, manifest, is_running=swimlane_running)
        self.safe_after_idle(self.set_scroll_fraction, gantt_panel, restore_scroll)
