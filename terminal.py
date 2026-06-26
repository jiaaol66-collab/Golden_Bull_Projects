# -*- coding: utf-8 -*-
import os
import sys
import subprocess
import threading
import datetime
import json
import time
import re
import traceback
import uuid
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from openpyxl import load_workbook
from award_config import (
    AWARD_FOLDER_MAP,
    get_award_config_file,
    get_award_config_label,
    get_award_folder,
    get_award_labels,
    get_manifest_award,
    has_award_config,
)
from config_editor import ConfigEditorWindow
from pipeline_gantt import PipelineGanttMixin
from workspace_ui import WorkspaceUIMixin
from style_config import *
import motion
from userlib.tools import custom_dialog

# ================= 底层解析器逻辑 =================
LOG_AUTO_FOLLOW_IDLE_MS = 3000

def _clean(v):
    if v is None: return ""
    s = str(v).strip()
    return "" if s in (".", "None") else s

def _is_step_id(v):
    s = _clean(v)
    return bool(s) and s.replace("_", "").isdigit()

def _step_folder(step, folder):
    folder = _clean(folder)
    if not folder: return ""
    if _is_step_id(step): return f"step_{_clean(step)} {folder}"
    return folder


def _quote_cli_arg(value):
    text = str(value)
    if not text:
        return '""'
    if re.search(r'[\s"]', text):
        return '"' + text.replace('"', '\\"') + '"'
    return text

def _rel_dir(folder, *subs):
    parts = [folder] + [_clean(s) for s in subs]
    parts = [p for p in parts if p]
    return os.path.join(*parts) if parts else ""

def _step_display_label(step_value, order_value, file_name):
    step_part = _clean(step_value) or "unknown"
    order_part = _clean(order_value)
    if isinstance(order_value, (int, float)):
        order_part = str(int(order_value))
    if not order_part:
        order_part = "0"
    file_part = os.path.splitext(_clean(file_name))[0] or "unnamed"
    return f"{order_part}_step_{step_part}_{file_part}"

def _split_markers(value):
    text = _clean(value)
    if not text:
        return []
    return [part for part in re.split(r"[，,、/;；\s]+", text) if part]


def _is_code_file_candidate(file_name):
    name = _clean(file_name)
    if not name:
        return False
    lowered = name.lower()
    if not lowered.endswith(".py"):
        return False
    if "[script]" in lowered or "notebook" in lowered:
        return False
    return True


def _find_default_update_script(workspace_root):
    for rel_path in (
        "update_all_code.py",
        os.path.join("资料", "代码", "更新代码", "update_all_code.py"),
    ):
        if os.path.isfile(os.path.join(workspace_root, rel_path)):
            return rel_path
    return ""


def _top_step_folder(rel_path):
    text = _clean(rel_path).replace("/", os.sep).replace("\\", os.sep)
    if not text:
        return ""
    first_part = text.split(os.sep, 1)[0]
    return first_part if first_part.lower().startswith("step_") else ""


def _natural_sort_key(text):
    parts = re.split(r"(\d+)", _clean(text).lower())
    key = []
    for part in parts:
        if not part:
            continue
        # Tag each segment so Python never compares raw int and str directly.
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part))
    return tuple(key)


def _discover_code_inventory(workspace_root, steps):
    main_rel_paths = set()
    step_code_folders = []
    folder_map = {}
    if os.path.isdir(workspace_root):
        try:
            root_names = sorted(os.listdir(workspace_root), key=_natural_sort_key)
        except OSError:
            root_names = []
        for name in root_names:
            abs_path = os.path.join(workspace_root, name)
            if not os.path.isdir(abs_path):
                continue
            if not name.lower().startswith("step_"):
                continue
            entry = {
                "folder_rel_path": name,
                "folder_name": name,
                "main_steps": [],
                "async_files": [],
                "order": None,
                "display_label": name,
                "exists": True,
                "abs_path": abs_path,
            }
            folder_map[name] = entry
            step_code_folders.append(entry)

    for step in steps:
        rel_path = step.get("rel_path", "")
        if not rel_path:
            continue
        norm_rel_path = os.path.normcase(os.path.normpath(rel_path))
        main_rel_paths.add(norm_rel_path)
        top_folder = _top_step_folder(rel_path)
        entry = folder_map.get(top_folder)
        if not entry:
            continue
        entry["main_steps"].append({
            "order": step.get("order"),
            "step_value": step.get("step_value", ""),
            "script_name": step.get("script_name", ""),
            "display_label": step.get("display_label", step.get("script_name", "")),
            "folder_rel_path": top_folder,
            "rel_path": rel_path,
            "abs_path": step.get("abs_path", os.path.join(workspace_root, rel_path)),
            "exists": step.get("exists", False),
        })

    for entry in step_code_folders:
        entry["main_steps"].sort(key=lambda item: (item.get("order") is None, item.get("order") or 999999, _natural_sort_key(item.get("display_label", item.get("script_name", "")))))
        if entry["main_steps"]:
            entry["order"] = entry["main_steps"][0].get("order")
        abs_dir = entry["abs_path"]
        async_files = []
        for current_root, dir_names, file_names in os.walk(abs_dir):
            dir_names[:] = sorted([d for d in dir_names if d not in {"__pycache__", ".git"}], key=_natural_sort_key)
            for name in sorted(file_names, key=_natural_sort_key):
                abs_path = os.path.join(current_root, name)
                if not _is_code_file_candidate(name):
                    continue
                rel_path = os.path.relpath(abs_path, workspace_root)
                norm_rel = os.path.normcase(os.path.normpath(rel_path))
                if norm_rel in main_rel_paths:
                    continue
                display_rel = os.path.relpath(abs_path, abs_dir)
                async_files.append({
                    "name": display_rel,
                    "display_label": display_rel,
                    "script_name": name,
                    "folder_rel_path": entry["folder_rel_path"],
                    "rel_path": rel_path,
                    "abs_path": abs_path,
                    "exists": True,
                })
        entry["async_files"] = sorted(async_files, key=lambda item: _natural_sort_key(item.get("display_label", item.get("name", ""))))

    step_code_folders = sorted(
        step_code_folders,
        key=lambda item: ((item.get("order") is None), item.get("order") or 999999, _natural_sort_key(item.get("folder_rel_path", ""))),
    )

    default_update_rel_path = _find_default_update_script(workspace_root)
    default_update_norm = os.path.normcase(os.path.normpath(default_update_rel_path)) if default_update_rel_path else ""
    other_root_codes = []
    if os.path.isdir(workspace_root):
        try:
            root_names = sorted(os.listdir(workspace_root), key=_natural_sort_key)
        except OSError:
            root_names = []
        for name in root_names:
            abs_path = os.path.join(workspace_root, name)
            if not os.path.isfile(abs_path):
                continue
            if not _is_code_file_candidate(name):
                continue
            rel_path = name
            norm_rel = os.path.normcase(os.path.normpath(rel_path))
            if norm_rel in main_rel_paths:
                continue
            other_root_codes.append({
                "name": name,
                "display_label": name,
                "script_name": name,
                "rel_path": rel_path,
                "abs_path": abs_path,
                "exists": True,
                "folder_rel_path": "",
                "is_root_code": True,
                "is_default_update": bool(default_update_norm and norm_rel == default_update_norm),
            })
    other_root_codes.sort(key=lambda item: _natural_sort_key(item.get("display_label", item.get("name", ""))))

    return step_code_folders, other_root_codes, default_update_rel_path

def build_workspace_manifest(blueprint_xlsx, workspace_root, award="私募"):
    wb = load_workbook(blueprint_xlsx, data_only=True)
    ws = wb["工作区"]
    rows = list(ws.iter_rows(values_only=True))
    header = list(rows[0])
    col = {name: i for i, name in enumerate(header)}

    data = [list(r) for r in rows[1:]]
    cur_award = ""
    for r in data:
        a = _clean(r[col["工作区名"]])
        if a: cur_award = a
        r[col["工作区名"]] = cur_award

    has_other_col = "其他" in col
    has_output_col = "输出文件" in col
    has_code_col = "对应代码" in col

    steps, verify = [], []
    docs_by_dir = {}
    docs_by_binding = {}
    output_folders = []
    output_seen = set()
    for r in data:
        if r[col["工作区名"]] != award: continue
        folder = _step_folder(r[col["步骤"]], r[col["工作区文件夹"]])
        step_value = _clean(r[col["步骤"]])
        sub_dirs = [r[col[f"子文件夹{i}"]] for i in range(1, 5)]
        rel_dir = _rel_dir(folder, *sub_dirs)
        script = _clean(r[col["相应代码和说明文件"]])
        order = r[col["运行顺序"]]
        item_type = _clean(r[col["代码/说明"]])
        other_value = _clean(r[col["其他"]]) if has_other_col else ""
        output_markers = _split_markers(r[col["输出文件"]]) if has_output_col else []
        code_label = _clean(r[col["对应代码"]]) if has_code_col else ""
        note = _clean(r[col["备注"]])

        if output_markers and rel_dir:
            marker_key = "|".join(output_markers)
            output_key = (rel_dir, marker_key, code_label)
            if output_key not in output_seen:
                output_seen.add(output_key)
                output_folders.append({
                    "step_value": step_value,
                    "order": int(order) if isinstance(order, (int, float)) else None,
                    "script_name": script,
                    "code_label": code_label,
                    "display_label": code_label or (_step_display_label(step_value, order, script) if isinstance(order, (int, float)) and script else ""),
                    "rel_dir": rel_dir,
                    "markers": output_markers,
                    "note": note,
                })

        is_pipeline = isinstance(order, (int, float)) and item_type == "代码" and script.endswith(".py")
        if is_pipeline:
            steps.append({
                "order": int(order),
                "step_value": step_value,
                "script_name": script,
                "display_label": _step_display_label(step_value, order, script),
                "folder_rel_path": rel_dir,
                "rel_path": os.path.join(rel_dir, script) if rel_dir else script,
                "other_binding": other_value,
            })
            continue

        is_doc_file = bool(script) and (
            item_type == "说明"
            or os.path.splitext(script)[1].lower() in {".doc", ".docx", ".pdf", ".txt", ".md"}
        )
        if is_doc_file:
            doc_item = {
                "name": script,
                "rel_path": os.path.join(rel_dir, script) if rel_dir else script,
                "note": note,
                "other_binding": other_value,
            }
            docs_by_dir.setdefault(rel_dir, []).append(doc_item)
            if other_value:
                docs_by_binding.setdefault(other_value, []).append(doc_item)
            continue

        if not script and "机构筛选数据" in rel_dir.replace(os.sep, "/"):
            verify.append({
                "rel_path": rel_dir,
                "note": note,
            })

    steps.sort(key=lambda s: s["order"])
    order_to_step = {s["order"]: s for s in steps}
    step_value_to_step = {}
    for s in steps:
        step_value_to_step.setdefault(s.get("step_value", ""), s)
    for step in steps:
        step_dir = os.path.dirname(step["rel_path"])
        bound_docs = docs_by_binding.get(step.get("other_binding", ""), []) if has_other_col and step.get("other_binding") else []
        step["docs"] = bound_docs or docs_by_dir.get(step_dir, [])
    for item in output_folders:
        if item.get("code_label"):
            item["display_label"] = item["code_label"]
            m = re.match(r"\s*(\d+)", item["code_label"])
            if m:
                item["order"] = int(m.group(1))
            m = re.search(r"step_?([0-9_]+)", item["code_label"])
            if m:
                item["step_value"] = m.group(1)
            continue
        step_obj = None
        item_order = item.get("order")
        item_step_value = item.get("step_value", "")
        if isinstance(item_order, int) and item_order in order_to_step:
            step_obj = order_to_step[item_order]
        elif item_step_value and item_step_value in step_value_to_step:
            step_obj = step_value_to_step[item_step_value]
        elif item.get("rel_dir"):
            m = re.search(r"step_([0-9_]+)", str(item["rel_dir"]).replace("\\", "/"))
            if m:
                step_obj = step_value_to_step.get(m.group(1))
        if step_obj:
            item["order"] = step_obj.get("order", item.get("order"))
            item["step_value"] = step_obj.get("step_value", item.get("step_value", ""))
            item["script_name"] = step_obj.get("script_name", item.get("script_name", ""))
            item["display_label"] = step_obj.get("display_label") or _step_display_label(
                item.get("step_value", ""),
                item.get("order", 0),
                item.get("script_name", ""),
            )
        else:
            if not item.get("display_label") and isinstance(item.get("order"), int) and item.get("script_name"):
                item["display_label"] = _step_display_label(item.get("step_value", ""), item.get("order", 0), item.get("script_name", ""))
            if not item.get("display_label"):
                item["display_label"] = item.get("rel_dir", "")
    output_folders.sort(key=lambda item: ((item["order"] is None), item["order"] or 999999, item["rel_dir"]))
    return {
        "workspace_root": workspace_root,
        "steps": steps,
        "verify_folders": verify,
        "output_folders": output_folders,
        "step_code_folders": [],
        "other_root_codes": [],
        "default_update_rel_path": "",
        "has_output_column": has_output_col,
        "has_other_column": has_other_col,
    }

def reconcile_filesystem(manifest):
    root = manifest["workspace_root"]
    for s in manifest["steps"]:
        p = os.path.join(root, s["rel_path"])
        s["abs_path"] = p
        s["exists"] = os.path.isfile(p)
        for doc in s.get("docs", []):
            doc_path = os.path.join(root, doc["rel_path"])
            doc["abs_path"] = doc_path
            doc["exists"] = os.path.isfile(doc_path)
    for item in manifest.get("output_folders", []):
        folder_path = os.path.join(root, item["rel_dir"])
        item["path"] = folder_path
        item["exists"] = os.path.isdir(folder_path)
        try:
            item["n_items"] = len(os.listdir(folder_path)) if item["exists"] else 0
        except OSError:
            item["n_items"] = 0
    for v in manifest["verify_folders"]:
        p = os.path.join(root, v["rel_path"])
        v["abs_path"] = p
        v["exists"] = os.path.isdir(p)
        v["n_files"] = len(os.listdir(p)) if v["exists"] else 0
    step_code_folders, other_root_codes, default_update_rel_path = _discover_code_inventory(root, manifest.get("steps", []))
    manifest["step_code_folders"] = step_code_folders
    manifest["other_root_codes"] = other_root_codes
    manifest["default_update_rel_path"] = default_update_rel_path
    return manifest

# ================= GUI 终端逻辑 =================
apply_theme()
# 开启全局微动效: 给所有 CTkButton 加平滑悬停(一次性打补丁，需在创建任何按钮前调用)。
motion.enable_global_motion()

