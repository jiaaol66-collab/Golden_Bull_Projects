import os
import re
import shutil
import subprocess
import sys
import time

import customtkinter as ctk

try:
    from .style_config import *
    from .motion import smooth_scroll_to
except Exception:
    from style_config import *
    from motion import smooth_scroll_to
from openpyxl import load_workbook
from award_config import get_manifest_award

try:
    import duckdb
except Exception:
    duckdb = None


def _clean_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in (".", "None") else text


def _parse_run_order(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value:
            return None
        if value.is_integer():
            return int(value)
        return None
    text = _clean_text(value)
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if re.match(r"^\d+\.0+$", text):
        return int(float(text))
    return None


def _natural_sort_key(text):
    parts = re.split(r"(\d+)", _clean_text(text).lower())
    key = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part))
    return tuple(key)


def _extract_step_title(*texts):
    for raw in texts:
        text = _clean_text(raw).replace("/", os.sep).replace("\\", os.sep)
        if not text:
            continue
        first_part = text.split(os.sep, 1)[0]
        if first_part.lower().startswith("step_"):
            return first_part
    for raw in texts:
        text = _clean_text(raw)
        if text:
            return text
    return "未命名步骤"


class WorkspaceUIMixin:
    def ensure_tab_busy_indicator(self, tab_id, parent):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return None
        bar = tab_data.get("busy_indicator_bar")
        if bar and bar.winfo_exists():
            return bar

        bar = ctk.CTkProgressBar(
            parent,
            width=92,
            height=6,
            corner_radius=6,
            mode="indeterminate",
            progress_color=ACCENT,
            fg_color=ACCENT_SEGMENT_BG,
        )
        tab_data["busy_indicator_bar"] = bar
        bar.place_forget()
        tab_data["busy_indicator_visible"] = False
        tab_data["busy_indicator_started_at"] = 0.0
        tab_data["busy_indicator_show_job"] = None
        tab_data["busy_indicator_hide_job"] = None
        return bar

    def request_tab_busy_indicator(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if getattr(self, "window_resizing", False):
            return
        if tab_data.get("console_resizing"):
            return
        if tab_data.get("busy_indicator_visible"):
            return
        if tab_data.get("busy_indicator_show_job"):
            return
        tab_data["busy_indicator_show_job"] = self.safe_after(120, self.show_tab_busy_indicator, tab_id)

    def show_tab_busy_indicator(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["busy_indicator_show_job"] = None
        parent = tab_data.get("tab_root")
        if not parent or not parent.winfo_exists():
            return
        bar = self.ensure_tab_busy_indicator(tab_id, parent)
        if not bar or not bar.winfo_exists():
            return
        if tab_data.get("busy_indicator_visible"):
            return
        bar.place(relx=1.0, x=-16, y=10, anchor="ne")
        bar.lift()
        tab_data["busy_indicator_visible"] = True
        tab_data["busy_indicator_started_at"] = time.monotonic()
        try:
            bar.start()
        except Exception:
            pass

    def hide_tab_busy_indicator(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if tab_data.get("busy_indicator_visible"):
            started_at = float(tab_data.get("busy_indicator_started_at", 0.0) or 0.0)
            elapsed_ms = (time.monotonic() - started_at) * 1000 if started_at else 0.0
            min_visible_ms = 240
            if elapsed_ms < min_visible_ms:
                delay_ms = int(max(0, min_visible_ms - elapsed_ms))
                self.cancel_after_handle(tab_data.get("busy_indicator_hide_job"))
                tab_data["busy_indicator_hide_job"] = self.safe_after(delay_ms, self._hide_tab_busy_indicator_now, tab_id)
                return
        self._hide_tab_busy_indicator_now(tab_id)

    def _hide_tab_busy_indicator_now(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["busy_indicator_hide_job"] = None
        show_job = tab_data.get("busy_indicator_show_job")
        if show_job:
            try:
                self.after_cancel(show_job)
            except Exception:
                pass
        tab_data["busy_indicator_show_job"] = None
        bar = tab_data.get("busy_indicator_bar")
        if bar and bar.winfo_exists():
            try:
                bar.stop()
            except Exception:
                pass
            bar.place_forget()
        tab_data["busy_indicator_visible"] = False
        tab_data["busy_indicator_started_at"] = 0.0

    def ensure_tab_loading_overlay(self, tab_id, parent):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return None
        overlay = tab_data.get("loading_overlay")
        if overlay and overlay.winfo_exists():
            return overlay

        overlay = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=RADIUS_OUTER)
        tab_data["loading_overlay"] = overlay

        overlay_content = ctk.CTkFrame(
            overlay,
            width=320,
            height=96,
            fg_color="transparent",
            corner_radius=RADIUS_PANEL,
            border_width=0,
            border_color=PANEL_BORDER,
        )
        overlay_content.place(relx=0.5, rely=0.45, anchor="center")
        overlay_content.pack_propagate(False)
        tab_data["loading_overlay_content"] = overlay_content

        caption = ctk.CTkLabel(overlay_content, text="请稍候", text_color=TEXT_MUTED, font=ui_font(11))
        caption.pack(padx=20, pady=(8, 2))
        tab_data["loading_overlay_caption"] = caption

        label = ctk.CTkLabel(overlay_content, text="加载中...", text_color=TEXT_PRIMARY, font=ui_font(18, "bold"))
        label.pack(padx=20, pady=(0, 10))
        tab_data["loading_overlay_label"] = label

        bar = ctk.CTkProgressBar(
            overlay_content,
            width=188,
            height=6,
            corner_radius=6,
            mode="indeterminate",
            progress_color=ACCENT,
            fg_color=ACCENT_SEGMENT_BG,
        )
        bar.pack(padx=20, pady=(0, 12))
        tab_data["loading_overlay_bar"] = bar

        overlay.place_forget()
        tab_data["loading_overlay_visible"] = False
        tab_data["loading_overlay_started_at"] = 0.0
        tab_data["loading_overlay_mode"] = ""
        return overlay

    def configure_tab_loading_overlay_style(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        overlay = tab_data.get("loading_overlay")
        content = tab_data.get("loading_overlay_content")
        caption = tab_data.get("loading_overlay_caption")
        label = tab_data.get("loading_overlay_label")
        bar = tab_data.get("loading_overlay_bar")
        if not overlay or not overlay.winfo_exists():
            return
        mode = tab_data.get("loading_overlay_mode") or "refresh"
        is_mount = mode == "mount"
        try:
            overlay.configure(fg_color=APP_BG if is_mount else "transparent")
        except Exception:
            pass
        if content and content.winfo_exists():
            try:
                content.configure(
                    fg_color="transparent" if is_mount else SURFACE_BG,
                    border_width=0 if is_mount else 1,
                    border_color=PANEL_BORDER,
                    width=320 if is_mount else 280,
                    height=96 if is_mount else 86,
                )
                content.place_configure(relx=0.5, rely=0.45 if is_mount else 0.43, anchor="center")
            except Exception:
                pass
        if caption and caption.winfo_exists():
            try:
                caption.configure(
                    text="正在准备界面" if is_mount else "正在处理",
                    text_color=TEXT_MUTED,
                    font=ui_font(11),
                )
            except Exception:
                pass
        if label and label.winfo_exists():
            try:
                label.configure(
                    text_color=TEXT_PRIMARY,
                    font=ui_font(18 if is_mount else 14, "bold"),
                )
            except Exception:
                pass
        if bar and bar.winfo_exists():
            try:
                bar.configure(
                    width=188 if is_mount else 220,
                    height=6 if is_mount else 8,
                    corner_radius=6,
                    fg_color=ACCENT_SEGMENT_BG,
                    progress_color=ACCENT,
                )
            except Exception:
                pass

    def start_mount_loading_overlay(self, tab_id, message="正在加载工作区"):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        parent = tab_data.get("tab_root")
        if not parent or not parent.winfo_exists():
            return
        overlay = self.ensure_tab_loading_overlay(tab_id, parent)
        if not overlay or not overlay.winfo_exists():
            return
        self._hide_tab_busy_indicator_now(tab_id)
        self.cancel_after_handle(tab_data.get("loading_overlay_show_job"))
        tab_data["loading_overlay_show_job"] = None
        self.cancel_after_handle(tab_data.get("loading_overlay_hide_job"))
        tab_data["loading_overlay_hide_job"] = None
        self.cancel_after_handle(tab_data.get("mount_loading_finish_job"))
        tab_data["mount_loading_finish_job"] = None
        self.cancel_after_handle(tab_data.get("loading_overlay_anim_job"))
        tab_data["loading_overlay_anim_job"] = None
        tab_data["loading_overlay_base_text"] = message
        tab_data["loading_overlay_anim_step"] = 0
        tab_data["loading_overlay_mode"] = "mount"
        self.configure_tab_loading_overlay_style(tab_id)
        self.show_tab_loading_overlay(tab_id, message)
        self.safe_after_idle(self.raise_tab_loading_overlay, tab_id)
        self.tick_loading_overlay_text(tab_id)

    def finish_mount_loading_overlay(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if getattr(self, "window_resizing", False):
            self.cancel_after_handle(tab_data.get("mount_loading_finish_job"))
            tab_data["mount_loading_finish_job"] = self.safe_after(180, self.finish_mount_loading_overlay, tab_id)
            return
        self.hide_tab_loading_overlay(tab_id)

    def tick_loading_overlay_text(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["loading_overlay_anim_job"] = None
        if not tab_data.get("loading_overlay_visible"):
            return
        label = tab_data.get("loading_overlay_label")
        if not label or not label.winfo_exists():
            return
        base_text = tab_data.get("loading_overlay_base_text") or "加载中"
        step = int(tab_data.get("loading_overlay_anim_step", 0) or 0)
        dots = "." * ((step % 3) + 1)
        label.configure(text=f"{base_text}{dots}")
        tab_data["loading_overlay_anim_step"] = step + 1
        tab_data["loading_overlay_anim_job"] = self.safe_after(280, self.tick_loading_overlay_text, tab_id)

    def request_tab_loading_overlay(self, tab_id, message="加载中..."):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if getattr(self, "window_resizing", False):
            return
        if tab_data.get("console_resizing"):
            return
        self.request_tab_busy_indicator(tab_id)
        label = tab_data.get("loading_overlay_label")
        if label and label.winfo_exists():
            label.configure(text=message)
        if tab_data.get("loading_overlay_visible"):
            return
        show_job = tab_data.get("loading_overlay_show_job")
        if show_job:
            return

        tab_data["loading_overlay_mode"] = "refresh"
        self.configure_tab_loading_overlay_style(tab_id)
        tab_data["loading_overlay_show_job"] = self.safe_after(900, self.show_tab_loading_overlay, tab_id, message)

    def show_tab_loading_overlay(self, tab_id, message="加载中..."):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["loading_overlay_show_job"] = None
        parent = tab_data.get("tab_root")
        if not parent or not parent.winfo_exists():
            return
        overlay = self.ensure_tab_loading_overlay(tab_id, parent)
        if not overlay or not overlay.winfo_exists():
            return
        self.configure_tab_loading_overlay_style(tab_id)
        label = tab_data.get("loading_overlay_label")
        if label and label.winfo_exists():
            label.configure(text=message)
        tab_data["loading_overlay_base_text"] = message.rstrip(".") or "加载中"
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        overlay.lift()
        tab_data["loading_overlay_visible"] = True
        tab_data["loading_overlay_started_at"] = time.monotonic()
        bar = tab_data.get("loading_overlay_bar")
        if bar and bar.winfo_exists():
            try:
                bar.start()
            except Exception:
                pass
        if not tab_data.get("loading_overlay_anim_job"):
            tab_data["loading_overlay_anim_job"] = self.safe_after(280, self.tick_loading_overlay_text, tab_id)
        self.safe_after_idle(self.raise_tab_loading_overlay, tab_id)

    def raise_tab_loading_overlay(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data or not tab_data.get("loading_overlay_visible"):
            return
        overlay = tab_data.get("loading_overlay")
        if not overlay or not overlay.winfo_exists():
            return
        try:
            overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            overlay.lift()
        except Exception:
            pass

    def hide_tab_loading_overlay(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        self.hide_tab_busy_indicator(tab_id)
        if tab_data.get("loading_overlay_visible"):
            started_at = float(tab_data.get("loading_overlay_started_at", 0.0) or 0.0)
            elapsed_ms = (time.monotonic() - started_at) * 1000 if started_at else 0.0
            min_visible_ms = 240
            if elapsed_ms < min_visible_ms:
                delay_ms = int(max(0, min_visible_ms - elapsed_ms))
                self.cancel_after_handle(tab_data.get("loading_overlay_hide_job"))
                tab_data["loading_overlay_hide_job"] = self.safe_after(delay_ms, self._hide_tab_loading_overlay_now, tab_id)
                return
        self._hide_tab_loading_overlay_now(tab_id)

    def _hide_tab_loading_overlay_now(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["loading_overlay_hide_job"] = None
        self.cancel_after_handle(tab_data.get("loading_overlay_anim_job"))
        tab_data["loading_overlay_anim_job"] = None
        self.cancel_after_handle(tab_data.get("mount_loading_finish_job"))
        tab_data["mount_loading_finish_job"] = None
        show_job = tab_data.get("loading_overlay_show_job")
        if show_job:
            try:
                self.after_cancel(show_job)
            except Exception:
                pass
        tab_data["loading_overlay_show_job"] = None

        overlay = tab_data.get("loading_overlay")
        if overlay and overlay.winfo_exists():
            try:
                overlay.configure(fg_color="transparent")
            except Exception:
                pass
            overlay.place_forget()
        tab_data["loading_overlay_visible"] = False
        tab_data["loading_overlay_started_at"] = 0.0
        tab_data["loading_overlay_mode"] = ""

        bar = tab_data.get("loading_overlay_bar")
        if bar and bar.winfo_exists():
            try:
                bar.stop()
            except Exception:
                pass

    def stop_workspace_stepper_breathing(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        job = tab_data.get("workspace_stepper_breath_job")
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        tab_data["workspace_stepper_breath_job"] = None
        tab_data["workspace_stepper_breath_on"] = False

    def tick_workspace_stepper_breathing(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["workspace_stepper_breath_job"] = None
        if not any(state == "running" for state in tab_data.get("step_states", {}).values()):
            tab_data["workspace_stepper_breath_on"] = False
            self.update_workspace_stepper_visuals(tab_id)
            return
        tab_data["workspace_stepper_breath_on"] = not bool(tab_data.get("workspace_stepper_breath_on"))
        self.update_workspace_stepper_visuals(tab_id)
        self.ensure_workspace_stepper_breathing(tab_id)

    def ensure_workspace_stepper_breathing(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        has_running = any(state == "running" for state in tab_data.get("step_states", {}).values())
        if not has_running:
            self.stop_workspace_stepper_breathing(tab_id)
            return
        if tab_data.get("workspace_stepper_breath_job"):
            return
        tab_data["workspace_stepper_breath_job"] = self.safe_after(520, self.tick_workspace_stepper_breathing, tab_id)

    def get_manifest_steps_in_order(self, manifest):
        steps = list((manifest or {}).get("steps", []))
        return sorted(
            steps,
            key=lambda item: (
                item.get("order") is None,
                item.get("order") if isinstance(item.get("order"), int) else 999999,
                _natural_sort_key(item.get("display_label", item.get("script_name", ""))),
            ),
        )

    def get_workspace_stepper_items(self, manifest):
        steps = self.get_manifest_steps_in_order(manifest)
        if not steps:
            return []
        groups = []
        group_index_map = {}
        items = []
        for step in steps:
            step_value = _clean_text(step.get("step_value", ""))
            group_key = step_value or f"order:{step.get('order', '')}"
            if group_key not in group_index_map:
                group_index_map[group_key] = len(groups)
                groups.append([])
            groups[group_index_map[group_key]].append(step)

        step_meta = {}
        for group_number, group_steps in enumerate(groups):
            total = len(group_steps)
            for idx, step in enumerate(group_steps, start=1):
                label = f"s{group_number}" if total == 1 else f"s{group_number}_{idx}"
                step_meta[id(step)] = label

        for step in steps:
            items.append({
                "step_id": step.get("order"),
                "label": step_meta.get(id(step), f"s{step.get('order', 0)}"),
                "exists": bool(step.get("exists")),
            })
        return items

    def should_show_workspace_stepper(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return False
        if tab_data.get("batch_has_started_steps") or tab_data.get("current_process") or tab_data.get("run_timer_running"):
            return True
        return any(state != "pending" for state in tab_data.get("step_states", {}).values())

    def get_workspace_stepper_style(self, status, breathing=False):
        if status == "running":
            return (ACCENT_HOVER, ACCENT_DEEP, TEXT_INVERSE, 2) if breathing else (ACCENT, ACCENT_HOVER, TEXT_INVERSE, 2)
        if status == "success":
            return SUCCESS, SUCCESS_HOVER, TEXT_INVERSE, 1
        if status == "error":
            return DANGER, DANGER_HOVER, TEXT_INVERSE, 1
        if status == "skip":
            return TEXT_MUTED, "#475569", TEXT_INVERSE, 1
        if status == "missing":
            return DIVIDER, BORDER, TEXT_MUTED, 1
        return ACCENT_SEGMENT_BG, BORDER, TEXT_PRIMARY, 1

    def get_workspace_stepper_status_map(self, tab_id, items):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return {}
        step_vars = tab_data.get("step_vars", {})
        step_states = tab_data.get("step_states", {})
        snapshot_active = bool(tab_data.get("workspace_stepper_snapshot_active"))
        snapshot_selected_orders = {
            order for order in tab_data.get("workspace_stepper_selected_orders_snapshot", [])
            if order is not None
        }
        status_map = {}
        for item in items:
            step_id = item.get("step_id")
            if snapshot_active:
                selected = step_id in snapshot_selected_orders
            else:
                step_var = step_vars.get(step_id)
                selected = step_var.get() == "1" if step_var else True
            if not item.get("exists"):
                status = "missing"
            elif not selected:
                status = "skip"
            else:
                status = step_states.get(step_id, "pending")
            status_map[step_id] = status
        return status_map

    def update_workspace_stepper_visuals(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        item_widgets = tab_data.get("workspace_stepper_item_widgets") or {}
        connector_widgets = tab_data.get("workspace_stepper_connector_widgets") or []
        items = tab_data.get("workspace_stepper_items_cache") or []
        if not item_widgets or not items:
            return
        breathing_on = bool(tab_data.get("workspace_stepper_breath_on"))
        status_map = self.get_workspace_stepper_status_map(tab_id, items)
        style_map = {}
        for item in items:
            step_id = item.get("step_id")
            status = status_map.get(step_id, "pending")
            fg_color, border_color, text_color, border_width = self.get_workspace_stepper_style(
                status,
                breathing=bool(status == "running" and breathing_on),
            )
            widget_info = item_widgets.get(step_id) or {}
            segment = widget_info.get("segment")
            label = widget_info.get("label")
            if segment and segment.winfo_exists():
                segment.configure(fg_color=fg_color, border_color=border_color, border_width=border_width)
            if label and label.winfo_exists():
                label.configure(text_color=text_color)
            style_map[step_id] = (status, border_color)
        for owner_step_id, connector in connector_widgets:
            if not connector.winfo_exists():
                continue
            owner_status, owner_border_color = style_map.get(owner_step_id, ("pending", BORDER))
            connector_color = owner_border_color if owner_status in {"running", "success", "error"} else DIVIDER
            connector.configure(fg_color=connector_color)

    def scroll_scrollable_frame_to_widget(self, scroll_frame, target_widget, top_padding=10):
        if not scroll_frame or not target_widget:
            return
        try:
            if not scroll_frame.winfo_exists() or not target_widget.winfo_exists():
                return
            scroll_frame.update_idletasks()
            target_widget.update_idletasks()
            canvas = getattr(scroll_frame, "_parent_canvas", None)
            if canvas is None:
                return
            bbox = canvas.bbox("all")
            if not bbox:
                return
            total_height = max(1, bbox[3] - bbox[1])
            canvas_height = max(1, canvas.winfo_height())
            scrollable_height = max(1, total_height - canvas_height)
            target_y = max(0, target_widget.winfo_y() - int(top_padding))
            fraction = max(0.0, min(target_y / scrollable_height, 1.0))
            smooth_scroll_to(canvas, fraction)
        except Exception:
            pass

    def scroll_current_step_into_view(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        current_step_id = tab_data.get("current_step_id")
        if current_step_id is None:
            return
        step_scroll = tab_data.get("step_scroll")
        step_widget = tab_data.get("step_widgets", {}).get(current_step_id)
        if not step_scroll or not step_widget:
            return
        try:
            if not step_scroll.winfo_exists() or not step_widget.winfo_exists():
                return
            step_scroll.update_idletasks()
            step_widget.update_idletasks()
            canvas = getattr(step_scroll, "_parent_canvas", None)
            if canvas is None:
                return
            bbox = canvas.bbox("all")
            if not bbox:
                return
            total_height = max(1, bbox[3] - bbox[1])
            canvas_height = max(1, canvas.winfo_height())
            scrollable_height = max(0, total_height - canvas_height)
            target_y = max(0, int(step_widget.winfo_y()))
            target_h = max(1, int(step_widget.winfo_height()))
            current_top = int(canvas.canvasy(0))
            current_bottom = current_top + canvas_height
            visible_margin = max(10, min(28, target_h // 2))
            if (current_top + visible_margin) <= target_y and (target_y + target_h) <= (current_bottom - visible_margin):
                return
            near_bottom_threshold = max(0, total_height - canvas_height - target_h * 2)
            if target_y >= near_bottom_threshold:
                smooth_scroll_to(canvas, 1.0)
                return
            desired_top = max(0, target_y - int(target_h * 1.15))
            fraction = 0.0 if scrollable_height <= 0 else max(0.0, min(desired_top / scrollable_height, 1.0))
            smooth_scroll_to(canvas, fraction)
        except Exception:
            pass

    def on_step_selection_changed(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        step_vars = tab_data.get("step_vars", {})
        if step_vars:
            tab_data["saved_step_selection_loaded"] = True
            tab_data["saved_step_selection_orders"] = [
                order for order, var in step_vars.items()
                if var and var.get() == "1"
            ]
        self.render_workspace_stepper(tab_id)
        if tab_data.get("suspend_gui_state_save"):
            return
        self.schedule_gui_state_save(tab_id)

    def render_workspace_stepper(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        container = tab_data.get("workspace_stepper_container")
        workspace_view_tabview = tab_data.get("workspace_view_tabview")
        if not container or not container.winfo_exists() or not workspace_view_tabview or not workspace_view_tabview.winfo_exists():
            return
        should_show = self.should_show_workspace_stepper(tab_id)
        if not should_show:
            self.stop_workspace_stepper_breathing(tab_id)
            if container.winfo_manager():
                container.pack_forget()
            return
        if not container.winfo_manager():
            container.pack(fill="x", padx=8, pady=(0, 4), before=workspace_view_tabview)
        items = self.get_workspace_stepper_items(tab_data.get("manifest", {}))
        if not items:
            container.pack_forget()
            return
        item_signature = [(item.get("step_id"), item.get("label"), item.get("exists")) for item in items]
        if tab_data.get("workspace_stepper_signature") != item_signature:
            for widget in container.winfo_children():
                widget.destroy()
            shell = ctk.CTkFrame(container, fg_color=SURFACE_BG, corner_radius=RADIUS_OUTER, border_width=1, border_color=DIVIDER)
            shell.pack(fill="x")
            row = ctk.CTkFrame(shell, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=6)
            item_widgets = {}
            connector_widgets = []
            for idx, item in enumerate(items):
                step_id = item.get("step_id")
                segment = ctk.CTkFrame(
                    row,
                    fg_color=ACCENT_SEGMENT_BG,
                    corner_radius=RADIUS_MD,
                    border_width=1,
                    border_color=BORDER,
                )
                segment.pack(side="left", fill="x", expand=True)
                label = ctk.CTkLabel(
                    segment,
                    text=item["label"],
                    text_color=TEXT_PRIMARY,
                    font=ui_font(11, "bold"),
                )
                label.pack(padx=7, pady=4)
                item_widgets[step_id] = {"segment": segment, "label": label}
                if idx < len(items) - 1:
                    connector = ctk.CTkFrame(row, fg_color=DIVIDER, height=2, width=10, corner_radius=RADIUS_NONE)
                    connector.pack(side="left", padx=3, pady=12)
                    connector_widgets.append((step_id, connector))
            tab_data["workspace_stepper_signature"] = item_signature
            tab_data["workspace_stepper_item_widgets"] = item_widgets
            tab_data["workspace_stepper_connector_widgets"] = connector_widgets
        tab_data["workspace_stepper_items_cache"] = items
        self.update_workspace_stepper_visuals(tab_id)
        self.ensure_workspace_stepper_breathing(tab_id)

    def get_left_panel_width(self, manifest):
        max_name_len = max((len(step.get("display_label", step.get("script_name", ""))) for step in manifest.get("steps", [])), default=12)
        estimated = 150 + max_name_len * 7
        return max(WIDTH_LEFT_PANEL_MIN, min(estimated, WIDTH_LEFT_PANEL_MAX))

    def build_tab_ui(self, tab_id, parent_frame):
        tab_data = self.active_tabs_data[tab_id]
        selected_workspace_view = tab_data.get("workspace_view_preferred", "主界面")
        self.ensure_tab_busy_indicator(tab_id, parent_frame)
        self.ensure_tab_loading_overlay(tab_id, parent_frame)

        workspace_stepper_container = ctk.CTkFrame(parent_frame, fg_color="transparent")
        tab_data["workspace_stepper_container"] = workspace_stepper_container

        workspace_view_tabview = ctk.CTkTabview(parent_frame, **tabview_style())
        workspace_view_tabview.pack(fill="both", expand=True, padx=8, pady=(0, 2))
        main_view = workspace_view_tabview.add("主界面")
        gantt_view = workspace_view_tabview.add("流水线")
        data_view = workspace_view_tabview.add("数据文件")
        resource_view = workspace_view_tabview.add("规则/所给数据集")
        results_view = workspace_view_tabview.add("计算结果")
        tab_data["workspace_view_tabview"] = workspace_view_tabview
        tab_data["main_view"] = main_view
        main_view.grid_columnconfigure(0, weight=1)
        main_view.grid_rowconfigure(0, weight=0)
        main_view.grid_rowconfigure(2, weight=1)

        content_container = ctk.CTkFrame(main_view, fg_color="transparent")
        content_container.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))
        content_container.grid_propagate(False)
        tab_data["content_container"] = content_container

        # 底部控制台区域主要对应 outer_panel_style、input_box_style 和控制台高度常量。
        console_sash = ctk.CTkFrame(main_view, height=HEIGHT_SASH, fg_color=BORDER, corner_radius=RADIUS_XS, cursor="sb_v_double_arrow")
        console_sash.grid(row=1, column=0, sticky="ew", padx=8, pady=(2, 0))
        console_sash.bind("<ButtonPress-1>", lambda event, tid=tab_id: self.start_console_resize(tid, event))
        tab_data["console_sash"] = console_sash

        console_container = ctk.CTkFrame(main_view, height=tab_data["console_height"], **outer_panel_style())
        console_container.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 4))
        console_container.pack_propagate(False)
        console_container.grid_columnconfigure(0, weight=1)
        console_container.grid_rowconfigure(2, weight=1)
        tab_data["console_container"] = console_container

        gantt_header = ctk.CTkFrame(gantt_view, fg_color="transparent")
        gantt_header.pack(fill="x", padx=10, pady=(8, 0))
        gantt_divider = ctk.CTkFrame(gantt_view, fg_color=DIVIDER, height=HEIGHT_DIVIDER, corner_radius=RADIUS_NONE)
        gantt_divider.pack(fill="x", padx=10, pady=(4, 0))
        gantt_panel = ctk.CTkScrollableFrame(gantt_view, **scrollable_style())
        gantt_panel.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        tab_data["gantt_header"] = gantt_header
        tab_data["gantt_panel"] = gantt_panel

        content_frame = ctk.CTkFrame(content_container, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, pady=(0, 3))

        # 主界面保持“代码执行区优先”，说明栏只占较窄固定宽度。
        left_outer = ctk.CTkFrame(content_frame, width=self.get_left_panel_width(tab_data["manifest"]), **outer_panel_style())
        left_outer.pack(side="left", fill="both", expand=True, padx=(0, 4))
        left_header = ctk.CTkFrame(left_outer, fg_color="transparent")
        left_header.pack(fill="x", padx=10, pady=(8, 0))
        left_divider = ctk.CTkFrame(left_outer, fg_color=DIVIDER, height=HEIGHT_DIVIDER, corner_radius=RADIUS_NONE)
        left_divider.pack(fill="x", padx=10, pady=(4, 0))
        left_panel = ctk.CTkFrame(left_outer, fg_color="transparent", corner_radius=RADIUS_NONE)
        left_panel.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self.active_tabs_data[tab_id]["left_header"] = left_header
        self.active_tabs_data[tab_id]["left_panel"] = left_panel

        middle_outer = ctk.CTkFrame(content_frame, width=WIDTH_MIDDLE_PANEL, **outer_panel_style())
        middle_outer.pack(side="left", fill="both", expand=False, padx=(4, 0))
        middle_outer.pack_propagate(False)
        middle_header = ctk.CTkFrame(middle_outer, fg_color="transparent")
        middle_header.pack(fill="x", padx=10, pady=(8, 0))
        middle_divider = ctk.CTkFrame(middle_outer, fg_color=DIVIDER, height=HEIGHT_DIVIDER, corner_radius=RADIUS_NONE)
        middle_divider.pack(fill="x", padx=10, pady=(4, 0))
        middle_panel = ctk.CTkScrollableFrame(middle_outer, **scrollable_style())
        middle_panel.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self.active_tabs_data[tab_id]["middle_header"] = middle_header
        self.active_tabs_data[tab_id]["middle_panel"] = middle_panel

        right_outer = ctk.CTkFrame(data_view, **outer_panel_style())
        right_outer.pack(fill="both", expand=True, padx=8, pady=(8, 8))
        right_header = ctk.CTkFrame(right_outer, fg_color="transparent")
        right_header.pack(fill="x", padx=10, pady=(8, 0))
        right_divider = ctk.CTkFrame(right_outer, fg_color=DIVIDER, height=HEIGHT_DIVIDER, corner_radius=RADIUS_NONE)
        right_divider.pack(fill="x", padx=10, pady=(4, 0))
        right_panel = ctk.CTkScrollableFrame(right_outer, **scrollable_style())
        right_panel.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self.active_tabs_data[tab_id]["right_header"] = right_header
        self.active_tabs_data[tab_id]["right_panel"] = right_panel

        resource_outer = ctk.CTkFrame(resource_view, **outer_panel_style())
        resource_outer.pack(fill="both", expand=True, padx=8, pady=(8, 8))
        resource_header = ctk.CTkFrame(resource_outer, fg_color="transparent")
        resource_header.pack(fill="x", padx=10, pady=(8, 0))
        resource_divider = ctk.CTkFrame(resource_outer, fg_color=DIVIDER, height=HEIGHT_DIVIDER, corner_radius=RADIUS_NONE)
        resource_divider.pack(fill="x", padx=10, pady=(4, 0))
        resource_panel = ctk.CTkScrollableFrame(resource_outer, **scrollable_style())
        resource_panel.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self.active_tabs_data[tab_id]["resource_header"] = resource_header
        self.active_tabs_data[tab_id]["resource_panel"] = resource_panel

        results_outer = ctk.CTkFrame(results_view, **outer_panel_style())
        results_outer.pack(fill="both", expand=True, padx=8, pady=(8, 8))
        results_header = ctk.CTkFrame(results_outer, fg_color="transparent")
        results_header.pack(fill="x", padx=10, pady=(8, 0))
        results_divider = ctk.CTkFrame(results_outer, fg_color=DIVIDER, height=HEIGHT_DIVIDER, corner_radius=RADIUS_NONE)
        results_divider.pack(fill="x", padx=10, pady=(4, 0))
        results_panel = ctk.CTkScrollableFrame(results_outer, **scrollable_style())
        results_panel.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self.active_tabs_data[tab_id]["results_header"] = results_header
        self.active_tabs_data[tab_id]["results_panel"] = results_panel

        log_ctrl_frame = ctk.CTkFrame(console_container, fg_color="transparent")
        log_ctrl_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(3, 0))
        ctk.CTkLabel(log_ctrl_frame, text="实时运行简报", text_color=TEXT_PRIMARY, font=ui_font(14, "bold")).pack(side="left")
        ctk.CTkLabel(log_ctrl_frame, text="已过滤冗余输出", text_color=TEXT_MUTED).pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            log_ctrl_frame,
            text="打开完整日志目录",
            width=WIDTH_LOG_DIR_BUTTON,
            height=HEIGHT_LOG_BUTTON,
            command=lambda m=tab_data.get("manifest", {}): self.open_path(self.get_workspace_logs_root(m) or self.get_logs_root(), ensure_dir=True),
            **button_secondary_style(),
        ).pack(side="right")

        progress_label = ctk.CTkLabel(console_container, text="", anchor="w", text_color=ACCENT_HOVER, font=ui_font(13, "bold"))
        progress_label.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 0))
        progress_label.grid_remove()
        self.active_tabs_data[tab_id]["progress_label"] = progress_label

        log_box = ctk.CTkTextbox(
            console_container,
            height=HEIGHT_LOG_BOX,
            state="disabled",
            corner_radius=RADIUS_XL,
            **input_box_style(),
        )
        log_box.grid(row=2, column=0, sticky="nsew", padx=10, pady=(4, 6))
        self.active_tabs_data[tab_id]["log_box"] = log_box
        self.bind_log_box_auto_follow(tab_id, log_box)

        self.render_tab_content(tab_id)
        self.render_workspace_stepper(tab_id)
        self.render_gantt_tab(tab_id)
        self.render_calc_results_panel(tab_id)
        try:
            workspace_view_tabview.set(selected_workspace_view)
        except Exception:
            workspace_view_tabview.set("主界面")
        tab_data["workspace_view_preferred"] = selected_workspace_view
        self.schedule_gui_state_save(tab_id)
        self.safe_after(80, self.apply_console_height, tab_id, self.active_tabs_data.get(tab_id, {}).get("console_height"), False)

    def render_tab_content(self, tab_id):
        tab_data = self.active_tabs_data[tab_id]
        tab_data["suspend_gui_state_save"] = True
        workspace_view_tabview = tab_data.get("workspace_view_tabview")
        if workspace_view_tabview and workspace_view_tabview.winfo_exists():
            try:
                tab_data["workspace_view_preferred"] = workspace_view_tabview.get()
            except Exception:
                pass
        left_panel = tab_data["left_panel"]
        left_header = tab_data.get("left_header")
        middle_panel = tab_data.get("middle_panel")
        middle_header = tab_data.get("middle_header")
        prev_values = {step_id: var.get() for step_id, var in tab_data["step_vars"].items()}
        if prev_values:
            tab_data["saved_step_selection_loaded"] = True
            tab_data["saved_step_selection_orders"] = [
                step_id for step_id, value in prev_values.items() if value == "1"
            ]
        selected_left_tab = tab_data.get("left_tab_preferred", "步骤代码")
        left_tabview = tab_data.get("left_tabview")
        if left_tabview and left_tabview.winfo_exists():
            try:
                selected_left_tab = left_tabview.get()
            except Exception:
                selected_left_tab = tab_data.get("left_tab_preferred", "步骤代码")

        if left_header:
            for widget in left_header.winfo_children():
                widget.destroy()
        for widget in left_panel.winfo_children():
            widget.destroy()
        if middle_header:
            for widget in middle_header.winfo_children():
                widget.destroy()
        if middle_panel:
            for widget in middle_panel.winfo_children():
                widget.destroy()
        tab_data["step_vars"] = {}
        tab_data["step_widgets"] = {}

        title_row = ctk.CTkFrame(left_header, fg_color="transparent")
        title_row.pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(title_row, text="代码执行区", text_color=TEXT_PRIMARY, font=ui_font(17, "bold")).pack(side="left")
        ctk.CTkButton(
            title_row,
            text="重命名",
            width=WIDTH_ACTION_BUTTON_XS,
            height=HEIGHT_BUTTON_SM,
            corner_radius=RADIUS_MD,
            command=lambda tid=tab_id: self.rename_workspace_display_name(tid),
            **button_secondary_style(),
        ).pack(side="right", padx=(0, 6))
        ctk.CTkButton(
            title_row,
            text="删除工作区",
            width=WIDTH_CLOSE_TAB_BUTTON,
            height=HEIGHT_BUTTON_SM,
            corner_radius=RADIUS_MD,
            command=lambda tid=tab_id: self.confirm_delete_workspace(tid),
            **button_danger_style(),
        ).pack(side="right")
        # ctk.CTkLabel(left_header, 
        #             # text="步骤主代码与代码文件夹分栏展示",
        #             text_color=TEXT_MUTED, font=ui_font(12)).pack(anchor="w", pady=(0, 4))

        # 左侧“步骤代码 / 代码文件夹”切换统一走 tabview_style。
        left_tabview = ctk.CTkTabview(left_panel, **tabview_style())
        left_tabview.pack(fill="both", expand=True)
        step_tab = left_tabview.add("步骤代码")
        code_tab = left_tabview.add("代码文件夹")
        tab_data["left_tabview"] = left_tabview

        self.render_step_code_tab(tab_id, step_tab, prev_values)
        self.render_code_folder_tab(tab_id, code_tab)

        try:
            left_tabview.set(selected_left_tab)
        except Exception:
            left_tabview.set("步骤代码")
        tab_data["left_tab_preferred"] = selected_left_tab
        tab_data["suspend_gui_state_save"] = False
        self.schedule_gui_state_save(tab_id)

        self.render_doc_panel(tab_id)
        self.render_right_panel(tab_id)
        self.render_resource_panel(tab_id)

    def render_step_code_tab(self, tab_id, parent, prev_values):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        manifest = tab_data.get("manifest", {})

        def toggle_all(val):
            for var in tab_data["step_vars"].values():
                var.set(val)

        layout_row = ctk.CTkFrame(parent, fg_color="transparent")
        layout_row.pack(fill="x", expand=False, anchor="n", pady=(2, 0))
        layout_row.grid_columnconfigure(0, weight=1, uniform="step_split")
        layout_row.grid_columnconfigure(1, weight=1, uniform="step_split")
        layout_row.grid_rowconfigure(0, weight=1)

        control_col = ctk.CTkFrame(layout_row, fg_color="transparent")
        control_col.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        status_values = list(tab_data.get("step_states", {}).values())
        if any(value == "error" for value in status_values):
            step_outline = DANGER
        elif tab_data.get("current_process") or tab_data.get("run_timer_running"):
            step_outline = ACCENT
        elif any(value == "success" for value in status_values):
            step_outline = SUCCESS
        else:
            step_outline = ACCENT_SEGMENT_HOVER

        step_frame = ctk.CTkFrame(
            layout_row,
            fg_color=PANEL_BG,
            corner_radius=RADIUS_PANEL,
            border_width=2,
            border_color=step_outline,
            height=220,
        )
        step_frame.grid(row=0, column=1, sticky="nsew")
        step_frame.grid_propagate(False)

        btn_frame = ctk.CTkFrame(control_col, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(0, 6))
        btn_frame.grid_columnconfigure(0, weight=1, uniform="control_buttons")
        btn_frame.grid_columnconfigure(1, weight=1, uniform="control_buttons")
        ctk.CTkButton(
            btn_frame,
            text="全选",
            height=HEIGHT_BUTTON_SM,
            corner_radius=RADIUS_MD,
            command=lambda: toggle_all("1"),
            **button_primary_style(),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(
            btn_frame,
            text="全不选",
            height=HEIGHT_BUTTON_SM,
            corner_radius=RADIUS_MD,
            command=lambda: toggle_all("0"),
            **button_soft_style(),
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        run_ctrl_frame = ctk.CTkFrame(control_col, fg_color="transparent")
        run_ctrl_frame.pack(fill="x")
        run_ctrl_frame.grid_columnconfigure(0, weight=1, uniform="run_buttons")
        run_ctrl_frame.grid_columnconfigure(1, weight=1, uniform="run_buttons")
        ctk.CTkButton(
            run_ctrl_frame,
            text="一键运行(所选)",
            height=HEIGHT_BUTTON_SM,
            corner_radius=RADIUS_LG,
            font=ui_font(13, "bold"),
            command=lambda tid=tab_id: self.start_batch_run(tid),
            **button_success_style(),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        pause_btn = ctk.CTkButton(
            run_ctrl_frame,
            text="暂停",
            height=HEIGHT_BUTTON_SM,
            corner_radius=RADIUS_LG,
            font=ui_font(13, "bold"),
            command=lambda tid=tab_id: self.kill_process(tid),
            state="disabled",
            **button_danger_style(),
        )
        pause_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        tab_data["pause_button"] = pause_btn

        institution_txt_exists = self.has_institution_txt(manifest=manifest)
        institution_btn = ctk.CTkButton(
            control_col,
            text="编辑机构名单 (txt)",
            height=HEIGHT_BUTTON_SM,
            corner_radius=RADIUS_MD,
            command=lambda tid=tab_id: self.open_workspace_inst_txt(tid),
            state="normal" if institution_txt_exists else "disabled",
            **button_secondary_style(),
        )
        institution_btn.pack(fill="x", pady=(8, 0))
        if not institution_txt_exists:
            ctk.CTkLabel(
                control_col,
                text="缺少 机构信息.txt",
                text_color=TEXT_MUTED,
                font=ui_font(11),
            ).pack(anchor="w", padx=4, pady=(4, 0))

        ctk.CTkButton(
            control_col,
            text="编辑文件结构",
            height=HEIGHT_BUTTON_SM,
            corner_radius=RADIUS_MD,
            command=lambda tid=tab_id: self.open_file_structure_editor_for_tab(tid),
            **button_secondary_style(),
        ).pack(fill="x", pady=(8, 0))

        step_title_row = ctk.CTkFrame(step_frame, fg_color="transparent")
        step_title_row.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkLabel(step_title_row, text="步骤脚本", text_color=TEXT_PRIMARY, font=ui_font(15, "bold")).pack(side="left")
        timer_label = ctk.CTkLabel(step_title_row, text="00:00:00", text_color=SUCCESS, font=ui_font(12, "bold"))
        timer_label.pack(side="right")
        tab_data["run_timer_label"] = timer_label
        self.refresh_run_timer_label(tab_id)
        ordered_steps = self.get_manifest_steps_in_order(manifest)
        if ordered_steps:
            tab_data["_step_manifest_retrying"] = False
        elif tab_data.get("bp_path") and not tab_data.get("_step_manifest_retrying"):
            tab_data["_step_manifest_retrying"] = True
            self.safe_after(0, self.rebuild_workspace_manifest_for_tab, tab_id)

        ctk.CTkLabel(
            step_title_row,
            text=f"{len(ordered_steps)} 项",
            text_color=TEXT_MUTED,
            font=ui_font(12),
        ).pack(side="right", padx=(0, 8))

        step_scroll = ctk.CTkScrollableFrame(step_frame, height=160, **scrollable_style())
        step_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        tab_data["step_scroll"] = step_scroll

        for step in ordered_steps:
            step_id = step["order"]
            default_value = "1" if step.get("exists") else "0"
            if step_id not in prev_values and tab_data.get("saved_step_selection_loaded"):
                default_value = "1" if step_id in set(tab_data.get("saved_step_selection_orders", [])) else "0"
            var = ctk.StringVar(value=prev_values.get(step_id, default_value))
            var.trace_add("write", lambda *_args, tid=tab_id: self.on_step_selection_changed(tid))
            tab_data["step_vars"][step_id] = var

            if step_id not in tab_data["step_states"]:
                tab_data["step_states"][step_id] = "pending"

            state_color = "gray"
            if tab_data["step_states"][step_id] == "success":
                state_color = SUCCESS
            elif tab_data["step_states"][step_id] == "error":
                state_color = DANGER

            display_label = step.get("display_label", step["script_name"])
            text = display_label if step.get("exists") else f"[缺失] {display_label}"
            state = "normal" if step.get("exists") else "disabled"

            row = ctk.CTkFrame(step_scroll, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=5)
            row.grid_columnconfigure(0, weight=1)
            row.grid_columnconfigure(1, weight=0)
            left_cell = ctk.CTkFrame(row, fg_color="transparent")
            left_cell.grid(row=0, column=0, sticky="ew")
            cb = ctk.CTkCheckBox(
                left_cell,
                text=text,
                variable=var,
                onvalue="1",
                offvalue="0",
                state=state,
                text_color=state_color,
                **checkbox_style(),
            )
            cb.pack(anchor="w")
            right_cell = ctk.CTkFrame(
                row,
                fg_color="transparent",
                width=WIDTH_ACTION_BUTTON_XS + 8,
                height=HEIGHT_ACTION_BUTTON_XS,
            )
            right_cell.grid(row=0, column=1, sticky="e")
            right_cell.grid_propagate(False)
            ctk.CTkButton(
                right_cell,
                text="打开",
                width=WIDTH_ACTION_BUTTON_XS,
                height=HEIGHT_BUTTON_XS,
                corner_radius=RADIUS_SM,
                state="normal" if step.get("exists") else "disabled",
                command=lambda p=step.get("abs_path"): self.open_file(p),
                **button_secondary_style(),
            ).place(relx=1.0, rely=0.5, anchor="e")
            tab_data["step_widgets"][step_id] = cb

        if tab_data.get("current_step_id") in tab_data.get("step_widgets", {}):
            self.safe_after(60, self.scroll_current_step_into_view, tab_id)

        if not ordered_steps:
            ctk.CTkLabel(
                step_scroll,
                text="当前工作区没有识别到顺序步骤代码。",
                text_color=TEXT_MUTED,
                wraplength=WRAP_LEFT_HINT,
                justify="left",
            ).pack(anchor="w", padx=10, pady=(8, 0))

    def get_root_tool_button_meta(self, item):
        rel_path = str(item.get("rel_path", ""))
        script_name = os.path.basename(rel_path).lower()
        label = item.get("display_label", item.get("name", ""))
        fg_color = SURFACE_BG
        hover_color = ITEM_HOVER
        text_color = TEXT_PRIMARY
        priority = 99

        if script_name == "update_all_code.py":
            label = "更新代码"
            fg_color = SUCCESS
            hover_color = SUCCESS_HOVER
            text_color = TEXT_INVERSE
            priority = 0
        elif script_name == "test.py":
            label = "继承工作区"
            fg_color = ACCENT
            hover_color = ACCENT_HOVER
            text_color = TEXT_INVERSE
            priority = 1
        elif script_name == "flush_all_data.py":
            label = "清空数据"
            fg_color = SECONDARY
            hover_color = SECONDARY_HOVER
            text_color = TEXT_INVERSE
            priority = 2
        elif script_name == "reset_all_code.py":
            label = "重置代码"
            fg_color = WARNING
            hover_color = WARNING_HOVER
            text_color = TEXT_PRIMARY
            priority = 3
        elif script_name == "code_backup.py":
            label = "代码备份"
            fg_color = BACKUP
            hover_color = BACKUP_HOVER
            text_color = TEXT_PRIMARY
            priority = 4

        return {
            "label": label,
            "fg_color": fg_color,
            "hover_color": hover_color,
            "text_color": text_color,
            "priority": priority,
        }

    def get_fixed_backup_code_item(self, workspace_root):
        rel_path = os.path.join("资料", "代码", "code_backup.py")
        abs_path = os.path.join(workspace_root, rel_path) if workspace_root else rel_path
        return {
            "name": "code_backup.py",
            "display_label": "代码备份",
            "script_name": "code_backup.py",
            "rel_path": rel_path,
            "abs_path": abs_path,
            "exists": os.path.isfile(abs_path),
            "folder_rel_path": "",
            "is_root_code": True,
            "is_fixed_backup": True,
        }

    def get_fixed_backup_doc_item(self, workspace_root):
        rel_path = os.path.join("资料", "说明", "readme_backup.py")
        abs_path = os.path.join(workspace_root, rel_path) if workspace_root else rel_path
        return {
            "name": "readme_backup.py",
            "display_label": "说明备份",
            "script_name": "readme_backup.py",
            "rel_path": rel_path,
            "abs_path": abs_path,
            "exists": os.path.isfile(abs_path),
            "is_fixed_backup": True,
        }

    def get_award_readme_item(self, workspace_root):
        project_root = os.path.dirname(os.path.abspath(__file__))
        award_root = ""
        if workspace_root:
            try:
                rel_to_project = os.path.relpath(os.path.abspath(workspace_root), project_root)
                first_part = rel_to_project.split(os.sep, 1)[0]
                if first_part and first_part not in {".", ".."}:
                    award_root = os.path.join(project_root, first_part)
            except Exception:
                award_root = ""
        if not award_root and workspace_root:
            award_root = os.path.dirname(os.path.abspath(workspace_root))
        rel_path = "README.md"
        abs_path = os.path.join(award_root, rel_path) if award_root else rel_path
        return {
            "name": "README.md",
            "display_label": "奖项 README",
            "rel_path": rel_path,
            "abs_path": abs_path,
            "exists": os.path.isfile(abs_path),
        }

    def render_code_folder_tab(self, tab_id, parent):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        manifest = tab_data.get("manifest", {})
        workspace_root = manifest.get("workspace_root", "")
        error_folder_rel_path = tab_data.get("error_folder_rel_path", "")
        error_file_rel_path = tab_data.get("error_file_rel_path", "")
        error_is_root = tab_data.get("error_is_root", False)

        header_frame = ctk.CTkFrame(parent, fg_color="transparent")
        header_frame.pack(fill="x", pady=(2, 0))
        ctk.CTkLabel(header_frame, text="代码文件夹", text_color=TEXT_PRIMARY, font=ui_font(15, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header_frame,
            text="展示步骤异步/辅助代码和根目录工具代码；已忽略 notebook 和 [script] 文件。",
            text_color=TEXT_MUTED,
            wraplength=WRAP_LEFT_HINT,
            justify="left",
            font=ui_font(12),
        ).pack(anchor="w", pady=(1, 5))

        # “代码文件夹”页主要组合 panel_card_style、surface_card_style、button_primary_style 和错误高亮颜色。
        code_scroll = ctk.CTkScrollableFrame(parent, **scrollable_style())
        code_scroll.pack(fill="both", expand=True)
        tab_data["code_folder_scroll"] = code_scroll
        scroll_target_widget = None

        ref_info_path = os.path.join(workspace_root, "参评信息")
        ref_info_exists = os.path.isdir(ref_info_path)
        ref_card = ctk.CTkFrame(code_scroll, **panel_card_style())
        ref_card.pack(fill="x", padx=6, pady=6)
        ctk.CTkLabel(ref_card, text="参评信息文件夹", text_color=TEXT_PRIMARY, font=ui_font(14, "bold")).pack(anchor="w", padx=10, pady=(10, 2))
        ctk.CTkLabel(
            ref_card,
            text=ref_info_path if ref_info_exists else "当前工作区未找到参评信息文件夹。",
            text_color=TEXT_MUTED,
            wraplength=WRAP_ROOT_CARD,
            justify="left",
        ).pack(anchor="w", padx=10)
        ctk.CTkButton(
            ref_card,
            text="打开参评信息",
            width=WIDTH_OPEN_INFO_BUTTON,
            corner_radius=RADIUS_SM,
            state="normal" if ref_info_exists else "disabled",
            command=lambda p=ref_info_path: self.open_path(p),
            **button_primary_style(),
        ).pack(anchor="w", padx=10, pady=(8, 10))

        root_card = ctk.CTkFrame(
            code_scroll,
            fg_color=ERROR_SURFACE if error_is_root else PANEL_BG,
            corner_radius=RADIUS_PANEL,
            border_width=ERROR_BORDER_WIDTH if error_is_root else 0,
            border_color=DANGER if error_is_root else PANEL_BG,
        )
        root_card.pack(fill="x", padx=6, pady=6)
        if error_is_root:
            scroll_target_widget = root_card
        ctk.CTkLabel(root_card, text="工具代码", text_color=TEXT_PRIMARY, font=ui_font(14, "bold")).pack(anchor="w", padx=10, pady=(10, 2))
        ctk.CTkLabel(root_card, text=workspace_root or "未找到工作区路径", text_color=TEXT_MUTED, wraplength=WRAP_ROOT_CARD, justify="left").pack(anchor="w", padx=10)
        root_btn_row = ctk.CTkFrame(root_card, fg_color="transparent")
        root_btn_row.pack(fill="x", padx=10, pady=(8, 8))
        ctk.CTkButton(
            root_btn_row,
            text="打开根目录",
            width=WIDTH_OPEN_FOLDER_BUTTON,
            corner_radius=RADIUS_SM,
            command=lambda p=workspace_root: self.open_path(p),
            **button_primary_style(),
        ).pack(side="left")
        other_root_codes = list(manifest.get("other_root_codes", []))
        fixed_backup_code = self.get_fixed_backup_code_item(workspace_root)
        backup_rel_norm = os.path.normcase(os.path.normpath(fixed_backup_code.get("rel_path", "")))
        if all(os.path.normcase(os.path.normpath(item.get("rel_path", ""))) != backup_rel_norm for item in other_root_codes):
            other_root_codes.append(fixed_backup_code)
        if other_root_codes:
            other_root_codes = sorted(
                other_root_codes,
                key=lambda item: (self.get_root_tool_button_meta(item)["priority"], _natural_sort_key(item.get("display_label", item.get("name", "")))),
            )
            for item in other_root_codes:
                meta = self.get_root_tool_button_meta(item)
                is_error_file = error_is_root and error_file_rel_path == item.get("rel_path", "")
                row = ctk.CTkButton(
                    root_card,
                    text=meta["label"],
                    anchor="w",
                    height=HEIGHT_BUTTON,
                    fg_color=ERROR_ITEM_BG if is_error_file else meta["fg_color"],
                    hover_color=ERROR_ITEM_HOVER if is_error_file else meta["hover_color"],
                    text_color=TEXT_PRIMARY if is_error_file else meta["text_color"],
                    corner_radius=RADIUS_LG,
                    command=lambda info=item, tid=tab_id: self.run_code_item(tid, info),
                )
                row.pack(fill="x", padx=10, pady=(0, 6))
        else:
            ctk.CTkLabel(
                root_card,
                text="根目录下没有额外的工具 Python 代码。",
                text_color=TEXT_MUTED,
                wraplength=WRAP_ROOT_CARD,
                justify="left",
            ).pack(anchor="w", padx=10, pady=(0, 10))

        def _is_folder_match(folder_rel_path):
            if not folder_rel_path or not error_folder_rel_path:
                return False
            folder_norm = os.path.normcase(os.path.normpath(folder_rel_path))
            error_norm = os.path.normcase(os.path.normpath(error_folder_rel_path))
            return error_norm == folder_norm or error_norm.startswith(folder_norm + os.sep)

        step_code_folders = sorted(
            manifest.get("step_code_folders", []),
            key=lambda folder: _natural_sort_key(folder.get("folder_rel_path", "")),
        )
        if not step_code_folders:
            ctk.CTkLabel(
                code_scroll,
                text="当前没有可展示的步骤代码文件夹。",
                text_color=TEXT_MUTED,
                wraplength=WRAP_LEFT_HINT,
                justify="left",
            ).pack(anchor="w", padx=10, pady=(8, 0))
            return

        for folder in step_code_folders:
            is_error_folder = _is_folder_match(folder.get("folder_rel_path", ""))
            card = ctk.CTkFrame(
                code_scroll,
                fg_color=ERROR_SURFACE if is_error_folder else PANEL_BG,
                corner_radius=RADIUS_PANEL,
                border_width=ERROR_BORDER_WIDTH if is_error_folder else 0,
                border_color=DANGER if is_error_folder else PANEL_BG,
            )
            card.pack(fill="x", padx=6, pady=6)
            if is_error_folder and scroll_target_widget is None:
                scroll_target_widget = card
            ctk.CTkLabel(
                card,
                text=_extract_step_title(
                    folder.get("folder_rel_path", ""),
                    folder.get("folder_name", ""),
                    folder.get("display_label", ""),
                ),
                text_color=TEXT_PRIMARY,
                font=ui_font(14, "bold"),
                wraplength=WRAP_FOLDER_CARD,
                justify="left",
            ).pack(anchor="w", padx=10, pady=(10, 2))
            ctk.CTkLabel(
                card,
                text=folder.get("folder_rel_path") or ".",
                text_color=TEXT_MUTED,
                wraplength=WRAP_FOLDER_CARD,
                justify="left",
            ).pack(anchor="w", padx=10)
            action_row = ctk.CTkFrame(card, fg_color="transparent")
            action_row.pack(fill="x", padx=10, pady=(8, 6))
            ctk.CTkButton(
                action_row,
                text="打开步骤文件夹",
                width=WIDTH_OPEN_STEP_BUTTON,
                corner_radius=RADIUS_SM,
                command=lambda p=folder.get("abs_path"): self.open_path(p),
                **button_primary_style(),
            ).pack(side="left")

            main_steps = folder.get("main_steps", [])
            if main_steps:
                ctk.CTkLabel(card, text="顺序代码", text_color=TEXT_PRIMARY, font=ui_font(13, "bold")).pack(anchor="w", padx=10, pady=(2, 4))
                for step in main_steps:
                    is_error_file = error_file_rel_path == step.get("rel_path", "")
                    row = ctk.CTkButton(
                        card,
                        text=step.get("display_label", step.get("script_name", "")),
                        anchor="w",
                        height=HEIGHT_BUTTON,
                        fg_color=ERROR_ITEM_BG if is_error_file else SURFACE_BG,
                        hover_color=ERROR_ITEM_HOVER if is_error_file else ITEM_HOVER,
                        text_color=TEXT_PRIMARY,
                        corner_radius=RADIUS_LG,
                        command=lambda info=step, tid=tab_id: self.run_code_item(tid, info),
                    )
                    row.pack(fill="x", padx=10, pady=(0, 6))

            async_files = folder.get("async_files", [])
            if async_files:
                ctk.CTkLabel(card, text="异步/辅助代码", text_color=TEXT_PRIMARY, font=ui_font(13, "bold")).pack(anchor="w", padx=10, pady=(2, 4))
                for item in async_files:
                    is_error_file = error_file_rel_path == item.get("rel_path", "")
                    row = ctk.CTkButton(
                        card,
                        text=item["name"],
                        anchor="w",
                        height=HEIGHT_BUTTON,
                        fg_color=ERROR_ITEM_BG if is_error_file else SURFACE_BG,
                        hover_color=ERROR_ITEM_HOVER if is_error_file else ITEM_HOVER,
                        text_color=TEXT_PRIMARY,
                        corner_radius=RADIUS_LG,
                        command=lambda info=item, tid=tab_id: self.run_code_item(tid, info),
                    )
                    row.pack(fill="x", padx=10, pady=(0, 6))
            else:
                ctk.CTkLabel(
                    card,
                    text="当前步骤文件夹没有额外的异步/辅助 Python 代码。",
                    text_color=TEXT_MUTED,
                    wraplength=WRAP_FOLDER_CARD,
                    justify="left",
                ).pack(anchor="w", padx=10, pady=(0, 10))

        if scroll_target_widget is not None:
            self.safe_after(60, self.scroll_scrollable_frame_to_widget, code_scroll, scroll_target_widget)

    def run_code_item(self, tab_id, item):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if tab_data.get("current_process"):
            self.log_msg(tab_id, "当前已有顺序代码正在运行，请先等待完成或点击暂停。")
            return
        self.clear_error_focus(tab_id)
        tab_data["batch_has_started_steps"] = False
        tab_data["main_batch_finished"] = False
        tab_data["post_batch_update_done"] = False
        self.refresh_tab_panels(tab_id)
        run_info = dict(item)
        run_info["order"] = None
        run_info["is_manual_code"] = True
        self.run_script_thread(run_info, tab_id)

    def _get_file_structure_column_names(self):
        return [
            "工作区名",
            "步骤",
            "工作区文件夹",
            "子文件夹1",
            "子文件夹2",
            "子文件夹3",
            "子文件夹4",
            "运行顺序",
            "代码/说明",
            "相应代码和说明文件",
            "保存在资料中的名称",
            "备注",
            "其他",
            "输出文件",
            "对应代码",
        ]

    def _normalize_file_structure_header(self, raw_header):
        header = []
        for value in list(raw_header or []):
            text = _clean_text(value)
            header.append(text)
        return header

    def _ensure_file_structure_columns(self, ws, required_columns):
        header_values = [cell.value for cell in ws[1]]
        header = self._normalize_file_structure_header(header_values)
        existing = {name: idx for idx, name in enumerate(header) if name}
        appended = []
        for name in required_columns:
            if name and name not in existing:
                appended.append(name)
        if not appended:
            return header, existing, False
        start_col = len(header) + 1
        for offset, name in enumerate(appended):
            ws.cell(row=1, column=start_col + offset, value=name)
            header.append(name)
        existing = {name: idx for idx, name in enumerate(header) if name}
        return header, existing, True

    def _load_file_structure_pipeline_rows(self, bp_path, award_name):
        wb = load_workbook(bp_path)
        if "工作区" not in wb.sheetnames:
            raise ValueError("未找到工作区 sheet：工作区")
        ws = wb["工作区"]
        required_columns = self._get_file_structure_column_names()
        header, col_map, changed = self._ensure_file_structure_columns(ws, required_columns)

        rows = []
        current_award = ""
        max_row = ws.max_row or 1
        for sheet_row in range(2, max_row + 1):
            award_cell = ws.cell(row=sheet_row, column=col_map["工作区名"] + 1).value
            award_text = _clean_text(award_cell)
            if award_text:
                current_award = award_text
            if current_award != award_name:
                continue

            run_order_cell = ws.cell(row=sheet_row, column=col_map["运行顺序"] + 1).value
            kind_cell = ws.cell(row=sheet_row, column=col_map["代码/说明"] + 1).value
            script_cell = ws.cell(row=sheet_row, column=col_map["相应代码和说明文件"] + 1).value

            script_text = _clean_text(script_cell)
            kind_text = _clean_text(kind_cell)
            order_num = _parse_run_order(run_order_cell)
            is_pipeline = order_num is not None and kind_text == "代码" and script_text.lower().endswith(".py")
            if not is_pipeline:
                continue

            row_values = {}
            for name in required_columns:
                if name == "工作区名":
                    continue
                idx = col_map.get(name)
                if idx is None:
                    row_values[name] = ""
                    continue
                row_values[name] = ws.cell(row=sheet_row, column=idx + 1).value

            rows.append({
                "sheet_row": sheet_row,
                "values": row_values,
            })

        return wb, ws, header, col_map, rows, changed

    def _set_file_structure_dirty(self, tab_id, dirty=True, message=""):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["file_structure_dirty"] = bool(dirty)
        status_var = tab_data.get("file_structure_status_var")
        if status_var:
            status_var.set(message or ("有未保存修改" if dirty else "已从文件读取"))

    def _read_file_structure_row_widgets(self, row_widget_info):
        values = {}
        for key, widget in (row_widget_info or {}).items():
            if not widget or not getattr(widget, "winfo_exists", lambda: False)():
                continue
            if isinstance(widget, ctk.CTkOptionMenu):
                values[key] = widget.get().strip()
            else:
                try:
                    values[key] = widget.get().strip()
                except Exception:
                    values[key] = ""
        return values

    def _render_file_structure_rows(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        scroll = tab_data.get("file_structure_scroll")
        if not scroll or not scroll.winfo_exists():
            return
        for widget in scroll.winfo_children():
            widget.destroy()

        rows = list(tab_data.get("file_structure_rows") or [])
        if not rows:
            ctk.CTkLabel(
                scroll,
                text="当前未识别到“顺序步骤代码”行。\n请确认 文件结构.xlsx 的“工作区名”块匹配当前奖项（如 私募/公募），且该行满足：运行顺序为数字 + 代码/说明=代码 + 文件名以 .py 结尾。",
                text_color=TEXT_MUTED,
                wraplength=WRAP_LEFT_HINT,
                justify="left",
            ).pack(anchor="w", padx=10, pady=(8, 0))
            tab_data["file_structure_row_widgets"] = []
            return
        row_widgets = []

        column_row_1 = [
            ("运行顺序", "顺序", 70),
            ("步骤", "步骤", 70),
            ("相应代码和说明文件", "代码文件", 260),
            ("保存在资料中的名称", "保存名", 220),
            ("代码/说明", "类型", 80),
        ]
        column_row_2 = [
            ("工作区文件夹", "文件夹", 200),
            ("子文件夹1", "子1", 120),
            ("子文件夹2", "子2", 120),
            ("子文件夹3", "子3", 120),
            ("子文件夹4", "子4", 120),
            ("对应代码", "对应代码", 180),
            ("输出文件", "输出文件", 220),
            ("其他", "其他", 180),
        ]

        for idx, row_model in enumerate(rows, start=1):
            card = ctk.CTkFrame(scroll, **panel_card_style())
            card.pack(fill="x", padx=6, pady=(6, 0))

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=10, pady=(10, 6))

            index_label = ctk.CTkLabel(top, text=str(idx), text_color=TEXT_MUTED, width=36, font=ui_font(12, "bold"))
            index_label.pack(side="left")

            handle = ctk.CTkFrame(top, width=26, height=26, fg_color=ACCENT_SEGMENT_BG, corner_radius=RADIUS_SM, border_width=1, border_color=BORDER)
            handle.pack(side="left", padx=(6, 10))
            handle.pack_propagate(False)
            handle_label = ctk.CTkLabel(handle, text="≡", text_color=TEXT_PRIMARY, font=ui_font(14, "bold"))
            handle_label.pack(expand=True)

            row1 = ctk.CTkFrame(top, fg_color="transparent")
            row1.pack(side="left", fill="x", expand=True)
            row1.grid_columnconfigure(0, weight=0)
            row1.grid_columnconfigure(1, weight=0)
            row1.grid_columnconfigure(2, weight=1)
            row1.grid_columnconfigure(3, weight=1)
            row1.grid_columnconfigure(4, weight=0)

            widgets = {}
            for col_idx, (key, label, width) in enumerate(column_row_1):
                field = ctk.CTkFrame(row1, fg_color="transparent")
                field.grid(row=0, column=col_idx, sticky="ew", padx=(0, 8))
                ctk.CTkLabel(field, text=label, text_color=TEXT_MUTED, font=ui_font(10)).pack(anchor="w")
                entry = ctk.CTkEntry(field, width=width, font=ui_font(12), **input_box_style())
                entry.pack(fill="x")
                raw_val = row_model.get("values", {}).get(key, "")
                if raw_val not in (None, ""):
                    entry.insert(0, str(raw_val))
                entry.bind("<KeyRelease>", lambda _e, tid=tab_id: self._set_file_structure_dirty(tid, True))
                widgets[key] = entry

            bottom = ctk.CTkFrame(card, fg_color="transparent")
            bottom.pack(fill="x", padx=10, pady=(0, 10))

            row2 = ctk.CTkFrame(bottom, fg_color="transparent")
            row2.pack(fill="x", expand=True)
            for c in range(len(column_row_2)):
                row2.grid_columnconfigure(c, weight=1 if c in {0, 6} else 0)

            for col_idx, (key, label, width) in enumerate(column_row_2):
                field = ctk.CTkFrame(row2, fg_color="transparent")
                field.grid(row=0, column=col_idx, sticky="ew", padx=(0, 8))
                ctk.CTkLabel(field, text=label, text_color=TEXT_MUTED, font=ui_font(10)).pack(anchor="w")
                entry = ctk.CTkEntry(field, width=width, font=ui_font(12), **input_box_style())
                entry.pack(fill="x")
                raw_val = row_model.get("values", {}).get(key, "")
                if raw_val not in (None, ""):
                    entry.insert(0, str(raw_val))
                entry.bind("<KeyRelease>", lambda _e, tid=tab_id: self._set_file_structure_dirty(tid, True))
                widgets[key] = entry

            note_field = ctk.CTkFrame(bottom, fg_color="transparent")
            note_field.pack(fill="x", pady=(8, 0))
            ctk.CTkLabel(note_field, text="备注", text_color=TEXT_MUTED, font=ui_font(10)).pack(anchor="w")
            note_entry = ctk.CTkEntry(note_field, font=ui_font(12), **input_box_style())
            note_entry.pack(fill="x")
            raw_note = row_model.get("values", {}).get("备注", "")
            if raw_note not in (None, ""):
                note_entry.insert(0, str(raw_note))
            note_entry.bind("<KeyRelease>", lambda _e, tid=tab_id: self._set_file_structure_dirty(tid, True))
            widgets["备注"] = note_entry

            row_widgets.append({
                "card": card,
                "index_label": index_label,
                "handle": handle,
                "handle_label": handle_label,
                "widgets": widgets,
            })

        tab_data["file_structure_row_widgets"] = row_widgets
        self._bind_file_structure_drag_events(tab_id)

    def _bind_file_structure_drag_events(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        for idx, info in enumerate(tab_data.get("file_structure_row_widgets") or []):
            handle = info.get("handle")
            label = info.get("handle_label")
            if not handle or not handle.winfo_exists():
                continue
            if getattr(handle, "_gb_fs_drag_bound", False):
                continue
            handle._gb_fs_drag_bound = True
            handle.bind("<ButtonPress-1>", lambda e, tid=tab_id, i=idx: self._start_file_structure_drag(tid, i, e), add="+")
            handle.bind("<ButtonRelease-1>", lambda e, tid=tab_id: self._finish_file_structure_drag(tid, e), add="+")
            handle.bind("<B1-Motion>", lambda e, tid=tab_id: self._move_file_structure_drag(tid, e), add="+")
            if label and label.winfo_exists():
                label.bind("<ButtonPress-1>", lambda e, tid=tab_id, i=idx: self._start_file_structure_drag(tid, i, e), add="+")
                label.bind("<ButtonRelease-1>", lambda e, tid=tab_id: self._finish_file_structure_drag(tid, e), add="+")
                label.bind("<B1-Motion>", lambda e, tid=tab_id: self._move_file_structure_drag(tid, e), add="+")

    def _start_file_structure_drag(self, tab_id, index, event):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["file_structure_drag"] = {
            "from_index": int(index),
            "hover_index": int(index),
        }
        self._highlight_file_structure_drag_target(tab_id, index)

    def _highlight_file_structure_drag_target(self, tab_id, hover_index):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        for idx, info in enumerate(tab_data.get("file_structure_row_widgets") or []):
            card = info.get("card")
            if not card or not card.winfo_exists():
                continue
            try:
                if idx == hover_index:
                    card.configure(border_width=2, border_color=ACCENT)
                else:
                    card.configure(border_width=1, border_color=PANEL_BORDER)
            except Exception:
                continue

    def _find_file_structure_hover_index(self, tab_id, event):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return None
        y = int(getattr(event, "y_root", 0) or 0)
        for idx, info in enumerate(tab_data.get("file_structure_row_widgets") or []):
            card = info.get("card")
            if not card or not card.winfo_exists():
                continue
            top = int(card.winfo_rooty())
            bottom = top + int(card.winfo_height())
            if top <= y <= bottom:
                return idx
        return None

    def _move_file_structure_drag(self, tab_id, event):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data or not tab_data.get("file_structure_drag"):
            return
        hover = self._find_file_structure_hover_index(tab_id, event)
        if hover is None:
            return
        tab_data["file_structure_drag"]["hover_index"] = int(hover)
        self._highlight_file_structure_drag_target(tab_id, hover)

    def _finish_file_structure_drag(self, tab_id, event):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        drag = tab_data.pop("file_structure_drag", None) or {}
        from_index = drag.get("from_index")
        hover_index = drag.get("hover_index")
        if from_index is None or hover_index is None:
            self._highlight_file_structure_drag_target(tab_id, -1)
            return
        from_index = int(from_index)
        hover_index = int(hover_index)
        self._highlight_file_structure_drag_target(tab_id, -1)
        if from_index == hover_index:
            return
        rows = list(tab_data.get("file_structure_rows") or [])
        if not (0 <= from_index < len(rows) and 0 <= hover_index < len(rows)):
            return
        moved = rows.pop(from_index)
        rows.insert(hover_index, moved)
        for idx, row_model in enumerate(rows, start=1):
            row_model.setdefault("values", {})["运行顺序"] = idx
        tab_data["file_structure_rows"] = rows
        self._set_file_structure_dirty(tab_id, True)
        self._render_file_structure_rows(tab_id)

    def load_file_structure_tab(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return False
        bp_path = tab_data.get("bp_path", "")
        award_name = _clean_text(get_manifest_award(tab_data.get("award", "")))
        if not bp_path or not os.path.isfile(bp_path):
            raise FileNotFoundError(f"未找到文件结构.xlsx：{bp_path}")
        wb, ws, header, col_map, rows, changed = self._load_file_structure_pipeline_rows(bp_path, award_name)
        tab_data["file_structure_bp_path"] = bp_path
        tab_data["file_structure_award_name"] = award_name
        tab_data["file_structure_header"] = header
        tab_data["file_structure_col_map"] = col_map
        tab_data["file_structure_rows"] = rows
        tab_data["file_structure_header_changed"] = bool(changed)
        tab_data["file_structure_loaded_at"] = time.time()
        tab_data["file_structure_workbook"] = wb
        tab_data["file_structure_sheet"] = ws
        self._set_file_structure_dirty(tab_id, False, "已从文件读取" + ("（已补齐缺失列，保存后生效）" if changed else ""))
        return True

    def save_file_structure_tab(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return False
        bp_path = tab_data.get("file_structure_bp_path") or tab_data.get("bp_path", "")
        if not bp_path or not os.path.isfile(bp_path):
            raise FileNotFoundError(f"未找到文件结构.xlsx：{bp_path}")

        wb = tab_data.get("file_structure_workbook")
        ws = tab_data.get("file_structure_sheet")
        if not wb or not ws:
            wb = load_workbook(bp_path)
            ws = wb["工作区"] if "工作区" in wb.sheetnames else wb.active

        required_columns = self._get_file_structure_column_names()
        header, col_map, _changed = self._ensure_file_structure_columns(ws, required_columns)

        rows = list(tab_data.get("file_structure_rows") or [])
        row_widgets = list(tab_data.get("file_structure_row_widgets") or [])
        for idx, row_model in enumerate(rows, start=1):
            row_model.setdefault("values", {})["运行顺序"] = idx
            widget_info = row_widgets[idx - 1] if idx - 1 < len(row_widgets) else {}
            new_values = self._read_file_structure_row_widgets(widget_info.get("widgets"))
            for key, value in new_values.items():
                if key not in row_model["values"]:
                    row_model["values"][key] = ""
                row_model["values"][key] = value

        for idx, row_model in enumerate(rows, start=1):
            sheet_row = int(row_model["sheet_row"])
            values = row_model.get("values", {})
            for col_name, raw_value in values.items():
                if col_name == "工作区名":
                    continue
                if col_name not in col_map:
                    continue
                col_index = col_map[col_name] + 1
                value = raw_value
                if col_name == "运行顺序":
                    try:
                        value = int(raw_value)
                    except Exception:
                        value = idx
                ws.cell(row=sheet_row, column=col_index, value=value)

        wb.save(bp_path)
        tab_data["file_structure_rows"] = rows
        self._set_file_structure_dirty(tab_id, False, "已保存到文件结构.xlsx")
        rebuild = getattr(self, "rebuild_workspace_manifest_for_tab", None)
        if callable(rebuild):
            rebuild(tab_id)
        return True

    def render_file_structure_tab(self, tab_id, parent):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        for widget in parent.winfo_children():
            widget.destroy()

        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(fill="x", pady=(2, 0))
        ctk.CTkLabel(header, text="文件结构", text_color=TEXT_PRIMARY, font=ui_font(15, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="维护 文件结构.xlsx 中“顺序步骤代码”的关键字段；左侧序号固定，拖动 ≡ 可交换行序（保存时会按当前行序重写运行顺序）。",
            text_color=TEXT_MUTED,
            wraplength=WRAP_LEFT_HINT,
            justify="left",
            font=ui_font(12),
        ).pack(anchor="w", pady=(1, 6))

        action_row = ctk.CTkFrame(parent, fg_color="transparent")
        action_row.pack(fill="x", pady=(0, 6))
        status_var = tab_data.get("file_structure_status_var")
        if not status_var:
            status_var = ctk.StringVar(value="未加载")
            tab_data["file_structure_status_var"] = status_var
        ctk.CTkLabel(action_row, textvariable=status_var, text_color=TEXT_MUTED, font=ui_font(11)).pack(side="left", padx=(2, 0))

        ctk.CTkButton(
            action_row,
            text="打开 xlsx",
            width=WIDTH_ACTION_BUTTON,
            corner_radius=RADIUS_SM,
            command=lambda tid=tab_id: self.open_file((self.active_tabs_data.get(tid, {}) or {}).get("bp_path", "")),
            **button_secondary_style(),
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            action_row,
            text="保存",
            width=WIDTH_ACTION_BUTTON,
            corner_radius=RADIUS_SM,
            command=lambda tid=tab_id: self._on_file_structure_save_clicked(tid),
            **button_primary_style(),
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            action_row,
            text="重载",
            width=WIDTH_ACTION_BUTTON,
            corner_radius=RADIUS_SM,
            command=lambda tid=tab_id: self._on_file_structure_reload_clicked(tid),
            **button_secondary_style(),
        ).pack(side="right")

        scroll = ctk.CTkScrollableFrame(parent, **scrollable_style())
        scroll.pack(fill="both", expand=True)
        tab_data["file_structure_scroll"] = scroll

        try:
            self.load_file_structure_tab(tab_id)
        except Exception as exc:
            ctk.CTkLabel(
                scroll,
                text=f"读取失败：{exc}",
                text_color=TEXT_MUTED,
                wraplength=WRAP_LEFT_HINT,
                justify="left",
            ).pack(anchor="w", padx=10, pady=(8, 0))
            return
        self._render_file_structure_rows(tab_id)

    def render_file_structure_view(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        parent = tab_data.get("file_structure_view")
        if not parent or not parent.winfo_exists():
            return
        self.render_file_structure_tab(tab_id, parent)

    def _on_file_structure_reload_clicked(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if tab_data.get("file_structure_dirty"):
            try:
                from tkinter import messagebox
                ok = messagebox.askokcancel("确认重载", "当前有未保存修改，确认丢弃并从磁盘重载吗？")
            except Exception:
                ok = True
            if not ok:
                return
        try:
            self.load_file_structure_tab(tab_id)
            self._render_file_structure_rows(tab_id)
        except Exception as exc:
            try:
                from tkinter import messagebox
                messagebox.showerror("重载失败", str(exc))
            except Exception:
                pass

    def _on_file_structure_save_clicked(self, tab_id):
        try:
            self.save_file_structure_tab(tab_id)
        except Exception as exc:
            try:
                from tkinter import messagebox
                messagebox.showerror("保存失败", str(exc))
            except Exception:
                pass

    def render_doc_panel(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        middle_panel = tab_data.get("middle_panel")
        middle_header = tab_data.get("middle_header")
        manifest = tab_data.get("manifest", {})
        if not middle_panel or not middle_header:
            return

        for widget in middle_header.winfo_children():
            widget.destroy()
        for widget in middle_panel.winfo_children():
            widget.destroy()

        # 中间说明文档区主要组合 panel_card_style、surface_card_style 与主/次按钮样式。
        header_row = ctk.CTkFrame(middle_header, fg_color="transparent")
        header_row.pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(header_row, text="说明文档区", text_color=TEXT_PRIMARY, font=ui_font(17, "bold")).pack(side="left")
        ctk.CTkButton(
            header_row,
            text="刷新说明",
            width=WIDTH_ACTION_BUTTON_SM,
            height=HEIGHT_BUTTON_SM,
            corner_radius=RADIUS_MD,
            command=lambda tid=tab_id: self.refresh_docs_from_xlsx(tid),
            **button_secondary_style(),
        ).pack(side="right")
        ctk.CTkLabel(middle_header, text="优先展示奖项 README.md，其余按文件结构表匹配说明文件", text_color=TEXT_MUTED, font=ui_font(12)).pack(anchor="w", pady=(0, 4))

        award_readme = self.get_award_readme_item(manifest.get("workspace_root", ""))
        readme_card = ctk.CTkFrame(middle_panel, **panel_card_style())
        readme_card.pack(fill="x", padx=6, pady=6)
        ctk.CTkLabel(
            readme_card,
            text="奖项 README",
            text_color=TEXT_PRIMARY,
            font=ui_font(13, "bold"),
        ).pack(anchor="w", padx=10, pady=(10, 4))
        readme_row = ctk.CTkFrame(readme_card, **surface_card_style())
        readme_row.pack(fill="x", padx=10, pady=(4, 8))
        readme_status_text = "README 已就绪" if award_readme.get("exists") else "README 缺失"
        readme_status_color = SUCCESS if award_readme.get("exists") else DANGER
        ctk.CTkLabel(
            readme_row,
            text=award_readme["name"],
            text_color=TEXT_PRIMARY,
            wraplength=WRAP_DOC_ITEM,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(8, 2))
        ctk.CTkLabel(
            readme_row,
            text=readme_status_text,
            text_color=readme_status_color,
        ).pack(anchor="w", padx=8)
        ctk.CTkButton(
            readme_row,
            text="打开 README",
            width=WIDTH_ACTION_BUTTON_XS,
            height=HEIGHT_BUTTON_XS,
            corner_radius=RADIUS_SM,
            state="normal" if award_readme.get("exists") else "disabled",
            command=lambda p=award_readme.get("abs_path"): self.open_file(p),
            **button_primary_style(),
        ).pack(anchor="e", padx=8, pady=(0, 8))

        fixed_backup_doc = self.get_fixed_backup_doc_item(manifest.get("workspace_root", ""))
        backup_card = ctk.CTkFrame(middle_panel, **panel_card_style())
        backup_card.pack(fill="x", padx=6, pady=6)
        ctk.CTkLabel(
            backup_card,
            text="说明备份",
            text_color=TEXT_PRIMARY,
            font=ui_font(13, "bold"),
        ).pack(anchor="w", padx=10, pady=(10, 4))
        backup_row = ctk.CTkFrame(backup_card, **surface_card_style())
        backup_row.pack(fill="x", padx=10, pady=(4, 8))
        backup_status_text = "备份脚本就绪" if fixed_backup_doc.get("exists") else "备份脚本缺失"
        backup_status_color = BACKUP if fixed_backup_doc.get("exists") else DANGER
        ctk.CTkLabel(
            backup_row,
            text=fixed_backup_doc["name"],
            text_color=TEXT_PRIMARY,
            wraplength=WRAP_DOC_ITEM,
            justify="left",
        ).pack(anchor="w", padx=8, pady=(8, 2))
        ctk.CTkLabel(
            backup_row,
            text=backup_status_text,
            text_color=backup_status_color,
        ).pack(anchor="w", padx=8)
        ctk.CTkButton(
            backup_row,
            text="运行备份",
            width=WIDTH_ACTION_BUTTON_XS,
            height=HEIGHT_BUTTON_XS,
            corner_radius=RADIUS_SM,
            state="normal" if fixed_backup_doc.get("exists") else "disabled",
            fg_color=BACKUP,
            hover_color=BACKUP_HOVER,
            text_color=TEXT_PRIMARY,
            command=lambda info=fixed_backup_doc, tid=tab_id: self.run_code_item(tid, info),
        ).pack(anchor="e", padx=8, pady=(0, 8))

        has_any_doc = False
        for step in manifest.get("steps", []):
            docs = step.get("docs", [])
            card = ctk.CTkFrame(middle_panel, **panel_card_style())
            card.pack(fill="x", padx=6, pady=6)
            ctk.CTkLabel(
                card,
                text=_extract_step_title(
                    step.get("folder_rel_path", ""),
                    step.get("rel_path", ""),
                    step.get("display_label", ""),
                ),
                text_color=TEXT_PRIMARY,
                font=ui_font(13, "bold"),
                wraplength=WRAP_FOLDER_CARD,
                justify="left",
            ).pack(anchor="w", padx=10, pady=(10, 4))
            if docs:
                has_any_doc = True
                for doc in docs:
                    row = ctk.CTkFrame(card, **surface_card_style())
                    row.pack(fill="x", padx=10, pady=(4, 6))
                    status_text = "说明文件就绪" if doc.get("exists") else "说明文件缺失"
                    status_color = SUCCESS if doc.get("exists") else DANGER
                    ctk.CTkLabel(row, text=doc["name"], text_color=TEXT_PRIMARY, wraplength=WRAP_DOC_ITEM, justify="left").pack(anchor="w", padx=8, pady=(8, 2))
                    ctk.CTkLabel(row, text=status_text, text_color=status_color).pack(anchor="w", padx=8)
                    if doc.get("note"):
                        ctk.CTkLabel(row, text=doc["note"], text_color=TEXT_MUTED, wraplength=WRAP_DOC_ITEM, justify="left").pack(anchor="w", padx=8, pady=(0, 4))
                    ctk.CTkButton(
                        row,
                        text="打开说明",
                        width=WIDTH_ACTION_BUTTON_XS,
                        height=HEIGHT_BUTTON_XS,
                        corner_radius=RADIUS_SM,
                        state="normal" if doc.get("exists") else "disabled",
                        command=lambda p=doc.get("abs_path"): self.open_path(p),
                        **button_primary_style(),
                    ).pack(anchor="e", padx=8, pady=(0, 8))
            else:
                ctk.CTkLabel(
                    card,
                    text="当前步骤未在 文件结构.xlsx 中匹配到说明文件。",
                    text_color=TEXT_MUTED,
                    wraplength=WRAP_DOC_EMPTY,
                    justify="left",
                ).pack(anchor="w", padx=10, pady=(0, 10))

        supplemental_doc_sections = list(manifest.get("supplemental_doc_sections", []))
        for section in supplemental_doc_sections:
            docs = list(section.get("docs", []))
            if not docs:
                continue
            has_any_doc = True
            card = ctk.CTkFrame(middle_panel, **panel_card_style())
            card.pack(fill="x", padx=6, pady=6)
            ctk.CTkLabel(
                card,
                text=_extract_step_title(
                    section.get("rel_dir", ""),
                    section.get("display_label", ""),
                ),
                text_color=TEXT_PRIMARY,
                font=ui_font(13, "bold"),
                wraplength=WRAP_FOLDER_CARD,
                justify="left",
            ).pack(anchor="w", padx=10, pady=(10, 4))
            for doc in docs:
                row = ctk.CTkFrame(card, **surface_card_style())
                row.pack(fill="x", padx=10, pady=(4, 6))
                status_text = "说明文件就绪" if doc.get("exists") else "说明文件缺失"
                status_color = SUCCESS if doc.get("exists") else DANGER
                ctk.CTkLabel(row, text=doc["name"], text_color=TEXT_PRIMARY, wraplength=WRAP_DOC_ITEM, justify="left").pack(anchor="w", padx=8, pady=(8, 2))
                ctk.CTkLabel(row, text=status_text, text_color=status_color).pack(anchor="w", padx=8)
                if doc.get("note"):
                    ctk.CTkLabel(row, text=doc["note"], text_color=TEXT_MUTED, wraplength=WRAP_DOC_ITEM, justify="left").pack(anchor="w", padx=8, pady=(0, 4))
                ctk.CTkButton(
                    row,
                    text="打开说明",
                    width=WIDTH_ACTION_BUTTON_XS,
                    height=HEIGHT_BUTTON_XS,
                    corner_radius=RADIUS_SM,
                    state="normal" if doc.get("exists") else "disabled",
                    command=lambda p=doc.get("abs_path"): self.open_file(p),
                    **button_primary_style(),
                ).pack(anchor="e", padx=8, pady=(0, 8))

        if not manifest.get("steps") and not supplemental_doc_sections:
            ctk.CTkLabel(middle_panel, text="当前工作区没有可展示的步骤。", text_color=TEXT_MUTED).pack(anchor="w", padx=10, pady=(10, 0))
        elif not has_any_doc:
            hint = ctk.CTkFrame(middle_panel, **panel_card_style())
            hint.pack(fill="x", padx=6, pady=6)
            ctk.CTkLabel(hint, text="未匹配到说明文件", text_color=TEXT_PRIMARY, font=ui_font(14, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
            ctk.CTkLabel(
                hint,
                text="请确认 文件结构.xlsx 中“代码/说明”为“说明”，且说明文件与步骤代码位于同一目录。",
                text_color=TEXT_MUTED,
                wraplength=WRAP_DOC_EMPTY,
                justify="left",
            ).pack(anchor="w", padx=10, pady=(0, 10))

        # 渲染完成后刷新存档指纹，作为下次自动刷新的比较基准。
        self.store_doc_panel_signature(tab_id)

    def refresh_docs_from_xlsx(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        manifest = tab_data.get("manifest", {})
        if not manifest:
            return
        try:
            tab_data["manifest"] = self.reconcile_manifest(manifest)
        except Exception as e:
            self.log_msg(tab_id, f"刷新说明状态失败: {e}")
            return
        self.render_doc_panel(tab_id)

    def render_resource_panel(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        resource_panel = tab_data.get("resource_panel")
        resource_header = tab_data.get("resource_header")
        manifest = tab_data.get("manifest", {})
        if not resource_panel or not resource_header:
            return

        for widget in resource_header.winfo_children():
            widget.destroy()
        for widget in resource_panel.winfo_children():
            widget.destroy()

        workspace_root = manifest.get("workspace_root", "")
        workspace_folder = os.path.basename(workspace_root)
        award_name = tab_data.get("award") or manifest.get("award") or ""
        year_text = self.get_workspace_year(workspace_folder)
        fixed_resources = self.get_award_year_fixed_resources(award_name, year_text)
        dataset_path = _clean_text(fixed_resources.get("dataset_path"))
        rule_path = _clean_text(fixed_resources.get("rule_path"))

        header_row = ctk.CTkFrame(resource_header, fg_color="transparent")
        header_row.pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(header_row, text="规则/所给数据集", text_color=TEXT_PRIMARY, font=ui_font(17, "bold")).pack(side="left")
        ctk.CTkLabel(
            resource_header,
            text=f"{award_name} · {year_text} 年指定资料",
            text_color=TEXT_MUTED,
            font=ui_font(12),
        ).pack(anchor="w", pady=(0, 4))

        for title, path_value, exists_check, open_text, open_command in [
            ("原始数据集", dataset_path, os.path.isdir, "打开文件夹", lambda p=dataset_path: self.open_path(p)),
            ("评奖规则", rule_path, os.path.isfile, "打开文件", lambda p=rule_path: self.open_file(p)),
        ]:
            card = ctk.CTkFrame(resource_panel, **panel_card_style())
            card.pack(fill="x", padx=6, pady=6)
            ctk.CTkLabel(card, text=title, text_color=TEXT_PRIMARY, font=ui_font(14, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
            exists = bool(path_value) and exists_check(path_value)
            if path_value:
                status_text = "已指定" if exists else "已指定，但路径缺失"
                status_color = SUCCESS if exists else DANGER
                name_text = os.path.basename(path_value) or path_value
                detail_text = path_value
            else:
                status_text = "未指定"
                status_color = TEXT_MUTED
                name_text = "未指定"
                detail_text = "请先在左侧边栏选择后点击确定。"
            ctk.CTkLabel(card, text=name_text, text_color=TEXT_PRIMARY, wraplength=WRAP_DOC_ITEM, justify="left").pack(anchor="w", padx=10, pady=(0, 2))
            ctk.CTkLabel(card, text=status_text, text_color=status_color).pack(anchor="w", padx=10)
            ctk.CTkLabel(card, text=detail_text, text_color=TEXT_MUTED, wraplength=WRAP_DOC_EMPTY, justify="left").pack(anchor="w", padx=10, pady=(2, 8))
            ctk.CTkButton(
                card,
                text=open_text,
                width=WIDTH_ACTION_BUTTON_SM,
                height=HEIGHT_BUTTON_SM,
                corner_radius=RADIUS_MD,
                state="normal" if exists else "disabled",
                command=open_command,
                **button_primary_style(),
            ).pack(anchor="e", padx=10, pady=(0, 10))

    def copy_to_clipboard(self, text):
        try:
            self.clipboard_clear()
            self.clipboard_append("" if text is None else str(text))
            self.update_idletasks()
        except Exception:
            return

    def _resolve_existing_paths(self, paths):
        resolved = []
        for path in paths or []:
            if not path:
                continue
            abs_path = os.path.normpath(os.path.abspath(str(path)))
            if os.path.exists(abs_path):
                resolved.append(abs_path)
        return resolved

    def _get_path_mtime(self, path):
        try:
            return float(os.path.getmtime(path))
        except OSError:
            return 0.0

    def _sort_paths_desc(self, paths):
        return sorted(paths or [], key=self._get_path_mtime, reverse=True)

    def _copy_paths_as_text(self, paths):
        resolved = self._resolve_existing_paths(paths)
        if not resolved:
            return {"ok": False, "ok_text": False, "count": 0, "paths": []}
        try:
            self.copy_to_clipboard("\r\n".join(resolved))
            return {"ok": True, "ok_text": True, "count": len(resolved), "paths": resolved}
        except Exception:
            return {"ok": False, "ok_text": False, "count": len(resolved), "paths": resolved}

    def copy_files_to_clipboard(self, paths):
        resolved = self._resolve_existing_paths(paths)
        if not resolved:
            return {"ok": False, "ok_files": False, "ok_text": False, "count": 0, "paths": []}
        if os.name != "nt":
            text_result = self._copy_paths_as_text(resolved)
            return {
                "ok": bool(text_result.get("ok_text")),
                "ok_files": False,
                "ok_text": bool(text_result.get("ok_text")),
                "count": text_result.get("count", 0),
                "paths": text_result.get("paths", []),
            }
        joined = "\r\n".join(resolved)
        try:
            import ctypes
            from ctypes import wintypes

            CF_HDROP = 15
            CF_UNICODETEXT = 13
            GMEM_MOVEABLE = 0x0002

            class DROPFILES(ctypes.Structure):
                _fields_ = [
                    ("pFiles", wintypes.DWORD),
                    ("pt_x", wintypes.LONG),
                    ("pt_y", wintypes.LONG),
                    ("fNC", wintypes.BOOL),
                    ("fWide", wintypes.BOOL),
                ]

            payload = ("\0".join(resolved) + "\0\0").encode("utf-16le")
            header = DROPFILES()
            header.pFiles = ctypes.sizeof(DROPFILES)
            header.pt_x = 0
            header.pt_y = 0
            header.fNC = 0
            header.fWide = 1

            total_size = ctypes.sizeof(DROPFILES) + len(payload)
            kernel32 = ctypes.windll.kernel32
            user32 = ctypes.windll.user32

            kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
            kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

            hglobal = kernel32.GlobalAlloc(GMEM_MOVEABLE, total_size)
            if not hglobal:
                text_result = self._copy_paths_as_text(resolved)
                return {"ok": bool(text_result.get("ok_text")), "ok_files": False, "ok_text": bool(text_result.get("ok_text")), "count": len(resolved), "paths": list(resolved)}
            locked = kernel32.GlobalLock(hglobal)
            if not locked:
                kernel32.GlobalFree(hglobal)
                text_result = self._copy_paths_as_text(resolved)
                return {"ok": bool(text_result.get("ok_text")), "ok_files": False, "ok_text": bool(text_result.get("ok_text")), "count": len(resolved), "paths": list(resolved)}
            ctypes.memmove(locked, ctypes.byref(header), ctypes.sizeof(DROPFILES))
            ctypes.memmove(locked + ctypes.sizeof(DROPFILES), payload, len(payload))
            kernel32.GlobalUnlock(hglobal)

            open_ok = False
            for _ in range(3):
                if user32.OpenClipboard(None):
                    open_ok = True
                    break
                time.sleep(0.03)
            if not open_ok:
                kernel32.GlobalFree(hglobal)
                text_result = self._copy_paths_as_text(resolved)
                return {"ok": bool(text_result.get("ok_text")), "ok_files": False, "ok_text": bool(text_result.get("ok_text")), "count": len(resolved), "paths": list(resolved)}
            try:
                ok_files = False
                for _ in range(3):
                    user32.EmptyClipboard()
                    ok_files = bool(user32.SetClipboardData(CF_HDROP, hglobal))
                    if ok_files:
                        break
                    time.sleep(0.03)
                if not ok_files:
                    kernel32.GlobalFree(hglobal)
                    text_result = self._copy_paths_as_text(resolved)
                    return {"ok": bool(text_result.get("ok_text")), "ok_files": False, "ok_text": bool(text_result.get("ok_text")), "count": len(resolved), "paths": list(resolved)}
                hglobal = None
                text_payload = (joined + "\0").encode("utf-16le")
                hglobal_text = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(text_payload))
                ok_text = False
                if hglobal_text:
                    locked_text = kernel32.GlobalLock(hglobal_text)
                    if locked_text:
                        ctypes.memmove(locked_text, text_payload, len(text_payload))
                        kernel32.GlobalUnlock(hglobal_text)
                        for _ in range(3):
                            ok_text = bool(user32.SetClipboardData(CF_UNICODETEXT, hglobal_text))
                            if ok_text:
                                break
                            time.sleep(0.03)
                        if ok_text:
                            hglobal_text = None
                    if hglobal_text:
                        kernel32.GlobalFree(hglobal_text)
                return {"ok": True, "ok_files": True, "ok_text": ok_text, "count": len(resolved), "paths": list(resolved)}
            finally:
                user32.CloseClipboard()
        except Exception:
            text_result = self._copy_paths_as_text(resolved)
            return {"ok": bool(text_result.get("ok_text")), "ok_files": False, "ok_text": bool(text_result.get("ok_text")), "count": len(resolved), "paths": list(resolved)}

    def copy_single_file_to_clipboard(self, path):
        return self.copy_files_to_clipboard([path])

    def copy_calc_results_paths(self, tab_id, paths, label=""):
        result = self.copy_files_to_clipboard(paths)
        ok = bool(result.get("ok"))
        resolved = result.get("paths") or []
        count = int(result.get("count") or 0)
        if hasattr(self, "log_msg") and resolved:
            preview = "\n".join(resolved[:30])
            suffix = f"\n...(共 {count} 项)" if count > 30 else ""
            self.log_msg(tab_id, f"已复制{label or '文件'}路径到剪贴板:\n{preview}{suffix}", raw=True)
        try:
            from tkinter import messagebox
            if ok:
                if result.get("ok_files") and result.get("ok_text"):
                    messagebox.showinfo("复制成功", f"已复制{label or '文件'}：{count} 项\n可直接粘贴到聊天窗口/文本框，也可在资源管理器粘贴文件。", parent=self)
                elif result.get("ok_text"):
                    messagebox.showinfo("复制成功", f"已复制{label or '文件'}路径：{count} 项\n可直接粘贴到聊天窗口/文本框。\n如需发送文件本体，请用“定位”后拖拽发送。", parent=self)
                else:
                    messagebox.showinfo("复制成功", f"已复制{label or '文件'}：{count} 项\n可在资源管理器粘贴文件。", parent=self)
            else:
                messagebox.showwarning("复制失败", f"未能复制{label or '文件'}，请确认路径存在。", parent=self)
        except Exception:
            return

    def reveal_in_explorer(self, path):
        resolved_path = os.path.normpath(os.path.abspath(str(path)))
        if not os.path.exists(resolved_path):
            return False
        if os.name != "nt":
            return False
        try:
            if os.path.isfile(resolved_path):
                subprocess.Popen(["explorer.exe", "/select,", resolved_path])
            else:
                subprocess.Popen(["explorer.exe", resolved_path])
            return True
        except Exception:
            return False

    def _iter_calc_result_folders_in_step(self, step_root, max_depth=2):
        if not step_root or not os.path.isdir(step_root):
            return []
        hits = []
        direct = os.path.join(step_root, "计算结果")
        if os.path.isdir(direct):
            hits.append(direct)
        for root, dirs, _files in os.walk(step_root):
            rel = os.path.relpath(root, step_root)
            depth = 0 if rel in {".", ""} else rel.count(os.sep) + 1
            if depth > max_depth:
                dirs[:] = []
                continue
            for folder in list(dirs):
                if folder == "计算结果":
                    hits.append(os.path.join(root, folder))
        return hits

    def find_workspace_calc_result_folders(self, workspace_root):
        if not workspace_root or not os.path.isdir(workspace_root):
            return []
        step_folders = []
        try:
            for name in os.listdir(workspace_root):
                abs_path = os.path.join(workspace_root, name)
                if not os.path.isdir(abs_path):
                    continue
                lower_name = name.lower()
                if not lower_name.startswith("step_"):
                    continue
                step_folders.append(abs_path)
        except OSError:
            step_folders = []

        preferred_steps = [p for p in step_folders if "计算" in os.path.basename(p)]
        if preferred_steps:
            step_folders = preferred_steps

        results = []
        for step_root in step_folders:
            results.extend(self._iter_calc_result_folders_in_step(step_root, max_depth=2))

        if not results:
            for root, dirs, _files in os.walk(workspace_root):
                rel = os.path.relpath(root, workspace_root)
                depth = 0 if rel in {".", ""} else rel.count(os.sep) + 1
                if depth > 3:
                    dirs[:] = []
                    continue
                for folder in list(dirs):
                    if folder == "计算结果":
                        results.append(os.path.join(root, folder))

        unique = sorted({os.path.normpath(os.path.abspath(p)) for p in results if os.path.isdir(p)})
        return unique

    def scan_calc_result_items(self, workspace_root):
        roots = self.find_workspace_calc_result_folders(workspace_root)
        items = []
        all_files = []
        for root in roots:
            root_files = []
            root_folders = []
            try:
                for name in os.listdir(root):
                    abs_path = os.path.join(root, name)
                    if os.path.isdir(abs_path):
                        root_folders.append(abs_path)
                    elif os.path.isfile(abs_path):
                        root_files.append(abs_path)
            except OSError:
                root_files = []
                root_folders = []

            groups = {}
            if root_files:
                root_files = self._sort_paths_desc(root_files)
                groups["根目录"] = {"folder": root, "files": list(root_files)}
                all_files.extend(root_files)

            for folder_path in sorted(root_folders):
                folder_name = os.path.basename(folder_path)
                group_name = "其他"
                if "周" in folder_name:
                    group_name = "周度"
                elif "月" in folder_name:
                    group_name = "月度"
                files = []
                try:
                    for child in os.listdir(folder_path):
                        child_path = os.path.join(folder_path, child)
                        if os.path.isfile(child_path):
                            files.append(child_path)
                except OSError:
                    files = []
                if not files:
                    continue
                files = self._sort_paths_desc(files)
                groups.setdefault(group_name, {"folder": folder_path, "files": []})["files"].extend(files)
                all_files.extend(files)

            for payload in groups.values():
                payload["files"] = self._sort_paths_desc(payload.get("files") or [])

            panel_candidates = []
            for file_path in {*(root_files or []), *[p for g in groups.values() for p in g.get("files", [])]}:
                base = os.path.basename(file_path)
                if "结果面板" in base or (base.endswith(".xlsx") and "面板" in base):
                    panel_candidates.append(file_path)
            panel_candidates = self._sort_paths_desc(panel_candidates)
            latest_ts = 0.0
            for file_path in {*(root_files or []), *[p for g in groups.values() for p in g.get("files", [])], *(panel_candidates or [])}:
                latest_ts = max(latest_ts, self._get_path_mtime(file_path))

            items.append(
                {
                    "root": root,
                    "groups": [(k, groups[k]) for k in ["周度", "月度", "根目录", "其他"] if k in groups],
                    "panel_candidates": panel_candidates,
                    "_latest_ts": latest_ts,
                }
            )

        all_files = sorted({os.path.normpath(os.path.abspath(p)) for p in all_files if os.path.isfile(p)})
        items.sort(key=lambda item: float(item.get("_latest_ts") or 0.0), reverse=True)
        for item in items:
            item.pop("_latest_ts", None)
        return items, self._sort_paths_desc(all_files)

    def render_calc_results_panel(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        results_panel = tab_data.get("results_panel")
        results_header = tab_data.get("results_header")
        manifest = tab_data.get("manifest", {})
        if not results_panel or not results_header:
            return

        for widget in results_header.winfo_children():
            widget.destroy()
        for widget in results_panel.winfo_children():
            widget.destroy()

        workspace_root = manifest.get("workspace_root", "")

        header_row = ctk.CTkFrame(results_header, fg_color="transparent")
        header_row.pack(fill="x", pady=(0, 2))
        ctk.CTkLabel(header_row, text="计算结果", text_color=TEXT_PRIMARY, font=ui_font(17, "bold")).pack(side="left")
        ctk.CTkButton(
            header_row,
            text="刷新",
            width=WIDTH_ACTION_BUTTON_SM,
            height=HEIGHT_BUTTON_SM,
            corner_radius=RADIUS_MD,
            command=lambda tid=tab_id: self.render_calc_results_panel(tid),
            **button_secondary_style(),
        ).pack(side="right")

        hint = ctk.CTkLabel(
            results_header,
            text="搜索工作区内 `计算结果` 目录（优先在包含“计算”的 step 目录内），并按周度/月度分层展示。",
            text_color=TEXT_MUTED,
            font=ui_font(12),
        )
        hint.pack(anchor="w", pady=(0, 4))

        if not workspace_root or not os.path.isdir(workspace_root):
            ctk.CTkLabel(results_panel, text="未识别到工作区根目录。", text_color=DANGER).pack(anchor="w", padx=10, pady=(10, 0))
            tab_data["calc_results_all_paths"] = []
            return

        folders, all_files = self.scan_calc_result_items(workspace_root)
        tab_data["calc_results_all_paths"] = list(all_files)

        top_actions = ctk.CTkFrame(results_panel, **panel_card_style())
        top_actions.pack(fill="x", padx=6, pady=(6, 10))
        ctk.CTkLabel(top_actions, text="快捷操作", text_color=TEXT_PRIMARY, font=ui_font(14, "bold")).pack(anchor="w", padx=10, pady=(10, 6))
        btn_row = ctk.CTkFrame(top_actions, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(
            btn_row,
            text="打开工作区",
            width=WIDTH_OPEN_INFO_BUTTON,
            corner_radius=RADIUS_SM,
            command=lambda p=workspace_root: self.open_path(p),
            **button_primary_style(),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btn_row,
            text="复制全部文件",
            width=WIDTH_ACTION_BUTTON,
            corner_radius=RADIUS_SM,
            state="normal" if all_files else "disabled",
            command=lambda tid=tab_id: self.copy_calc_results_paths(tid, self.active_tabs_data.get(tid, {}).get("calc_results_all_paths", []), "文件"),
            **button_secondary_style(),
        ).pack(side="left")

        if not folders:
            ctk.CTkLabel(
                results_panel,
                text="未找到 `计算结果` 目录。通常位于 `step_4 计算/计算结果` 或类似位置。",
                text_color=TEXT_MUTED,
                wraplength=WRAP_PANEL_MD,
                justify="left",
            ).pack(anchor="w", padx=10, pady=(0, 10))
            return

        for info in folders:
            root_path = info.get("root", "")
            rel = os.path.relpath(root_path, workspace_root) if root_path else ""
            card = ctk.CTkFrame(results_panel, **panel_card_style())
            card.pack(fill="x", padx=6, pady=6)
            ctk.CTkLabel(card, text=rel or root_path, text_color=TEXT_PRIMARY, font=ui_font(14, "bold"), wraplength=WRAP_PANEL_MD, justify="left").pack(anchor="w", padx=10, pady=(10, 4))

            folder_btn_row = ctk.CTkFrame(card, fg_color="transparent")
            folder_btn_row.pack(fill="x", padx=10, pady=(0, 10))
            ctk.CTkButton(
                folder_btn_row,
                text="打开目录",
                width=WIDTH_OPEN_INFO_BUTTON,
                corner_radius=RADIUS_SM,
                command=lambda p=root_path: self.open_path(p),
                **button_primary_style(),
            ).pack(side="left", padx=(0, 6))
            ctk.CTkButton(
                folder_btn_row,
                text="复制目录",
                width=WIDTH_ACTION_BUTTON,
                corner_radius=RADIUS_SM,
                command=lambda tid=tab_id, p=root_path: self.copy_calc_results_paths(tid, [p], "目录"),
                **button_secondary_style(),
            ).pack(side="left")

            panel_candidates = info.get("panel_candidates") or []
            if panel_candidates:
                panel_path = panel_candidates[0]
                panel_row = ctk.CTkFrame(card, **surface_card_style())
                panel_row.pack(fill="x", padx=10, pady=(0, 8))
                ctk.CTkLabel(panel_row, text=os.path.basename(panel_path), text_color=TEXT_PRIMARY, font=ui_font(13, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
                ctk.CTkLabel(panel_row, text=panel_path, text_color=TEXT_MUTED, wraplength=WRAP_PANEL_MD, justify="left").pack(anchor="w", padx=8, pady=(2, 8))
                action_row = ctk.CTkFrame(panel_row, fg_color="transparent")
                action_row.pack(fill="x", padx=8, pady=(0, 10))
                ctk.CTkButton(
                    action_row,
                    text="打开结果面板",
                    width=WIDTH_OPEN_INFO_BUTTON,
                    corner_radius=RADIUS_SM,
                    command=lambda p=panel_path: self.open_file(p),
                    **button_primary_style(),
                ).pack(side="left", padx=(0, 6))
                ctk.CTkButton(
                    action_row,
                    text="复制文件",
                    width=WIDTH_ACTION_BUTTON,
                    corner_radius=RADIUS_SM,
                    command=lambda tid=tab_id, p=panel_path: self.copy_calc_results_paths(tid, [p], "文件"),
                    **button_secondary_style(),
                ).pack(side="left")
                ctk.CTkButton(
                    action_row,
                    text="定位",
                    width=WIDTH_ACTION_BUTTON,
                    corner_radius=RADIUS_SM,
                    command=lambda p=panel_path: self.reveal_in_explorer(p),
                    **button_secondary_style(),
                ).pack(side="left", padx=(6, 0))

            for group_name, payload in info.get("groups", []):
                files = payload.get("files") or []
                if not files:
                    continue
                ctk.CTkLabel(card, text=group_name, text_color=TEXT_PRIMARY, font=ui_font(13, "bold")).pack(anchor="w", padx=10, pady=(4, 4))
                for file_path in files:
                    row = ctk.CTkFrame(card, **surface_card_style())
                    row.pack(fill="x", padx=10, pady=4)
                    ctk.CTkLabel(row, text=os.path.basename(file_path), text_color=TEXT_PRIMARY, font=ui_font(12, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
                    ctk.CTkLabel(row, text=file_path, text_color=TEXT_MUTED, wraplength=WRAP_PANEL_MD, justify="left").pack(anchor="w", padx=8, pady=(2, 8))
                    action_row = ctk.CTkFrame(row, fg_color="transparent")
                    action_row.pack(fill="x", padx=8, pady=(0, 10))
                    ctk.CTkButton(
                        action_row,
                        text="打开",
                        width=WIDTH_OPEN_INFO_BUTTON,
                        corner_radius=RADIUS_SM,
                        command=lambda p=file_path: self.open_file(p),
                        **button_primary_style(),
                    ).pack(side="left", padx=(0, 6))
                    ctk.CTkButton(
                        action_row,
                        text="复制文件",
                        width=WIDTH_ACTION_BUTTON,
                        corner_radius=RADIUS_SM,
                        command=lambda tid=tab_id, p=file_path: self.copy_calc_results_paths(tid, [p], "文件"),
                        **button_secondary_style(),
                    ).pack(side="left")
                    ctk.CTkButton(
                        action_row,
                        text="定位",
                        width=WIDTH_ACTION_BUTTON,
                        corner_radius=RADIUS_SM,
                        command=lambda p=file_path: self.reveal_in_explorer(p),
                        **button_secondary_style(),
                    ).pack(side="left", padx=(6, 0))

    def open_path(self, path, ensure_dir=False):
        if not path:
            return
        try:
            resolved_path = os.path.normpath(os.path.abspath(path))
            if ensure_dir and not os.path.exists(resolved_path):
                os.makedirs(resolved_path, exist_ok=True)
            os.startfile(resolved_path)
        except OSError:
            print(f"无法打开路径: {os.path.normpath(os.path.abspath(path))}")

    def open_text_file_in_editor(self, path):
        resolved_path = os.path.normpath(os.path.abspath(path))
        if not os.path.isfile(resolved_path):
            return False
        editor_commands = [
            ("trae", "--reuse-window", "--goto", resolved_path),
            ("code", "--reuse-window", "--goto", resolved_path),
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        for command in editor_commands:
            executable = shutil.which(command[0])
            if not executable:
                continue
            try:
                subprocess.Popen(
                    [executable, *command[1:]],
                    cwd=os.path.dirname(resolved_path) or None,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                return True
            except Exception:
                continue
        return False

    def open_file(self, path):
        resolved_path = os.path.normpath(os.path.abspath(path))
        ext = os.path.splitext(resolved_path)[1].lower()
        if ext in {".py", ".md", ".txt", ".json", ".log", ".csv"}:
            if self.open_text_file_in_editor(resolved_path):
                return
        self.open_path(resolved_path)

    def get_scroll_fraction(self, scroll_frame):
        try:
            canvas = getattr(scroll_frame, "_parent_canvas", None)
            if not canvas:
                return 0.0
            yview = canvas.yview()
            if not yview:
                return 0.0
            return float(yview[0])
        except Exception:
            return 0.0

    def set_scroll_fraction(self, scroll_frame, fraction):
        try:
            canvas = getattr(scroll_frame, "_parent_canvas", None)
            if not canvas:
                return
            f = 0.0 if fraction is None else float(fraction)
            if f < 0.0:
                f = 0.0
            elif f > 1.0:
                f = 1.0
            canvas.yview_moveto(f)
        except Exception:
            return

    def set_right_panel_view(self, tab_id, view_name):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        right_panel = tab_data.get("right_panel")
        last_rendered = tab_data.get("right_panel_rendered_view")
        if right_panel:
            if last_rendered == "output":
                tab_data["right_scroll_output"] = self.get_scroll_fraction(right_panel)
            elif last_rendered == "database":
                tab_data["right_scroll_database"] = self.get_scroll_fraction(right_panel)
        tab_data["right_view"] = view_name
        self.render_right_panel(tab_id)
        self.schedule_gui_state_save(tab_id)

    def set_auto_refresh_enabled(self, tab_id, enabled):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["auto_refresh_enabled"] = bool(enabled)
        var = tab_data.get("auto_refresh_var")
        if var:
            var.set(bool(enabled))

    def set_output_marker_filter(self, tab_id, value):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        tab_data["output_marker_filter"] = value
        self.render_output_board(tab_id)

    def apply_output_code_filter(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        var = tab_data.get("output_code_filter_var")
        tab_data["output_code_filter"] = var.get().strip() if var else ""
        self.render_output_board(tab_id)

    def render_right_panel(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        if tab_data.get("right_view") == "database":
            self.render_database_panel(tab_id)
        else:
            self.render_output_board(tab_id)

    def render_right_panel_switcher(self, parent, tab_id):
        tab_data = self.active_tabs_data.get(tab_id, {})
        switcher = ctk.CTkSegmentedButton(
            parent,
            values=["数据文件", "数据库"],
            command=lambda value, tid=tab_id: self.set_right_panel_view(tid, "database" if value == "数据库" else "output"),
            **segmented_button_style(),
        )
        switcher.pack(fill="x", padx=10, pady=(0, 6))
        switcher.set("数据库" if tab_data.get("right_view") == "database" else "数据文件")

    def get_output_folders(self, manifest, limit=12):
        configured_outputs = manifest.get("output_folders", [])
        if configured_outputs:
            return configured_outputs
        folders = []
        seen = set()
        workspace_root = manifest["workspace_root"]
        for step in manifest.get("steps", []):
            rel_dir = os.path.dirname(step.get("rel_path", ""))
            abs_dir = os.path.join(workspace_root, rel_dir) if rel_dir else workspace_root
            key = os.path.normcase(os.path.normpath(abs_dir))
            if key in seen:
                continue
            seen.add(key)
            exists = os.path.isdir(abs_dir)
            try:
                n_items = len(os.listdir(abs_dir)) if exists else 0
            except OSError:
                n_items = 0
            folders.append(
                {
                    "order": step.get("order"),
                    "script_name": step.get("script_name", ""),
                    "display_label": step.get("display_label", step.get("script_name", "")),
                    "rel_dir": rel_dir or ".",
                    "path": abs_dir,
                    "exists": exists,
                    "n_items": n_items,
                }
            )
        return folders[:limit]

    def get_output_folder_groups(self, manifest, limit=18, marker_filter="", code_query=""):
        output_folders = self.get_output_folders(manifest, limit=limit)
        normalized_query = (code_query or "").strip().lower()
        marker_key = ""
        if marker_filter == "机构":
            marker_key = "ins"
        elif marker_filter == "全量":
            marker_key = "全量"
        if marker_key:
            output_folders = [item for item in output_folders if marker_key in [str(m).lower() for m in (item.get("markers") or [])]]
        if normalized_query:
            filtered = []
            for item in output_folders:
                text = " ".join(
                    [
                        str(item.get("display_label", "")),
                        str(item.get("script_name", "")),
                        str(item.get("rel_dir", "")),
                    ]
                ).lower()
                if normalized_query in text:
                    filtered.append(item)
            output_folders = filtered
        groups = {}
        ordered_keys = []
        for item in output_folders:
            markers = item.get("markers") or []
            if not markers:
                if "未分类" not in groups:
                    groups["未分类"] = []
                    ordered_keys.append("未分类")
                groups["未分类"].append(item)
                continue
            for marker in markers:
                if marker not in groups:
                    groups[marker] = []
                    ordered_keys.append(marker)
                groups[marker].append(item)
        return [(key, groups[key]) for key in ordered_keys]

    def get_observe_folders(self, manifest):
        workspace_root = manifest["workspace_root"]
        observe_candidates = [
            ("INS 观察文件夹", os.path.join("重要文件", "机构筛选数据")),
        ]
        folders = []
        for label, rel_path in observe_candidates:
            abs_path = os.path.join(workspace_root, rel_path)
            if not os.path.isdir(abs_path):
                continue
            try:
                n_items = len(os.listdir(abs_path))
            except OSError:
                n_items = 0
            folders.append(
                {
                    "label": label,
                    "rel_path": rel_path,
                    "path": abs_path,
                    "n_items": n_items,
                }
            )
        return folders

    def get_database_path(self, manifest):
        workspace_root = str((manifest or {}).get("workspace_root", "") or "").strip()
        if not workspace_root:
            return ""
        workspace_name = os.path.basename(workspace_root)
        year_text = self.get_workspace_year(workspace_name)
        if not year_text or year_text == "未识别":
            return ""
        db_path = os.path.join(os.path.dirname(workspace_root), "数据库", str(year_text), "DB_PRIVATE.duckdb")
        return db_path if os.path.isfile(db_path) else ""

    def get_database_tables(self, db_path, limit=16):
        if not duckdb or not db_path or not os.path.isfile(db_path):
            return [], ""
        try:
            conn = duckdb.connect(db_path, read_only=True)
            rows = conn.execute(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                ORDER BY
                    CASE WHEN table_schema LIKE 'step%' THEN 0 ELSE 1 END,
                    table_schema,
                    table_name
                LIMIT ?
                """,
                [limit],
            ).fetchall()
            conn.close()
            return rows, ""
        except Exception as e:
            return [], str(e)

    def execute_db_query(self, db_path, sql):
        if not duckdb:
            return "未安装 duckdb Python 包，当前无法在界面内查询数据库。"
        try:
            conn = duckdb.connect(db_path, read_only=True)
            cursor = conn.execute(sql)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            conn.close()
            return self.format_query_result(columns, rows)
        except Exception as e:
            return f"查询失败:\n{e}"

    def format_query_result(self, columns, rows):
        if not columns:
            return "查询已执行，但没有可展示的结果列。"
        if not rows:
            return "查询成功，结果为空。"
        widths = []
        preview_rows = rows[:20]
        for idx, col in enumerate(columns):
            cell_width = max(len(str(col)), *(len(str(row[idx])) for row in preview_rows))
            widths.append(min(max(cell_width, 6), 28))
        header = " | ".join(str(col).ljust(widths[idx])[:widths[idx]] for idx, col in enumerate(columns))
        divider = "-+-".join("-" * width for width in widths)
        body = []
        for row in preview_rows:
            body.append(" | ".join(str(row[idx]).ljust(widths[idx])[:widths[idx]] for idx in range(len(columns))))
        if len(rows) > len(preview_rows):
            body.append(f"... 共 {len(rows)} 行，仅展示前 {len(preview_rows)} 行")
        return "\n".join([header, divider] + body)

    def run_db_query(self, tab_id, sql, title):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        db_path = self.get_database_path(tab_data["manifest"])
        if not db_path:
            tab_data["db_result_title"] = title
            tab_data["db_result_text"] = "当前年份数据库缺失，待入库。"
            self.render_database_panel(tab_id)
            return
        tab_data["db_result_title"] = title
        tab_data["db_result_text"] = self.execute_db_query(db_path, sql)
        self.render_database_panel(tab_id)

    def render_output_board(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        manifest = tab_data["manifest"]
        right_panel = tab_data.get("right_panel")
        right_header = tab_data.get("right_header")
        if not right_panel or not right_header:
            return

        last_rendered = tab_data.get("right_panel_rendered_view")
        if last_rendered == "output":
            tab_data["right_scroll_output"] = self.get_scroll_fraction(right_panel)
        restore_scroll = tab_data.get("right_scroll_output", 0.0)

        for widget in right_header.winfo_children():
            widget.destroy()
        for widget in right_panel.winfo_children():
            widget.destroy()

        # 右侧输出看板主要组合 segmented_button_style、option_menu_style、panel_card_style 和 surface_card_style。
        ctk.CTkLabel(right_header, text="数据文件区", text_color=TEXT_PRIMARY, font=ui_font(17, "bold")).pack(anchor="w", pady=(0, 2))
        hint_text = "先把原输出文件看板放到“数据文件”栏，后面再继续细调格式。" if manifest.get("has_output_column") else "当前先在“数据文件”栏里集中展示各步骤输出目录。"
        ctk.CTkLabel(right_header, text=hint_text, text_color=TEXT_MUTED, font=ui_font(12)).pack(anchor="w", pady=(0, 4))
        self.render_right_panel_switcher(right_header, tab_id)

        action_frame = ctk.CTkFrame(right_header, fg_color="transparent")
        action_frame.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(
            action_frame,
            text="打开工作区",
            width=WIDTH_ACTION_BUTTON,
            corner_radius=RADIUS_MD,
            command=lambda p=manifest["workspace_root"]: self.open_path(p),
            **button_primary_style(),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            action_frame,
            text="刷新看板",
            width=WIDTH_ACTION_BUTTON,
            corner_radius=RADIUS_MD,
            command=lambda tid=tab_id: self.refresh_output_board(tid),
            **button_secondary_style(),
        ).pack(side="left")
        auto_var = tab_data.get("auto_refresh_var")
        ctk.CTkSwitch(
            action_frame,
            text="自动刷新",
            variable=auto_var,
            onvalue=True,
            offvalue=False,
            command=lambda tid=tab_id, v=auto_var: self.set_auto_refresh_enabled(tid, v.get()),
        ).pack(side="right")

        filter_frame = ctk.CTkFrame(right_header, fg_color="transparent")
        filter_frame.pack(fill="x", pady=(0, 6))
        marker_filter = tab_data.get("output_marker_filter", "全部")
        marker_switch = ctk.CTkSegmentedButton(
            filter_frame,
            values=["全部", "机构", "全量"],
            command=lambda value, tid=tab_id: self.set_output_marker_filter(tid, value),
            **segmented_button_style(),
        )
        marker_switch.pack(side="left", padx=(0, 8))
        marker_switch.set(marker_filter)

        code_options = []
        seen_codes = set()
        for item in manifest.get("output_folders", [])[:200]:
            label = str(item.get("code_label") or item.get("display_label") or "").strip()
            if not label:
                continue
            key = label.lower()
            if key in seen_codes:
                continue
            seen_codes.add(key)
            code_options.append(label)

        def _code_sort_key(text):
            matched = re.match(r"\s*(\d+)", text)
            if matched:
                return (0, int(matched.group(1)))
            return (1, text.lower())

        code_options.sort(key=_code_sort_key)
        code_options = ["全部"] + code_options

        code_var = tab_data.get("output_code_filter_var")
        if not code_var:
            code_var = ctk.StringVar(value=tab_data.get("output_code_filter", ""))
            tab_data["output_code_filter_var"] = code_var
        code_choice_var = tab_data.get("output_code_choice_var")
        if not code_choice_var:
            code_choice_var = ctk.StringVar(value="全部")
            tab_data["output_code_choice_var"] = code_choice_var
        current_query = (tab_data.get("output_code_filter", "") or "").strip()
        code_choice_var.set(current_query if current_query in code_options else "全部")
        ctk.CTkOptionMenu(
            filter_frame,
            values=code_options,
            variable=code_choice_var,
            command=lambda value, tid=tab_id: (
                tab_data.__setitem__("output_code_filter", "" if value == "全部" else value),
                code_var.set("" if value == "全部" else value),
                self.render_output_board(tid),
            ),
            **option_menu_style(fg_color=ACCENT_SEGMENT_BG, button_color=ACCENT, button_hover_color=ACCENT_HOVER, text_color=TEXT_PRIMARY),
        ).pack(side="left", padx=(0, 8))
        code_entry = ctk.CTkEntry(filter_frame, textvariable=code_var, placeholder_text="代码筛选", height=HEIGHT_INPUT)
        code_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        code_entry.bind("<Return>", lambda _e, tid=tab_id: self.apply_output_code_filter(tid))
        ctk.CTkButton(
            filter_frame,
            text="筛选",
            width=WIDTH_FILTER_BUTTON,
            height=HEIGHT_BUTTON_SM,
            corner_radius=RADIUS_MD,
            command=lambda tid=tab_id: self.apply_output_code_filter(tid),
            **button_secondary_style(),
        ).pack(side="left")

        observe_folders = self.get_observe_folders(manifest)
        if observe_folders:
            observe_card = ctk.CTkFrame(right_panel, **panel_card_style())
            observe_card.pack(fill="x", padx=10, pady=(0, 10))
            ctk.CTkLabel(observe_card, text="观察文件夹", text_color=TEXT_PRIMARY, font=ui_font(15, "bold")).pack(anchor="w", padx=10, pady=(10, 6))
            for item in observe_folders:
                row = ctk.CTkFrame(observe_card, **surface_card_style())
                row.pack(fill="x", padx=10, pady=4)
                ctk.CTkLabel(row, text=item["label"], anchor="w", text_color=TEXT_PRIMARY, font=ui_font(13, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
                ctk.CTkLabel(
                    row,
                    text=item["rel_path"].replace(os.sep, " / "),
                    text_color=TEXT_MUTED,
                    anchor="w",
                    wraplength=WRAP_PANEL_MD,
                    justify="left",
                ).pack(anchor="w", padx=8)
                ctk.CTkLabel(row, text=f"目录就绪 ({item['n_items']} 项)", text_color=SUCCESS, anchor="w").pack(anchor="w", padx=8)
                ctk.CTkButton(
                    row,
                    text="打开文件夹",
                    width=WIDTH_OPEN_FOLDER_BUTTON,
                    height=HEIGHT_BUTTON_XS,
                    corner_radius=RADIUS_SM,
                    command=lambda p=item["path"]: self.open_path(p),
                    **button_primary_style(),
                ).pack(anchor="e", padx=8, pady=(4, 8))

        folder_card = ctk.CTkFrame(right_panel, **panel_card_style())
        folder_card.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        folder_title = "输出文件目录" if manifest.get("has_output_column") else "步骤输出文件夹"
        ctk.CTkLabel(folder_card, text=folder_title, text_color=TEXT_PRIMARY, font=ui_font(15, "bold")).pack(anchor="w", padx=10, pady=(10, 6))
        folder_groups = self.get_output_folder_groups(
            manifest,
            marker_filter=tab_data.get("output_marker_filter", ""),
            code_query=tab_data.get("output_code_filter", ""),
        )
        if folder_groups:
            for group_name, items in folder_groups:
                group_card = ctk.CTkFrame(folder_card, **surface_card_style(fg_color=ACCENT_GROUP_BG))
                group_card.pack(fill="x", padx=10, pady=6)
                ctk.CTkLabel(group_card, text=group_name, text_color=TEXT_PRIMARY, font=ui_font(14, "bold")).pack(anchor="w", padx=10, pady=(10, 6))
                for item in items:
                    row = ctk.CTkFrame(group_card, **surface_card_style())
                    row.pack(fill="x", padx=10, pady=(0, 8))
                    title = item.get("display_label", item["script_name"])
                    status_text = f"目录就绪 ({item['n_items']} 项)" if item["exists"] else "目录缺失"
                    status_color = SUCCESS if item["exists"] else DANGER
                    ctk.CTkLabel(row, text=title, anchor="w", text_color=TEXT_PRIMARY, font=ui_font(13, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
                    ctk.CTkLabel(row, text=status_text, text_color=status_color, anchor="w").pack(anchor="w", padx=8)
                    if item.get("note"):
                        ctk.CTkLabel(row, text=item["note"], text_color=TEXT_MUTED, anchor="w", wraplength=WRAP_PANEL_LG, justify="left").pack(anchor="w", padx=8)
                    ctk.CTkLabel(
                        row,
                        text=item["rel_dir"].replace(os.sep, " / "),
                        text_color=TEXT_MUTED,
                        anchor="w",
                        wraplength=WRAP_PANEL_LG,
                        justify="left",
                    ).pack(anchor="w", padx=8)
                    ctk.CTkButton(
                        row,
                        text="打开文件夹",
                        width=WIDTH_OPEN_FOLDER_BUTTON,
                        height=HEIGHT_BUTTON_XS,
                        corner_radius=RADIUS_SM,
                        command=lambda p=item["path"]: self.open_path(p),
                        **button_primary_style(),
                    ).pack(anchor="e", padx=8, pady=(4, 8))
        else:
            empty_text = "当前工作区未在 文件结构.xlsx 的“输出文件”列中配置输出目录。" if manifest.get("has_output_column") else "当前工作区未识别到步骤输出文件夹。"
            ctk.CTkLabel(folder_card, text=empty_text, text_color=TEXT_MUTED, wraplength=WRAP_PANEL_LG, justify="left").pack(anchor="w", padx=10, pady=(0, 10))
        tab_data["right_panel_rendered_view"] = "output"
        self.safe_after_idle(self.set_scroll_fraction, self.active_tabs_data.get(tab_id, {}).get("right_panel"), restore_scroll)
        # 渲染完成后刷新存档指纹，作为下次自动刷新的比较基准。
        self.store_right_panel_signature(tab_id)

    def render_database_panel(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        manifest = tab_data["manifest"]
        right_panel = tab_data.get("right_panel")
        right_header = tab_data.get("right_header")
        if not right_panel or not right_header:
            return

        last_rendered = tab_data.get("right_panel_rendered_view")
        if last_rendered == "database":
            tab_data["right_scroll_database"] = self.get_scroll_fraction(right_panel)
        restore_scroll = tab_data.get("right_scroll_database", 0.0)

        for widget in right_header.winfo_children():
            widget.destroy()
        for widget in right_panel.winfo_children():
            widget.destroy()

        # 数据库面板与输出面板保持同一套卡片体系，输入结果框样式来自 input_box_style。
        ctk.CTkLabel(right_header, text="数据库查询区", text_color=TEXT_PRIMARY, font=ui_font(17, "bold")).pack(anchor="w", pady=(0, 2))
        ctk.CTkLabel(right_header, text="轻量速查当前工作区 DuckDB 表和结果", text_color=TEXT_MUTED, font=ui_font(12)).pack(anchor="w", pady=(0, 4))
        self.render_right_panel_switcher(right_header, tab_id)
        header_row = ctk.CTkFrame(right_header, fg_color="transparent")
        header_row.pack(fill="x", pady=(0, 6))
        auto_var = tab_data.get("auto_refresh_var")
        ctk.CTkSwitch(
            header_row,
            text="自动刷新",
            variable=auto_var,
            onvalue=True,
            offvalue=False,
            command=lambda tid=tab_id, v=auto_var: self.set_auto_refresh_enabled(tid, v.get()),
        ).pack(side="right")

        db_path = self.get_database_path(manifest)
        db_card = ctk.CTkFrame(right_panel, **panel_card_style())
        db_card.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(db_card, text="当前数据库", text_color=TEXT_PRIMARY, font=ui_font(15, "bold")).pack(anchor="w", padx=10, pady=(10, 6))
        workspace_year = self.get_workspace_year(os.path.basename(manifest.get("workspace_root", "")))
        if db_path:
            ctk.CTkLabel(db_card, text=db_path, text_color=TEXT_MUTED, wraplength=WRAP_PANEL_MD, justify="left").pack(anchor="w", padx=10)
            btn_row = ctk.CTkFrame(db_card, fg_color="transparent")
            btn_row.pack(fill="x", padx=10, pady=(8, 10))
            ctk.CTkButton(
                btn_row,
                text="打开数据库目录",
                width=WIDTH_OPEN_INFO_BUTTON,
                corner_radius=RADIUS_SM,
                command=lambda p=os.path.dirname(db_path): self.open_path(p),
                **button_primary_style(),
            ).pack(side="left", padx=(0, 6))
            ctk.CTkButton(
                btn_row,
                text="刷新数据库",
                width=WIDTH_ACTION_BUTTON,
                corner_radius=RADIUS_SM,
                command=lambda tid=tab_id: self.render_database_panel(tid),
                **button_secondary_style(),
            ).pack(side="left")
        else:
            hint = "当前年份数据库缺失，待入库。"
            if workspace_year and workspace_year != "未识别":
                hint = f"未找到 {workspace_year} 年数据库，当前状态：缺失待入库。"
            ctk.CTkLabel(db_card, text=hint, text_color=DANGER, wraplength=WRAP_PANEL_MD, justify="left").pack(anchor="w", padx=10, pady=(0, 10))

        table_card = ctk.CTkFrame(right_panel, **panel_card_style())
        table_card.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(table_card, text="常用表速查", text_color=TEXT_PRIMARY, font=ui_font(15, "bold")).pack(anchor="w", padx=10, pady=(10, 6))
        tables, table_error = self.get_database_tables(db_path)
        if table_error:
            ctk.CTkLabel(table_card, text=f"读取表列表失败: {table_error}", text_color=DANGER, wraplength=WRAP_PANEL_MD, justify="left").pack(anchor="w", padx=10, pady=(0, 10))
        elif tables:
            for schema_name, table_name in tables:
                full_name = f"{schema_name}.{table_name}"
                row = ctk.CTkFrame(table_card, **surface_card_style())
                row.pack(fill="x", padx=10, pady=4)
                ctk.CTkLabel(row, text=full_name, text_color=TEXT_PRIMARY, font=ui_font(13, "bold")).pack(anchor="w", padx=8, pady=(8, 0))
                btn_row = ctk.CTkFrame(row, fg_color="transparent")
                btn_row.pack(anchor="e", padx=8, pady=(6, 8))
                ctk.CTkButton(
                    btn_row,
                    text="查行数",
                    width=WIDTH_QUERY_BUTTON,
                    height=HEIGHT_BUTTON_XS,
                    corner_radius=RADIUS_SM,
                    command=lambda tid=tab_id, sql=f"SELECT COUNT(*) AS row_count FROM {full_name}", title=f"{full_name} 行数": self.run_db_query(tid, sql, title),
                    **button_secondary_style(),
                ).pack(side="left", padx=(0, 6))
                ctk.CTkButton(
                    btn_row,
                    text="前20行",
                    width=WIDTH_QUERY_BUTTON,
                    height=HEIGHT_BUTTON_XS,
                    corner_radius=RADIUS_SM,
                    command=lambda tid=tab_id, sql=f"SELECT * FROM {full_name} LIMIT 20", title=f"{full_name} 前20行": self.run_db_query(tid, sql, title),
                    **button_primary_style(),
                ).pack(side="left")
        else:
            ctk.CTkLabel(table_card, text="当前数据库暂无可展示表。", text_color=TEXT_MUTED).pack(anchor="w", padx=10, pady=(0, 10))

        result_card = ctk.CTkFrame(right_panel, **panel_card_style())
        result_card.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        ctk.CTkLabel(result_card, text=tab_data.get("db_result_title", "数据库查询结果"), text_color=TEXT_PRIMARY, font=ui_font(15, "bold")).pack(anchor="w", padx=10, pady=(10, 6))
        result_box = ctk.CTkTextbox(
            result_card,
            height=HEIGHT_DB_RESULT,
            corner_radius=RADIUS_LG,
            **input_box_style(),
        )
        result_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        result_box.insert("1.0", tab_data.get("db_result_text", ""))
        result_box.configure(state="disabled")
        tab_data["right_panel_rendered_view"] = "database"
        self.safe_after_idle(self.set_scroll_fraction, self.active_tabs_data.get(tab_id, {}).get("right_panel"), restore_scroll)
        # 渲染完成后刷新存档指纹，作为下次自动刷新的比较基准。
        self.store_right_panel_signature(tab_id)

    # ---- 自动刷新防闪烁: 内容指纹 ----
    # 自动刷新每 4 秒会重扫文件系统并尝试重建说明面板与右侧面板。
    # 但绝大多数刷新里输出内容并没有变化，整块销毁重建会造成"闪现割裂感"。
    # 这里为两块面板各算一个内容指纹，指纹不变就完全跳过重建，从根上消除闪烁。
    def _stable_signature(self, parts):
        import hashlib
        text = "\x01".join("" if p is None else str(p) for p in parts)
        return hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()

    def compute_doc_panel_signature(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return None
        manifest = tab_data.get("manifest", {})
        parts = ["doc"]
        backup = self.get_fixed_backup_doc_item(manifest.get("workspace_root", ""))
        parts.append("backup|%s|%s" % (backup.get("name"), backup.get("exists")))
        for step in manifest.get("steps", []):
            parts.append("step|" + str(step.get("display_label", step.get("script_name", ""))))
            docs = step.get("docs", [])
            if not docs:
                parts.append("nodoc")
            for doc in docs:
                parts.append("d|%s|%s|%s" % (doc.get("name"), doc.get("exists"), doc.get("note")))
        return self._stable_signature(parts)

    def compute_right_panel_signature(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return None
        manifest = tab_data.get("manifest", {})
        view = tab_data.get("right_view", "output")
        if view == "database":
            # 数据库面板由用户查询驱动，自动刷新不应重建(否则会清空查询结果与滚动)。
            db_path = self.get_database_path(manifest) or ""
            return self._stable_signature(["database", db_path])
        parts = [
            "output",
            tab_data.get("output_marker_filter", ""),
            tab_data.get("output_code_filter", ""),
            manifest.get("has_output_column"),
        ]
        for obs in self.get_observe_folders(manifest):
            parts.append("obs|%s|%s|%s" % (obs.get("label"), obs.get("rel_path"), obs.get("n_items")))
        groups = self.get_output_folder_groups(
            manifest,
            marker_filter=tab_data.get("output_marker_filter", ""),
            code_query=tab_data.get("output_code_filter", ""),
        )
        for group_name, items in groups:
            parts.append("g|" + str(group_name))
            for item in items:
                parts.append("i|%s|%s|%s|%s|%s" % (
                    item.get("display_label", item.get("script_name")),
                    item.get("exists"),
                    item.get("n_items"),
                    item.get("note"),
                    item.get("rel_dir"),
                ))
        return self._stable_signature(parts)

    def store_doc_panel_signature(self, tab_id):
        # 任意路径渲染完说明面板后，刷新存档指纹，保证下次自动刷新的比较基准准确。
        tab_data = self.active_tabs_data.get(tab_id)
        if tab_data is None:
            return
        try:
            tab_data["doc_panel_signature"] = self.compute_doc_panel_signature(tab_id)
        except Exception:
            tab_data["doc_panel_signature"] = None

    def store_right_panel_signature(self, tab_id):
        # 任意路径渲染完右侧面板后，刷新存档指纹。
        tab_data = self.active_tabs_data.get(tab_id)
        if tab_data is None:
            return
        try:
            tab_data["right_panel_signature"] = self.compute_right_panel_signature(tab_id)
        except Exception:
            tab_data["right_panel_signature"] = None

    def refresh_output_board(self, tab_id):
        tab_data = self.active_tabs_data.get(tab_id)
        if not tab_data:
            return
        current_manifest = tab_data["manifest"]
        tab_data["manifest"] = self.reconcile_manifest(current_manifest)

        # 说明面板: 指纹未变则跳过重建。计算失败时按原逻辑照常重建(安全兜底)。
        try:
            doc_sig = self.compute_doc_panel_signature(tab_id)
        except Exception:
            doc_sig = None
        if doc_sig is None or doc_sig != tab_data.get("doc_panel_signature"):
            self.render_doc_panel(tab_id)

        # 右侧面板: 同理，指纹未变则跳过重建。
        try:
            right_sig = self.compute_right_panel_signature(tab_id)
        except Exception:
            right_sig = None
        if right_sig is None or right_sig != tab_data.get("right_panel_signature"):
            self.render_right_panel(tab_id)
