# -*- coding: utf-8 -*-
import os
import tkinter as tk
from tkinter import messagebox

from openpyxl import load_workbook

try:
    import customtkinter as ctk
except ModuleNotFoundError:
    ctk = None

if ctk is not None:
    try:
        from .style_config import *
    except Exception:
        from style_config import *


COMPACT_FONT_SIZE = 8
ROW_INDEX_WIDTH = 56
DRAG_HANDLE_WIDTH = 34
ROW_GAP_WIDTH = 6
ROW_NUMBER_WIDTH = ROW_INDEX_WIDTH + DRAG_HANDLE_WIDTH + ROW_GAP_WIDTH
DEFAULT_COLUMN_WIDTH = 96
HEADER_HEIGHT = 32
ROW_HEIGHT = 26
RENDER_CHUNK_SIZE = 80
WORKSPACE_COLUMN_NAME = "工作区名"

COMPACT_COLUMN_WIDTHS = {
    "工作区名": 88,
    "步骤": 54,
    "工作区文件夹": 118,
    "子文件夹1": 84,
    "子文件夹2": 84,
    "子文件夹3": 84,
    "子文件夹4": 84,
    "运行顺序": 68,
    "代码/说明": 74,
    "代码子文件夹": 96,
    "相应代码和说明文件": 178,
    "保存在资料中的名称": 168,
    "备注": 178,
    "其他": 136,
    "输出文件": 150,
    "对应代码": 136,
}

# 轻量渲染配色（全部用原生 tk 控件，避免 CTkEntry/CTkLabel 的重量级开销）。
# 仅在 customtkinter 可用时定义（此时 style_config 已 import）：
# 斑马纹两色 + 激活行底色 + 单元格细边框，焦点态由 tk 的 highlight 环负责。
if ctk is not None:
    ROW_BG_EVEN = SURFACE_BG          # 偶数行底色（白）
    ROW_BG_ODD = INPUT_BG             # 奇数行底色（极浅冷灰），形成斑马纹
    ROW_BG_ACTIVE = "#E8EEFB"         # 当前选中行底色（极浅靛蓝，呼应主色 ACCENT）
    CELL_BORDER = BORDER              # 单元格静态边框色
    CELL_BORDER_ACTIVE = ACCENT       # 当前行单元格边框 / 焦点环色
    HEADER_BG = ACCENT_SEGMENT_BG     # 表头底色
    CELL_FONT = (FONT_FAMILY, COMPACT_FONT_SIZE)
    CELL_FONT_BOLD = (FONT_FAMILY, COMPACT_FONT_SIZE, "bold")
    HEADER_FONT = (FONT_FAMILY, COMPACT_FONT_SIZE + 1, "bold")