class GoldenBullTerminal(WorkspaceUIMixin, PipelineGanttMixin, ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("金牛奖终端中控台")
        self.geometry("1120x720")
        try:
            self.after(0, lambda: self.state("zoomed"))
        except Exception:
            pass
        self.configure(fg_color=APP_BG)
        
        self.active_tabs_data = {}
        self.workspace_menu_display_map = {}
        self.workspace_menu_reverse_map = {}
        self.year_menu_values = {}
        self.sidebar_collapsed = False
        self.sidebar_user_locked = False
        self.sidebar_expanded_width = 220
        self.window_resize_job = None
        self.suppress_window_configure = False
        self.window_resizing = False
        self.window_resizing_clear_job = None
        self.console_resize_active_tab = None
        self.auto_refresh_interval_ms = 4000
        self.tab_hover_close_button = None
        self.tab_hover_close_target = None
        self.tab_hover_hide_job = None
        self.poll_process_job = None
        self.app_closing = False
        self.sidebar_dataset_map = {}
        self.sidebar_rule_map = {}
        self.sidebar_custom_resource_paths = {}
        self.sidebar_browse_option_label = "浏览..."
        self.sidebar_unassigned_option_label = "未指定"
        self.sidebar_dataset_var = ctk.StringVar(value="未识别")
        self.sidebar_rule_var = ctk.StringVar(value="未识别")
        self.sidebar_initialize_context = {"active": False, "award": "", "year": "", "armed_at": 0.0}
        self.config_editor_window = None
        
        if not os.path.exists("logs"):
            os.makedirs("logs")

        self.setup_layout()
        self.protocol("WM_DELETE_WINDOW", self.on_app_close)
        self.poll_process_job = self.safe_after(1000, self.poll_process_states)
        self.bind("<Configure>", self.on_window_configure)
        self.window_resize_job = self.safe_after(150, self.apply_adaptive_layout)

    def is_app_alive(self):
        if getattr(self, "app_closing", False):
            return False
        try:
            return bool(self.winfo_exists())
        except Exception:
            return False

    def safe_invoke(self, callback, *args):
        if not self.is_app_alive():
            return
        try:
            callback(*args)
        except tk.TclError:
            return

    def safe_after(self, delay_ms, callback, *args):
        if not self.is_app_alive():
            return None
        try:
            return self.after(delay_ms, lambda cb=callback, a=args: self.safe_invoke(cb, *a))
        except tk.TclError:
            return None

    def safe_after_idle(self, callback, *args):
        if not self.is_app_alive():
            return None
        try:
            return self.after_idle(lambda cb=callback, a=args: self.safe_invoke(cb, *a))
        except tk.TclError:
            return None

    def cancel_after_handle(self, handle):
        if not handle:
            return
        try:
            self.after_cancel(handle)
        except Exception:
            pass

    def on_app_close(self):
        if self.app_closing:
            return
        self.app_closing = True
        self.cancel_after_handle(self.poll_process_job)
        self.poll_process_job = None
        self.cancel_after_handle(self.window_resize_job)
        self.window_resize_job = None
        self.cancel_after_handle(self.window_resizing_clear_job)
        self.window_resizing_clear_job = None
        self.cancel_hide_tab_hover_close()
        try:
            self.unbind("<Configure>")
            self.unbind("<B1-Motion>")
            self.unbind("<ButtonRelease-1>")
        except Exception:
            pass
        for tab_id in list(self.active_tabs_data.keys()):
            try:
                self.cleanup_tab_runtime(tab_id)
            except Exception:
                pass
        self.destroy()

    def destroy(self):
        self.app_closing = True
        self.cancel_after_handle(getattr(self, "poll_process_job", None))
        self.poll_process_job = None
        self.cancel_after_handle(getattr(self, "window_resize_job", None))
        self.window_resize_job = None
        self.cancel_after_handle(getattr(self, "window_resizing_clear_job", None))
        self.window_resizing_clear_job = None
        self.cancel_hide_tab_hover_close()
        try:
            super().destroy()
        except tk.TclError:
            pass

    def setup_layout(self):
        # 整个左侧边栏主要对应 style_config 中的 SIDEBAR_BG、option_menu_style 和按钮样式 helper。
        sidebar_menu_height = max(30, HEIGHT_OPTION_MENU - 4)
        sidebar_compact_button_height = max(24, HEIGHT_BUTTON_SM - 4)
        sidebar_section_font = ui_font(13, "bold")
        sidebar_hint_font = ui_font(10)
        sidebar_compact_font = ui_font(12)
        sidebar_compact_path_font = ui_font(10)

        self.sidebar = ctk.CTkFrame(self, width=self.sidebar_expanded_width, corner_radius=RADIUS_OUTER, fg_color=SIDEBAR_BG)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        ctk.CTkLabel(
            self.sidebar,
            text="工作区配置台",
            font=ui_font(24, "bold"),
            text_color=TEXT_PRIMARY,
        ).pack(pady=(24, 6))
        ctk.CTkLabel(
            self.sidebar,
            text="选择奖项、挂载工作区并调度步骤",
            text_color=TEXT_MUTED,
            font=ui_font(12),
        ).pack(pady=(0, 22))
        
        ctk.CTkLabel(self.sidebar, text="选择评选奖项", text_color=TEXT_PRIMARY).pack(anchor="w", padx=22)
        self.award_menu = ctk.CTkOptionMenu(
            self.sidebar,
            values=get_award_labels(),
            command=self.update_year_menu,
            corner_radius=RADIUS_MD,
            height=sidebar_menu_height,
            font=sidebar_compact_font,
            **option_menu_style(),
        )
        self.award_menu.pack(fill="x", padx=20, pady=(5, 15))

        ctk.CTkLabel(self.sidebar, text="选择年份", text_color=TEXT_PRIMARY).pack(anchor="w", padx=22)
        self.year_menu = ctk.CTkOptionMenu(
            self.sidebar,
            values=[],
            command=self.on_year_menu_change,
            corner_radius=RADIUS_MD,
            height=sidebar_menu_height,
            font=sidebar_compact_font,
            **option_menu_style(),
        )
        self.year_menu.pack(fill="x", padx=20, pady=(5, 15))

        ctk.CTkLabel(self.sidebar, text="选择已有工作区", text_color=TEXT_PRIMARY).pack(anchor="w", padx=22)
        self.workspace_menu = ctk.CTkOptionMenu(
            self.sidebar,
            values=[],
            corner_radius=RADIUS_MD,
            height=sidebar_menu_height,
            font=sidebar_compact_font,
            **option_menu_style(),
        )
        self.workspace_menu.pack(fill="x", padx=20, pady=(5, 20))
        
        ctk.CTkButton(
            self.sidebar,
            text="挂载至右侧面板",
            command=self.mount_workspace,
            corner_radius=RADIUS_MD,
            height=HEIGHT_BUTTON,
            font=ui_font(14, "bold"),
            **button_primary_style(),
        ).pack(fill="x", padx=20, pady=(0, 20))

        ctk.CTkButton(
            self.sidebar,
            text="初始化",
            command=self.on_sidebar_initialize_click,
            corner_radius=RADIUS_MD,
            height=HEIGHT_BUTTON,
            font=ui_font(14, "bold"),
            fg_color="#000000",
            hover_color="#1a1a1a",
            text_color="#ffffff",
        ).pack(fill="x", padx=20, pady=(0, 14))

        self.sidebar_scroll_area = ctk.CTkScrollableFrame(
            self.sidebar,
            fg_color="transparent",
            corner_radius=RADIUS_NONE,
        )
        self.sidebar_scroll_area.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        sidebar_resource_card = ctk.CTkFrame(self.sidebar_scroll_area, **panel_card_style())
        sidebar_resource_card.pack(fill="x", padx=4, pady=(0, 12))
        ctk.CTkLabel(
            sidebar_resource_card,
            text="资料浏览",
            text_color=TEXT_PRIMARY,
            font=ui_font(13, "bold"),
        ).pack(anchor="w", padx=8, pady=(8, 1))
        ctk.CTkLabel(
            sidebar_resource_card,
            text="选择当前奖项/年份对应的原始数据集与评奖规则",
            text_color=TEXT_MUTED,
            font=sidebar_hint_font,
            wraplength=138,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(0, 6))

        ctk.CTkLabel(sidebar_resource_card, text="原始数据集", text_color=TEXT_PRIMARY, font=sidebar_section_font).pack(anchor="w", padx=8)
        self.sidebar_dataset_menu = ctk.CTkOptionMenu(
            sidebar_resource_card,
            values=[self.sidebar_unassigned_option_label, self.sidebar_browse_option_label],
            variable=self.sidebar_dataset_var,
            command=self.on_sidebar_dataset_change,
            corner_radius=RADIUS_MD,
            height=sidebar_menu_height,
            font=sidebar_compact_font,
            **option_menu_style(),
        )
        self.sidebar_dataset_menu.pack(fill="x", padx=8, pady=(3, 8))

        ctk.CTkLabel(sidebar_resource_card, text="评奖规则", text_color=TEXT_PRIMARY, font=sidebar_section_font).pack(anchor="w", padx=8)
        self.sidebar_rule_menu = ctk.CTkOptionMenu(
            sidebar_resource_card,
            values=[self.sidebar_unassigned_option_label, self.sidebar_browse_option_label],
            variable=self.sidebar_rule_var,
            command=self.on_sidebar_rule_change,
            corner_radius=RADIUS_MD,
            height=sidebar_menu_height,
            font=sidebar_compact_font,
            **option_menu_style(),
        )
        self.sidebar_rule_menu.pack(fill="x", padx=8, pady=(3, 8))

        ctk.CTkButton(
            sidebar_resource_card,
            text="确定",
            command=self.confirm_sidebar_resource_selection,
            corner_radius=RADIUS_MD,
            height=sidebar_compact_button_height,
            font=sidebar_hint_font,
            **button_primary_style(),
        ).pack(fill="x", padx=8, pady=(0, 8))

        sidebar_db_card = ctk.CTkFrame(self.sidebar_scroll_area, **panel_card_style())
        sidebar_db_card.pack(fill="x", padx=4, pady=(0, 12))
        ctk.CTkLabel(
            sidebar_db_card,
            text="数据库维护",
            text_color=TEXT_PRIMARY,
            font=ui_font(13, "bold"),
        ).pack(anchor="w", padx=8, pady=(8, 1))
        ctk.CTkLabel(
            sidebar_db_card,
            text="按当前奖项与年份执行删库和入库，不从工作区内授权。",
            text_color=TEXT_MUTED,
            font=sidebar_hint_font,
            wraplength=138,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(0, 6))
        sidebar_db_btn_row = ctk.CTkFrame(sidebar_db_card, fg_color="transparent")
        sidebar_db_btn_row.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkButton(
            sidebar_db_btn_row,
            text="删旧库",
            command=self.on_sidebar_delete_database_click,
            corner_radius=RADIUS_MD,
            height=sidebar_compact_button_height,
            font=sidebar_hint_font,
            width=70,
            **button_warning_style(),
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(
            sidebar_db_btn_row,
            text="数据入库",
            command=self.on_sidebar_data_ingestion_click,
            corner_radius=RADIUS_MD,
            height=sidebar_compact_button_height,
            font=sidebar_hint_font,
            width=70,
            **button_primary_style(),
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        self.sidebar_config_card = ctk.CTkFrame(self.sidebar_scroll_area, **panel_card_style())
        self.sidebar_config_card.pack(fill="x", padx=4, pady=(0, 12))
        ctk.CTkLabel(
            self.sidebar_config_card,
            text="配置文件",
            text_color=TEXT_PRIMARY,
            font=ui_font(13, "bold"),
        ).pack(anchor="w", padx=8, pady=(8, 1))
        ctk.CTkLabel(
            self.sidebar_config_card,
            text="数据库下方的配置入口；支持弹出编辑界面和 JSON 导入。",
            text_color=TEXT_MUTED,
            font=sidebar_hint_font,
            wraplength=138,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(0, 6))
        self.sidebar_config_status_label = ctk.CTkLabel(
            self.sidebar_config_card,
            text="当前奖项暂未接入配置文件",
            text_color=TEXT_MUTED,
            font=sidebar_hint_font,
            wraplength=138,
            justify="left",
        )
        self.sidebar_config_status_label.pack(anchor="w", padx=8, pady=(0, 4))
        self.sidebar_config_json_label = ctk.CTkLabel(
            self.sidebar_config_card,
            text="JSON: 未选择",
            text_color=TEXT_MUTED,
            font=sidebar_hint_font,
            wraplength=138,
            justify="left",
        )
        self.sidebar_config_json_label.pack(anchor="w", padx=8, pady=(0, 8))

        sidebar_config_btn_row_1 = ctk.CTkFrame(self.sidebar_config_card, fg_color="transparent")
        sidebar_config_btn_row_1.pack(fill="x", padx=8, pady=(0, 6))
        self.sidebar_open_config_editor_btn = ctk.CTkButton(
            sidebar_config_btn_row_1,
            text="打开配置界面",
            command=self.open_sidebar_config_editor,
            corner_radius=RADIUS_MD,
            height=sidebar_compact_button_height,
            font=sidebar_hint_font,
            width=70,
            **button_primary_style(),
        )
        self.sidebar_open_config_editor_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.sidebar_open_config_file_btn = ctk.CTkButton(
            sidebar_config_btn_row_1,
            text="打开配置文件",
            command=self.open_sidebar_config_file,
            corner_radius=RADIUS_MD,
            height=sidebar_compact_button_height,
            font=sidebar_hint_font,
            width=70,
            **button_secondary_style(),
        )
        self.sidebar_open_config_file_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

        sidebar_config_btn_row_2 = ctk.CTkFrame(self.sidebar_config_card, fg_color="transparent")
        sidebar_config_btn_row_2.pack(fill="x", padx=8, pady=(0, 8))
        self.sidebar_select_config_json_btn = ctk.CTkButton(
            sidebar_config_btn_row_2,
            text="选择 JSON",
            command=self.browse_sidebar_config_json,
            corner_radius=RADIUS_MD,
            height=sidebar_compact_button_height,
            font=sidebar_hint_font,
            width=70,
            **button_secondary_style(),
        )
        self.sidebar_select_config_json_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.sidebar_apply_config_json_btn = ctk.CTkButton(
            sidebar_config_btn_row_2,
            text="应用 JSON",
            command=self.apply_sidebar_config_json,
            corner_radius=RADIUS_MD,
            height=sidebar_compact_button_height,
            font=sidebar_hint_font,
            width=70,
            **button_soft_style(),
        )
        self.sidebar_apply_config_json_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))
        
        self.update_year_menu(self.award_menu.get())

        self.sidebar_toggle_bar = ctk.CTkFrame(self, width=WIDTH_SIDEBAR_TOGGLE_BAR, corner_radius=RADIUS_NONE, fg_color="transparent")
        self.sidebar_toggle_bar.pack(side="left", fill="y")
        self.sidebar_toggle_bar.pack_propagate(False)
        self.sidebar_toggle_btn = ctk.CTkButton(
            self.sidebar_toggle_bar,
            text="<<",
            width=WIDTH_SIDEBAR_TOGGLE_BUTTON,
            height=HEIGHT_TOGGLE,
            corner_radius=RADIUS_MD,
            command=self.toggle_sidebar,
            **button_secondary_style(),
        )
        self.sidebar_toggle_btn.pack(padx=4, pady=(10, 0))

        self.main_area = ctk.CTkFrame(self, fg_color="transparent")
        self.main_area.pack(side="left", fill="both", expand=True)

        # 主标签页外观统一走 tabview_style，面板底色使用 PANEL_BG。
        self.tabview = ctk.CTkTabview(
            self.main_area,
            corner_radius=RADIUS_OUTER,
            **tabview_style(fg_color=PANEL_BG),
        )
        self.tabview.pack(fill="both", expand=True, padx=10, pady=(2, 8))

    def _is_widget_descendant(self, widget, ancestor):
        current = widget
        while current is not None:
            if current == ancestor:
                return True
            try:
                current = current.master
            except Exception:
                return False
        return False

    def _get_tab_segmented_button(self):
        return getattr(self.tabview, "_segmented_button", None)

    def _get_tab_button_widget(self, tab_id):
        segmented = self._get_tab_segmented_button()
        buttons_dict = getattr(segmented, "_buttons_dict", {}) if segmented else {}
        return buttons_dict.get(tab_id)

    def ensure_tab_hover_close_button(self):
        segmented = self._get_tab_segmented_button()
        if not segmented:
            return None
        if self.tab_hover_close_button and self.tab_hover_close_button.winfo_exists():
            return self.tab_hover_close_button
        self.tab_hover_close_button = ctk.CTkButton(
            segmented,
            text="×",
            width=TAB_CLOSE_BUTTON_SIZE,
            height=TAB_CLOSE_BUTTON_SIZE,
            corner_radius=TAB_CLOSE_BUTTON_SIZE // 2,
            font=ui_font(13, "bold"),
            fg_color="transparent",
            hover_color=TAB_CLOSE_HOVER_BG,
            text_color=DANGER,
            border_width=0,
            command=self.close_hovered_tab,
        )
        self.tab_hover_close_button.bind("<Enter>", lambda _event: self.cancel_hide_tab_hover_close())
        self.tab_hover_close_button.bind("<Leave>", lambda _event: self.schedule_hide_tab_hover_close())
        return self.tab_hover_close_button

    def cancel_hide_tab_hover_close(self):
        if self.tab_hover_hide_job:
            self.after_cancel(self.tab_hover_hide_job)
            self.tab_hover_hide_job = None

    def schedule_hide_tab_hover_close(self):
        self.cancel_hide_tab_hover_close()
        self.tab_hover_hide_job = self.safe_after(120, self.maybe_hide_tab_hover_close)

    def maybe_hide_tab_hover_close(self):
        self.tab_hover_hide_job = None
        if not self.tab_hover_close_button or not self.tab_hover_close_button.winfo_exists():
            return
        pointer_widget = self.winfo_containing(self.winfo_pointerx(), self.winfo_pointery())
        if pointer_widget:
            if self._is_widget_descendant(pointer_widget, self.tab_hover_close_button):
                return
            button_widget = self._get_tab_button_widget(self.tab_hover_close_target)
            if button_widget and self._is_widget_descendant(pointer_widget, button_widget):
                return
        self.hide_tab_hover_close()

    def hide_tab_hover_close(self):
        self.cancel_hide_tab_hover_close()
        self.tab_hover_close_target = None
        if self.tab_hover_close_button and self.tab_hover_close_button.winfo_exists():
            self.tab_hover_close_button.place_forget()

    def show_tab_hover_close(self, tab_id):
        button_widget = self._get_tab_button_widget(tab_id)
        close_button = self.ensure_tab_hover_close_button()
        if not button_widget or not close_button or not button_widget.winfo_exists():
            return
        self.cancel_hide_tab_hover_close()
        self.tab_hover_close_target = tab_id
        button_widget.update_idletasks()
        close_button.place(
            in_=button_widget,
            relx=1.0,
            x=TAB_CLOSE_OFFSET_X,
            y=TAB_CLOSE_OFFSET_Y,
            anchor="ne",
        )
        close_button.lift()

    def close_hovered_tab(self):
        tab_id = self.tab_hover_close_target
        self.hide_tab_hover_close()
        if tab_id:
            self.close_tab(tab_id)

    def refresh_tab_hover_close_bindings(self):
        segmented = self._get_tab_segmented_button()
        if not segmented:
            return
        buttons_dict = getattr(segmented, "_buttons_dict", {})
        for tab_id, button_widget in buttons_dict.items():
            if getattr(button_widget, "_gb_hover_close_bound", False):
                continue
            button_widget._gb_hover_close_bound = True
            button_widget.bind("<Enter>", lambda _event, tid=tab_id: self.show_tab_hover_close(tid), add="+")
            button_widget.bind("<Leave>", lambda _event: self.schedule_hide_tab_hover_close(), add="+")
        self.hide_tab_hover_close()
        self.refresh_all_workspace_tab_button_styles()

    def get_sidebar_award_root(self, award_name):
        folder = get_award_folder(award_name)
        if not folder:
            return ""
        return os.path.normpath(os.path.abspath(folder))

    def get_sidebar_award_config_path(self, award_name):
        return get_award_config_file(award_name, project_root=os.path.dirname(os.path.abspath(__file__)))

    def get_sidebar_award_config_label(self, award_name):
        return get_award_config_label(award_name) or "配置文件"

    def has_sidebar_award_config(self, award_name):
        return has_award_config(award_name, project_root=os.path.dirname(os.path.abspath(__file__)))

    def clear_sidebar_initialize_context(self):
        self.sidebar_initialize_context = {"active": False, "award": "", "year": "", "armed_at": 0.0}

    def get_award_initialize_script_path(self, award_root):
        award_root = _clean(award_root)
        if not award_root or not os.path.isdir(award_root):
            return ""
        candidate = os.path.join(award_root, "initialize.py")
        if os.path.isfile(candidate):
            return candidate
        return ""

    def on_sidebar_initialize_click(self):
        award_name = self.award_menu.get()
        year_text = _clean(self.year_menu.get())
        award_root = self.get_sidebar_award_root(award_name)
        if not award_root or not year_text or year_text == "无可用年份":
            messagebox.showinfo("提示", "请先选择有效的奖项和年份。")
            return
        script_path = self.get_award_initialize_script_path(award_root)
        if not script_path:
            messagebox.showwarning("未找到初始化脚本", f"未在奖项根目录找到 initialize.py：\n{award_root}")
            return
        self.sidebar_initialize_context = {"active": True, "award": award_name, "year": year_text, "armed_at": time.time()}
        threading.Thread(
            target=self._run_award_initialize_worker,
            args=(award_root, script_path, award_name, year_text),
            daemon=True,
        ).start()

    def _run_award_initialize_worker(self, award_root, script_path, award_name, year_text):
        ok = False
        detail = ""
        try:
            result = subprocess.run(
                [sys.executable, script_path],
                cwd=award_root,
                capture_output=True,
                text=True,
                env=os.environ.copy(),
            )
            ok = result.returncode == 0
            detail = (result.stdout or "").strip() or (result.stderr or "").strip()
        except Exception as exc:
            ok = False
            detail = str(exc)
        self.safe_after(0, self._after_award_initialize_worker, ok, award_name, year_text, script_path, detail)

    def summarize_initialize_output(self, detail, ok=True):
        lines = [line.strip() for line in str(detail or "").splitlines() if line.strip()]
        if not lines or ok:
            return ""
        priority_keywords = ("error", "exception", "failed", "失败", "异常", "报错", "traceback")
        key_lines = [line for line in lines if any(keyword in line.lower() for keyword in priority_keywords)]
        picked = key_lines[:3] if key_lines else lines[-3:]
        return "\n".join(picked[:3])

    def _after_award_initialize_worker(self, ok, award_name, year_text, script_path, detail):
        title = "初始化完成" if ok else "初始化失败"
        script_name = os.path.basename(script_path)
        msg = f"{award_name} · {year_text}\n脚本: {script_name}"
        summary = self.summarize_initialize_output(detail, ok=ok)
        if summary:
            msg = f"{msg}\n\n关键信息:\n{summary}"
        if not ok:
            self.clear_sidebar_initialize_context()
        else:
            current_workspace = self.resolve_workspace_menu_selection(award_name, year_text)
            self.award_menu.set(award_name)
            self.update_year_menu(award_name, selected_year=year_text, selected_workspace=current_workspace)
        if ok:
            messagebox.showinfo(title, msg)
        else:
            messagebox.showerror(title, msg)

    def get_award_resource_config_path(self, award_name):
        award_root = self.get_sidebar_award_root(award_name)
        if not award_root:
            return ""
        return os.path.join(award_root, "奖项资料配置.json")

    def load_award_resource_config(self, award_name):
        path = self.get_award_resource_config_path(award_name)
        payload = self.read_json_file(path, default={})
        return payload if isinstance(payload, dict) else {}

    def save_award_resource_config(self, award_name, payload):
        path = self.get_award_resource_config_path(award_name)
        if not path:
            return
        self.write_json_file(path, payload)

    def get_award_year_fixed_resources(self, award_name, selected_year):
        year_text = _clean(selected_year)
        config = self.load_award_resource_config(award_name)
        years = config.get("years", {})
        if not year_text or not isinstance(years, dict):
            return {}
        item = years.get(year_text, {})
        return item if isinstance(item, dict) else {}

    def save_award_year_fixed_resource(self, award_name, selected_year, resource_key, path):
        year_text = _clean(selected_year)
        if not award_name or not year_text or resource_key not in {"dataset_path", "rule_path", "config_json_path"}:
            return
        config = self.load_award_resource_config(award_name)
        years = config.get("years")
        if not isinstance(years, dict):
            years = {}
        year_payload = years.get(year_text)
        if not isinstance(year_payload, dict):
            year_payload = {}
        resolved_path = os.path.normpath(os.path.abspath(path))
        year_payload[resource_key] = resolved_path
        year_payload["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        years[year_text] = year_payload
        config["version"] = 1
        config["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        config["years"] = years
        self.save_award_resource_config(award_name, config)

    def clear_award_year_fixed_resources(self, award_name, selected_year, resource_keys=None):
        year_text = _clean(selected_year)
        if not award_name or not year_text:
            return
        config = self.load_award_resource_config(award_name)
        years = config.get("years")
        if not isinstance(years, dict) or year_text not in years:
            return
        year_payload = years.get(year_text)
        if not isinstance(year_payload, dict):
            year_payload = {}
        keys = resource_keys or ["dataset_path", "rule_path", "config_json_path"]
        for key in keys:
            year_payload.pop(key, None)
        if any(_clean(year_payload.get(key)) for key in ("dataset_path", "rule_path", "config_json_path")):
            year_payload["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            years[year_text] = year_payload
        else:
            years.pop(year_text, None)
        config["version"] = 1
        config["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        config["years"] = years
        self.save_award_resource_config(award_name, config)

    def refresh_sidebar_config_browser(self, selected_award=None, selected_year=None):
        award_name = selected_award or self.award_menu.get()
        year_text = _clean(selected_year or self.year_menu.get())
        valid_year = bool(year_text and year_text != "无可用年份")
        config_label = self.get_sidebar_award_config_label(award_name)
        config_path = self.get_sidebar_award_config_path(award_name)
        fixed_resources = self.get_award_year_fixed_resources(award_name, year_text) if valid_year else {}
        config_json_path = _clean(fixed_resources.get("config_json_path"))

        has_mapping = bool(config_path)
        config_exists = bool(config_path and os.path.isfile(config_path))
        if not has_mapping:
            status_text = "当前奖项暂未接入配置文件"
        elif not config_exists:
            status_text = f"{config_label}\n未找到: {config_path}"
        else:
            status_text = f"{config_label}\n{os.path.relpath(config_path, os.path.dirname(os.path.abspath(__file__)))}"
        self.sidebar_config_status_label.configure(text=status_text)

        if config_json_path and os.path.isfile(config_json_path):
            json_text = f"JSON: {os.path.basename(config_json_path)}"
        elif config_json_path:
            json_text = f"JSON: 路径失效\n{config_json_path}"
        else:
            json_text = "JSON: 未选择"
        self.sidebar_config_json_label.configure(text=json_text)

        editor_state = "normal" if (valid_year and config_exists) else "disabled"
        file_state = "normal" if config_exists else "disabled"
        json_state = "normal" if (valid_year and has_mapping) else "disabled"
        apply_state = "normal" if (valid_year and config_exists and config_json_path and os.path.isfile(config_json_path)) else "disabled"
        self.sidebar_open_config_editor_btn.configure(state=editor_state)
        self.sidebar_open_config_file_btn.configure(state=file_state)
        self.sidebar_select_config_json_btn.configure(state=json_state)
        self.sidebar_apply_config_json_btn.configure(state=apply_state)

    def browse_sidebar_config_json(self):
        award_name = self.award_menu.get()
        year_text = _clean(self.year_menu.get())
        config_path = self.get_sidebar_award_config_path(award_name)
        if not award_name or not year_text or year_text == "无可用年份":
            messagebox.showinfo("提示", "请先选择有效的奖项和年份。")
            return ""
        initial_dir = os.path.dirname(config_path) if config_path and os.path.isfile(config_path) else os.path.dirname(os.path.abspath(__file__))
        selected_path = filedialog.askopenfilename(
            parent=self,
            title=f"选择 {award_name} {year_text} 的配置 JSON",
            initialdir=initial_dir,
            filetypes=[
                ("JSON 文件", "*.json"),
                ("文本文件", "*.txt"),
                ("所有文件", "*.*"),
            ],
        )
        if not selected_path:
            return ""
        selected_path = os.path.normpath(os.path.abspath(selected_path))
        if not os.path.isfile(selected_path):
            messagebox.showwarning("提示", f"所选路径不是文件:\n{selected_path}")
            return ""
        self.save_award_year_fixed_resource(award_name, year_text, "config_json_path", selected_path)
        self.refresh_sidebar_config_browser(award_name, year_text)
        return selected_path

    def _ensure_sidebar_config_editor(self, award_name, year_text):
        config_path = self.get_sidebar_award_config_path(award_name)
        normalized_year = _clean(year_text)
        if not config_path:
            messagebox.showinfo("提示", f"{award_name} 暂未配置映射文件。")
            return None
        if not os.path.isfile(config_path):
            messagebox.showwarning("未找到配置文件", f"未找到配置文件:\n{config_path}")
            return None
        if self.config_editor_window and self.config_editor_window.winfo_exists():
            try:
                same_file = os.path.normcase(self.config_editor_window.config_file_path) == os.path.normcase(os.path.normpath(config_path))
                same_year = _clean(getattr(self.config_editor_window, "year_text", "")) == normalized_year
                if same_file and same_year:
                    self.config_editor_window.focus()
                    self.config_editor_window.lift()
                    return self.config_editor_window
                self.config_editor_window.destroy()
            except Exception:
                self.config_editor_window = None
            self.config_editor_window = None
        try:
            self.config_editor_window = ConfigEditorWindow(
                self,
                award_name=award_name,
                year_text=normalized_year,
                config_file_path=config_path,
                config_label=self.get_sidebar_award_config_label(award_name),
                on_saved=lambda _path: self.refresh_sidebar_config_browser(award_name, normalized_year),
            )
        except Exception as exc:
            messagebox.showerror("打开配置界面失败", str(exc))
            self.config_editor_window = None
            return None
        return self.config_editor_window

    def open_sidebar_config_editor(self):
        award_name = self.award_menu.get()
        year_text = _clean(self.year_menu.get())
        if not award_name or not year_text or year_text == "无可用年份":
            messagebox.showinfo("提示", "请先选择有效的奖项和年份。")
            return
        self._ensure_sidebar_config_editor(award_name, year_text)

    def apply_sidebar_config_json(self):
        award_name = self.award_menu.get()
        year_text = _clean(self.year_menu.get())
        if not award_name or not year_text or year_text == "无可用年份":
            messagebox.showinfo("提示", "请先选择有效的奖项和年份。")
            return
        fixed_resources = self.get_award_year_fixed_resources(award_name, year_text)
        json_path = _clean(fixed_resources.get("config_json_path"))
        if not json_path:
            messagebox.showinfo("提示", "请先选择一个 JSON 文件。")
            return
        editor = self._ensure_sidebar_config_editor(award_name, year_text)
        if not editor:
            return
        editor.load_json_file(json_path)

    def open_sidebar_config_file(self):
        award_name = self.award_menu.get()
        config_path = self.get_sidebar_award_config_path(award_name)
        if not config_path or not os.path.isfile(config_path):
            messagebox.showwarning("未找到配置文件", f"未找到配置文件:\n{config_path}")
            return
        try:
            self.open_file(config_path)
        except Exception as exc:
            messagebox.showerror("打开配置文件失败", str(exc))

    def _find_sidebar_display_label_by_path(self, display_map, path):
        target = os.path.normcase(os.path.normpath(path))
        for label, raw_path in display_map.items():
            if os.path.normcase(os.path.normpath(raw_path)) == target:
                return label
        return ""

    def _get_sidebar_custom_resource_path(self, award_name, selected_year, resource_kind):
        key = (_clean(award_name), _clean(selected_year), resource_kind)
        return _clean(self.sidebar_custom_resource_paths.get(key))

    def _set_sidebar_custom_resource_path(self, award_name, selected_year, resource_kind, path):
        key = (_clean(award_name), _clean(selected_year), resource_kind)
        resolved_path = _clean(path)
        if resolved_path:
            self.sidebar_custom_resource_paths[key] = os.path.normpath(os.path.abspath(resolved_path))
        else:
            self.sidebar_custom_resource_paths.pop(key, None)

    def _make_sidebar_resource_options(self, root_dir, entries):
        if not entries:
            return {}, []
        items = []
        for entry in entries:
            path = os.path.normpath(entry["path"])
            label = _clean(entry.get("label")) or os.path.basename(path) or path
            rel_path = ""
            try:
                rel_path = os.path.relpath(path, root_dir).replace(os.sep, " / ")
            except Exception:
                rel_path = path
            items.append((label, rel_path, path))
        items.sort(key=lambda item: (_natural_sort_key(item[0]), _natural_sort_key(item[1])))
        display_map = {}
        used = set()
        for label, rel_path, path in items:
            candidate = label
            if candidate in used:
                candidate = f"{label} · {rel_path}"
            if candidate in used:
                candidate = rel_path
            if candidate in used:
                candidate = path
            used.add(candidate)
            display_map[candidate] = path
        return display_map, list(display_map.keys())

    def _gather_original_dataset_entries(self, award_root, selected_year):
        entries = []
        seen = set()
        year_text = _clean(selected_year)
        search_roots = [award_root]
        parent_root = os.path.dirname(award_root)
        if not os.path.isdir(os.path.join(award_root, "原始数据集")) and os.path.isdir(os.path.join(parent_root, "原始数据集")):
            search_roots.append(parent_root)
        for root_dir in search_roots:
            original_root = os.path.join(root_dir, "原始数据集")
            candidate_dirs = []
            if year_text:
                candidate_dirs.append((f"{year_text} 原始数据集", os.path.join(original_root, year_text)))
            candidate_dirs.extend(
                [
                    ("原始数据集", original_root),
                    (f"{year_text} 资料 / 原始数据集", os.path.join(root_dir, "资料", "原始数据集", year_text)) if year_text else None,
                    ("资料 / 原始数据集", os.path.join(root_dir, "资料", "原始数据集")),
                ]
            )
            for item in candidate_dirs:
                if not item:
                    continue
                label, path = item
                norm_path = os.path.normpath(path)
                if norm_path in seen or not os.path.isdir(norm_path):
                    continue
                seen.add(norm_path)
                entries.append({"label": label, "path": norm_path})
            if not os.path.isdir(original_root):
                continue
            try:
                names = sorted(os.listdir(original_root), key=_natural_sort_key)
            except OSError:
                names = []
            for name in names:
                abs_path = os.path.join(original_root, name)
                if not os.path.isdir(abs_path):
                    continue
                if year_text and year_text not in name:
                    continue
                norm_path = os.path.normpath(abs_path)
                if norm_path in seen:
                    continue
                seen.add(norm_path)
                entries.append({"label": name, "path": norm_path})
        return entries

    def _gather_rule_entries(self, award_root, selected_year):
        entries = []
        seen = set()
        year_text = _clean(selected_year)
        allowed_exts = {".doc", ".docx", ".pdf", ".txt", ".md"}
        ignore_dirs = {"__pycache__", ".git", ".idea", "myenv", "userlib", "代码备份", "_log", "logs"}
        primary_keywords = ("评选方案", "评奖规则", "参评须知")
        fallback_keywords = ("方案", "规则", "须知")
        scored_entries = []
        search_roots = [award_root]
        parent_root = os.path.dirname(award_root)
        if not os.path.isdir(os.path.join(award_root, "原始数据集")) and os.path.isdir(parent_root):
            search_roots.append(parent_root)

        for search_root in search_roots:
            for root, dir_names, file_names in os.walk(search_root):
                rel_root = os.path.relpath(root, search_root)
                if rel_root == ".":
                    depth = 0
                else:
                    depth = rel_root.count(os.sep) + 1
                dir_names[:] = [
                    name for name in dir_names
                    if name not in ignore_dirs and not name.startswith(".") and depth < 5
                ]
                for name in file_names:
                    ext = os.path.splitext(name)[1].lower()
                    if ext not in allowed_exts:
                        continue
                    matched = None
                    if any(keyword in name for keyword in primary_keywords):
                        matched = "primary"
                    elif any(keyword in name for keyword in fallback_keywords):
                        matched = "fallback"
                    if not matched:
                        continue
                    abs_path = os.path.normpath(os.path.join(root, name))
                    score = 0
                    if matched == "primary":
                        score += 40
                    if year_text and year_text in abs_path:
                        score += 20
                    if "方案资料" in abs_path or "方案&结果" in abs_path:
                        score += 15
                    if "原始数据集" in abs_path:
                        score += 10
                    if "说明" in abs_path:
                        score -= 8
                    if search_root != award_root:
                        score -= 3
                    score -= depth
                    scored_entries.append((score, name, abs_path))

        scored_entries.sort(key=lambda item: (-item[0], _natural_sort_key(item[1]), item[2]))
        for _score, name, path in scored_entries[:20]:
            if path in seen:
                continue
            seen.add(path)
            entries.append({"label": name, "path": path})
        return entries

    def _build_sidebar_resource_values(self, award_root, entries, fixed_path="", custom_path=""):
        display_map, labels = self._make_sidebar_resource_options(award_root, entries)
        fixed_label = self._find_sidebar_display_label_by_path(display_map, fixed_path) if fixed_path else ""
        custom_label = self._find_sidebar_display_label_by_path(display_map, custom_path) if custom_path else ""
        if fixed_path and not fixed_label:
            fixed_entry = {"label": f"已指定 · {os.path.basename(fixed_path) or fixed_path}", "path": fixed_path}
            display_map, labels = self._make_sidebar_resource_options(award_root, [fixed_entry, *entries])
            fixed_label = self._find_sidebar_display_label_by_path(display_map, fixed_path)
            custom_label = self._find_sidebar_display_label_by_path(display_map, custom_path) if custom_path else custom_label
        if custom_path and not custom_label:
            custom_entry = {"label": f"自选 · {os.path.basename(custom_path) or custom_path}", "path": custom_path}
            display_map, labels = self._make_sidebar_resource_options(award_root, [custom_entry, *entries])
            fixed_label = self._find_sidebar_display_label_by_path(display_map, fixed_path) if fixed_path else fixed_label
            custom_label = self._find_sidebar_display_label_by_path(display_map, custom_path)
        values = [self.sidebar_unassigned_option_label, *labels, self.sidebar_browse_option_label]
        return display_map, values, fixed_label, custom_label

    def refresh_sidebar_resource_browser(self, selected_award=None, selected_year=None, preferred_dataset_path="", preferred_rule_path=""):
        award_name = selected_award or self.award_menu.get()
        year_text = selected_year or self.year_menu.get()
        award_root = self.get_sidebar_award_root(award_name)
        fixed_resources = self.get_award_year_fixed_resources(award_name, year_text)
        fixed_dataset_path = _clean(fixed_resources.get("dataset_path"))
        fixed_rule_path = _clean(fixed_resources.get("rule_path"))
        custom_dataset_path = self._get_sidebar_custom_resource_path(award_name, year_text, "dataset")
        custom_rule_path = self._get_sidebar_custom_resource_path(award_name, year_text, "rule")
        dataset_entries = self._gather_original_dataset_entries(award_root, year_text) if award_root else []
        rule_entries = self._gather_rule_entries(award_root, year_text) if award_root else []

        dataset_map, dataset_values, fixed_dataset_label, custom_dataset_label = self._build_sidebar_resource_values(
            award_root,
            dataset_entries,
            fixed_dataset_path,
            custom_dataset_path,
        )
        rule_map, rule_values, fixed_rule_label, custom_rule_label = self._build_sidebar_resource_values(
            award_root,
            rule_entries,
            fixed_rule_path,
            custom_rule_path,
        )
        self.sidebar_dataset_map = dataset_map
        self.sidebar_rule_map = rule_map
        self.sidebar_dataset_menu.configure(values=dataset_values)
        self.sidebar_rule_menu.configure(values=rule_values)

        current_dataset = self.sidebar_dataset_var.get()
        current_rule = self.sidebar_rule_var.get()
        preferred_dataset_label = self._find_sidebar_display_label_by_path(dataset_map, preferred_dataset_path) if preferred_dataset_path else ""
        preferred_rule_label = self._find_sidebar_display_label_by_path(rule_map, preferred_rule_path) if preferred_rule_path else ""
        self.sidebar_dataset_var.set(
            current_dataset
            if current_dataset in dataset_map or current_dataset == self.sidebar_unassigned_option_label
            else (preferred_dataset_label or fixed_dataset_label or custom_dataset_label or self.sidebar_unassigned_option_label)
        )
        self.sidebar_rule_var.set(
            current_rule
            if current_rule in rule_map or current_rule == self.sidebar_unassigned_option_label
            else (preferred_rule_label or fixed_rule_label or custom_rule_label or self.sidebar_unassigned_option_label)
        )
        self.refresh_sidebar_config_browser(award_name, year_text)

    def browse_sidebar_dataset(self):
        award_name = self.award_menu.get()
        year_text = _clean(self.year_menu.get())
        award_root = self.get_sidebar_award_root(award_name)
        if not award_root or not year_text or year_text == "无可用年份":
            messagebox.showinfo("提示", "请先选择有效的奖项和年份。")
            return ""
        current_path = self.sidebar_dataset_map.get(self.sidebar_dataset_var.get(), "")
        initial_dir = current_path if current_path and os.path.isdir(current_path) else os.path.join(award_root, "原始数据集")
        if not os.path.isdir(initial_dir):
            initial_dir = award_root
        selected_path = filedialog.askdirectory(
            parent=self,
            title=f"选择 {award_name} {year_text} 的原始数据集文件夹",
            initialdir=initial_dir,
            mustexist=True,
        )
        if not selected_path:
            return ""
        selected_path = os.path.normpath(os.path.abspath(selected_path))
        if not os.path.isdir(selected_path):
            messagebox.showwarning("提示", f"所选路径不是文件夹:\n{selected_path}")
            return ""
        self._set_sidebar_custom_resource_path(award_name, year_text, "dataset", selected_path)
        self.refresh_sidebar_resource_browser(award_name, year_text, preferred_dataset_path=selected_path)
        return selected_path

    def browse_sidebar_rule(self):
        award_name = self.award_menu.get()
        year_text = _clean(self.year_menu.get())
        award_root = self.get_sidebar_award_root(award_name)
        if not award_root or not year_text or year_text == "无可用年份":
            messagebox.showinfo("提示", "请先选择有效的奖项和年份。")
            return ""
        current_path = self.sidebar_rule_map.get(self.sidebar_rule_var.get(), "")
        initial_dir = os.path.dirname(current_path) if current_path and os.path.isfile(current_path) else award_root
        selected_path = filedialog.askopenfilename(
            parent=self,
            title=f"选择 {award_name} {year_text} 的评奖规则文件",
            initialdir=initial_dir,
            filetypes=[
                ("文档文件", "*.docx *.doc *.pdf *.md *.txt"),
                ("所有文件", "*.*"),
            ],
        )
        if not selected_path:
            return ""
        selected_path = os.path.normpath(os.path.abspath(selected_path))
        if not os.path.isfile(selected_path):
            messagebox.showwarning("提示", f"所选路径不是文件:\n{selected_path}")
            return ""
        self._set_sidebar_custom_resource_path(award_name, year_text, "rule", selected_path)
        self.refresh_sidebar_resource_browser(award_name, year_text, preferred_rule_path=selected_path)
        return selected_path

    def on_sidebar_dataset_change(self, selected_value):
        if selected_value == self.sidebar_browse_option_label:
            selected_path = self.browse_sidebar_dataset()
            if not selected_path:
                self.refresh_sidebar_resource_browser(self.award_menu.get(), self.year_menu.get())

    def on_sidebar_rule_change(self, selected_value):
        if selected_value == self.sidebar_browse_option_label:
            selected_path = self.browse_sidebar_rule()
            if not selected_path:
                self.refresh_sidebar_resource_browser(self.award_menu.get(), self.year_menu.get())

    def refresh_resource_assignment_tabs(self, award_name, selected_year):
        year_text = _clean(selected_year)
        for tab_id, tab_data in list(self.active_tabs_data.items()):
            if _clean(tab_data.get("award")) != _clean(award_name):
                continue
            manifest = tab_data.get("manifest", {})
            workspace_folder = os.path.basename(manifest.get("workspace_root", ""))
            if self.get_workspace_year(workspace_folder) != year_text:
                continue
            try:
                self.render_resource_panel(tab_id)
            except Exception:
                continue

    def confirm_sidebar_resource_selection(self):
        award_name = self.award_menu.get()
        year_text = _clean(self.year_menu.get())
        if not award_name or not year_text or year_text == "无可用年份":
            messagebox.showinfo("提示", "请先选择有效的奖项和年份。")
            return
        dataset_label = self.sidebar_dataset_var.get()
        rule_label = self.sidebar_rule_var.get()
        if dataset_label == self.sidebar_browse_option_label or rule_label == self.sidebar_browse_option_label:
            messagebox.showinfo("提示", "请先完成浏览选择，再点击确定。")
            return

        dataset_path = self.sidebar_dataset_map.get(dataset_label, "")
        rule_path = self.sidebar_rule_map.get(rule_label, "")
        if dataset_label not in {self.sidebar_unassigned_option_label, ""} and not dataset_path:
            messagebox.showwarning("提示", "当前原始数据集选择无效，请重新选择。")
            return
        if rule_label not in {self.sidebar_unassigned_option_label, ""} and not rule_path:
            messagebox.showwarning("提示", "当前评奖规则选择无效，请重新选择。")
            return

        if dataset_label == self.sidebar_unassigned_option_label:
            self.clear_award_year_fixed_resources(award_name, year_text, ["dataset_path"])
            self._set_sidebar_custom_resource_path(award_name, year_text, "dataset", "")
            dataset_path = ""
        else:
            self.save_award_year_fixed_resource(award_name, year_text, "dataset_path", dataset_path)
        if rule_label == self.sidebar_unassigned_option_label:
            self.clear_award_year_fixed_resources(award_name, year_text, ["rule_path"])
            self._set_sidebar_custom_resource_path(award_name, year_text, "rule", "")
            rule_path = ""
        else:
            self.save_award_year_fixed_resource(award_name, year_text, "rule_path", rule_path)

        self.refresh_sidebar_resource_browser(
            award_name,
            year_text,
            preferred_dataset_path=dataset_path,
            preferred_rule_path=rule_path,
        )
        self.refresh_resource_assignment_tabs(award_name, year_text)
        messagebox.showinfo("已更新", f"已更新 {award_name} {year_text} 的资料指定。")

    def is_workspace_tab_running(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return False
        if self.is_main_process_running(tab_id) or self.has_async_processes(tab_id):
            return True
        if tab_data.get("run_timer_running") or tab_data.get("attempt_active"):
            return True
        return any(state == "running" for state in tab_data.get("step_states", {}).values())

    def get_workspace_tab_button_style(self, tab_id, selected=False, breathing=False):
        if self.is_workspace_tab_running(tab_id):
            if breathing:
                return SUCCESS_HOVER, "#065F46", TEXT_INVERSE
            return "#10B981", SUCCESS_HOVER, TEXT_INVERSE
        if selected:
            return ACCENT, ACCENT_HOVER, TEXT_INVERSE
        return ACCENT_SEGMENT_BG, ACCENT_SEGMENT_HOVER, TEXT_PRIMARY

    def refresh_workspace_tab_button_style(self, tab_id):
        button_widget = self._get_tab_button_widget(tab_id)
        if not button_widget or not button_widget.winfo_exists():
            return
        tab_data = self.active_tabs_data.get(tab_id, {})
        try:
            selected = self.tabview.get() == tab_id
        except Exception:
            selected = False
        fg_color, hover_color, text_color = self.get_workspace_tab_button_style(
            tab_id,
            selected=selected,
            breathing=bool(tab_data.get("tab_breath_on")),
        )
        try:
            button_widget.configure(fg_color=fg_color, hover_color=hover_color, text_color=text_color)
        except Exception:
            return

    def refresh_all_workspace_tab_button_styles(self):
        for tab_id in list(self.active_tabs_data.keys()):
            self.refresh_workspace_tab_button_style(tab_id)

    def stop_workspace_tab_breathing(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        job = tab_data.get("tab_breath_job")
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        tab_data["tab_breath_job"] = None
        tab_data["tab_breath_on"] = False
        self.refresh_workspace_tab_button_style(tab_id)

    def tick_workspace_tab_breathing(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["tab_breath_job"] = None
        if not self.is_workspace_tab_running(tab_id):
            self.stop_workspace_tab_breathing(tab_id)
            return
        tab_data["tab_breath_on"] = not bool(tab_data.get("tab_breath_on"))
        self.refresh_workspace_tab_button_style(tab_id)
        self.ensure_workspace_tab_breathing(tab_id)

    def ensure_workspace_tab_breathing(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if not self.is_workspace_tab_running(tab_id):
            self.stop_workspace_tab_breathing(tab_id)
            return
        self.refresh_workspace_tab_button_style(tab_id)
        if tab_data.get("tab_breath_job"):
            return
        tab_data["tab_breath_job"] = self.safe_after(520, self.tick_workspace_tab_breathing, tab_id)

    def on_window_configure(self, event):
        if event.widget is not self:
            return
        if self.suppress_window_configure:
            return
        self.window_resizing = True
        self.cancel_after_handle(self.window_resizing_clear_job)
        self.window_resizing_clear_job = self.safe_after(260, self._clear_window_resizing_state)
        if self.window_resize_job:
            self.after_cancel(self.window_resize_job)
        self.window_resize_job = self.safe_after(120, self.apply_adaptive_layout)

    def _clear_window_resizing_state(self):
        self.window_resizing_clear_job = None
        self.window_resizing = False

    def get_default_console_height(self, window_height=None):
        height = window_height or self.winfo_height()
        if height <= 1:
            height = 780
        return max(CONSOLE_MIN_HEIGHT, int(height * 0.5))

    def update_sidebar_width(self, width):
        self.sidebar_expanded_width = width
        if not self.sidebar_collapsed:
            self.sidebar.configure(width=width)

    def update_sidebar_toggle_button(self):
        self.sidebar_toggle_btn.configure(text=">>" if self.sidebar_collapsed else "<<")

    def set_sidebar_collapsed(self, collapsed, auto=False):
        if collapsed == self.sidebar_collapsed:
            if not collapsed:
                self.update_sidebar_width(self.sidebar_expanded_width)
            self.update_sidebar_toggle_button()
            return
        if collapsed:
            self.sidebar.pack_forget()
        else:
            self.sidebar.pack(side="left", fill="y", before=self.sidebar_toggle_bar)
            self.update_sidebar_width(self.sidebar_expanded_width)
        self.sidebar_collapsed = collapsed
        if not auto:
            self.sidebar_user_locked = True
        self.update_sidebar_toggle_button()

    def toggle_sidebar(self):
        self.set_sidebar_collapsed(not self.sidebar_collapsed, auto=False)

    def remember_console_height(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        console_container = tab_data.get("console_container")
        if console_container and console_container.winfo_exists():
            tab_data["console_height"] = max(CONSOLE_MIN_HEIGHT, console_container.winfo_height())

    def on_console_sash_release(self, tab_id, _event=None):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if tab_data.get("console_resizing"):
            tab_data["console_resizing"] = False
            tab_data["console_resize_start_y"] = None
            tab_data["console_resize_start_height"] = None
            self.console_resize_active_tab = None
            self.unbind("<B1-Motion>")
            self.unbind("<ButtonRelease-1>")
        tab_data["console_user_locked"] = True
        self.safe_after_idle(self.remember_console_height, tab_id)

    def apply_console_height(self, tab_id, target_height=None, remember=True):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        console_container = tab_data.get("console_container")
        main_view = tab_data.get("main_view")
        content_container = tab_data.get("content_container")
        console_sash = tab_data.get("console_sash")
        if not console_container or not console_container.winfo_exists() or not main_view or not main_view.winfo_exists():
            return
        total_height = main_view.winfo_height()
        if total_height <= 1:
            self.safe_after(80, self.apply_console_height, tab_id, target_height, remember)
            return
        min_console = CONSOLE_MIN_HEIGHT
        max_console = max(min_console, total_height - CONSOLE_DEFAULT_LG)
        if max_console <= min_console:
            return
        desired_console = target_height if target_height is not None else tab_data.get("console_height", self.get_default_console_height())
        desired_console = max(min_console, min(desired_console, max_console))
        console_container.configure(height=desired_console)
        console_container.pack_propagate(False)
        sash_height = HEIGHT_SASH
        if console_sash and console_sash.winfo_exists():
            try:
                sash_height = max(HEIGHT_SASH, console_sash.winfo_height())
            except Exception:
                sash_height = HEIGHT_SASH
        if content_container and content_container.winfo_exists():
            content_height = max(150, total_height - desired_console - sash_height - 10)
            content_container.configure(height=content_height)
        if remember:
            tab_data["console_height"] = desired_console

    def start_console_resize(self, tab_id, event):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if self.console_resize_active_tab is not None and self.console_resize_active_tab != tab_id:
            self.on_console_sash_release(self.console_resize_active_tab)
        tab_data["console_resize_start_y"] = event.y_root
        console_container = tab_data.get("console_container")
        current_height = tab_data.get("console_height", self.get_default_console_height())
        if console_container and console_container.winfo_exists():
            current_height = max(CONSOLE_MIN_HEIGHT, console_container.winfo_height())
        tab_data["console_resize_start_height"] = current_height
        tab_data["console_resizing"] = True
        self.console_resize_active_tab = tab_id
        self.bind("<B1-Motion>", lambda e, tid=tab_id: self.drag_console_resize(tid, e))
        self.bind("<ButtonRelease-1>", lambda e, tid=tab_id: self.on_console_sash_release(tid, e))

    def drag_console_resize(self, tab_id, event):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if not tab_data.get("console_resizing"):
            return
        start_y = tab_data.get("console_resize_start_y")
        start_height = tab_data.get("console_resize_start_height")
        if start_y is None or start_height is None:
            return
        delta = start_y - event.y_root
        tab_data["console_user_locked"] = True
        self.apply_console_height(tab_id, start_height + delta, remember=True)

    def apply_adaptive_layout(self):
        self.window_resize_job = None
        width = self.winfo_width()
        if width <= 1:
            return
        if not self.sidebar_user_locked:
            self.set_sidebar_collapsed(width < 900, auto=True)
        if not self.sidebar_collapsed:
            self.update_sidebar_width(WIDTH_SIDEBAR_NARROW if width < 1150 else WIDTH_SIDEBAR_WIDE)
        progress_wrap = max(240, self.main_area.winfo_width() - 80)
        default_console_height = self.get_default_console_height()
        for tab_id, tab_data in self.active_tabs_data.items():
            progress_label = tab_data.get("progress_label")
            if progress_label and progress_label.winfo_exists():
                progress_label.configure(wraplength=progress_wrap, justify="left")
            if not tab_data.get("console_user_locked"):
                self.apply_console_height(tab_id, default_console_height, remember=False)

    def get_left_panel_width(self, manifest):
        max_name_len = max((len(step.get("display_label", step.get("script_name", ""))) for step in manifest.get("steps", [])), default=12)
        estimated = 150 + max_name_len * 7
        return max(WIDTH_LEFT_PANEL_MIN, min(estimated, WIDTH_LEFT_PANEL_MAX))

    def scan_workspaces(self, award):
        root_dir = get_award_folder(award)
        if not os.path.exists(root_dir): return []
        
        valid_workspaces = []
        ignore_dirs = {"数据库", "代码备份", "工作区设置", "__pycache__"}
        
        for folder in os.listdir(root_dir):
            if folder in ignore_dirs: continue
            path = os.path.join(root_dir, folder)
            if os.path.isdir(path):
                bp1 = os.path.join(path, "资料", "代码", "工作区设置", "文件结构.xlsx")
                bp2 = os.path.join(path, "工作区设置", "文件结构.xlsx")
                if os.path.exists(bp1) or os.path.exists(bp2):
                    valid_workspaces.append(folder)
        return sorted(valid_workspaces)

    def get_workspace_year(self, workspace_name):
        match = re.match(r"^\s*(\d{4})", str(workspace_name or ""))
        return match.group(1) if match else "未识别"

    def scan_workspace_years(self, award):
        current_year = datetime.datetime.now().year
        return [str(year) for year in range(current_year, 2023, -1)]

    def build_workspace_menu_state(self, award, year=""):
        all_workspaces = self.scan_workspaces(award)
        selected_year = str(year or "").strip()
        if selected_year and selected_year != "全部":
            workspaces = [folder for folder in all_workspaces if self.get_workspace_year(folder) == selected_year]
        else:
            workspaces = list(all_workspaces)
        workspace_entries = []
        for folder in workspaces:
            manifest_stub = {
                "workspace_root": os.path.join(get_award_folder(award), folder),
                "award": award,
            }
            display_name = self.get_workspace_display_name(manifest_stub) or folder
            workspace_entries.append((display_name.lower(), display_name, folder))
        workspace_entries.sort(key=lambda item: (item[0], item[1], item[2]))
        display_map = {}
        reverse_map = {}
        used = set()
        for _, display_name, folder in workspace_entries:
            label = display_name
            if label in used:
                label = f"{display_name} · {folder}"
            used.add(label)
            display_map[label] = folder
            reverse_map[folder] = label
        return workspaces, display_map, reverse_map

    def resolve_workspace_menu_selection(self, award=None, year=None):
        award = award or self.award_menu.get()
        year = year or self.year_menu.get()
        selected_label = self.workspace_menu.get()
        display_map = getattr(self, "workspace_menu_display_map", {}).get((award, year), {})
        return display_map.get(selected_label, selected_label)

    def on_year_menu_change(self, selected_year):
        self.clear_sidebar_initialize_context()
        self.update_workspace_menu(self.award_menu.get(), selected_year)
        self.refresh_sidebar_resource_browser(self.award_menu.get(), selected_year)
        self.refresh_sidebar_config_browser(self.award_menu.get(), selected_year)

    def prompt_display_name(self, title, prompt, initial_value="", allow_empty=True):
        try:
            value = simpledialog.askstring(title, prompt, initialvalue=initial_value, parent=self)
        except Exception:
            value = None
        if value is None:
            return None
        value = str(value).strip()
        if not value and allow_empty:
            return ""
        return value

    def normalize_alias_text(self, text, max_length):
        text = _clean(text)
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text)
        return text[:max_length]

    def refresh_workspace_tab_title(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        display_name = self.get_workspace_display_name(tab_data.get("manifest", {})) or tab_id
        button_widget = self._get_tab_button_widget(tab_id)
        if button_widget and button_widget.winfo_exists():
            try:
                button_widget.configure(text=display_name)
            except Exception:
                pass
        tab_data["tab_display_name"] = display_name
        self.refresh_workspace_tab_button_style(tab_id)

    def rename_workspace_display_name(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        manifest = tab_data.get("manifest", {})
        current_name = self.get_workspace_display_name(manifest)
        new_name = self.prompt_display_name("重命名工作区", "输入工作区显示名；留空可恢复为真实目录名。", current_name, allow_empty=True)
        if new_name is None:
            return
        normalized_name = self.normalize_alias_text(new_name, 32)
        self.save_workspace_display_name(manifest, normalized_name)
        award = tab_data.get("award") or self.award_menu.get()
        workspace_folder = os.path.basename(manifest.get("workspace_root", ""))
        selected_year = self.get_workspace_year(workspace_folder)
        self.refresh_workspace_tab_title(tab_id)
        self.update_year_menu(award, selected_year=selected_year, selected_workspace=workspace_folder)
        self.refresh_tab_panels(tab_id)
        display_name = self.get_workspace_display_name(manifest)
        self.log_msg(tab_id, f"工作区显示名已更新为: {display_name}")

    def rename_attempt_display_name(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        manifest = tab_data.get("manifest", {})
        session_id = _clean(tab_data.get("attempt_selected_session_id"))
        if not session_id:
            self.log_msg(tab_id, "当前没有可重命名的尝试。")
            return
        current_summary = self.load_attempt_summary(manifest, session_id)
        current_name = _clean(current_summary.get("attempt_name"))
        new_name = self.prompt_display_name("重命名尝试", "输入尝试显示名；留空可恢复默认时间标签。", current_name, allow_empty=True)
        if new_name is None:
            return
        normalized_name = self.normalize_alias_text(new_name, 24)
        updated_summary = self.save_attempt_display_name(manifest, session_id, normalized_name)
        if not updated_summary:
            self.log_msg(tab_id, "尝试显示名更新失败。")
            return
        if _clean(tab_data.get("timeline_batch_session_id")) == session_id:
            tab_data["attempt_name"] = normalized_name
        self.render_gantt_tab(tab_id)
        shown_name = _clean(updated_summary.get("attempt_name")) or "默认时间标签"
        self.log_msg(tab_id, f"尝试显示名已更新为: {shown_name}")

    def should_refresh_terminal_after_run(self, step_info):
        if not step_info:
            return False
        script_name = os.path.basename(step_info.get("script_name") or step_info.get("rel_path") or "")
        return script_name.lower() == "test.py"

    def refresh_terminal_after_test_run(self, tab_id, step_info):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        award = tab_data.get("award") or self.award_menu.get()
        current_year = self.year_menu.get() if hasattr(self, "year_menu") else ""
        current_workspace = self.resolve_workspace_menu_selection(award, current_year)
        self.award_menu.set(award)
        self.update_year_menu(award, selected_year=current_year, selected_workspace=current_workspace)
        for open_tab_id in list(self.active_tabs_data.keys()):
            self.refresh_tab_panels(open_tab_id)
        self.log_msg(tab_id, f"检测到 {os.path.basename(step_info.get('rel_path', step_info.get('script_name', 'test.py')))} 执行完成，已刷新终端工作区列表。")

    def update_year_menu(self, selected_award, selected_year="", selected_workspace=""):
        self.clear_sidebar_initialize_context()
        years = self.scan_workspace_years(selected_award)
        self.year_menu_values[selected_award] = list(years)
        if years:
            self.year_menu.configure(values=years)
            target_year = selected_year if selected_year in years else years[0]
            self.year_menu.set(target_year)
            self.update_workspace_menu(selected_award, target_year, selected_workspace=selected_workspace)
            self.refresh_sidebar_resource_browser(selected_award, target_year)
            self.refresh_sidebar_config_browser(selected_award, target_year)
        else:
            self.year_menu.configure(values=["无可用年份"])
            self.year_menu.set("无可用年份")
            self.workspace_menu.configure(values=["无可用工作区"])
            self.workspace_menu.set("无可用工作区")
            self.refresh_sidebar_resource_browser(selected_award, "")
            self.refresh_sidebar_config_browser(selected_award, "")

    def update_workspace_menu(self, selected_award, selected_year="", selected_workspace=""):
        workspaces, display_map, reverse_map = self.build_workspace_menu_state(selected_award, selected_year)
        if workspaces:
            labels = list(display_map.keys())
            key = (selected_award, selected_year)
            self.workspace_menu_display_map[key] = display_map
            self.workspace_menu_reverse_map[key] = reverse_map
            self.workspace_menu.configure(values=labels)
            if selected_workspace and selected_workspace in reverse_map:
                self.workspace_menu.set(reverse_map[selected_workspace])
            else:
                self.workspace_menu.set(labels[-1])
        else:
            self.workspace_menu.configure(values=["无可用工作区"])
            self.workspace_menu.set("无可用工作区")

    def run_delete_workspace_script(self, workspace_root):
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "delete_workspace.py")
        if not os.path.isfile(script_path):
            return False, f"未找到删除脚本: {script_path}"
        result = subprocess.run(
            [sys.executable, script_path, workspace_root],
            cwd=os.path.dirname(script_path),
            capture_output=True,
            text=True,
        )
        message = (result.stdout or "").strip() or (result.stderr or "").strip()
        return result.returncode == 0, message

    def confirm_delete_workspace(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        manifest = tab_data.get("manifest", {})
        workspace_root = manifest.get("workspace_root", "")
        workspace_name = self.get_workspace_display_name(manifest) or os.path.basename(workspace_root) or tab_id
        award = tab_data.get("award") or self.award_menu.get()
        current_run = self.is_main_process_running(tab_id) or self.has_async_processes(tab_id)
        message = (
            f"确认删除工作区 `{workspace_name}` ?\n\n"
            "删除后将移除整个工作区目录，并一并删除该工作区在 logs 下的所有日志与尝试归档，且不可恢复。"
        )
        if current_run:
            message += "\n当前仍有运行中的代码，确认后会先终止再删除。"
        confirmed = custom_dialog("确认删除工作区", message, "confirm", "确认删除", "取消")
        if not confirmed:
            return
        self.cleanup_tab_runtime(tab_id)
        ok, detail = self.run_delete_workspace_script(workspace_root)
        if not ok:
            custom_dialog("删除失败", detail or f"工作区删除失败: {workspace_root}", "error", "确认")
            return
        self.finalize_tab_close(tab_id)
        self.update_year_menu(award)

    def get_institution_txt_path(self, manifest=None, award="", ws_name=""):
        if isinstance(manifest, dict):
            workspace_root = _clean(manifest.get("workspace_root"))
            if workspace_root:
                return os.path.join(workspace_root, "参评信息", "机构信息.txt")
        award = _clean(award)
        ws_name = _clean(ws_name)
        award_root = get_award_folder(award)
        if not award_root or not ws_name or ws_name == "无可用工作区":
            return ""
        return os.path.join(award_root, ws_name, "参评信息", "机构信息.txt")

    def has_institution_txt(self, manifest=None, award="", ws_name=""):
        txt_path = self.get_institution_txt_path(manifest=manifest, award=award, ws_name=ws_name)
        return bool(txt_path and os.path.isfile(txt_path))

    def get_sidebar_selected_year_int(self):
        year_text = _clean(self.year_menu.get())
        if not year_text or year_text == "无可用年份":
            return None
        match = re.search(r"\b(20\d{2})\b", year_text)
        if not match:
            return None
        try:
            return int(match.group(1))
        except Exception:
            return None

    def get_award_year_database_path(self, award_name, year_value):
        award_root = self.get_sidebar_award_root(award_name)
        if not award_root or not year_value:
            return ""
        return os.path.join(award_root, "数据库", str(year_value), "DB_PRIVATE.duckdb")

    def get_award_data_ingestion_script_path(self, award_name):
        award_root = self.get_sidebar_award_root(award_name)
        if not award_root:
            return ""
        path = os.path.join(award_root, "data_ingestion.py")
        return path if os.path.isfile(path) else ""

    def choose_sidebar_ingestion_source_file(self, award_name, year_value):
        award_root = self.get_sidebar_award_root(award_name)
        if not award_root:
            return ""
        initial_dir = os.path.join(award_root, "原始数据集", str(year_value)) if year_value else award_root
        if not os.path.isdir(initial_dir):
            initial_dir = award_root
        selected_path = filedialog.askopenfilename(
            parent=self,
            title=f"选择用于入库的 Excel 文件{'' if year_value is None else f'（{year_value}）'}",
            initialdir=initial_dir,
            filetypes=[
                ("Excel 文件", "*.xlsx *.xls *.xlsm"),
                ("所有文件", "*.*"),
            ],
        )
        if not selected_path:
            return ""
        selected_path = os.path.normpath(os.path.abspath(selected_path))
        if not os.path.isfile(selected_path):
            messagebox.showwarning("提示", f"所选路径不是文件:\n{selected_path}")
            return ""
        return selected_path

    def any_tab_process_running(self):
        for tab_id, tab_data in list(self.active_tabs_data.items()):
            if not tab_data:
                continue
            if tab_data.get("current_process") or self.has_async_processes(tab_id):
                return True
        return False

    def get_execution_tab_for_award(self, award_name):
        current_tab_id = self.tabview.get() if hasattr(self, "tabview") else ""
        current_tab_data = self.active_tabs_data.get(current_tab_id)
        if current_tab_data and _clean(current_tab_data.get("award")) == _clean(award_name):
            return current_tab_id
        for tab_id, tab_data in list(self.active_tabs_data.items()):
            if tab_data and _clean(tab_data.get("award")) == _clean(award_name):
                return tab_id
        return ""

    def on_sidebar_delete_database_click(self):
        award_name = self.award_menu.get()
        year_value = self.get_sidebar_selected_year_int()
        if not award_name or year_value is None:
            messagebox.showinfo("提示", "请先选择有效的奖项和年份。")
            return
        if self.any_tab_process_running():
            custom_dialog("请先停止运行", "当前仍有运行中的顺序或异步代码，请先暂停后再删库。", "info", "确认")
            return
        db_path = self.get_award_year_database_path(award_name, year_value)
        if not db_path:
            custom_dialog("缺少数据库路径", "未能定位当前奖项年份对应的数据库。", "error", "确认")
            return
        wal_path = db_path + ".wal"
        message = (
            f"确认删除 {award_name} {year_value} 年数据库？\n\n"
            f"目标文件:\n{db_path}\n\n"
            "此操作不可恢复，但不会删除原始 Excel。"
        )
        confirmed = custom_dialog("确认删除旧库", message, "confirm", "确认删除", "取消")
        if not confirmed:
            return
        removed_any = False
        errors = []
        for target in [db_path, wal_path]:
            if not os.path.exists(target):
                continue
            try:
                os.remove(target)
                removed_any = True
            except Exception as e:
                errors.append(f"{target}\n{e}")
        if errors:
            custom_dialog("删除失败", "\n\n".join(errors), "error", "确认")
            return
        if removed_any:
            messagebox.showinfo("删除完成", f"已删除旧数据库:\n{db_path}")
        else:
            messagebox.showinfo("删除完成", f"未发现可删除的数据库文件:\n{db_path}")

    def on_sidebar_data_ingestion_click(self):
        award_name = self.award_menu.get()
        year_value = self.get_sidebar_selected_year_int()
        if not award_name or year_value is None:
            messagebox.showinfo("提示", "请先选择有效的奖项和年份。")
            return
        if self.any_tab_process_running():
            custom_dialog("请先停止运行", "当前仍有运行中的顺序或异步代码，请先暂停后再入库。", "info", "确认")
            return
        script_path = self.get_award_data_ingestion_script_path(award_name)
        if not script_path:
            custom_dialog("缺少脚本", "未找到奖项根目录下的 `data_ingestion.py`。", "error", "确认")
            return
        selected_src = self.choose_sidebar_ingestion_source_file(award_name, year_value)
        if not selected_src:
            return
        db_path = self.get_award_year_database_path(award_name, year_value)
        preview = (
            f"奖项: {award_name}\n"
            f"年份: {year_value}\n"
            f"目标数据库: {db_path}\n"
            f"源文件: {selected_src}\n\n"
            "确认开始入库吗？"
        )
        confirmed = custom_dialog("确认开始数据入库", preview, "confirm", "开始入库", "取消")
        if not confirmed:
            return
        active_tab_id = self.get_execution_tab_for_award(award_name)
        tab_data = self.active_tabs_data.get(active_tab_id)
        if not tab_data:
            messagebox.showinfo("提示", f"请先至少挂载一个 `{award_name}` 工作区页签，用于承载入库日志。")
            return
        manifest = tab_data.get("manifest", {})
        workspace_root = manifest.get("workspace_root", "")
        rel_path = os.path.relpath(script_path, workspace_root) if workspace_root else script_path
        src_arg = os.path.normpath(os.path.abspath(selected_src))
        self.clear_error_focus(active_tab_id)
        tab_data["batch_has_started_steps"] = False
        tab_data["main_batch_finished"] = False
        tab_data["post_batch_update_done"] = False
        self.refresh_tab_panels(active_tab_id)
        run_info = {
            "order": None,
            "is_manual_code": True,
            "is_root_code": True,
            "display_label": "数据入库",
            "script_name": os.path.basename(script_path),
            "rel_path": rel_path,
            "folder_rel_path": "",
            "argv": ["--yr", str(year_value), "--src", src_arg],
        }
        self.log_msg(active_tab_id, f"准备入库: award={award_name}, year={year_value}, src={src_arg}")
        self.run_script_thread(run_info, active_tab_id)

    def open_inst_txt(self):
        award = self.award_menu.get()
        ws_name = self.resolve_workspace_menu_selection(award, self.year_menu.get())
        txt_path = self.get_institution_txt_path(award=award, ws_name=ws_name)
        if not txt_path:
            return
        if os.path.exists(txt_path):
            os.startfile(txt_path)
        else:
            print(f"未找到机构信息配置文件: {txt_path}")

    def open_workspace_inst_txt(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        txt_path = self.get_institution_txt_path(manifest=tab_data.get("manifest", {}))
        if not txt_path:
            return
        if os.path.exists(txt_path):
            os.startfile(txt_path)
        else:
            print(f"未找到机构信息配置文件: {txt_path}")

    def show_gui_error(self, title, exc, user_message="", tab_id=None):
        detail = traceback.format_exc()
        print(detail, file=sys.stderr)
        if tab_id in self.active_tabs_data:
            message = user_message or f"{title}: {exc}"
            try:
                self.log_msg(tab_id, message)
            except Exception:
                pass
        dialog_text = user_message or str(exc)
        try:
            messagebox.showerror(title, f"{dialog_text}\n\n详细异常:\n{exc}")
        except Exception:
            print(f"{title}: {dialog_text}\n{exc}", file=sys.stderr)

    def mount_workspace(self):
        award = self.award_menu.get()
        ws_name = self.resolve_workspace_menu_selection(award, self.year_menu.get())
        if ws_name == "无可用工作区": return
        
        tab_id = f"{award}-{ws_name}"
        if tab_id in self.active_tabs_data:
            self.tabview.set(tab_id)
            return

        tab_created = False
        prev_suppress_configure = self.suppress_window_configure
        try:
            self.suppress_window_configure = True
            self.cancel_after_handle(self.window_resize_job)
            self.window_resize_job = None
            ws_root = os.path.join(AWARD_FOLDER_MAP[award], ws_name)
            bp_path = os.path.join(ws_root, "资料", "代码", "工作区设置", "文件结构.xlsx")
            if not os.path.exists(bp_path):
                bp_path = os.path.join(ws_root, "工作区设置", "文件结构.xlsx")

            manifest = build_workspace_manifest(bp_path, ws_root, get_manifest_award(award))
            manifest = reconcile_filesystem(manifest)
            self.sync_workspace_archive_metadata(manifest)

            tab_frame = self.tabview.add(tab_id)
            tab_created = True
            self.tabview.set(tab_id)

            self.active_tabs_data[tab_id] = {
                "award": award,
                "bp_path": bp_path,
                "manifest": manifest,
                "left_panel": None,
                "middle_panel": None,
                "right_panel": None,
                "resource_panel": None,
                "left_header": None,
                "middle_header": None,
                "right_header": None,
                "resource_header": None,
                "log_box": None,
                "progress_label": None,
                "pause_button": None,
                "run_timer_label": None,
                "workspace_view_tabview": None,
                "main_view": None,
                "workspace_stepper_container": None,
                "workspace_view_preferred": "主界面",
                "gantt_header": None,
                "gantt_panel": None,
                "tab_root": tab_frame,
                "content_container": None,
                "console_container": None,
                "console_sash": None,
                "step_scroll": None,
                "step_vars": {},
                "step_widgets": {},
                "step_states": {},
                "saved_step_selection_loaded": False,
                "saved_step_selection_orders": [],
                "workspace_stepper_selected_orders_snapshot": [],
                "workspace_stepper_snapshot_active": False,
                "gui_state_save_job": None,
                "suspend_gui_state_save": False,
                "workspace_stepper_breath_job": None,
                "workspace_stepper_breath_on": False,
                "tab_breath_job": None,
                "tab_breath_on": False,
                "current_process": None,
                "current_run_info": None,
                "current_step_id": None,
                "progress_active": False,
                "batch_has_started_steps": False,
                "main_batch_finished": False,
                "post_batch_update_done": False,
                "run_timer_started_at": None,
                "run_timer_elapsed": 0.0,
                "run_timer_running": False,
                "run_timer_failed": False,
                "run_timer_mode": "",
                "timeline_batch_session_id": "",
                "attempt_active": False,
                "attempt_started_at_iso": "",
                "attempt_started_at_epoch": 0.0,
                "attempt_status": "",
                "attempt_pending_final_status": "",
                "attempt_pending_final_message": "",
                "attempt_selected_session_id": "",
                "attempt_display_map": {},
                "gantt_final_refresh_job": None,
                "gantt_final_refresh_session_id": "",
                "gantt_final_autoscaled_session_id": "",
                "gantt_last_refresh": 0.0,
                "gantt_scroll_fraction": 0.0,
                "error_folder_rel_path": "",
                "error_file_rel_path": "",
                "error_is_root": False,
                "left_tab_preferred": "步骤代码",
                "async_pid_file": self.make_async_pid_file(manifest, tab_id),
                "async_log_dir": self.make_async_log_dir(manifest, tab_id),
                "console_height": self.get_default_console_height(),
                "console_user_locked": False,
                "log_auto_follow_enabled": True,
                "log_auto_follow_resume_job": None,
                "log_auto_follow_last_user_ts": 0.0,
                "refresh_panels_job": None,
                "loading_overlay_show_job": None,
                "loading_overlay_hide_job": None,
                "loading_overlay_anim_job": None,
                "mount_loading_finish_job": None,
                "right_view": "output",
                "db_result_title": "数据库查询结果",
                "db_result_text": "点击右侧数据库卡片中的快捷按钮后，这里会显示查询结果。",
                "auto_refresh_enabled": False,
                "auto_refresh_var": ctk.BooleanVar(value=False),
                "last_auto_refresh": 0.0,
            }
            self.start_mount_loading_overlay(tab_id, "正在加载工作区")
            self.restore_workspace_gui_state(tab_id)
            self.build_tab_ui(tab_id, tab_frame)
            self.safe_after_idle(self.raise_tab_loading_overlay, tab_id)
            self.refresh_workspace_tab_title(tab_id)
            self.ensure_workspace_tab_breathing(tab_id)
            self.safe_after_idle(self.refresh_tab_hover_close_bindings)
            self.suppress_window_configure = prev_suppress_configure
            self.safe_after_idle(self.apply_adaptive_layout)
            self.active_tabs_data.get(tab_id, {})["mount_loading_finish_job"] = self.safe_after(320, self.finish_mount_loading_overlay, tab_id)
        except Exception as exc:
            self.suppress_window_configure = prev_suppress_configure
            if tab_id in self.active_tabs_data:
                self.active_tabs_data.pop(tab_id, None)
            if tab_created:
                try:
                    self.tabview.delete(tab_id)
                except Exception:
                    pass
            self.show_gui_error("挂载工作区失败", exc, f"工作区 `{ws_name}` 挂载失败，请查看异常信息并检查该工作区结构。")

    def reconcile_manifest(self, manifest):
        return reconcile_filesystem(manifest)

    def make_timeline_id(self, prefix):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}"

    def get_timeline_axis(self, tab_id, step_info):
        tab_data = self.active_tabs_data.get(tab_id)
        manifest = tab_data.get("manifest", {}) if tab_data else {}
        if step_info.get("is_post_batch_update") or step_info.get("is_root_code"):
            return "root"
        if step_info.get("order") is not None:
            return "main"
        rel_path = os.path.normcase(os.path.normpath(step_info.get("rel_path", "")))
        main_rel_paths = {
            os.path.normcase(os.path.normpath(item.get("rel_path", "")))
            for item in manifest.get("steps", [])
            if item.get("rel_path")
        }
        if rel_path and rel_path in main_rel_paths:
            return "main"
        folder_rel_path = str(step_info.get("folder_rel_path", ""))
        if folder_rel_path.lower().startswith("step_"):
            return "async"
        return "root"

    def build_timeline_env(self, tab_id, step_info):
        tab_data = self.active_tabs_data.get(tab_id)
        manifest = tab_data.get("manifest", {}) if tab_data else {}
        axis = self.get_timeline_axis(tab_id, step_info)
        source = "manual"
        if step_info.get("is_post_batch_update"):
            source = "post_batch_update"
        elif axis == "main":
            source = "main_batch"
        elif step_info.get("is_root_code"):
            source = "root_manual"

        session_id = step_info.get("timeline_session_id", "")
        if not session_id:
            if step_info.get("is_post_batch_update") or axis == "main":
                session_id = tab_data.get("timeline_batch_session_id", "") if tab_data else ""
                if not session_id:
                    session_id = self.make_timeline_id("session")
                    if tab_data is not None:
                        tab_data["timeline_batch_session_id"] = session_id
            else:
                session_id = self.make_timeline_id("session")

        return {
            "GB_TIMELINE_RUN_ID": self.make_timeline_id("run"),
            "GB_TIMELINE_SESSION_ID": session_id,
            "GB_TIMELINE_PARENT_REL": "",
            "GB_TIMELINE_PARENT_RUN_ID": "",
            "GB_TIMELINE_AXIS": axis,
            "GB_TIMELINE_SOURCE": source,
            "GB_TIMELINE_REL_PATH": step_info.get("rel_path", ""),
            "GB_TIMELINE_WORKSPACE_ROOT": manifest.get("workspace_root", ""),
        }

    def get_live_main_timer_seconds(self, tab_data):
        if not tab_data:
            return 0.0
        elapsed = tab_data.get("run_timer_elapsed", 0.0)
        if tab_data.get("run_timer_running") and tab_data.get("run_timer_started_at") is not None:
            elapsed = time.monotonic() - tab_data["run_timer_started_at"]
        try:
            return max(0.0, float(elapsed))
        except (TypeError, ValueError):
            return 0.0

    def write_json_file(self, path, payload):
        if not path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def read_json_file(self, path, default=None):
        fallback = {} if default is None else default
        if not path or not os.path.isfile(path):
            return fallback
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return fallback
        return data if data is not None else fallback

    def get_workspace_gui_state_path(self, manifest):
        workspace_root = str((manifest or {}).get("workspace_root", "")).strip()
        if not workspace_root:
            return ""
        return os.path.join(workspace_root, "参评信息", "gui_state.json")

    def normalize_gui_step_order(self, value):
        try:
            order = int(value)
        except (TypeError, ValueError):
            return None
        return order if order >= 0 else None

    def normalize_gui_step_state(self, value):
        state = _clean(value).lower()
        if state == "running":
            return "pending"
        if state in {"pending", "success", "error", "skip", "missing"}:
            return state
        return "pending"

    def get_valid_manifest_step_orders(self, manifest):
        return [
            step.get("order")
            for step in (manifest or {}).get("steps", [])
            if isinstance(step.get("order"), int)
        ]

    def load_workspace_gui_state(self, manifest):
        return self.read_json_file(self.get_workspace_gui_state_path(manifest), default={})

    def restore_workspace_gui_state(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        manifest = tab_data.get("manifest", {})
        state = self.load_workspace_gui_state(manifest)
        if not isinstance(state, dict) or not state:
            return

        valid_orders = self.get_valid_manifest_step_orders(manifest)
        valid_order_set = set(valid_orders)

        has_selected_orders = "selected_step_orders" in state
        restored_selected_orders = []
        seen_orders = set()
        for raw_order in state.get("selected_step_orders", []):
            order = self.normalize_gui_step_order(raw_order)
            if order is None or order not in valid_order_set or order in seen_orders:
                continue
            restored_selected_orders.append(order)
            seen_orders.add(order)
        tab_data["saved_step_selection_loaded"] = has_selected_orders
        tab_data["saved_step_selection_orders"] = restored_selected_orders

        restored_stepper_snapshot_orders = []
        seen_snapshot_orders = set()
        for raw_order in state.get("workspace_stepper_selected_orders_snapshot", []):
            order = self.normalize_gui_step_order(raw_order)
            if order is None or order not in valid_order_set or order in seen_snapshot_orders:
                continue
            restored_stepper_snapshot_orders.append(order)
            seen_snapshot_orders.add(order)
        tab_data["workspace_stepper_selected_orders_snapshot"] = restored_stepper_snapshot_orders
        tab_data["workspace_stepper_snapshot_active"] = bool(
            state.get("workspace_stepper_snapshot_active") and restored_stepper_snapshot_orders
        )

        restored_states = {}
        raw_step_states = state.get("step_states", {})
        if isinstance(raw_step_states, dict):
            for order in valid_orders:
                raw_value = raw_step_states.get(str(order), raw_step_states.get(order))
                restored_states[order] = self.normalize_gui_step_state(raw_value)
        tab_data["step_states"].update(restored_states)

        try:
            elapsed = max(0.0, float(state.get("last_main_timer_seconds", 0.0)))
        except (TypeError, ValueError):
            elapsed = 0.0
        tab_data["run_timer_started_at"] = None
        tab_data["run_timer_elapsed"] = elapsed
        tab_data["run_timer_running"] = False
        tab_data["run_timer_failed"] = bool(state.get("run_timer_failed"))
        tab_data["run_timer_mode"] = ""

        left_tab = _clean(state.get("left_tab_preferred"))
        if left_tab in {"步骤代码", "代码文件夹"}:
            tab_data["left_tab_preferred"] = left_tab

        right_view = _clean(state.get("right_view"))
        if right_view in {"output", "database"}:
            tab_data["right_view"] = right_view

        tab_data["attempt_selected_session_id"] = _clean(state.get("attempt_selected_session_id"))
        tab_data["error_folder_rel_path"] = _clean(state.get("error_folder_rel_path"))
        tab_data["error_file_rel_path"] = _clean(state.get("error_file_rel_path"))
        tab_data["error_is_root"] = bool(state.get("error_is_root"))

    def build_workspace_gui_state_payload(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return {}
        manifest = tab_data.get("manifest", {})
        valid_orders = self.get_valid_manifest_step_orders(manifest)
        valid_order_set = set(valid_orders)

        workspace_view = _clean(tab_data.get("workspace_view_preferred", "主界面")) or "主界面"
        workspace_view_tabview = tab_data.get("workspace_view_tabview")
        if workspace_view_tabview and workspace_view_tabview.winfo_exists():
            try:
                workspace_view = _clean(workspace_view_tabview.get()) or workspace_view
            except Exception:
                pass
        if workspace_view not in {"主界面", "流水线", "数据文件", "规则/所给数据集"}:
            workspace_view = "主界面"

        left_tab = _clean(tab_data.get("left_tab_preferred", "步骤代码")) or "步骤代码"
        left_tabview = tab_data.get("left_tabview")
        if left_tabview and left_tabview.winfo_exists():
            try:
                left_tab = _clean(left_tabview.get()) or left_tab
            except Exception:
                pass
        if left_tab not in {"步骤代码", "代码文件夹"}:
            left_tab = "步骤代码"

        step_vars = tab_data.get("step_vars", {})
        if step_vars and not tab_data.get("suspend_gui_state_save"):
            selected_orders = [order for order in valid_orders if step_vars.get(order) and step_vars[order].get() == "1"]
        else:
            selected_orders = [
                order for order in tab_data.get("saved_step_selection_orders", [])
                if order in valid_order_set
            ] if tab_data.get("saved_step_selection_loaded") else []

        step_states = {}
        for order in valid_orders:
            step_states[str(order)] = self.normalize_gui_step_state(tab_data.get("step_states", {}).get(order))

        stepper_snapshot_orders = [
            order for order in tab_data.get("workspace_stepper_selected_orders_snapshot", [])
            if order in valid_order_set
        ]
        stepper_snapshot_active = bool(tab_data.get("workspace_stepper_snapshot_active") and stepper_snapshot_orders)

        return {
            "version": 1,
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "selected_step_orders": selected_orders,
            "step_states": step_states,
            "workspace_stepper_selected_orders_snapshot": stepper_snapshot_orders,
            "workspace_stepper_snapshot_active": stepper_snapshot_active,
            "last_main_timer_seconds": round(self.get_live_main_timer_seconds(tab_data), 3),
            "run_timer_failed": bool(tab_data.get("run_timer_failed")),
            "workspace_view_preferred": workspace_view,
            "left_tab_preferred": left_tab,
            "right_view": "database" if tab_data.get("right_view") == "database" else "output",
            "attempt_selected_session_id": _clean(tab_data.get("attempt_selected_session_id")),
            "error_folder_rel_path": _clean(tab_data.get("error_folder_rel_path")),
            "error_file_rel_path": _clean(tab_data.get("error_file_rel_path")),
            "error_is_root": bool(tab_data.get("error_is_root")),
        }

    def save_workspace_gui_state(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["gui_state_save_job"] = None
        manifest = tab_data.get("manifest", {})
        path = self.get_workspace_gui_state_path(manifest)
        if not path:
            return
        payload = self.build_workspace_gui_state_payload(tab_id)
        self.write_json_file(path, payload)
        tab_data["saved_step_selection_loaded"] = "selected_step_orders" in payload
        tab_data["saved_step_selection_orders"] = list(payload.get("selected_step_orders", []))

    def schedule_gui_state_save(self, tab_id, delay_ms=180):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        job = tab_data.get("gui_state_save_job")
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        tab_data["gui_state_save_job"] = self.safe_after(delay_ms, self.save_workspace_gui_state, tab_id)

    def extract_error_excerpt(self, log_path, max_lines=6):
        if not log_path or not os.path.isfile(log_path):
            return ""
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
        except OSError:
            return ""
        if not lines:
            return ""
        keywords = ("traceback", "error", "exception")
        important = [line for line in lines if any(key in line.lower() for key in keywords)]
        source_lines = important if important else lines
        excerpt = source_lines[-max_lines:]
        return "\n".join(excerpt[-max_lines:])

    def update_attempt_error_snapshot(self, tab_id, run_info=None):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        run_info = run_info or tab_data.get("current_run_info") or {}
        log_path = str(run_info.get("log_filename", "")).strip()
        excerpt = self.extract_error_excerpt(log_path)
        tab_data["attempt_error_excerpt"] = excerpt
        tab_data["attempt_error_log_path"] = log_path

    def append_terminal_timeline_end(self, tab_id, run_info, status):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data or not run_info:
            return
        timeline_env = dict(run_info.get("timeline_env") or {})
        run_id = str(timeline_env.get("GB_TIMELINE_RUN_ID", "")).strip()
        session_id = str(timeline_env.get("GB_TIMELINE_SESSION_ID", "")).strip()
        rel_path = str(timeline_env.get("GB_TIMELINE_REL_PATH", "")).strip()
        if not run_id or not session_id or not rel_path:
            return
        manifest = tab_data.get("manifest", {})
        time_record_path = self.get_time_record_path(manifest)
        if not time_record_path:
            return
        os.makedirs(os.path.dirname(time_record_path), exist_ok=True)
        started_at = run_info.get("timeline_started_at")
        try:
            started_at = float(started_at)
        except (TypeError, ValueError):
            started_at = None
        now_dt = datetime.datetime.now()
        duration_seconds = round(max(0.0, time.time() - started_at), 3) if started_at else 0.0
        payload = {
            "event": "end",
            "run_id": run_id,
            "session_id": session_id,
            "parent_rel": str(timeline_env.get("GB_TIMELINE_PARENT_REL", "")).strip(),
            "parent_run_id": str(timeline_env.get("GB_TIMELINE_PARENT_RUN_ID", "")).strip(),
            "rel_path": rel_path,
            "axis": str(timeline_env.get("GB_TIMELINE_AXIS", "")).strip(),
            "source": str(timeline_env.get("GB_TIMELINE_SOURCE", "")).strip(),
            "status": status,
            "ts": now_dt.isoformat(sep=" ", timespec="milliseconds"),
            "duration": duration_seconds,
            "pid": run_info.get("pid"),
            "data_scope": "",
        }
        try:
            with open(time_record_path, "a", encoding="utf-8") as f:
                f.write("GB_TIMELINE " + json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError:
            return

    def get_session_timeline_lines(self, source_path, session_id):
        session_id = str(session_id or "").strip()
        if not source_path or not os.path.isfile(source_path) or not session_id:
            return []
        lines = []
        prefix = "GB_TIMELINE "
        try:
            with open(source_path, "r", encoding="utf-8", errors="ignore") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line.startswith(prefix):
                        continue
                    try:
                        payload = json.loads(line[len(prefix):])
                    except json.JSONDecodeError:
                        continue
                    if str(payload.get("session_id", "")).strip() != session_id:
                        continue
                    lines.append(prefix + json.dumps(payload, ensure_ascii=False))
        except OSError:
            return []
        return lines

    def serialize_attempt_record_entry(self, entry):
        start_at = entry.get("start_at")
        end_at = self.get_timeline_entry_end(entry)
        duration_seconds = entry.get("duration_seconds", 0.0)
        try:
            duration_seconds = round(float(duration_seconds), 3)
        except (TypeError, ValueError):
            duration_seconds = 0.0
        return {
            "run_id": str(entry.get("run_id", "")).strip(),
            "session_id": str(entry.get("session_id", "")).strip(),
            "parent_run_id": str(entry.get("parent_run_id", "")).strip(),
            "parent_rel": str(entry.get("parent_rel", "")).strip(),
            "rel_path": str(entry.get("rel_path", "")).strip(),
            "label": str(entry.get("label", "")).strip(),
            "axis": str(entry.get("axis", "")).strip(),
            "kind": str(entry.get("kind", "")).strip(),
            "status": str(entry.get("status", "")).strip(),
            "data_scope": str(entry.get("data_scope", "")).strip(),
            "started_at": start_at.isoformat(sep=" ", timespec="seconds") if start_at else "",
            "ended_at": end_at.isoformat(sep=" ", timespec="seconds") if end_at else "",
            "duration_seconds": duration_seconds,
        }

    def build_attempt_records_summary_payload(self, tab_id, session_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data or not session_id:
            return []
        entries = self.get_time_record_entries(tab_id, session_id=session_id, max_items=None)
        return [self.serialize_attempt_record_entry(entry) for entry in entries]

    def build_attempt_summary_payload(self, tab_id, status, message=""):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return {}
        manifest = tab_data.get("manifest", {})
        session_id = str(tab_data.get("timeline_batch_session_id", "")).strip()
        if not session_id:
            return {}
        workspace_meta = self.sync_workspace_archive_metadata(manifest)
        entries = self.get_time_record_entries(tab_id, session_id=session_id, max_items=None)
        valid_starts = [entry.get("start_at") for entry in entries if entry.get("start_at")]
        valid_ends = [self.get_timeline_entry_end(entry) for entry in entries if entry.get("start_at")]
        started_dt = self.parse_time_record_datetime(tab_data.get("attempt_started_at_iso")) or (min(valid_starts) if valid_starts else datetime.datetime.now())
        ended_dt = None
        if status != "running":
            ended_dt = max(valid_ends) if valid_ends else datetime.datetime.now()
        selected_step_total = 0
        for step in manifest.get("steps", []):
            step_id = step.get("order")
            step_var = tab_data.get("step_vars", {}).get(step_id)
            if step_var and step_var.get() == "1":
                selected_step_total += 1
        status_groups = {"done": 0, "running": 0, "failed": 0}
        main_count = 0
        async_count = 0
        for entry in entries:
            if entry.get("axis") == "main":
                main_count += 1
            else:
                async_count += 1
            entry_status = str(entry.get("status", "")).lower()
            if entry_status == "done":
                status_groups["done"] += 1
            elif entry_status == "running":
                status_groups["running"] += 1
            elif entry_status in {"failed", "error", "unfinished", "cancelled"}:
                status_groups["failed"] += 1
        return {
            "workspace_id": workspace_meta.get("workspace_id", ""),
            "session_id": session_id,
            "attempt_name": tab_data.get("attempt_name", ""),
            "status": status,
            "status_label": self.get_attempt_status_label(status),
            "started_at": started_dt.isoformat(sep=" ", timespec="seconds"),
            "ended_at": ended_dt.isoformat(sep=" ", timespec="seconds") if ended_dt else "",
            "main_timer_seconds": round(self.get_live_main_timer_seconds(tab_data), 3),
            "workspace_root": manifest.get("workspace_root", ""),
            "workspace_name": os.path.basename(manifest.get("workspace_root", "")),
            "workspace_display_name": self.get_workspace_display_name(manifest),
            "award": tab_data.get("award", ""),
            "selected_step_total": selected_step_total,
            "main_entry_total": main_count,
            "async_entry_total": async_count,
            "done_entry_total": status_groups["done"],
            "running_entry_total": status_groups["running"],
            "failed_entry_total": status_groups["failed"],
            "entry_total": len(entries),
            "has_post_batch_update": bool(tab_data.get("post_batch_update_done")),
            "error_folder_rel_path": tab_data.get("error_folder_rel_path", ""),
            "error_file_rel_path": tab_data.get("error_file_rel_path", ""),
            "error_excerpt": tab_data.get("attempt_error_excerpt", ""),
            "error_log_path": tab_data.get("attempt_error_log_path", ""),
            "note": message or "",
            "archived_at": datetime.datetime.now().isoformat(sep=" ", timespec="seconds"),
        }

    def upsert_attempt_index(self, manifest, summary):
        if not manifest or not summary:
            return
        index_path = self.get_attempt_index_path(manifest)
        if not index_path:
            return
        index_items = [item for item in self.load_attempt_index(manifest) if item.get("session_id") != summary.get("session_id")]
        index_items.append(dict(summary))
        index_items.sort(key=lambda item: str(item.get("started_at", "")), reverse=True)
        self.write_json_file(index_path, index_items)

    def persist_attempt_snapshot(self, tab_id, status, final=False, message=""):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return {}
        manifest = tab_data.get("manifest", {})
        self.sync_workspace_archive_metadata(manifest)
        session_id = str(tab_data.get("timeline_batch_session_id", "")).strip()
        if not session_id:
            return {}
        attempt_dir = self.get_attempt_dir(manifest, session_id)
        if not attempt_dir:
            return {}
        os.makedirs(attempt_dir, exist_ok=True)
        summary = self.build_attempt_summary_payload(tab_id, status, message=message)
        if not summary:
            return {}
        summary["is_final"] = bool(final)
        self.write_json_file(self.get_attempt_summary_path(manifest, session_id), summary)
        timeline_lines = self.get_session_timeline_lines(self.get_time_record_path(manifest), session_id)
        timeline_path = self.get_attempt_timeline_path(manifest, session_id)
        with open(timeline_path, "w", encoding="utf-8") as f:
            if timeline_lines:
                f.write("\n".join(timeline_lines) + "\n")
        records_summary_path = self.get_attempt_records_summary_path(manifest, session_id)
        records_summary = self.build_attempt_records_summary_payload(tab_id, session_id)
        self.write_json_file(records_summary_path, records_summary)
        self.upsert_attempt_index(manifest, summary)
        return summary

    def begin_batch_attempt(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return ""
        session_id = self.make_timeline_id("session")
        now = datetime.datetime.now()
        tab_data["timeline_batch_session_id"] = session_id
        tab_data["attempt_active"] = True
        tab_data["attempt_started_at_iso"] = now.isoformat(sep=" ", timespec="seconds")
        tab_data["attempt_started_at_epoch"] = time.time()
        tab_data["attempt_status"] = "running"
        tab_data["attempt_name"] = ""
        tab_data["attempt_pending_final_status"] = ""
        tab_data["attempt_pending_final_message"] = ""
        tab_data["attempt_selected_session_id"] = session_id
        tab_data["attempt_error_excerpt"] = ""
        tab_data["attempt_error_log_path"] = ""
        self.persist_attempt_snapshot(tab_id, "running", final=False, message="开始执行所选步骤。")
        return session_id

    def mark_attempt_ready_to_finalize(self, tab_id, status, message=""):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data or not tab_data.get("attempt_active"):
            return {}
        tab_data["attempt_pending_final_status"] = status
        tab_data["attempt_pending_final_message"] = message or ""
        if self.is_main_process_running(tab_id):
            self.persist_attempt_snapshot(tab_id, "running", final=False, message=message or "主步骤链已结束，等待顺序步骤进程结束。")
            return {}
        return self.complete_attempt_run(tab_id, status, message)

    def complete_attempt_run(self, tab_id, status, message=""):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data or not tab_data.get("attempt_active"):
            return {}
        summary = self.persist_attempt_snapshot(tab_id, status, final=True, message=message)
        tab_data["attempt_active"] = False
        tab_data["attempt_status"] = status
        tab_data["attempt_pending_final_status"] = ""
        tab_data["attempt_pending_final_message"] = ""
        tab_data["timeline_batch_session_id"] = ""
        if summary.get("session_id"):
            tab_data["attempt_selected_session_id"] = summary["session_id"]
        self.schedule_final_gantt_autoscale_refresh(tab_id, summary.get("session_id"))
        self.schedule_gui_state_save(tab_id)
        return summary

    def schedule_final_gantt_autoscale_refresh(self, tab_id, session_id, delay_ms=900):
        tab_data = self.active_tabs_data.get(tab_id)
        session_id = _clean(session_id)
        if not tab_data or not session_id:
            return
        if _clean(tab_data.get("gantt_final_autoscaled_session_id")) == session_id:
            return
        job = tab_data.get("gantt_final_refresh_job")
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        tab_data["gantt_final_refresh_session_id"] = session_id
        tab_data["gantt_final_refresh_job"] = self.safe_after(delay_ms, self.finalize_gantt_autoscale_refresh, tab_id, session_id)

    def finalize_gantt_autoscale_refresh(self, tab_id, session_id):
        tab_data = self.active_tabs_data.get(tab_id)
        session_id = _clean(session_id)
        if not tab_data or not session_id:
            return
        tab_data["gantt_final_refresh_job"] = None
        if _clean(tab_data.get("gantt_final_refresh_session_id")) != session_id:
            return
        if tab_data.get("attempt_active") and _clean(tab_data.get("timeline_batch_session_id")) == session_id:
            return
        try:
            self.render_gantt_tab(tab_id)
        except Exception:
            return
        tab_data["gantt_final_refresh_session_id"] = ""
        tab_data["gantt_final_autoscaled_session_id"] = session_id

    def start_batch_run(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if tab_data.get("current_process"):
            self.log_msg(tab_id, "当前仍有顺序代码在运行，请先等待完成或点击暂停。")
            return
        selected_orders = self.reset_selected_steps_for_new_attempt(tab_id)
        if not selected_orders:
            self.log_msg(tab_id, "当前没有勾选可执行的顺序步骤代码。")
            return
        self.clear_error_focus(tab_id)
        tab_data["batch_has_started_steps"] = False
        tab_data["main_batch_finished"] = False
        tab_data["post_batch_update_done"] = False
        self.begin_batch_attempt(tab_id)
        self.start_run_timer(tab_id, "main_batch")
        self.refresh_tab_panels(tab_id)
        self.log_msg(tab_id, "开始执行所选步骤...")
        self.run_next_step(tab_id)

    def run_next_step(self, tab_id):
        tab_data = self.active_tabs_data[tab_id]
        manifest = tab_data["manifest"]
        
        for step in manifest["steps"]:
            step_id = step["order"]
            if tab_data["step_vars"][step_id].get() == "1" and tab_data["step_states"][step_id] == "pending":
                tab_data["step_states"][step_id] = "running"
                tab_data["batch_has_started_steps"] = True
                tab_data["current_step_id"] = step_id
                self.render_workspace_stepper(tab_id)
                self.animate_running(tab_id, step_id)
                self.safe_after(40, self.scroll_current_step_into_view, tab_id)
                self.run_script_thread(step, tab_id)
                return
        tab_data["current_step_id"] = None
        self.finalize_main_batch(tab_id)
        if self.run_post_batch_update(tab_id):
            return
        self.log_msg(tab_id, "主步骤链已执行完毕。")
        self.mark_attempt_ready_to_finalize(tab_id, "success", "主步骤链与本轮尝试已执行完毕。")

    def finalize_main_batch(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data or tab_data.get("main_batch_finished"):
            return
        tab_data["main_batch_finished"] = True
        if tab_data.get("run_timer_mode") == "main_batch":
            self.stop_run_timer(tab_id, failed=False)
        self.update_progress(tab_id, "")

    def run_post_batch_update(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data or not tab_data.get("batch_has_started_steps") or tab_data.get("post_batch_update_done"):
            return False
        manifest = tab_data.get("manifest", {})
        rel_path = manifest.get("default_update_rel_path", "")
        if not rel_path:
            return False
        abs_path = os.path.join(manifest["workspace_root"], rel_path)
        if not os.path.isfile(abs_path):
            return False
        tab_data["post_batch_update_done"] = True
        self.log_msg(tab_id, "主步骤链已结束，开始执行默认收尾代码 update_all_code.py。")
        self.run_script_thread({
            "order": None,
            "script_name": os.path.basename(rel_path),
            "display_label": "update_all_code.py",
            "rel_path": rel_path,
            "folder_rel_path": "",
            "is_root_code": True,
            "is_post_batch_update": True,
        }, tab_id)
        return True

    def animate_running(self, tab_id, step_id, is_light=False):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data or tab_data["step_states"].get(step_id) != "running": return
        color = ACCENT_SOFT_HOVER if is_light else ACCENT_HOVER
        tab_data["step_widgets"][step_id].configure(text_color=color)
        self.safe_after(600, self.animate_running, tab_id, step_id, not is_light)

    def make_async_pid_file(self, manifest, tab_id):
        safe_name = re.sub(r'[<>:"/\\\\|?*]', "_", tab_id)
        runtime_root = self.get_workspace_runtime_root(manifest)
        path = os.path.join(runtime_root, f"async_{safe_name}.pid")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("")
        return path

    def make_async_log_dir(self, manifest, tab_id):
        safe_name = re.sub(r'[<>:"/\\\\|?*]', "_", tab_id)
        runtime_root = self.get_workspace_runtime_root(manifest)
        path = os.path.join(runtime_root, "async", safe_name)
        os.makedirs(path, exist_ok=True)
        return path

    def get_run_log_path(self, manifest, step_info, timeline_env):
        session_id = str((timeline_env or {}).get("GB_TIMELINE_SESSION_ID", "")).strip()
        axis = str((timeline_env or {}).get("GB_TIMELINE_AXIS", "")).strip()
        run_id = str((timeline_env or {}).get("GB_TIMELINE_RUN_ID", "")).strip()
        safe_label = re.sub(r'[\\/:*?"<>|]+', "_", step_info.get("display_label", step_info.get("script_name", "script")))
        if session_id:
            if axis == "main":
                base_dir = self.get_attempt_main_logs_dir(manifest, session_id)
            else:
                base_dir = self.get_attempt_async_logs_dir(manifest, session_id)
        else:
            base_dir = self.get_workspace_runtime_root(manifest)
        if not base_dir:
            base_dir = self.get_logs_root()
        os.makedirs(base_dir, exist_ok=True)
        prefix = run_id or datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return os.path.join(base_dir, f"{prefix}_{safe_label}.log")

    def get_async_pids(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return []
        pid_file = tab_data.get("async_pid_file")
        if not pid_file or not os.path.exists(pid_file):
            return []
        pids = []
        try:
            with open(pid_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.isdigit():
                        pids.append(int(line))
        except Exception:
            return []
        return sorted(set(pids))

    def is_pid_running(self, pid):
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return False
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        except Exception:
            return False
        return True

    def get_live_async_pids(self, tab_id):
        raw_pids = self.get_async_pids(tab_id)
        live_pids = [pid for pid in raw_pids if self.is_pid_running(pid)]
        if len(live_pids) != len(raw_pids):
            tab_data = self.active_tabs_data.get(tab_id)
            pid_file = (tab_data or {}).get("async_pid_file")
            if pid_file:
                try:
                    with open(pid_file, "w", encoding="utf-8") as f:
                        if live_pids:
                            f.write("\n".join(str(pid) for pid in live_pids) + "\n")
                        else:
                            f.write("")
                except Exception:
                    pass
        return live_pids

    def has_async_processes(self, tab_id):
        return bool(self.get_live_async_pids(tab_id))

    def clear_async_pid_file(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        pid_file = tab_data.get("async_pid_file")
        if not pid_file:
            return
        try:
            with open(pid_file, "w", encoding="utf-8") as f:
                f.write("")
        except Exception:
            pass

    def is_main_process_running(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return False
        proc = tab_data.get("current_process")
        if not proc:
            return False
        if proc.poll() is None:
            return True
        tab_data["current_process"] = None
        return False

    def poll_process_states(self):
        active_tab_id = None
        try:
            active_tab_id = self.tabview.get()
        except Exception:
            active_tab_id = None
        for tab_id in list(self.active_tabs_data.keys()):
            main_running = self.is_main_process_running(tab_id)
            enabled = main_running or self.has_async_processes(tab_id)
            self.set_pause_button_state(tab_id, enabled)
            self.refresh_run_timer_label(tab_id)
            self.ensure_workspace_tab_breathing(tab_id)
            tab_data = self.active_tabs_data.get(tab_id)
            if tab_data and tab_data.get("attempt_active"):
                pending_status = _clean(tab_data.get("attempt_pending_final_status"))
                if pending_status and not main_running:
                    self.complete_attempt_run(tab_id, pending_status, tab_data.get("attempt_pending_final_message", ""))
                    tab_data = self.active_tabs_data.get(tab_id)
            if active_tab_id != tab_id:
                continue
            if not tab_data:
                continue
            selected_session_id = str(tab_data.get("attempt_selected_session_id", "")).strip()
            active_session_id = str(tab_data.get("timeline_batch_session_id", "")).strip()
            should_refresh_gantt = (
                self.get_workspace_view_name(tab_id) == "流水线"
                and self.is_main_process_running(tab_id)
                and bool(tab_data.get("attempt_active"))
                and selected_session_id
                and selected_session_id == active_session_id
            )
            if should_refresh_gantt:
                now = time.monotonic()
                last_gantt_refresh = float(tab_data.get("gantt_last_refresh", 0.0) or 0.0)
                if (now - last_gantt_refresh) * 1000 >= self.auto_refresh_interval_ms:
                    tab_data["gantt_last_refresh"] = now
                    self.render_gantt_tab(tab_id)
            if not tab_data.get("auto_refresh_enabled", False):
                continue
            now = time.monotonic()
            last = tab_data.get("last_auto_refresh", 0.0)
            if (now - last) * 1000 < self.auto_refresh_interval_ms:
                continue
            tab_data["last_auto_refresh"] = now
            self.refresh_output_board(tab_id)
        self.poll_process_job = self.safe_after(1000, self.poll_process_states)

    def set_pause_button_state(self, tab_id, enabled):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        pause_button = tab_data.get("pause_button")
        if pause_button and pause_button.winfo_exists():
            pause_button.configure(state="normal" if enabled else "disabled")

    def reset_run_timer_display(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["run_timer_started_at"] = None
        tab_data["run_timer_elapsed"] = 0.0
        tab_data["run_timer_running"] = False
        tab_data["run_timer_failed"] = False
        tab_data["run_timer_mode"] = ""
        self.refresh_run_timer_label(tab_id)

    def reset_selected_steps_for_new_attempt(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return []
        selected_orders = []
        for step in tab_data.get("manifest", {}).get("steps", []):
            step_id = step.get("order")
            step_var = tab_data.get("step_vars", {}).get(step_id)
            if step_id is None or not step_var or step_var.get() != "1":
                continue
            if not step.get("exists"):
                continue
            tab_data["step_states"][step_id] = "pending"
            selected_orders.append(step_id)
        tab_data["saved_step_selection_loaded"] = True
        tab_data["saved_step_selection_orders"] = list(selected_orders)
        if selected_orders:
            tab_data["workspace_stepper_selected_orders_snapshot"] = list(selected_orders)
            tab_data["workspace_stepper_snapshot_active"] = True

        tab_data["current_process"] = None
        tab_data["current_run_info"] = None
        tab_data["current_step_id"] = None
        tab_data["progress_active"] = False
        tab_data["batch_has_started_steps"] = False
        tab_data["main_batch_finished"] = False
        tab_data["post_batch_update_done"] = False
        tab_data["attempt_active"] = False
        tab_data["attempt_status"] = ""
        self.clear_error_focus(tab_id)
        self.reset_run_timer_display(tab_id)
        self.refresh_tab_panels(tab_id)
        self.schedule_gui_state_save(tab_id)
        return selected_orders

    def format_elapsed_time(self, elapsed_seconds):
        total_seconds = max(0, int(elapsed_seconds))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def refresh_run_timer_label(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        label = tab_data.get("run_timer_label")
        if not label or not label.winfo_exists():
            return
        elapsed = tab_data.get("run_timer_elapsed", 0.0)
        if tab_data.get("run_timer_running") and tab_data.get("run_timer_started_at") is not None:
            elapsed = time.monotonic() - tab_data["run_timer_started_at"]
        color = DANGER if tab_data.get("run_timer_failed") else SUCCESS
        label.configure(text=self.format_elapsed_time(elapsed), text_color=color)

    def start_run_timer(self, tab_id, mode):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["run_timer_started_at"] = time.monotonic()
        tab_data["run_timer_elapsed"] = 0.0
        tab_data["run_timer_running"] = True
        tab_data["run_timer_failed"] = False
        tab_data["run_timer_mode"] = mode
        self.refresh_run_timer_label(tab_id)
        self.schedule_gui_state_save(tab_id)

    def stop_run_timer(self, tab_id, failed=False):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if tab_data.get("run_timer_running") and tab_data.get("run_timer_started_at") is not None:
            tab_data["run_timer_elapsed"] = time.monotonic() - tab_data["run_timer_started_at"]
        tab_data["run_timer_running"] = False
        tab_data["run_timer_started_at"] = None
        tab_data["run_timer_failed"] = bool(failed)
        self.refresh_run_timer_label(tab_id)
        self.schedule_gui_state_save(tab_id)

    def clear_error_focus(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["error_folder_rel_path"] = ""
        tab_data["error_file_rel_path"] = ""
        tab_data["error_is_root"] = False
        self.schedule_gui_state_save(tab_id)

    def set_error_focus(self, tab_id, step_info):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        folder_rel_path = step_info.get("folder_rel_path", "") if step_info else ""
        rel_path = step_info.get("rel_path", "") if step_info else ""
        is_root_code = bool(step_info.get("is_root_code")) if step_info else False
        tab_data["error_folder_rel_path"] = folder_rel_path
        tab_data["error_file_rel_path"] = rel_path
        tab_data["error_is_root"] = bool(is_root_code or not folder_rel_path)
        tab_data["left_tab_preferred"] = "代码文件夹"
        left_tabview = tab_data.get("left_tabview")
        if left_tabview and left_tabview.winfo_exists():
            try:
                left_tabview.set("代码文件夹")
            except Exception:
                pass
        self.schedule_gui_state_save(tab_id)

    def fail_current_chain(self, tab_id, step_info, message="", affect_timer=True):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        self.update_attempt_error_snapshot(tab_id)
        tab_data["current_process"] = None
        tab_data["current_run_info"] = None
        tab_data["current_step_id"] = None
        tab_data["main_batch_finished"] = True
        tab_data["post_batch_update_done"] = True
        if affect_timer:
            self.stop_run_timer(tab_id, failed=True)
        self.set_error_focus(tab_id, step_info or {})
        step_id = step_info.get("order") if step_info else None
        if step_id is not None:
            self.set_step_result(tab_id, step_id, False)
        else:
            self.set_pause_button_state(tab_id, self.has_async_processes(tab_id))
        self.complete_attempt_run(tab_id, "failed", message or "当前尝试执行失败。")
        self.refresh_tab_panels(tab_id)
        self.set_pause_button_state(tab_id, self.has_async_processes(tab_id))
        if self.has_async_processes(tab_id):
            self.log_msg(tab_id, "主链已失败，异步子进程保留现场，未自动终止。")
        if message:
            self.log_msg(tab_id, message)

    def finish_manual_code_run(self, tab_id, step_info, success):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["current_run_info"] = None
        if success:
            self.refresh_tab_panels(tab_id)
            self.log_msg(tab_id, f"代码执行完成: {step_info.get('display_label', step_info.get('script_name', ''))}")
        else:
            self.fail_current_chain(tab_id, step_info, "代码执行失败，已终止当前链条并高亮错误文件夹。", affect_timer=False)

    def set_step_result(self, tab_id, step_id, success):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data: return
        
        tab_data["step_states"][step_id] = "success" if success else "error"
        if tab_data.get("current_step_id") == step_id:
            tab_data["current_step_id"] = None
        self.update_progress(tab_id, "")
        self.set_pause_button_state(tab_id, self.has_async_processes(tab_id))
        
        # 只要存在 widget 就更新颜色
        if step_id in tab_data["step_widgets"]:
            color = SUCCESS if success else DANGER
            tab_data["step_widgets"][step_id].configure(text_color=color)
        self.render_workspace_stepper(tab_id)
        self.schedule_gui_state_save(tab_id)
        
        if success:
            self.safe_after(500, self.run_next_step, tab_id)

    def finalize_step_success(self, tab_id, step_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if tab_data["step_states"].get(step_id) != "running":
            return
        tab_data["current_run_info"] = None
        self.set_step_result(tab_id, step_id, True)
        self.refresh_tab_panels(tab_id)

    def finish_post_batch_update(self, tab_id, success):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["current_run_info"] = None
        self.update_progress(tab_id, "")
        if success:
            self.log_msg(tab_id, "默认收尾代码 update_all_code.py 已执行完成。")
            self.mark_attempt_ready_to_finalize(tab_id, "success", "主步骤链和默认收尾代码已执行完毕。")
            self.log_msg(tab_id, "全部流程已执行完毕。")
        else:
            self.fail_current_chain(tab_id, {
                "display_label": "update_all_code.py",
                "script_name": "update_all_code.py",
                "rel_path": tab_data.get("manifest", {}).get("default_update_rel_path", ""),
                "folder_rel_path": "",
                "is_root_code": True,
            }, "默认收尾代码 update_all_code.py 执行失败，已高亮根目录。", affect_timer=False)

    def update_progress(self, tab_id, msg):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        progress_label = tab_data.get("progress_label")
        if progress_label and progress_label.winfo_exists():
            progress_label.configure(text=msg)
            if msg:
                progress_label.grid()
            else:
                progress_label.grid_remove()
        tab_data["progress_active"] = bool(msg)

    def cancel_log_auto_follow_resume(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        job = tab_data.get("log_auto_follow_resume_job")
        if job:
            self.cancel_after_handle(job)
        tab_data["log_auto_follow_resume_job"] = None

    def is_log_box_near_bottom(self, log_box, threshold=0.02):
        if not log_box or not log_box.winfo_exists():
            return True
        try:
            yview = log_box.yview()
        except Exception:
            return True
        if not yview:
            return True
        return float(yview[1]) >= 1.0 - float(threshold)

    def scroll_log_box_to_bottom(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        log_box = tab_data.get("log_box")
        if not log_box or not log_box.winfo_exists():
            return
        try:
            log_box.see("end")
        except Exception:
            return
        tab_data["log_auto_follow_enabled"] = True
        tab_data["log_auto_follow_last_user_ts"] = 0.0
        self.cancel_log_auto_follow_resume(tab_id)

    def resume_log_auto_follow(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["log_auto_follow_resume_job"] = None
        last_user_ts = float(tab_data.get("log_auto_follow_last_user_ts", 0.0) or 0.0)
        if last_user_ts:
            elapsed_ms = int((time.monotonic() - last_user_ts) * 1000)
            if elapsed_ms < LOG_AUTO_FOLLOW_IDLE_MS:
                tab_data["log_auto_follow_resume_job"] = self.safe_after(
                    max(80, LOG_AUTO_FOLLOW_IDLE_MS - elapsed_ms),
                    self.resume_log_auto_follow,
                    tab_id,
                )
                return
        self.scroll_log_box_to_bottom(tab_id)

    def update_log_auto_follow_state(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        log_box = tab_data.get("log_box")
        if self.is_log_box_near_bottom(log_box):
            tab_data["log_auto_follow_enabled"] = True
            tab_data["log_auto_follow_last_user_ts"] = 0.0
            self.cancel_log_auto_follow_resume(tab_id)
            return
        tab_data["log_auto_follow_enabled"] = False
        tab_data["log_auto_follow_last_user_ts"] = time.monotonic()
        self.cancel_log_auto_follow_resume(tab_id)
        tab_data["log_auto_follow_resume_job"] = self.safe_after(LOG_AUTO_FOLLOW_IDLE_MS, self.resume_log_auto_follow, tab_id)

    def on_log_box_user_interaction(self, tab_id, _event=None):
        self.safe_after(0, self.update_log_auto_follow_state, tab_id)
        return None

    def bind_log_box_auto_follow(self, tab_id, log_box):
        if not log_box or not log_box.winfo_exists():
            return
        text_widget = getattr(log_box, "_textbox", None)
        if text_widget and getattr(text_widget, "_gb_log_auto_follow_bound", False):
            return
        sequences = [
            "<MouseWheel>",
            "<Button-4>",
            "<Button-5>",
            "<Shift-MouseWheel>",
            "<Prior>",
            "<Next>",
            "<Up>",
            "<Down>",
            "<Home>",
            "<End>",
            "<ButtonPress-1>",
            "<B1-Motion>",
        ]
        for sequence in sequences:
            try:
                log_box.bind(sequence, lambda event, tid=tab_id: self.on_log_box_user_interaction(tid, event), add="+")
            except Exception:
                continue
        y_scrollbar = getattr(log_box, "_y_scrollbar", None)
        if y_scrollbar and y_scrollbar.winfo_exists():
            try:
                text_widget = getattr(log_box, "_textbox", None)
                y_scrollbar.configure(
                    command=lambda *args, tid=tab_id, tb=text_widget: (
                        tb.yview(*args) if tb is not None else None,
                        self.safe_after(0, self.update_log_auto_follow_state, tid),
                    )[0]
                )
            except Exception:
                pass
        if text_widget is not None:
            text_widget._gb_log_auto_follow_bound = True

    def log_msg(self, tab_id, msg, raw=False, overwrite_last=False):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if overwrite_last:
            self.update_progress(tab_id, msg)
            return
        self.update_progress(tab_id, "")
        log_box = tab_data["log_box"]
        log_box.configure(state="normal")
        if not raw:
            log_box.insert("end", f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        else:
            log_box.insert("end", f"{msg}\n")
        if tab_data.get("log_auto_follow_enabled", True):
            log_box.see("end")
        log_box.configure(state="disabled")
        tab_data["progress_active"] = False

    def terminate_process_tree(self, proc):
        if not proc:
            return
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def terminate_async_processes(self, tab_id):
        for pid in self.get_async_pids(tab_id):
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass
        self.clear_async_pid_file(tab_id)


    def run_script_thread(self, step_info, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        run_info = dict(step_info)
        tab_data["current_run_info"] = run_info
        self.log_msg(tab_id, f"开始运行: {step_info.get('display_label', step_info['script_name'])}")
        self.set_pause_button_state(tab_id, True)
        threading.Thread(target=self._exec_subprocess, args=(run_info, tab_id), daemon=True).start()


    def is_progress_line(self, line):
        return "%" in line and "|" in line and "/" in line and "[" in line and "]" in line


    def is_important_log(self, line):
        # 如果包含进度条常见特征符，直接放行
        if self.is_progress_line(line):
            return True
        # 保留原有的关键字过滤
        if line.startswith("0 ") or line.startswith("1 ") or line.startswith("..."): return False
        if "Name:" in line and "Length:" in line and "dtype:" in line: return False
        if line.startswith("<class") or line.startswith("#   Column") or line.startswith("---  ------"): return False
        if "RangeIndex:" in line or "Data columns" in line or "memory usage:" in line or "dtypes:" in line: return False
        important_keywords = ["---", "[DB]", "正在", "完成", "成功", "写入", "报错", "异常", "Error", "Exception", "用时", "共"]
        for kw in important_keywords:
            if kw in line: return True
        return False


    def _exec_subprocess(self, step_info, tab_id):
        tab_data = self.active_tabs_data[tab_id]
        manifest = tab_data["manifest"]
        env = os.environ.copy()
        runtime_patch_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gb_runtime_patch")
        step_entry_script = os.path.join(runtime_patch_dir, "step_process_entry.py")
        existing_pythonpath = str(env.get("PYTHONPATH", "")).strip()
        pythonpath_parts = [part for part in existing_pythonpath.split(os.pathsep) if part]
        if runtime_patch_dir not in pythonpath_parts:
            pythonpath_parts.insert(0, runtime_patch_dir)
        env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["GB_ENABLE_ASYNC_LOG_SHIM"] = "1"
        env["GB_ASYNC_PID_FILE"] = os.path.abspath(tab_data["async_pid_file"])
        timeline_env = self.build_timeline_env(tab_id, step_info)
        log_filename = self.get_run_log_path(manifest, step_info, timeline_env)
        session_id = str(timeline_env.get("GB_TIMELINE_SESSION_ID", "")).strip()
        if session_id:
            env["GB_ASYNC_LOG_DIR"] = os.path.abspath(self.get_attempt_async_logs_dir(manifest, session_id))
        else:
            env["GB_ASYNC_LOG_DIR"] = os.path.abspath(tab_data["async_log_dir"])
        run_info = tab_data.get("current_run_info")
        if run_info is not None:
            run_info["timeline_env"] = dict(timeline_env)
            run_info["timeline_started_at"] = time.time()
        env.update(timeline_env)
        init_ctx = getattr(self, "sidebar_initialize_context", {}) or {}
        init_env_applied = False
        if init_ctx.get("active") and _clean(init_ctx.get("year")) and _clean(init_ctx.get("award")) == _clean(tab_data.get("award")):
            env["GB_INIT_FROM_TERMINAL"] = "1"
            env["GB_INIT_YEAR"] = str(init_ctx.get("year")).strip()
            init_env_applied = True
        
        try:
            with open(log_filename, "w", encoding="utf-8") as f:
                if run_info is not None:
                    run_info["log_filename"] = os.path.abspath(log_filename)
                extra_argv = []
                for arg in step_info.get("argv", []) or []:
                    if arg is None:
                        continue
                    extra_argv.append(str(arg))
                cmd = [sys.executable, step_entry_script, step_info["rel_path"], *extra_argv]
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=manifest["workspace_root"],
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                    env=env
                )
                
                # --- 新增：存储进程句柄 ---
                tab_data["current_process"] = process
                if run_info is not None:
                    run_info["pid"] = process.pid

                pending_progress_line = None

                def flush_pending_progress():
                    nonlocal pending_progress_line
                    if not pending_progress_line:
                        return
                    f.write(pending_progress_line + "\n")
                    f.flush()
                    if self.is_important_log(pending_progress_line):
                        self.safe_after(0, self.log_msg, tab_id, pending_progress_line, True, True)
                    pending_progress_line = None

                for line in process.stdout:
                    chunks = line.replace("\r", "\n").splitlines()
                    if not chunks and line:
                        chunks = [line.rstrip("\r\n")]
                    for chunk in chunks:
                        clean_line = chunk.strip()
                        if not clean_line:
                            flush_pending_progress()
                            f.write("\n")
                            f.flush()
                            continue
                        if self.is_progress_line(clean_line):
                            pending_progress_line = clean_line
                            self.safe_after(0, self.update_progress, tab_id, clean_line)
                            continue
                        flush_pending_progress()
                        f.write(chunk + "\n")
                        f.flush()
                        if self.is_important_log(clean_line):
                            self.safe_after(0, self.log_msg, tab_id, clean_line, True, False)

                flush_pending_progress()
                
                process.wait()
                # --- 新增：任务完成后清理句柄 ---
                tab_data["current_process"] = None
                if init_env_applied:
                    year_info_path = os.path.join(manifest["workspace_root"], "参评信息", "年份信息.txt")
                    if os.path.isfile(year_info_path):
                        self.clear_sidebar_initialize_context()
                self.safe_after(0, self.set_pause_button_state, tab_id, self.has_async_processes(tab_id))
                
                
            if process.returncode == 0:
                self.safe_after(0, self.log_msg, tab_id, f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] ==== 执行成功 ====")
                if self.should_refresh_terminal_after_run(step_info):
                    self.safe_after(0, self.refresh_terminal_after_test_run, tab_id, step_info)
                if step_info.get("is_post_batch_update"):
                    self.safe_after(0, self.finish_post_batch_update, tab_id, True)
                elif step_info.get("is_manual_code"):
                    self.safe_after(0, self.finish_manual_code_run, tab_id, step_info, True)
                else:
                    self.safe_after(0, self.finalize_step_success, tab_id, step_info["order"])
            else:
                self.update_attempt_error_snapshot(tab_id, run_info or step_info)
                self.append_terminal_timeline_end(tab_id, run_info or step_info, "failed")
                self.safe_after(0, self.log_msg, tab_id, f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] ==== 执行失败: 返回码 {process.returncode} ====")
                if step_info.get("is_post_batch_update"):
                    self.safe_after(0, self.finish_post_batch_update, tab_id, False)
                elif step_info.get("is_manual_code"):
                    self.safe_after(0, self.finish_manual_code_run, tab_id, step_info, False)
                else:
                    self.safe_after(0, self.fail_current_chain, tab_id, step_info, "代码执行失败，已终止当前链条并高亮错误文件夹。")
                
        except Exception as e:
            tab_data["current_process"] = None
            self.update_attempt_error_snapshot(tab_id, run_info or step_info)
            self.append_terminal_timeline_end(tab_id, run_info or step_info, "error")
            self.safe_after(0, self.set_pause_button_state, tab_id, self.has_async_processes(tab_id))
            self.safe_after(0, self.log_msg, tab_id, f"进程拉起异常: {str(e)}")
            if step_info.get("is_post_batch_update"):
                self.safe_after(0, self.finish_post_batch_update, tab_id, False)
            elif step_info.get("is_manual_code"):
                self.safe_after(0, self.finish_manual_code_run, tab_id, step_info, False)
            else:
                self.safe_after(0, self.fail_current_chain, tab_id, step_info, "进程拉起异常，已终止当前链条并高亮错误文件夹。")


    def refresh_tab_panels(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if tab_data.get("refresh_panels_job"):
            return
        self.request_tab_loading_overlay(tab_id, "正在刷新界面...")
        tab_data["refresh_panels_job"] = self.safe_after_idle(self._refresh_tab_panels_impl, tab_id)

    def _refresh_tab_panels_impl(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["refresh_panels_job"] = None
        try:
            current_manifest = tab_data.get("manifest", {})
            tab_data["manifest"] = reconcile_filesystem(current_manifest)
            self.render_tab_content(tab_id)
            self.render_workspace_stepper(tab_id)
            self.render_gantt_tab(tab_id)
            # 计算结果页需要跟着文件系统刷新，避免用户停留在其它页运行 step_4 后结果区仍显示旧内容。
            self.render_calc_results_panel(tab_id)
        except Exception as exc:
            self.show_gui_error("刷新界面失败", exc, "当前标签页刷新失败，界面已保留现场，请检查报错信息。", tab_id=tab_id)
        finally:
            self.hide_tab_loading_overlay(tab_id)

    def cleanup_tab_runtime(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        self.save_workspace_gui_state(tab_id)
        self.stop_workspace_tab_breathing(tab_id)
        self.cancel_log_auto_follow_resume(tab_id)
        self.cancel_after_handle(tab_data.get("refresh_panels_job"))
        tab_data["refresh_panels_job"] = None
        self.hide_tab_loading_overlay(tab_id)
        proc = tab_data.get("current_process")
        if proc:
            self.terminate_process_tree(proc)
            tab_data["current_process"] = None
        self.terminate_async_processes(tab_id)
        self.update_progress(tab_id, "")
        self.set_pause_button_state(tab_id, False)
        pid_file = tab_data.get("async_pid_file")
        if pid_file and os.path.exists(pid_file):
            try:
                os.remove(pid_file)
            except OSError:
                pass

    def finalize_tab_close(self, tab_id):
        self.hide_tab_hover_close()
        tab_data = self.active_tabs_data.get(tab_id)
        if tab_data:
            self.stop_workspace_tab_breathing(tab_id)
            self.cancel_log_auto_follow_resume(tab_id)
            job = tab_data.get("gui_state_save_job")
            if job:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
        try:
            self.tabview.delete(tab_id)
        except Exception:
            pass
        self.active_tabs_data.pop(tab_id, None)
        self.safe_after_idle(self.refresh_tab_hover_close_bindings)

    def close_tab(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        self.cleanup_tab_runtime(tab_id)
        self.finalize_tab_close(tab_id)

    def kill_process(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data: return
        current_run_info = tab_data.get("current_run_info") or {}
        affect_timer = not current_run_info.get("is_post_batch_update") and not current_run_info.get("is_manual_code")
        
        proc = tab_data.get("current_process")
        if proc:
            self.append_terminal_timeline_end(tab_id, current_run_info, "cancelled")
            # 强制杀死进程
            self.terminate_process_tree(proc)
            tab_data["current_process"] = None
            current_step_id = tab_data.get("current_step_id")
            if current_step_id in tab_data["step_states"]:
                tab_data["step_states"][current_step_id] = "error"
            if current_step_id in tab_data["step_widgets"]:
                tab_data["step_widgets"][current_step_id].configure(text_color=DANGER)
            self.render_workspace_stepper(tab_id)
            self.update_progress(tab_id, "")
            self.terminate_async_processes(tab_id)
            self.set_pause_button_state(tab_id, False)
            if affect_timer:
                self.stop_run_timer(tab_id, failed=True)
            self.set_error_focus(tab_id, tab_data.get("current_run_info") or {})
            tab_data["current_run_info"] = None
            self.complete_attempt_run(tab_id, "cancelled", "用户手动终止了当前尝试。")
            self.refresh_tab_panels(tab_id)
            self.log_msg(tab_id, "!!! 已强制终止当前进程 !!!")
        else:
            had_async = self.has_async_processes(tab_id)
            self.terminate_async_processes(tab_id)
            self.set_pause_button_state(tab_id, False)
            if had_async:
                if affect_timer:
                    self.stop_run_timer(tab_id, failed=True)
                self.set_error_focus(tab_id, tab_data.get("current_run_info") or {})
                tab_data["current_run_info"] = None
                self.complete_attempt_run(tab_id, "cancelled", "用户手动终止了当前尝试。")
                self.refresh_tab_panels(tab_id)
            if had_async:
                self.log_msg(tab_id, "!!! 已强制终止异步启动的子进程 !!!")
            else:
                self.log_msg(tab_id, "当前没有正在运行的进程。")
    

if __name__ == "__main__":
    app = GoldenBullTerminal()
    app.mainloop()