REQUIRED_COLUMNS = [
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

# 注意：不强制套用 REQUIRED_COLUMNS 的完整结构。表头一律按文件实际列读取，
# 只保证以下三列（运行/输出阶段需要写回结果的列）一定存在，缺失时追加到表尾。
ENSURE_TAIL_COLUMNS = ["其他", "输出文件", "对应代码"]


def _clean_text(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in (".", "None") else text


class FileStructureEditorWindow(ctk.CTkToplevel if ctk is not None else object):
    def __init__(self, master, award_name, year_text, workspace_name, blueprint_xlsx_path, on_saved=None):
        if ctk is None:
            raise RuntimeError("当前环境缺少 customtkinter，无法打开文件结构编辑界面。")
        super().__init__(master)
        self.master = master
        self.award_name = str(award_name or "").strip()
        self.year_text = str(year_text or "").strip()
        self.workspace_name = str(workspace_name or "").strip()
        self.blueprint_xlsx_path = os.path.normpath(os.path.abspath(blueprint_xlsx_path))
        self.on_saved = on_saved

        self.workbook = None
        self.sheet = None
        self.header = []
        self.rows = []
        self.display_header = []
        self.display_column_indices = []
        self.visible_row_indices = []
        self.filtered_by_award = False
        self.row_widgets = []
        self.current_cell_focus = {"row_index": None, "col_index": None}
        self.drag_state = None
        self._drop_line = None  # 拖拽换序时的落点指示线（按需创建）
        self.dirty = False
        self.table_loaded = False
        self.rendering = False
        self.render_job = None
        self._after_handles = set()
        self.last_scrolled_row_index = None
        self._global_scroll_bound = False
        # O(1) 高亮追踪：只重绘"上一行 + 当前行"，不再每次遍历整表
        self._active_row_index = None
        self._drag_target_index = None

        self.status_var = ctk.StringVar(value="窗口已打开，正在准备表格...")
        self.workspace_name_var = ctk.StringVar(value=self.award_name or self.workspace_name)

        self.title(f"文件结构编辑器 - {self.award_name} {self.workspace_name}")
        self.geometry("1700x980")
        self.minsize(1280, 760)
        self.configure(fg_color=APP_BG)
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self.protocol("WM_DELETE_WINDOW", self.on_window_close)
        try:
            self._track_after(self.after(0, lambda: self.state("zoomed")))
        except Exception:
            pass

        self.build_layout()
        self._install_global_scroll_bindings()
        self.show_empty_state("正在准备表格...")
        self._bring_to_front()
        self._track_after(self.after(80, self.load_table_on_demand))
        self._track_after(self.after(1600, lambda: self.attributes("-topmost", False)))

    def _track_after(self, handle):
        if handle:
            self._after_handles.add(handle)
        return handle

    def _cancel_tracked_after_jobs(self):
        for handle in list(self._after_handles):
            try:
                self.after_cancel(handle)
            except Exception:
                pass
        self._after_handles.clear()

    def build_layout(self):
        header = ctk.CTkFrame(self, **outer_panel_style())
        header.pack(fill="x", padx=16, pady=(16, 8))
        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="x", padx=14, pady=(10, 4))
        ctk.CTkLabel(
            title_row,
            text=f"文件结构编辑器 · {self.workspace_name}",
            font=ui_font(18, "bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left")
        ctk.CTkLabel(
            title_row,
            text=self.award_name,
            font=ui_font(11, "bold"),
            text_color=TEXT_MUTED,
        ).pack(side="left", padx=(10, 0))
        workspace_editor = ctk.CTkFrame(title_row, fg_color="transparent")
        workspace_editor.pack(side="right")
        ctk.CTkLabel(
            workspace_editor,
            text="工作区名",
            font=ui_font(11, "bold"),
            text_color=TEXT_MUTED,
        ).pack(side="left", padx=(0, 8))
        self.workspace_name_entry = ctk.CTkEntry(
            workspace_editor,
            width=180,
            height=30,
            textvariable=self.workspace_name_var,
            font=ui_font(11, "bold"),
            **input_box_style(),
        )
        self.workspace_name_entry.pack(side="left")
        self.workspace_name_entry.bind("<KeyRelease>", lambda _e: self._mark_dirty("工作区名已修改，尚未保存"))
        ctk.CTkLabel(
            header,
            text=self.blueprint_xlsx_path,
            font=ui_font(10),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=14, pady=(0, 2))
        ctk.CTkLabel(
            header,
            textvariable=self.status_var,
            font=ui_font(10),
            text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=14, pady=(0, 10))

        toolbar = ctk.CTkFrame(self, **panel_card_style())
        toolbar.pack(fill="x", padx=16, pady=(0, 8))
        self.btn_help = ctk.CTkButton(toolbar, text="工作区说明", width=96, height=28, font=ui_font(11, "bold"), command=self.show_workspace_help, **button_secondary_style())
        self.btn_help.pack(side="left", padx=(10, 6), pady=8)
        self.btn_load = ctk.CTkButton(toolbar, text="重新加载表格", width=98, height=28, font=ui_font(11, "bold"), command=self.load_table_on_demand, **button_primary_style())
        self.btn_load.pack(side="left", padx=(0, 6), pady=8)
        self.btn_focus_award = ctk.CTkButton(toolbar, text="定位当前奖项", width=104, height=28, font=ui_font(11, "bold"), command=self.focus_current_award_block, **button_secondary_style())
        self.btn_focus_award.pack(side="left", padx=(0, 6), pady=8)
        self.btn_insert = ctk.CTkButton(toolbar, text="插入空行", width=86, height=28, font=ui_font(11, "bold"), command=self.insert_blank_row_below_current, **button_soft_style())
        self.btn_insert.pack(side="left", padx=(0, 6), pady=8)
        self.btn_dup = ctk.CTkButton(toolbar, text="复制行插入", width=96, height=28, font=ui_font(11, "bold"), command=self.duplicate_current_row, **button_soft_style())
        self.btn_dup.pack(side="left", padx=(0, 6), pady=8)
        self.btn_delete = ctk.CTkButton(toolbar, text="删除当前行", width=96, height=28, font=ui_font(11, "bold"), command=self.delete_current_row, **button_warning_style())
        self.btn_delete.pack(side="left", padx=(0, 6), pady=8)
        self.btn_copy_row = ctk.CTkButton(toolbar, text="复制当前行", width=96, height=28, font=ui_font(11, "bold"), command=self.copy_current_row, **button_soft_style())
        self.btn_copy_row.pack(side="left", padx=(0, 6), pady=8)
        self.btn_copy_all = ctk.CTkButton(toolbar, text="复制整表", width=86, height=28, font=ui_font(11, "bold"), command=self.copy_all_as_tsv, **button_secondary_style())
        self.btn_copy_all.pack(side="left", padx=(0, 6), pady=8)
        self.btn_open = ctk.CTkButton(toolbar, text="打开 xlsx", width=86, height=28, font=ui_font(11, "bold"), command=self.open_xlsx_file, **button_secondary_style())
        self.btn_open.pack(side="right", padx=(6, 10), pady=8)
        self.btn_save = ctk.CTkButton(toolbar, text="保存", width=78, height=28, font=ui_font(11, "bold"), command=self.save_to_workbook, **button_primary_style())
        self.btn_save.pack(side="right", padx=(0, 6), pady=8)
        self.btn_reload = ctk.CTkButton(toolbar, text="重载", width=78, height=28, font=ui_font(11, "bold"), command=self.reload_from_disk, **button_secondary_style())
        self.btn_reload.pack(side="right", padx=(0, 6), pady=8)

        self.edit_buttons = [
            self.btn_focus_award,
            self.btn_insert,
            self.btn_dup,
            self.btn_delete,
            self.btn_copy_row,
            self.btn_copy_all,
            self.btn_save,
            self.btn_reload,
        ]
        self._set_edit_controls_enabled(False)

        table_outer = ctk.CTkFrame(self, **outer_panel_style())
        table_outer.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        table_outer.grid_columnconfigure(2, weight=1)
        table_outer.grid_rowconfigure(1, weight=1)

        idx_corner = tk.Frame(table_outer, width=ROW_INDEX_WIDTH, height=HEADER_HEIGHT, bg=HEADER_BG)
        idx_corner.grid(row=0, column=0, sticky="nw", padx=(10, 4), pady=(10, 4))
        idx_corner.pack_propagate(False)
        self.header_index = tk.Label(
            idx_corner, text="#", bg=HEADER_BG, fg=TEXT_PRIMARY, font=HEADER_FONT
        )
        self.header_index.pack(fill="both", expand=True)

        handle_corner = tk.Frame(table_outer, width=DRAG_HANDLE_WIDTH, height=HEADER_HEIGHT, bg=HEADER_BG)
        handle_corner.grid(row=0, column=1, sticky="nw", padx=(0, 6), pady=(10, 4))
        handle_corner.pack_propagate(False)
        self.header_handle = tk.Label(
            handle_corner, text="", bg=HEADER_BG, fg=TEXT_MUTED, font=HEADER_FONT
        )
        self.header_handle.pack(fill="both", expand=True)

        self.header_canvas = tk.Canvas(table_outer, bg=SURFACE_BG, highlightthickness=0, height=HEADER_HEIGHT + 4)
        self.header_canvas.grid(row=0, column=2, sticky="ew", padx=(0, 10), pady=(10, 4))

        self.index_canvas = tk.Canvas(table_outer, bg=SURFACE_BG, highlightthickness=0, width=ROW_INDEX_WIDTH + 4)
        self.index_canvas.grid(row=1, column=0, sticky="ns", padx=(10, 4), pady=(0, 0))

        self.handle_canvas = tk.Canvas(table_outer, bg=SURFACE_BG, highlightthickness=0, width=DRAG_HANDLE_WIDTH + 8)
        self.handle_canvas.grid(row=1, column=1, sticky="ns", padx=(0, 6), pady=(0, 0))

        self.body_canvas = tk.Canvas(table_outer, bg=SURFACE_BG, highlightthickness=0)
        self.body_canvas.grid(row=1, column=2, sticky="nsew", padx=(0, 0), pady=(0, 0))

        self.v_scrollbar = tk.Scrollbar(table_outer, orient="vertical", command=self._yview)
        self.v_scrollbar.grid(row=1, column=3, sticky="ns", padx=(0, 10), pady=(0, 0))

        self.h_scrollbar = tk.Scrollbar(table_outer, orient="horizontal", command=self._xview)
        self.h_scrollbar.grid(row=2, column=2, sticky="ew", padx=(0, 0), pady=(4, 10))

        self.header_inner = tk.Frame(self.header_canvas, bg=SURFACE_BG)
        self.index_inner = tk.Frame(self.index_canvas, bg=SURFACE_BG)
        self.handle_inner = tk.Frame(self.handle_canvas, bg=SURFACE_BG)
        self.body_inner = tk.Frame(self.body_canvas, bg=SURFACE_BG)

        self.header_window_id = self.header_canvas.create_window((0, 0), window=self.header_inner, anchor="nw")
        self.index_window_id = self.index_canvas.create_window((0, 0), window=self.index_inner, anchor="nw")
        self.handle_window_id = self.handle_canvas.create_window((0, 0), window=self.handle_inner, anchor="nw")
        self.body_window_id = self.body_canvas.create_window((0, 0), window=self.body_inner, anchor="nw")

        self.body_canvas.configure(xscrollcommand=self._on_body_xscroll, yscrollcommand=self._on_body_yscroll)
        self.index_canvas.configure(yscrollcommand=self._on_index_yscroll)
        self.handle_canvas.configure(yscrollcommand=self._on_handle_yscroll)

        self.header_inner.bind("<Configure>", lambda _e: self._update_scrollregions())
        self.index_inner.bind("<Configure>", lambda _e: self._update_scrollregions())
        self.handle_inner.bind("<Configure>", lambda _e: self._update_scrollregions())
        self.body_inner.bind("<Configure>", lambda _e: self._update_scrollregions())
        self.index_canvas.bind("<Configure>", self._on_index_canvas_configure)
        self.handle_canvas.bind("<Configure>", self._on_handle_canvas_configure)
        self.body_canvas.bind("<Configure>", self._on_body_canvas_configure)
        # 滚轮统一由全局 bind_all 处理器分发（见 _install_global_scroll_bindings），
        # 不再对每个单元格/容器逐个绑定，既加快创建又避免重复触发。

    def _set_edit_controls_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for button in self.edit_buttons:
            try:
                button.configure(state=state)
            except Exception:
                pass

    def _bring_to_front(self):
        try:
            self.attributes("-topmost", True)
        except Exception:
            pass
        try:
            self.deiconify()
        except Exception:
            pass
        try:
            self.lift()
        except Exception:
            pass
        try:
            self.focus_force()
        except Exception:
            pass

    def _install_global_scroll_bindings(self):
        if self._global_scroll_bound:
            return
        self._global_scroll_bound = True
        try:
            self.bind_all("<MouseWheel>", self._on_global_mousewheel, add="+")
            self.bind_all("<Shift-MouseWheel>", self._on_global_shift_mousewheel, add="+")
        except Exception:
            self._global_scroll_bound = False

    def _is_widget_descendant_of(self, widget, ancestor):
        current = widget
        while current is not None:
            if current == ancestor:
                return True
            try:
                current = current.master
            except Exception:
                return False
        return False

    def _pointer_in_table_area(self):
        try:
            widget = self.winfo_containing(self.winfo_pointerx(), self.winfo_pointery())
        except Exception:
            return False
        if not widget:
            return False
        for ancestor in (
            self.body_canvas,
            self.index_canvas,
            self.handle_canvas,
            self.header_canvas,
            self.body_inner,
            self.index_inner,
            self.handle_inner,
            self.header_inner,
        ):
            if self._is_widget_descendant_of(widget, ancestor):
                return True
        return False

    def _wheel_units_from_delta(self, delta):
        try:
            delta = int(delta)
        except Exception:
            delta = 0
        if delta == 0:
            return 0
        if abs(delta) >= 120:
            units = int(round(-delta / 120))
            return units if units != 0 else (-1 if delta > 0 else 1)
        return -1 if delta > 0 else 1

    def _on_global_mousewheel(self, event):
        try:
            if not self.winfo_exists():
                return None
        except Exception:
            return None
        if not self._pointer_in_table_area():
            return None
        return self._on_mousewheel(event)

    def _on_global_shift_mousewheel(self, event):
        try:
            if not self.winfo_exists():
                return None
        except Exception:
            return None
        if not self._pointer_in_table_area():
            return None
        return self._on_shift_mousewheel(event)

    def show_workspace_help(self):
        docx_path = self.get_workspace_help_docx_path()
        if os.path.isfile(docx_path):
            os.startfile(docx_path)
            return
        messagebox.showwarning("未找到说明文件", f"未找到说明文件：\n{docx_path}", parent=self)

    def get_workspace_help_docx_path(self):
        return os.path.join(os.path.dirname(self.blueprint_xlsx_path), "工作区说明.docx")

    def load_table_on_demand(self):
        if self.rendering:
            return
        self._bring_to_front()
        if self.table_loaded and self.row_widgets:
            self.status_var.set("表格已加载，可直接编辑。")
            return
        try:
            self.load_from_workbook()
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc), parent=self)
            return
        self.table_loaded = True
        self.render_table()

    def load_from_workbook(self):
        if not os.path.isfile(self.blueprint_xlsx_path):
            raise FileNotFoundError(f"未找到文件结构文件:\n{self.blueprint_xlsx_path}")
        self.workbook = load_workbook(self.blueprint_xlsx_path)
        if "工作区" not in self.workbook.sheetnames:
            raise ValueError("文件结构.xlsx 缺少工作区 sheet。")
        self.sheet = self.workbook["工作区"]
        self._expand_merged_cells()

        # 直接读取文件实际表头的全部列，不强行套用 REQUIRED_COLUMNS。
        header = [_clean_text(cell.value) for cell in self.sheet[1]]
        while header and not header[-1]:
            header.pop()
        if not header:
            raise ValueError("工作区 sheet 的表头为空。")

        # 仅保证"其他 / 输出文件 / 对应代码"三列存在（缺失则追加到表尾），其余列原样保留。
        appended = False
        existing = set(header)
        for name in ENSURE_TAIL_COLUMNS:
            if name not in existing:
                header.append(name)
                existing.add(name)
                appended = True
        if appended:
            for col_index, name in enumerate(header, start=1):
                self.sheet.cell(row=1, column=col_index, value=name)

        self.header = header
        self.rows = []
        max_col = len(self.header)
        # 用 iter_rows 批量读取（比逐格 cell() 快很多）；不存在的尾列自动补 None，
        # 与原先逐格读取的结果完全等价。
        for row_vals in self.sheet.iter_rows(min_row=2, max_col=max_col, values_only=True):
            self.rows.append(list(row_vals))
        self._rebuild_visible_model()
        self.dirty = appended
        self.current_cell_focus = {"row_index": None, "col_index": None}
        self.last_scrolled_row_index = None
        self.status_var.set(
            f"已读取整表 {len(self.rows)} 行，当前工作区显示 {len(self.visible_row_indices)} 行"
            + ("（已补齐缺失列，保存后生效）" if appended else "")
        )
        self._set_edit_controls_enabled(True)

    def _rebuild_visible_model(self):
        workspace_col = self._column_index(WORKSPACE_COLUMN_NAME)
        self.display_column_indices = [idx for idx, name in enumerate(self.header) if idx != workspace_col]
        self.display_header = [self.header[idx] for idx in self.display_column_indices]

        matched = []
        if workspace_col >= 0:
            last_award = ""
            for row_index, row_values in enumerate(self.rows):
                raw_award = self._get_row_award(row_values)
                if raw_award:
                    last_award = raw_award
                effective_award = raw_award or last_award
                if effective_award == self.award_name:
                    matched.append(row_index)
        self.filtered_by_award = bool(matched)
        self.visible_row_indices = matched if matched else list(range(len(self.rows)))
        self.award_sparse_mode = False
        if self.filtered_by_award:
            non_empty_award_cells = 0
            for idx in self.visible_row_indices:
                if _clean_text(self._get_row_award(self.rows[idx])):
                    non_empty_award_cells += 1
                    if non_empty_award_cells > 1:
                        break
            self.award_sparse_mode = non_empty_award_cells <= 1

        workspace_value = self.award_name or self.workspace_name
        if workspace_col >= 0 and self.visible_row_indices:
            first_idx = self.visible_row_indices[0]
            if 0 <= first_idx < len(self.rows):
                workspace_value = _clean_text(self.rows[first_idx][workspace_col]) or workspace_value
        self.workspace_name_var.set(workspace_value)

    def _expand_merged_cells(self):
        ranges = list(self.sheet.merged_cells.ranges)
        for merged_range in ranges:
            min_col, min_row, max_col, max_row = merged_range.bounds
            value = self.sheet.cell(row=min_row, column=min_col).value
            self.sheet.unmerge_cells(str(merged_range))
            for row_index in range(min_row, max_row + 1):
                for col_index in range(min_col, max_col + 1):
                    self.sheet.cell(row=row_index, column=col_index, value=value)

    def show_empty_state(self, text):
        self._clear_rendered_widgets()
        placeholder = ctk.CTkLabel(
            self.body_inner,
            text=text,
            text_color=TEXT_MUTED,
            font=ui_font(12),
            justify="left",
        )
        placeholder.pack(anchor="w", padx=12, pady=12)
        self._reset_scroll_position()
        self._update_scrollregions()

    def _clear_rendered_widgets(self):
        if self.render_job:
            try:
                self.after_cancel(self.render_job)
            except Exception:
                pass
            self.render_job = None
        self.rendering = False
        self.row_widgets = []
        # 控件已全部销毁，旧的高亮索引失效，需复位
        self._active_row_index = None
        self._drag_target_index = None
        self._drop_line = None  # 落点指示线是 body_inner 子控件，已随之销毁
        for widget in self.header_inner.winfo_children():
            widget.destroy()
        for widget in self.index_inner.winfo_children():
            widget.destroy()
        for widget in self.handle_inner.winfo_children():
            widget.destroy()
        for widget in self.body_inner.winfo_children():
            widget.destroy()
        self._update_scrollregions()

    def _column_width(self, name):
        return COMPACT_COLUMN_WIDTHS.get(name, DEFAULT_COLUMN_WIDTH)

    def _build_header_row(self):
        for widget in self.header_inner.winfo_children():
            widget.destroy()
        inner = tk.Frame(self.header_inner, bg=SURFACE_BG)
        inner.pack(anchor="w")
        for name in self.display_header:
            cell = tk.Frame(inner, width=self._column_width(name), height=HEADER_HEIGHT, bg=HEADER_BG)
            cell.pack(side="left", padx=(0, 4))
            cell.pack_propagate(False)
            tk.Label(
                cell,
                text=name or "-",
                bg=HEADER_BG,
                fg=TEXT_PRIMARY,
                font=HEADER_FONT,
            ).pack(fill="both", expand=True)

    def render_table(self):
        if not self.table_loaded:
            self.show_empty_state("未加载表格，点击上方“加载表格”。")
            return
        self._clear_rendered_widgets()
        self._build_header_row()
        self._reset_scroll_position()
        self.rendering = True
        self.status_var.set(f"正在加载当前工作区表格... 0/{len(self.visible_row_indices)}")
        # 同步渲染首屏（不经过 after），避免“清空 → 重建”之间画出一帧空白造成闪烁。
        # 超出首块的剩余行（大表）才用 after 续渲染，此时表格已非空，不会再闪。
        self._render_rows_chunk(0)

    def _render_rows_chunk(self, start_index):
        self.render_job = None
        total = len(self.visible_row_indices)
        end_index = min(start_index + RENDER_CHUNK_SIZE, total)
        for visible_index in range(start_index, end_index):
            full_row_index = self.visible_row_indices[visible_index]
            values = self.rows[full_row_index] if 0 <= full_row_index < len(self.rows) else []
            self._create_row_widgets(visible_index, values)
        self._update_scrollregions()
        if end_index < total:
            self.status_var.set(f"正在加载当前工作区表格... {end_index}/{total}")
            self.render_job = self._track_after(self.after(10, lambda idx=end_index: self._render_rows_chunk(idx)))
            return
        self.rendering = False
        self._refresh_row_highlight()
        self._reset_scroll_position()
        self.status_var.set(f"已加载当前工作区 {total} 行，可稳定编辑。")
        self._bring_to_front()
        current_row = self.current_cell_focus.get("row_index")
        if current_row is not None:
            self._track_after(self.after(30, lambda idx=current_row: self.scroll_row_into_view(idx)))

    def _create_row_widgets(self, row_index, values):
        drag_enabled = row_index != 0
        base_bg = ROW_BG_EVEN if row_index % 2 == 0 else ROW_BG_ODD

        # 左侧固定：行号列
        index_row = tk.Frame(self.index_inner, bg=SURFACE_BG, width=ROW_INDEX_WIDTH, height=ROW_HEIGHT)
        index_row.pack(anchor="w", pady=(0, 2))
        index_row.pack_propagate(False)
        number_label = tk.Label(
            index_row,
            text=str(row_index + 1),
            bg=ACCENT_SEGMENT_BG,
            fg=TEXT_PRIMARY,
            font=CELL_FONT_BOLD,
        )
        number_label.pack(fill="both", expand=True)

        # 左侧固定：拖拽手柄列（第一行不可拖动）
        handle_row = tk.Frame(self.handle_inner, bg=SURFACE_BG, width=DRAG_HANDLE_WIDTH, height=ROW_HEIGHT)
        handle_row.pack(anchor="w", pady=(0, 2))
        handle_row.pack_propagate(False)
        drag_handle = tk.Label(
            handle_row,
            text="" if not drag_enabled else "| | |",
            bg=ACCENT_SEGMENT_BG if not drag_enabled else SECONDARY,
            fg=TEXT_MUTED if not drag_enabled else TEXT_INVERSE,
            font=CELL_FONT_BOLD,
            cursor="arrow" if not drag_enabled else "fleur",
        )
        drag_handle.pack(fill="both", expand=True)

        # 数据区：一行的所有单元格
        row_frame = tk.Frame(self.body_inner, bg=base_bg)
        row_frame.pack(anchor="w", pady=(0, 2))

        cells = []
        cell_wraps = []
        # 先建好 info（含 cells/cell_wraps 空列表），绑定时捕获 info 而非行号，
        # 这样增量插入/删除/换序后行号位移，绑定仍能解析到“当前”所在行。
        info = {
            "number": number_label,
            "index_row": index_row,
            "handle_row": handle_row,
            "handle": drag_handle,
            "frame": row_frame,
            "cells": cells,
            "cell_wraps": cell_wraps,
            "base_bg": base_bg,
            "handle_hover": False,
            "drag_enabled": drag_enabled,
        }

        for display_col_index, header_index in enumerate(self.display_column_indices):
            name = self.header[header_index]
            wrap = tk.Frame(row_frame, bg=base_bg, width=self._column_width(name), height=ROW_HEIGHT)
            wrap.pack(side="left", padx=(0, 4))
            wrap.pack_propagate(False)
            entry = tk.Entry(
                wrap,
                bg=base_bg,
                fg=TEXT_PRIMARY,
                font=CELL_FONT,
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground=CELL_BORDER,
                highlightcolor=CELL_BORDER_ACTIVE,
                insertbackground=TEXT_PRIMARY,
            )
            entry.pack(fill="both", expand=True)
            value = values[header_index] if header_index < len(values) else ""
            if value not in (None, ""):
                entry.insert(0, str(value))
            entry.bind("<KeyRelease>", lambda _e: self._mark_dirty("有未保存修改"))
            entry.bind("<FocusIn>", lambda _e, info=info, c=display_col_index: self._on_cell_focus(info, c))
            cells.append(entry)
            cell_wraps.append(wrap)

        # 位置无关的拖拽/悬停绑定：所有行都绑，第 0 行能否拖动由 start_drag 运行时判断。
        drag_handle.bind("<ButtonPress-1>", lambda e, info=info: self._on_handle_press(info, e), add="+")
        drag_handle.bind("<B1-Motion>", self.move_drag, add="+")
        drag_handle.bind("<ButtonRelease-1>", self.finish_drag, add="+")
        drag_handle.bind("<Enter>", lambda _e, info=info: self._on_handle_enter(info, True), add="+")
        drag_handle.bind("<Leave>", lambda _e, info=info: self._on_handle_enter(info, False), add="+")

        self.row_widgets.append(info)

    # ---- 位置无关解析 + 事件路由（增量渲染的基础）----
    def _row_index_of(self, info):
        # 按对象标识查找某行 info 当前所在的可见索引
        for i, w in enumerate(self.row_widgets):
            if w is info:
                return i
        return None

    def _on_cell_focus(self, info, col_index):
        r = self._row_index_of(info)
        if r is not None:
            self._set_current_focus(r, col_index)

    def _on_handle_press(self, info, event):
        idx = self._row_index_of(info)
        if idx is not None:
            self.start_drag(idx, event)

    def _on_handle_enter(self, info, hovering):
        idx = self._row_index_of(info)
        if idx is not None:
            self._set_handle_hover(idx, hovering)

    # ---- 增量渲染：行重排 / 插入 / 删除 / 移动（不重建整表）----
    def _reindex_rows(self):
        # 行位移后，只用 configure 刷新各行的行号、可拖动状态、斑马底色与高亮，
        # 不创建/销毁任何控件，因此无闪烁、无卡顿。
        self._active_row_index = None
        self._drag_target_index = None
        for i, info in enumerate(self.row_widgets):
            info["base_bg"] = ROW_BG_EVEN if i % 2 == 0 else ROW_BG_ODD
            drag_enabled = (i != 0)
            info["drag_enabled"] = drag_enabled
            try:
                info["number"].configure(text=str(i + 1))
                info["handle"].configure(
                    text="" if not drag_enabled else "| | |",
                    fg=TEXT_MUTED if not drag_enabled else TEXT_INVERSE,
                    cursor="arrow" if not drag_enabled else "fleur",
                )
            except Exception:
                pass
            self._paint_row_active(i, False)
            self._paint_handle(i)
        self._set_active_row(self.current_cell_focus.get("row_index"))

    def _pack_row_at(self, info, visible_index):
        # 把某行的三列控件 pack 到指定可见位置（用 before/after 重排，不重建）
        if visible_index < len(self.row_widgets) - 1:
            ref = self.row_widgets[visible_index + 1]
            for key in ("index_row", "handle_row", "frame"):
                try:
                    info[key].pack_configure(before=ref[key])
                except Exception:
                    pass
        elif len(self.row_widgets) > 1:
            ref = self.row_widgets[visible_index - 1]
            for key in ("index_row", "handle_row", "frame"):
                try:
                    info[key].pack_configure(after=ref[key])
                except Exception:
                    pass
        # 否则是唯一一行，_create_row_widgets 已 pack 在末尾，无需重排

    def _insert_row_widget(self, visible_index, values):
        # 仅新建“一行”控件并插到指定可见位置
        self._create_row_widgets(visible_index, values)  # 先 append 到末尾
        info = self.row_widgets.pop()                     # 取出刚建的那一行
        self.row_widgets.insert(visible_index, info)
        self._pack_row_at(info, visible_index)
        self._reindex_rows()
        self._update_scrollregions()

    def _delete_row_widget(self, visible_index):
        # 仅销毁“一行”控件
        if not (0 <= visible_index < len(self.row_widgets)):
            return
        info = self.row_widgets.pop(visible_index)
        for key in ("index_row", "handle_row", "frame"):
            try:
                info[key].destroy()  # 子控件（行号/手柄/单元格）随之销毁
            except Exception:
                pass
        self._reindex_rows()
        self._update_scrollregions()

    def _move_row_widget(self, from_index, to_index):
        # 拖拽换序：只把“一行”控件挪到新位置，其余行不动
        if from_index == to_index:
            return
        if not (0 <= from_index < len(self.row_widgets)):
            return
        info = self.row_widgets.pop(from_index)
        to_index = max(0, min(to_index, len(self.row_widgets)))
        self.row_widgets.insert(to_index, info)
        self._pack_row_at(info, to_index)
        self._reindex_rows()
        self._update_scrollregions()

    def _xview(self, *args):
        self.header_canvas.xview(*args)
        self.body_canvas.xview(*args)

    def _yview(self, *args):
        self.index_canvas.yview(*args)
        self.handle_canvas.yview(*args)
        self.body_canvas.yview(*args)

    def _on_body_xscroll(self, first, last):
        self.h_scrollbar.set(first, last)
        try:
            self.header_canvas.xview_moveto(first)
        except Exception:
            pass

    def _on_body_yscroll(self, first, last):
        self.v_scrollbar.set(first, last)
        try:
            self.index_canvas.yview_moveto(first)
            self.handle_canvas.yview_moveto(first)
        except Exception:
            pass

    def _on_index_yscroll(self, first, last):
        self.v_scrollbar.set(first, last)

    def _on_handle_yscroll(self, first, last):
        self.v_scrollbar.set(first, last)

    def _on_index_canvas_configure(self, _event):
        try:
            self.index_canvas.itemconfigure(self.index_window_id, width=self.index_canvas.winfo_width())
        except Exception:
            pass
        self._update_scrollregions()

    def _on_handle_canvas_configure(self, _event):
        try:
            self.handle_canvas.itemconfigure(self.handle_window_id, width=self.handle_canvas.winfo_width())
        except Exception:
            pass
        self._update_scrollregions()

    def _on_body_canvas_configure(self, _event):
        self._update_scrollregions()

    def _update_scrollregions(self):
        for canvas in (self.header_canvas, self.index_canvas, self.handle_canvas, self.body_canvas):
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
            except Exception:
                pass

    def _reset_scroll_position(self):
        try:
            self.header_canvas.xview_moveto(0.0)
            self.body_canvas.xview_moveto(0.0)
            self.index_canvas.yview_moveto(0.0)
            self.handle_canvas.yview_moveto(0.0)
            self.body_canvas.yview_moveto(0.0)
        except Exception:
            pass

    def _bind_scroll_events(self, widget):
        try:
            widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
            widget.bind("<Shift-MouseWheel>", self._on_shift_mousewheel, add="+")
        except Exception:
            pass

    def _on_mousewheel(self, event):
        if self.rendering:
            return "break"
        units = self._wheel_units_from_delta(getattr(event, "delta", 0))
        if units == 0:
            return "break"
        self.index_canvas.yview_scroll(units, "units")
        self.handle_canvas.yview_scroll(units, "units")
        self.body_canvas.yview_scroll(units, "units")
        return "break"

    def _on_shift_mousewheel(self, event):
        if self.rendering:
            return "break"
        units = self._wheel_units_from_delta(getattr(event, "delta", 0))
        if units == 0:
            return "break"
        self.header_canvas.xview_scroll(units, "units")
        self.body_canvas.xview_scroll(units, "units")
        return "break"

    def _set_current_focus(self, row_index, col_index):
        self.current_cell_focus = {"row_index": row_index, "col_index": col_index}
        self._set_active_row(row_index)

    def _mark_dirty(self, message="有未保存修改"):
        self.dirty = True
        self.status_var.set(message)

    def _collect_rows_from_widgets(self):
        if not self.table_loaded:
            return
        workspace_col = self._column_index(WORKSPACE_COLUMN_NAME)
        workspace_value = self.workspace_name_var.get().strip()
        first_full_row_index = self.visible_row_indices[0] if self.visible_row_indices else None
        for visible_index, row_widget in enumerate(self.row_widgets):
            if visible_index >= len(self.visible_row_indices):
                continue
            full_row_index = self.visible_row_indices[visible_index]
            if not (0 <= full_row_index < len(self.rows)):
                continue
            existing = list(self.rows[full_row_index])
            if len(existing) < len(self.header):
                existing.extend([""] * (len(self.header) - len(existing)))
            for cell_index, header_index in enumerate(self.display_column_indices):
                existing[header_index] = row_widget["cells"][cell_index].get()
            if workspace_col >= 0 and self.filtered_by_award:
                if self.award_sparse_mode and first_full_row_index is not None:
                    if full_row_index == first_full_row_index:
                        existing[workspace_col] = workspace_value
                    else:
                        if _clean_text(existing[workspace_col]) == "":
                            existing[workspace_col] = ""
                else:
                    existing[workspace_col] = workspace_value
            self.rows[full_row_index] = existing

    def _get_current_row_index(self):
        row_index = self.current_cell_focus.get("row_index")
        if row_index is None or not (0 <= row_index < len(self.visible_row_indices)):
            return None
        return int(row_index)

    def _column_index(self, column_name):
        try:
            return self.header.index(column_name)
        except ValueError:
            return -1

    def _make_blank_row(self, seed_award=""):
        values = ["" for _ in self.header]
        award_col = self._column_index(WORKSPACE_COLUMN_NAME)
        if award_col >= 0 and seed_award:
            values[award_col] = seed_award
        return values

    def _get_row_award(self, row_values):
        award_col = self._column_index(WORKSPACE_COLUMN_NAME)
        if award_col < 0 or award_col >= len(row_values):
            return ""
        return _clean_text(row_values[award_col])

    def _current_award_block_first_row(self):
        return 0 if self.visible_row_indices else None

    def _paint_handle(self, row_index):
        # 单独重绘某一行的拖拽手柄底色（综合可拖动 / 选中 / 悬停 / 拖拽目标四种状态）
        if not (0 <= row_index < len(self.row_widgets)):
            return
        info = self.row_widgets[row_index]
        if not info.get("drag_enabled"):
            bg = ACCENT_SEGMENT_BG
        elif row_index == self._drag_target_index or info.get("handle_hover"):
            bg = ACCENT_HOVER
        elif row_index == self._active_row_index:
            bg = ACCENT
        else:
            bg = SECONDARY
        try:
            info["handle"].configure(bg=bg)
        except Exception:
            pass

    def _paint_row_active(self, row_index, active):
        # 单独重绘某一行的行号 / 单元格底色与边框（不含手柄，手柄由 _paint_handle 负责）
        if not (0 <= row_index < len(self.row_widgets)):
            return
        info = self.row_widgets[row_index]
        body_bg = ROW_BG_ACTIVE if active else info.get("base_bg", ROW_BG_EVEN)
        border = CELL_BORDER_ACTIVE if active else CELL_BORDER
        try:
            info["number"].configure(
                bg=ACCENT if active else ACCENT_SEGMENT_BG,
                fg=TEXT_INVERSE if active else TEXT_PRIMARY,
            )
        except Exception:
            pass
        try:
            info["frame"].configure(bg=body_bg)
        except Exception:
            pass
        for wrap in info.get("cell_wraps", []):
            try:
                wrap.configure(bg=body_bg)
            except Exception:
                pass
        for cell in info.get("cells", []):
            try:
                cell.configure(bg=body_bg, highlightbackground=border)
            except Exception:
                pass

    def _set_active_row(self, new_index):
        # 只重绘"上一选中行 + 新选中行"两行，避免遍历整表
        old_index = self._active_row_index
        if old_index == new_index:
            return
        self._active_row_index = new_index
        if old_index is not None and 0 <= old_index < len(self.row_widgets):
            self._paint_row_active(old_index, False)
            self._paint_handle(old_index)
        if new_index is not None and 0 <= new_index < len(self.row_widgets):
            self._paint_row_active(new_index, True)
            self._paint_handle(new_index)

    def _refresh_row_highlight(self):
        # 兼容旧调用点：把高亮同步到 current_cell_focus 指向的行（O(1)）
        self._set_active_row(self.current_cell_focus.get("row_index"))

    def scroll_row_into_view(self, row_index):
        if row_index is None or not (0 <= row_index < len(self.row_widgets)):
            return
        frame = self.row_widgets[row_index]["frame"]
        try:
            self.body_canvas.update_idletasks()
            bbox = self.body_canvas.bbox("all")
            if not bbox:
                return
            total_height = max(1, bbox[3] - bbox[1])
            canvas_height = max(1, self.body_canvas.winfo_height())
            scrollable_height = max(1, total_height - canvas_height)
            target_y = max(0, frame.winfo_y() - 10)
            fraction = max(0.0, min(target_y / scrollable_height, 1.0))
            self.index_canvas.yview_moveto(fraction)
            self.handle_canvas.yview_moveto(fraction)
            self.body_canvas.yview_moveto(fraction)
            self.last_scrolled_row_index = row_index
        except Exception:
            pass

    def _set_handle_hover(self, row_index, hovering):
        if row_index is None or not (0 <= row_index < len(self.row_widgets)):
            return
        self.row_widgets[row_index]["handle_hover"] = bool(hovering)
        self._paint_handle(row_index)

    def start_drag(self, row_index, _event):
        if self.rendering or not self.table_loaded:
            return
        # 第 0 行是奖项锚定行，运行时拒绝拖动（位置无关绑定下由此判定）
        if row_index is None or row_index == 0 or not (0 <= row_index < len(self.row_widgets)):
            return
        self._collect_rows_from_widgets()
        self.drag_state = {"from_index": int(row_index), "hover_index": int(row_index)}
        self._highlight_drag_target(int(row_index))
        self._update_drag_hint()

    def _find_hover_index(self, event):
        y_root = int(getattr(event, "y_root", 0) or 0)
        for row_index, widget_info in enumerate(self.row_widgets):
            handle_widget = widget_info["handle"]
            if not handle_widget.winfo_exists():
                continue
            top = handle_widget.winfo_rooty()
            bottom = top + handle_widget.winfo_height()
            if top <= y_root <= bottom:
                return row_index
        return None

    def move_drag(self, event):
        if not self.drag_state:
            return
        hover_index = self._find_hover_index(event)
        if hover_index is None:
            return
        self.drag_state["hover_index"] = int(hover_index)
        self._highlight_drag_target(int(hover_index))
        self._update_drag_hint()

    def finish_drag(self, _event):
        if not self.drag_state:
            return
        from_index = self.drag_state.get("from_index")
        hover_index = self.drag_state.get("hover_index")
        self.drag_state = None
        self._highlight_drag_target(-1)
        self._hide_drop_line()
        if from_index is None or hover_index is None or from_index == hover_index:
            if from_index is not None:
                self.status_var.set("未改变行顺序。")
            return
        if not (0 <= from_index < len(self.visible_row_indices) and 0 <= hover_index < len(self.visible_row_indices)):
            return
        from_full_index = self.visible_row_indices[from_index]
        hover_full_index = self.visible_row_indices[hover_index]
        row_data = self.rows.pop(from_full_index)
        if from_full_index < hover_full_index:
            hover_full_index -= 1
        self.rows.insert(hover_full_index, row_data)
        self._rebuild_visible_model()
        # 关键：被移动行重建后的“真实可见位置”，保证控件与数据严格对齐（兼容过滤场景）。
        # 不能直接用 hover_index —— 向下拖时数据经“先删后插”修正会比悬停位置上移一格。
        try:
            target_visible = self.visible_row_indices.index(hover_full_index)
        except ValueError:
            target_visible = max(0, min(hover_index, len(self.visible_row_indices) - 1))
        self.current_cell_focus = {"row_index": target_visible, "col_index": self.current_cell_focus.get("col_index") or 0}
        self.last_scrolled_row_index = None
        self._mark_dirty(f"已将第 {from_index + 1} 行移动到第 {target_visible + 1} 行，尚未保存")
        # 增量：只把被拖动的那一行控件挪到新位置，其余行原地不动
        self._move_row_widget(from_index, target_visible)

    def _highlight_drag_target(self, hover_index):
        # 只重绘"上一拖拽目标 + 新拖拽目标"两个手柄，避免遍历整表
        target = hover_index if (hover_index is not None and hover_index >= 0) else None
        old = self._drag_target_index
        if old == target:
            return
        self._drag_target_index = target
        if old is not None and 0 <= old < len(self.row_widgets):
            self._paint_handle(old)
        if target is not None and 0 <= target < len(self.row_widgets):
            self._paint_handle(target)

    # ---- 拖拽换序的落点提示（状态栏文案 + 落点指示线）----
    def _predicted_drop_index(self, from_index, hover_index):
        # 预测松开后被移动行的最终可见位置（与 finish_drag 的“先删后插”修正一致）
        n = len(self.row_widgets)
        if n == 0:
            return 0
        hover_index = max(0, min(hover_index, n - 1))
        if from_index == hover_index:
            return from_index
        if from_index < hover_index:
            return hover_index - 1  # 向下拖：删除自身后整体上移一格
        return hover_index          # 向上拖：直接落在悬停行处

    def _show_drop_line(self, target_index):
        # 在落点处画一条贴主色的细线（落在目标行上沿；末尾则落在最后一行下沿）
        n = len(self.row_widgets)
        if n == 0:
            return
        if self._drop_line is None or not self._drop_line.winfo_exists():
            self._drop_line = tk.Frame(self.body_inner, height=2, bg=ACCENT)
        target_index = max(0, min(target_index, n))
        try:
            if target_index >= n:
                ref = self.row_widgets[-1]["frame"]
                y = ref.winfo_y() + ref.winfo_height()
            else:
                y = self.row_widgets[target_index]["frame"].winfo_y()
            self._drop_line.place(x=0, y=max(0, y - 1), relwidth=1, height=2)
            self._drop_line.lift()
        except Exception:
            pass

    def _hide_drop_line(self):
        if self._drop_line is not None:
            try:
                self._drop_line.place_forget()
            except Exception:
                pass

    def _update_drag_hint(self):
        if not self.drag_state:
            return
        from_index = self.drag_state.get("from_index")
        hover_index = self.drag_state.get("hover_index")
        if from_index is None or hover_index is None:
            return
        target = self._predicted_drop_index(from_index, hover_index)
        self._show_drop_line(target)
        if target == from_index:
            self.status_var.set(f"正在移动第 {from_index + 1} 行（松开放回原位）")
        else:
            self.status_var.set(f"正在移动第 {from_index + 1} 行  →  松开后置于第 {target + 1} 行")

    def reload_from_disk(self):
        if self.rendering:
            return
        if self.dirty:
            confirmed = messagebox.askokcancel("确认重载", "当前有未保存修改，确认丢弃并从磁盘重载吗？", parent=self)
            if not confirmed:
                return
        try:
            self.load_from_workbook()
        except Exception as exc:
            messagebox.showerror("重载失败", str(exc), parent=self)
            return
        self.render_table()

    def save_to_workbook(self):
        if not self.table_loaded:
            messagebox.showinfo("提示", "请先加载表格。", parent=self)
            return
        if self.rendering:
            messagebox.showinfo("提示", "表格仍在加载中，请稍候。", parent=self)
            return
        self._collect_rows_from_widgets()
        ws = self.sheet
        max_col = len(self.header)
        workspace_col = self._column_index(WORKSPACE_COLUMN_NAME)
        workspace_value = self.workspace_name_var.get().strip()
        if workspace_col >= 0 and self.filtered_by_award:
            for full_row_index in self.visible_row_indices:
                if 0 <= full_row_index < len(self.rows):
                    row_values = list(self.rows[full_row_index])
                    if len(row_values) < len(self.header):
                        row_values.extend([""] * (len(self.header) - len(row_values)))
                    row_values[workspace_col] = workspace_value
                    self.rows[full_row_index] = row_values
        for col_index, name in enumerate(self.header, start=1):
            ws.cell(row=1, column=col_index, value=name)
        required_total_rows = len(self.rows) + 1
        if ws.max_row > required_total_rows:
            ws.delete_rows(required_total_rows + 1, ws.max_row - required_total_rows)
        for row_offset, row_values in enumerate(self.rows, start=2):
            for col_index in range(1, max_col + 1):
                value = row_values[col_index - 1] if col_index - 1 < len(row_values) else ""
                ws.cell(row=row_offset, column=col_index, value=value if value != "" else None)
        self.workbook.save(self.blueprint_xlsx_path)
        self.dirty = False
        self.status_var.set(f"保存成功，已写回 {self.blueprint_xlsx_path}")
        if callable(self.on_saved):
            try:
                self.on_saved(self.blueprint_xlsx_path)
            except Exception:
                pass
        messagebox.showinfo("保存成功", f"文件结构已写回：\n{self.blueprint_xlsx_path}", parent=self)

    def open_xlsx_file(self):
        if os.path.isfile(self.blueprint_xlsx_path):
            os.startfile(self.blueprint_xlsx_path)

    def copy_current_row(self):
        if not self.table_loaded:
            messagebox.showinfo("提示", "请先加载表格。", parent=self)
            return
        self._collect_rows_from_widgets()
        row_index = self._get_current_row_index()
        if row_index is None:
            messagebox.showinfo("提示", "请先点击一行中的任意单元格。", parent=self)
            return
        full_row_index = self.visible_row_indices[row_index]
        row_values = self.rows[full_row_index]
        text = "\t".join("" if header_index >= len(row_values) or row_values[header_index] is None else str(row_values[header_index]) for header_index in self.display_column_indices)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set(f"已复制第 {row_index + 1} 行。")

    def copy_all_as_tsv(self):
        if not self.table_loaded:
            messagebox.showinfo("提示", "请先加载表格。", parent=self)
            return
        self._collect_rows_from_widgets()
        lines = ["\t".join(self.display_header)]
        for full_row_index in self.visible_row_indices:
            row = self.rows[full_row_index]
            lines.append("\t".join("" if header_index >= len(row) or row[header_index] is None else str(row[header_index]) for header_index in self.display_column_indices))
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self.status_var.set("已复制当前工作区表格（TSV）。")

    def insert_blank_row_below_current(self):
        if not self.table_loaded or self.rendering:
            return
        self._collect_rows_from_widgets()
        row_index = self._get_current_row_index()
        if row_index is None:
            row_index = len(self.visible_row_indices) - 1
        seed_award = self.workspace_name_var.get().strip() or self.award_name
        if row_index is None or row_index < 0 or row_index >= len(self.visible_row_indices):
            full_insert_at = len(self.rows)
            visible_insert_at = len(self.visible_row_indices)
        else:
            full_insert_at = self.visible_row_indices[row_index] + 1
            visible_insert_at = row_index + 1
        self.rows.insert(full_insert_at, self._make_blank_row(seed_award=seed_award))
        self._rebuild_visible_model()
        self.current_cell_focus = {"row_index": visible_insert_at, "col_index": 0}
        self.last_scrolled_row_index = None
        self._mark_dirty(f"已在第 {visible_insert_at + 1} 行插入空行，尚未保存")
        # 增量：只新建这一行控件，其余行仅刷新行号/斑马（不重建）
        self._insert_row_widget(visible_insert_at, self.rows[full_insert_at])
        self.scroll_row_into_view(visible_insert_at)

    def duplicate_current_row(self):
        if not self.table_loaded or self.rendering:
            return
        self._collect_rows_from_widgets()
        row_index = self._get_current_row_index()
        if row_index is None:
            messagebox.showinfo("提示", "请先点击一行中的任意单元格。", parent=self)
            return
        full_row_index = self.visible_row_indices[row_index]
        insert_at = full_row_index + 1
        self.rows.insert(insert_at, list(self.rows[full_row_index]))
        self._rebuild_visible_model()
        self.current_cell_focus = {"row_index": row_index + 1, "col_index": self.current_cell_focus.get("col_index") or 0}
        self.last_scrolled_row_index = None
        self._mark_dirty(f"已复制第 {row_index + 1} 行到第 {row_index + 2} 行，尚未保存")
        # 增量：只新建复制出的这一行控件
        self._insert_row_widget(row_index + 1, self.rows[insert_at])
        self.scroll_row_into_view(row_index + 1)

    def delete_current_row(self):
        if not self.table_loaded or self.rendering:
            return
        self._collect_rows_from_widgets()
        row_index = self._get_current_row_index()
        if row_index is None:
            messagebox.showinfo("提示", "请先点击一行中的任意单元格。", parent=self)
            return
        confirmed = messagebox.askokcancel("确认删除", f"确认删除第 {row_index + 1} 行吗？", parent=self)
        if not confirmed:
            return
        full_row_index = self.visible_row_indices[row_index]
        self.rows.pop(full_row_index)
        self._rebuild_visible_model()
        if self.visible_row_indices:
            self.current_cell_focus = {"row_index": min(row_index, len(self.visible_row_indices) - 1), "col_index": 0}
        else:
            self.current_cell_focus = {"row_index": None, "col_index": None}
        self.last_scrolled_row_index = None
        self._mark_dirty(f"已删除第 {row_index + 1} 行，尚未保存")
        # 增量：只销毁这一行控件，其余行仅刷新行号/斑马（不重建）
        self._delete_row_widget(row_index)
        new_focus = self.current_cell_focus.get("row_index")
        if new_focus is not None:
            self.scroll_row_into_view(new_focus)

    def focus_current_award_block(self):
        if not self.table_loaded:
            messagebox.showinfo("提示", "请先加载表格。", parent=self)
            return
        self._collect_rows_from_widgets()
        row_index = self._current_award_block_first_row()
        if row_index is None:
            messagebox.showinfo("提示", f"当前表中未找到“{self.award_name}”对应区块。", parent=self)
            return
        self.current_cell_focus = {"row_index": row_index, "col_index": 0}
        self.last_scrolled_row_index = None
        self._refresh_row_highlight()
        self._track_after(self.after(30, lambda idx=row_index: self.scroll_row_into_view(idx)))
        self.status_var.set(f"已定位到 {self.award_name} 区块首行（第 {row_index + 1} 行）。")

    def on_window_close(self):
        if self.dirty:
            confirmed = messagebox.askokcancel("确认关闭", "当前有未保存修改，确认直接关闭吗？", parent=self)
            if not confirmed:
                return
        self._cancel_tracked_after_jobs()
        self.destroy()
