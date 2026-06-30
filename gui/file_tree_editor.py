# -*- coding: utf-8 -*-
"""
文件结构「树状视图」编辑器。

设计要点（与原表格编辑器共享同一套数据约定，保证零格式风险）：
  1. 树只是 self.rows 的一个“索引/视图”，不重新生成整表。
  2. 编辑节点 = 原地修改对应行的单元格；未触碰的行字节不变。
  3. 保存 = 把 self.rows 写回（空值写 None），奖项名稀疏填充天然保留。
  4. FileStructureEditorWindow 的构造签名与原编辑器一致，terminal 调用契约不变。

FileTreeModel 为纯 Python（不依赖 tkinter），可独立做往返/编辑测试。
"""

import os
import copy
import re

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog
except Exception:  # 无显示环境下仍可 import FileTreeModel
    tk = None
    ttk = None
    messagebox = None
    simpledialog = None

try:
    from openpyxl import load_workbook
except Exception:
    load_workbook = None


# 标准列顺序（缺列时按此补齐尾部三列）
CANON_COLUMNS = [
    "工作区名", "步骤", "工作区文件夹", "子文件夹1", "子文件夹2", "子文件夹3", "子文件夹4",
    "运行顺序", "代码/说明", "代码子文件夹", "相应代码和说明文件", "保存在资料中的名称",
    "备注", "其他", "输出文件", "对应代码",
]
ENSURE_TAIL_COLUMNS = ["其他", "输出文件", "对应代码"]
WORKSPACE_COLUMN_NAME = "工作区名"
UNNAMED_PLACEHOLDER = "(未命名)"
BLANK_OPTION_LABEL = "(空白)"
CODE_SUBDIR_OPTIONS = [BLANK_OPTION_LABEL, "工作区设置", "更新代码", "notebook"]
OUTPUT_MARKER_OPTIONS = ["全量", "ins"]
RUN_ORDER_LIMIT = 100
STEP_LIMIT = 20


def _clean(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in (".", "None") else text


def _split_binding_tokens(value):
    text = _clean(value)
    if not text:
        return []
    parts = [p for p in re.split(r"[，,、/;；\s]+", text) if p]
    seen = set()
    out = []
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _join_binding_tokens(tokens):
    items = []
    seen = set()
    for t in (tokens or []):
        v = _clean(t)
        if not v or v in seen:
            continue
        seen.add(v)
        items.append(v)
    return ",".join(items)


def _default_extension_for_type(file_type):
    return ".docx" if file_type == "说明" else ".py"


def _iter_short_ids():
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for a in alphabet:
        for b in alphabet:
            yield a + b


def _is_step_id(value):
    s = _clean(value)
    return bool(s) and s.replace("_", "").isdigit()


# ======================================================================
#  纯数据层：行 ↔ 树
# ======================================================================
class FileTreeModel:
    """把扁平的 self.rows 索引成文件夹树；所有编辑都原地改 self.rows。"""

    def __init__(self, header, rows):
        self.header = list(header)
        self.rows = rows  # 共享引用，原地修改
        self.col = {name: i for i, name in enumerate(self.header)}
        self.tree = None
        self.index = {}
        self.rebuild()

    # ---- 单元格读写 ----
    def _ci(self, name):
        return self.col.get(name, -1)

    def cell(self, row, name):
        i = self._ci(name)
        return _clean(row[i]) if 0 <= i < len(row) else ""

    def _set_on(self, row, name, value):
        i = self._ci(name)
        if i < 0:
            return
        while len(row) <= i:
            row.append(None)
        row[i] = value if (value is not None and str(value) != "") else None

    def set_cell(self, ri, name, value):
        if 0 <= ri < len(self.rows):
            self._set_on(self.rows[ri], name, value)

    # ---- 行的路径与分类 ----
    def _segments(self, row):
        """返回该行的文件夹路径段：[顶层, 子1, 子2, ...]；空列表＝工作区根。"""
        top = self.cell(row, "工作区文件夹")
        if not top:
            return []
        segs = [top]
        for k in range(1, 5):
            s = self.cell(row, f"子文件夹{k}")
            if s:
                segs.append(s)
            else:
                break
        return segs

    def _classify(self, row):
        if self.cell(row, "相应代码和说明文件"):
            return "file"
        if self.cell(row, "输出文件"):
            return "output"
        return "folder"

    def _col_for_level(self, level):
        return "工作区文件夹" if level == 0 else f"子文件夹{level}"

    def _row_matches_path(self, row, path):
        """row 的 0..len(path)-1 层是否逐段等于 path（即 path 是该行路径的前缀）。"""
        for i, seg in enumerate(path):
            if self.cell(row, self._col_for_level(i)) != seg:
                return False
        return True

    def _top_step(self, top_name):
        for row in self.rows:
            if self.cell(row, "工作区文件夹") == top_name:
                s = self.cell(row, "步骤")
                if s:
                    return s
        return ""

    # ---- 构建树 ----
    def rebuild(self):
        root = {"kind": "root", "name": "（工作区根目录）", "path": (),
                "children": [], "files": [], "outputs": [], "folder_rows": []}
        index = {(): root}

        def get_folder(segs):
            node = root
            for d in range(len(segs)):
                key = tuple(segs[: d + 1])
                if key not in index:
                    parent = index[tuple(segs[:d])]
                    fn = {"kind": "folder", "name": segs[d], "path": key, "step": "",
                          "children": [], "files": [], "outputs": [], "folder_rows": []}
                    index[key] = fn
                    parent["children"].append(fn)
                node = index[key]
            return node

        for ri, row in enumerate(self.rows):
            segs = self._segments(row)
            kind = self._classify(row)
            node = get_folder(segs) if segs else root
            if kind == "file":
                node["files"].append(ri)
            elif kind == "output":
                node["outputs"].append(ri)
            else:
                node["folder_rows"].append(ri)

        for key, node in index.items():
            if len(key) == 1:
                node["step"] = self._top_step(key[0])

        self.tree = root
        self.index = index

    # ---- 编辑：均原地改 self.rows，再 rebuild ----
    def rename_folder(self, path, new_name):
        new_name = (new_name or "").strip()
        if not new_name or not path or tuple(path) == ():
            return False
        path = tuple(path)
        if path[-1] == new_name:
            return False
        level = len(path) - 1
        colname = self._col_for_level(level)
        for ri, row in enumerate(self.rows):
            if self._row_matches_path(row, path):
                self._set_on(row, colname, new_name)
        self.rebuild()
        return True

    def set_top_step(self, path, step):
        path = tuple(path)
        if len(path) != 1:
            return False
        step = (step or "").strip()
        for row in self.rows:
            if self.cell(row, "工作区文件夹") == path[0]:
                self._set_on(row, "步骤", step)
        self.rebuild()
        return True

    def edit_file(self, ri, fields):
        if not (0 <= ri < len(self.rows)):
            return
        for name, val in fields.items():
            self._set_on(self.rows[ri], name, val)
        self.rebuild()

    def add_file(self, folder_path, name="新文件.py", file_type="代码"):
        folder_path = tuple(folder_path)
        row = [None] * len(self.header)
        for i, seg in enumerate(folder_path):
            self._set_on(row, self._col_for_level(i), seg)
        if folder_path:
            self._set_on(row, "步骤", self._top_step(folder_path[0]))
        self._set_on(row, "相应代码和说明文件", name)
        self._set_on(row, "代码/说明", file_type)
        self.rows.append(row)
        self.rebuild()
        return len(self.rows) - 1

    def add_folder(self, parent_path, name="新文件夹"):
        parent_path = tuple(parent_path)
        full = parent_path + (name,)
        row = [None] * len(self.header)
        for i, seg in enumerate(full):
            self._set_on(row, self._col_for_level(i), seg)
        if len(full) > 1:
            self._set_on(row, "步骤", self._top_step(full[0]))
        self.rows.append(row)
        self.rebuild()
        return full

    def add_output(self, folder_path, marker="ins", code=""):
        folder_path = tuple(folder_path)
        row = [None] * len(self.header)
        for i, seg in enumerate(folder_path):
            self._set_on(row, self._col_for_level(i), seg)
        if folder_path:
            self._set_on(row, "步骤", self._top_step(folder_path[0]))
        self._set_on(row, "输出文件", marker)
        self._set_on(row, "对应代码", code)
        self.rows.append(row)
        self.rebuild()
        return len(self.rows) - 1

    def delete_file(self, ri):
        if 0 <= ri < len(self.rows):
            del self.rows[ri]
            self.rebuild()

    def delete_folder(self, path):
        path = tuple(path)
        if path == ():
            return
        self.rows[:] = [row for row in self.rows if not self._row_matches_path(row, path)]
        self.rebuild()

    # ---- 便捷读取（供 UI 表单用）----
    def file_fields(self, ri):
        row = self.rows[ri]
        return {name: self.cell(row, name) for name in (
            "相应代码和说明文件", "代码/说明", "代码子文件夹", "保存在资料中的名称",
            "运行顺序", "其他", "备注",
        )}

    def output_fields(self, ri):
        row = self.rows[ri]
        return {"输出文件": self.cell(row, "输出文件"), "对应代码": self.cell(row, "对应代码")}


# ======================================================================
#  读 / 写 工作簿（与原编辑器同约定）
# ======================================================================
def load_blueprint(path):
    """读取 文件结构.xlsx -> (workbook, sheet, header, rows)。缺尾部三列则补齐。"""
    wb = load_workbook(path)
    if "工作区" not in wb.sheetnames:
        raise ValueError("缺少『工作区』sheet。")
    ws = wb["工作区"]
    header = [_clean(c.value) for c in ws[1]]
    while header and not header[-1]:
        header.pop()
    if not header:
        raise ValueError("表头为空。")
    appended = False
    existing = set(header)
    for name in ENSURE_TAIL_COLUMNS:
        if name not in existing:
            header.append(name)
            existing.add(name)
            appended = True
    if appended:
        for ci, name in enumerate(header, start=1):
            ws.cell(row=1, column=ci, value=name)
    max_col = len(header)
    rows = [list(r) for r in ws.iter_rows(min_row=2, max_col=max_col, values_only=True)]
    return wb, ws, header, rows


def save_blueprint(wb, ws, header, rows, path):
    """把 header + rows 写回（空值写 None），奖项名稀疏填充天然保留。"""
    max_col = len(header)
    for ci, name in enumerate(header, start=1):
        ws.cell(row=1, column=ci, value=name)
    required_total = len(rows) + 1
    if ws.max_row > required_total:
        ws.delete_rows(required_total + 1, ws.max_row - required_total)
    for off, row in enumerate(rows, start=2):
        for ci in range(1, max_col + 1):
            v = row[ci - 1] if ci - 1 < len(row) else ""
            ws.cell(row=off, column=ci, value=v if (v is not None and str(v) != "") else None)
    wb.save(path)


# ======================================================================
#  UI：ttk 树 + 右侧详情表单
# ======================================================================
# 配色（Ink & Azure，与主程序一致）
PALETTE = dict(
    app_bg="#ECF1F8", surface="#FFFFFF", input_bg="#F6F8FC", panel="#FBFCFE",
    accent="#3556D4", accent_hover="#2A45B5", accent_soft="#E6EAF2", accent_tint="#E8EEFB",
    secondary="#465062", text="#1A2333", muted="#66728A", border="#D3DBE6",
    code="#3556D4", doc="#7A6A4F", output="#1E8E7E", danger="#C0492F",
)
FONT = "Microsoft YaHei UI"


class FileStructureEditorWindow(tk.Toplevel if tk else object):
    """树状视图文件结构编辑器。构造签名与原表格编辑器保持一致。"""

    def __init__(self, master, award_name, year_text, workspace_name,
                 blueprint_xlsx_path, on_saved=None):
        super().__init__(master)
        self.award_name = award_name
        self.year_text = year_text
        self.workspace_name = workspace_name
        self.blueprint_xlsx_path = blueprint_xlsx_path
        self.on_saved = on_saved
        self.dirty = False

        self.workbook = self.sheet = None
        self.header = []
        self.rows = []
        self.model = None
        self._item_meta = {}       # treeview item id -> ("folder"/file/output/root, key)
        self._selected = None
        # 撤销 / 重做 / 回到初始
        self._undo_stack = []
        self._redo_stack = []
        self._initial_snapshot = None
        # 展开状态（按文件夹路径记忆，避免每次重建都全展开）
        self._open_paths = None
        self._first_populate = True
        self._award_label = None
        self._undo_btn = None
        self._redo_btn = None
        self._doc_to_codes = {}
        self._detail_state = {}

        self.title(f"文件结构（树状视图） · {workspace_name or award_name}")
        self.geometry("1080x680")
        self.configure(bg=PALETTE["app_bg"])
        self.minsize(820, 520)

        self._build_style()
        self._build_layout()
        self._load()

    # ---------- 样式 ----------
    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("FS.Treeview",
                        background=PALETTE["surface"], fieldbackground=PALETTE["surface"],
                        foreground=PALETTE["text"], rowheight=28, borderwidth=0,
                        font=(FONT, 10))
        style.configure("FS.Treeview.Heading",
                        background=PALETTE["accent_soft"], foreground=PALETTE["secondary"],
                        font=(FONT, 9, "bold"), relief="flat", borderwidth=0)
        style.map("FS.Treeview",
                  background=[("selected", PALETTE["accent_tint"])],
                  foreground=[("selected", PALETTE["text"])])
        style.layout("FS.Treeview", [("FS.Treeview.treearea", {"sticky": "nswe"})])

    # ---------- 布局 ----------
    def _build_layout(self):
        # 顶栏
        top = tk.Frame(self, bg=PALETTE["surface"], height=52)
        top.pack(side="top", fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="文件结构编辑器", bg=PALETTE["surface"], fg=PALETTE["text"],
                 font=(FONT, 13, "bold")).pack(side="left", padx=(16, 8))
        tk.Label(top, text="树状视图", bg=PALETTE["accent_tint"], fg=PALETTE["accent"],
                 font=(FONT, 9, "bold"), padx=8, pady=2).pack(side="left", pady=14)
        self._award_label = tk.Label(top, text=f"工作区：{self.award_name}", bg=PALETTE["accent_soft"],
                 fg=PALETTE["text"], font=(FONT, 10, "bold"), padx=10, pady=4)
        self._award_label.pack(side="left", padx=10, pady=12)
        self._tk_button(top, "编辑工作区名", self.edit_award_name, small=True).pack(side="left", padx=6, pady=12)

        self._tk_button(top, "保存并生成", self.save, primary=True).pack(side="right", padx=(6, 14), pady=10)
        self._tk_button(top, "打开xlsx", self.open_xlsx_file).pack(side="right", padx=6, pady=10)
        self._tk_button(top, "表格视图", self.open_spreadsheet_view).pack(side="right", padx=6, pady=10)
        # 撤销 / 重做 / 回到初始
        self._tk_button(top, "回到初始", self.reset_all, danger=True).pack(side="right", padx=6, pady=10)
        self._redo_btn = self._tk_button(top, "重做", self.redo)
        self._redo_btn.pack(side="right", padx=4, pady=10)
        self._undo_btn = self._tk_button(top, "撤销", self.undo)
        self._undo_btn.pack(side="right", padx=4, pady=10)

        # 提示条
        banner = tk.Frame(self, bg=PALETTE["accent_tint"])
        banner.pack(side="top", fill="x")
        tk.Label(banner, text="你只编辑文件夹树与文件详情；保存时系统自动生成标准 16 列稀疏表，无需手改表格。",
                 bg=PALETTE["accent_tint"], fg="#2c3a63", font=(FONT, 9), anchor="w",
                 padx=16, pady=6).pack(fill="x")

        # 主体：左树 右表单
        body = tk.Frame(self, bg=PALETTE["app_bg"])
        body.pack(side="top", fill="both", expand=True)

        # 左
        left = tk.Frame(body, bg=PALETTE["panel"], width=520)
        left.pack(side="left", fill="both")
        left.pack_propagate(False)
        ltool = tk.Frame(left, bg=PALETTE["panel"])
        ltool.pack(side="top", fill="x", padx=8, pady=8)
        tk.Label(ltool, text="文件夹树", bg=PALETTE["panel"], fg=PALETTE["secondary"],
                 font=(FONT, 10, "bold")).pack(side="left")
        self._tk_button(ltool, "删除", self.on_delete, small=True, danger=True).pack(side="right")
        self._tk_button(ltool, "＋ 文件", self.on_add_file, small=True).pack(side="right", padx=6)
        self._tk_button(ltool, "＋ 文件夹", self.on_add_folder, small=True).pack(side="right")
        self._tk_button(ltool, "＋ 输出文件夹", self.on_add_output_folder, small=True).pack(side="right", padx=6)
        self._tk_button(ltool, "＋ 步骤文件夹", self.on_add_step_folder, small=True).pack(side="right", padx=6)

        treewrap = tk.Frame(left, bg=PALETTE["surface"], highlightthickness=1,
                            highlightbackground=PALETTE["border"])
        treewrap.pack(side="top", fill="both", expand=True, padx=8, pady=(0, 8))
        self.tree = ttk.Treeview(treewrap, style="FS.Treeview", show="tree headings",
                                 columns=("type", "order", "group"), selectmode="browse")
        self.tree.heading("#0", text="名称")
        self.tree.heading("type", text="类型")
        self.tree.heading("order", text="序")
        self.tree.heading("group", text="组")
        self.tree.column("#0", width=320, minwidth=220, stretch=True)
        self.tree.column("type", width=64, anchor="center", stretch=False)
        self.tree.column("order", width=40, anchor="center", stretch=False)
        self.tree.column("group", width=40, anchor="center", stretch=False)
        vsb = ttk.Scrollbar(treewrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("folder", foreground=PALETTE["text"])
        self.tree.tag_configure("file_code", foreground=PALETTE["code"])
        self.tree.tag_configure("file_doc", foreground=PALETTE["doc"])
        self.tree.tag_configure("output", foreground=PALETTE["output"])
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<BackSpace>", lambda e: self.on_delete())

        # 右
        right = tk.Frame(body, bg=PALETTE["surface"])
        right.pack(side="left", fill="both", expand=True)
        rhead = tk.Frame(right, bg=PALETTE["surface"])
        rhead.pack(side="top", fill="x")
        self.right_title = tk.Label(rhead, text="文件详情", bg=PALETTE["surface"],
                                    fg=PALETTE["secondary"], font=(FONT, 10, "bold"), anchor="w",
                                    padx=18, pady=10)
        self.right_title.pack(fill="x")
        self.detail = tk.Frame(right, bg=PALETTE["surface"])
        self.detail.pack(side="top", fill="both", expand=True)

        # 底部状态
        self.status_var = tk.StringVar(value="")
        status = tk.Label(self, textvariable=self.status_var, bg=PALETTE["panel"],
                          fg=PALETTE["muted"], font=(FONT, 9), anchor="w", padx=16, pady=5)
        status.pack(side="bottom", fill="x")

        # 快捷键：撤销 / 重做
        self.bind("<Control-z>", lambda e: self.undo())
        self.bind("<Control-Z>", lambda e: self.undo())
        self.bind("<Control-y>", lambda e: self.redo())
        self.bind("<Control-Shift-Z>", lambda e: self.redo())

    def _tk_button(self, parent, text, cmd, primary=False, small=False, danger=False):
        bg = PALETTE["accent"] if primary else PALETTE["surface"]
        fg = "#FFFFFF" if primary else (PALETTE["danger"] if danger else PALETTE["secondary"])
        b = tk.Button(parent, text=text, command=cmd, font=(FONT, 9 if small else 10, "bold"),
                      bg=bg, fg=fg, relief="flat", bd=0, cursor="hand2",
                      activebackground=PALETTE["accent_hover"] if primary else PALETTE["input_bg"],
                      activeforeground=fg, padx=10 if small else 14, pady=4 if small else 7,
                      highlightthickness=1, highlightbackground=PALETTE["border"])
        return b

    # ---------- 加载 ----------
    def _detect_award(self):
        """读取首个非空『工作区名』作为正在编辑的工作区名（不写死私募）。"""
        ci = self.header.index(WORKSPACE_COLUMN_NAME) if WORKSPACE_COLUMN_NAME in self.header else -1
        if ci >= 0:
            for row in self.rows:
                a = _clean(row[ci]) if ci < len(row) else ""
                if a:
                    return a
        return self.award_name

    def _load(self):
        try:
            self.workbook, self.sheet, self.header, self.rows = load_blueprint(self.blueprint_xlsx_path)
        except Exception as exc:
            if messagebox:
                messagebox.showerror("加载失败", str(exc), parent=self)
            return
        self.model = FileTreeModel(self.header, self.rows)
        self._doc_to_codes = self._build_doc_to_codes_from_rows()
        # 用文件里真实的工作区名（首行锚定值）刷新显示
        detected = self._detect_award()
        if detected:
            self.award_name = detected
            if self._award_label is not None:
                self._award_label.config(text=f"工作区：{detected}")
            self.title(f"文件结构（树状视图） · {detected}")
        # 初始快照（供「回到初始」）
        self._initial_snapshot = copy.deepcopy(self.rows)
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.populate_tree()
        self._update_undo_buttons()
        self.status_var.set(f"已加载 {len(self.rows)} 行 · 工作区：{self.award_name}")

    def _effective_step_for_row(self, ri):
        if not (0 <= ri < len(self.rows)):
            return ""
        row = self.rows[ri]
        step_value = self.model.cell(row, "步骤")
        if step_value:
            return step_value
        segs = self.model._segments(row)
        if segs:
            return self.model._top_step(segs[0])
        return ""

    def _codes_in_same_step(self, ri):
        step_value = _clean(self._effective_step_for_row(ri))
        items = []
        for cri, row in enumerate(self.rows):
            if not self.model.cell(row, "相应代码和说明文件"):
                continue
            if self.model.cell(row, "代码/说明") != "代码":
                continue
            if _clean(self._effective_step_for_row(cri)) != step_value:
                continue
            name = self.model.cell(row, "相应代码和说明文件") or f"row_{cri}"
            items.append((cri, name))
        items.sort(key=lambda it: it[1])
        return items

    def _docs_in_same_step(self, ri):
        step_value = _clean(self._effective_step_for_row(ri))
        items = []
        for dri, row in enumerate(self.rows):
            if not self.model.cell(row, "相应代码和说明文件"):
                continue
            if self.model.cell(row, "代码/说明") != "说明":
                continue
            if _clean(self._effective_step_for_row(dri)) != step_value:
                continue
            name = self.model.cell(row, "相应代码和说明文件") or f"row_{dri}"
            items.append((dri, name))
        items.sort(key=lambda it: it[1])
        return items

    def _format_code_choice(self, ri):
        if not (0 <= ri < len(self.rows)):
            return ""
        row = self.rows[ri]
        if self.model.cell(row, "代码/说明") != "代码":
            return ""
        name = self.model.cell(row, "相应代码和说明文件")
        if not name:
            return ""
        step_value = _clean(self._effective_step_for_row(ri)) or "unknown"
        order_value = _clean(self.model.cell(row, "运行顺序"))
        file_stem = os.path.splitext(_clean(name))[0] or "unnamed"
        if order_value:
            return f"{order_value}_step_{step_value}_{file_stem}"
        return file_stem

    def _code_choices_in_same_step(self, ri):
        step_value = _clean(self._effective_step_for_row(ri))
        items = []
        seen = set()
        for cri, row in enumerate(self.rows):
            if self.model.cell(row, "代码/说明") != "代码":
                continue
            if not self.model.cell(row, "相应代码和说明文件"):
                continue
            if _clean(self._effective_step_for_row(cri)) != step_value:
                continue
            label = self._format_code_choice(cri)
            if not label or label in seen:
                continue
            seen.add(label)
            items.append(label)
        items.sort()
        return items

    def _build_doc_to_codes_from_rows(self):
        token_to_doc = {}
        doc_to_codes = {}
        for ri, row in enumerate(self.rows):
            if not self.model.cell(row, "相应代码和说明文件"):
                continue
            if self.model.cell(row, "代码/说明") != "说明":
                continue
            tokens = _split_binding_tokens(self.model.cell(row, "其他"))
            if not tokens:
                continue
            doc_to_codes.setdefault(ri, set())
            for token in tokens:
                token_to_doc.setdefault(token, []).append(ri)
        for ri, row in enumerate(self.rows):
            if not self.model.cell(row, "相应代码和说明文件"):
                continue
            if self.model.cell(row, "代码/说明") != "代码":
                continue
            for token in _split_binding_tokens(self.model.cell(row, "其他")):
                for doc_ri in token_to_doc.get(token, []):
                    doc_to_codes.setdefault(doc_ri, set()).add(ri)
        return doc_to_codes

    def _recompute_and_write_binding_tokens(self):
        doc_ids = {}
        id_iter = _iter_short_ids()
        for ri, row in enumerate(self.rows):
            if not self.model.cell(row, "相应代码和说明文件"):
                continue
            if self.model.cell(row, "代码/说明") != "说明":
                continue
            code_set = set(self._doc_to_codes.get(ri, set()))
            allowed = {cri for cri, _ in self._codes_in_same_step(ri)}
            code_set = {c for c in code_set if c in allowed}
            if not code_set:
                doc_ids[ri] = ""
                continue
            doc_ids[ri] = next(id_iter)
        code_to_doc_ids = {}
        for doc_ri, token in doc_ids.items():
            if not token:
                continue
            for code_ri in self._doc_to_codes.get(doc_ri, set()):
                code_to_doc_ids.setdefault(code_ri, set()).add(token)
        for ri, row in enumerate(self.rows):
            if not self.model.cell(row, "相应代码和说明文件"):
                continue
            typ = self.model.cell(row, "代码/说明")
            if typ == "说明":
                self.model._set_on(row, "其他", doc_ids.get(ri, "") or None)
            elif typ == "代码":
                tokens = sorted(code_to_doc_ids.get(ri, set()))
                self.model._set_on(row, "其他", _join_binding_tokens(tokens) or None)

    def _find_saved_name_conflict(self, new_saved_name, exclude_ri=None):
        target = _clean(new_saved_name)
        if not target:
            return None
        target_key = target.lower()
        for ri, row in enumerate(self.rows):
            if exclude_ri is not None and ri == exclude_ri:
                continue
            existing = self.model.cell(row, "保存在资料中的名称")
            if not existing:
                continue
            if existing.lower() != target_key:
                continue
            deployed = self.model.cell(row, "相应代码和说明文件")
            segs = self.model._segments(row)
            rel_dir = "/".join([s for s in segs if s])
            label = deployed or existing
            return {
                "ri": ri,
                "sheet_row": ri + 2,
                "existing": existing,
                "label": label,
                "rel_dir": rel_dir,
            }
        return None

    def edit_award_name(self):
        if simpledialog is None:
            return
        current = self._detect_award() or self.award_name
        new_name = simpledialog.askstring("编辑工作区名", "请输入工作区名（写入『工作区名』列的锚定值）：",
                                          initialvalue=current, parent=self)
        if new_name is None:
            return
        new_name = (new_name or "").strip()
        if not new_name or new_name == current:
            return
        if WORKSPACE_COLUMN_NAME not in self.header:
            if messagebox:
                messagebox.showerror("无法编辑", f"缺少列：{WORKSPACE_COLUMN_NAME}", parent=self)
            return
        ci = self.header.index(WORKSPACE_COLUMN_NAME)
        self._push_undo()
        updated = False
        for row in self.rows:
            while len(row) <= ci:
                row.append(None)
            if _clean(row[ci]):
                row[ci] = new_name
                updated = True
                break
        if not updated:
            if not self.rows:
                self.rows.append([None] * len(self.header))
            while len(self.rows[0]) <= ci:
                self.rows[0].append(None)
            self.rows[0][ci] = new_name
        self.award_name = new_name
        if self._award_label is not None:
            self._award_label.config(text=f"工作区：{new_name}")
        self.title(f"文件结构（树状视图） · {new_name}")
        if self.model:
            try:
                self.model.rebuild()
            except Exception:
                pass
        self.populate_tree()
        self._mark_dirty("已更新工作区名（未保存）")
        self._update_undo_buttons()

    # ---------- 渲染树 ----------
    def _capture_open(self):
        """记录当前所有文件夹的展开状态（按路径）。"""
        opened = set()
        for iid, meta in self._item_meta.items():
            if meta[0] == "folder":
                try:
                    if self.tree.item(iid, "open"):
                        opened.add(tuple(meta[1]))
                except Exception:
                    pass
        return opened

    def populate_tree(self):
        # 重建前先记住展开状态，避免每次都全部展开
        if not self._first_populate:
            self._open_paths = self._capture_open()
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self._item_meta = {}
        root = self.model.tree
        # 根目录文件直接挂顶层
        self._insert_files(self.model.tree, "")
        for child in root["children"]:
            self._insert_folder(child, "")
        self._insert_outputs(root, "")
        self._first_populate = False

    def _folder_open_state(self, path):
        # 首次加载：仅展开顶层；之后：沿用用户记忆的展开状态
        if self._open_paths is None:
            return len(path) <= 1
        return tuple(path) in self._open_paths

    def _insert_folder(self, node, parent_iid):
        step = node.get("step", "")
        label = node["name"]
        if step:
            label = f"step_{step} · {node['name']}"
        iid = self.tree.insert(parent_iid, "end", text="📁 " + label,
                               values=("文件夹", "", ""),
                               open=self._folder_open_state(node["path"]), tags=("folder",))
        self._item_meta[iid] = ("folder", node["path"])
        for child in node["children"]:
            self._insert_folder(child, iid)
        self._insert_outputs(node, iid)
        self._insert_files(node, iid)

    def _insert_files(self, node, parent_iid):
        for ri in node["files"]:
            row = self.rows[ri]
            name = self.model.cell(row, "相应代码和说明文件")
            typ = self.model.cell(row, "代码/说明") or "代码"
            order = self.model.cell(row, "运行顺序")
            group = self.model.cell(row, "其他")
            icon = "🟦" if typ == "代码" else "📄"
            tag = "file_code" if typ == "代码" else "file_doc"
            iid = self.tree.insert(parent_iid, "end", text=f"{icon} {name}",
                                   values=(typ, order, group), tags=(tag,))
            self._item_meta[iid] = ("file", ri)

    def _insert_outputs(self, node, parent_iid):
        for ri in node["outputs"]:
            row = self.rows[ri]
            marker = self.model.cell(row, "输出文件")
            code = self.model.cell(row, "对应代码")
            label = f"输出文件 · {marker}" + (f" → {code}" if code else "")
            iid = self.tree.insert(parent_iid, "end", text="📤 " + label,
                                   values=("输出", "", ""), tags=("output",))
            self._item_meta[iid] = ("output", ri)

    # ---------- 定位 / 揭示新建项 ----------
    def _find_iid(self, meta):
        kind, key = meta
        for iid, m in self._item_meta.items():
            if m[0] != kind:
                continue
            mk = m[1]
            if isinstance(key, (tuple, list)) or isinstance(mk, (tuple, list)):
                if tuple(mk) == tuple(key):
                    return iid
            elif mk == key:
                return iid
        return None

    def _reveal(self, meta):
        """选中并滚动到指定节点（自动展开其祖先）。"""
        iid = self._find_iid(meta)
        if not iid:
            return
        try:
            self.tree.see(iid)            # 自动展开祖先并滚动到可见
            self.tree.selection_set(iid)
            self.tree.focus(iid)
        except Exception:
            pass

    # ---------- 撤销 / 重做 / 回到初始 ----------
    def _push_undo(self):
        self._undo_stack.append(copy.deepcopy(self.rows))
        if len(self._undo_stack) > 100:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _restore(self, snapshot):
        self.rows[:] = copy.deepcopy(snapshot)   # 原地替换内容（model 共享同一对象）
        self.model.rebuild()
        self._selected = None
        self.populate_tree()
        self._update_undo_buttons()

    def undo(self):
        if not self._undo_stack:
            self.status_var.set("没有可撤销的操作。")
            return
        self._redo_stack.append(copy.deepcopy(self.rows))
        snap = self._undo_stack.pop()
        self._restore(snap)
        self.dirty = True
        self.status_var.set("已撤销。")

    def redo(self):
        if not self._redo_stack:
            self.status_var.set("没有可重做的操作。")
            return
        self._undo_stack.append(copy.deepcopy(self.rows))
        snap = self._redo_stack.pop()
        self._restore(snap)
        self.dirty = True
        self.status_var.set("已重做。")

    def reset_all(self):
        if self._initial_snapshot is None:
            return
        if messagebox and not messagebox.askokcancel(
                "回到初始", "放弃所有改动，回到本次打开时的状态？", parent=self):
            return
        self._push_undo()  # 让“回到初始”本身也可撤销
        self._restore(self._initial_snapshot)
        self.dirty = True
        self.status_var.set("已回到初始状态（仍可撤销）。")

    def _update_undo_buttons(self):
        try:
            if self._undo_btn:
                self._undo_btn.config(state="normal" if self._undo_stack else "disabled")
            if self._redo_btn:
                self._redo_btn.config(state="normal" if self._redo_stack else "disabled")
        except Exception:
            pass

    # ---------- 选择 -> 表单 ----------
    def on_select(self, _e=None):
        sel = self.tree.selection()
        if not sel:
            return
        meta = self._item_meta.get(sel[0])
        if not meta:
            return
        self._selected = meta
        kind, key = meta
        self._detail_state = {}
        for w in self.detail.winfo_children():
            w.destroy()
        if kind == "file":
            self._form_file(key)
        elif kind == "folder":
            self._form_folder(key)
        elif kind == "output":
            self._form_output(key)
        else:
            self.right_title.config(text="工作区根目录")

    # ---- 表单构件 ----
    def _field(self, parent, label, value, hint="", width=None, readonly=False, state_key=None):
        wrap = tk.Frame(parent, bg=PALETTE["surface"])
        wrap.pack(fill="x", pady=(0, 12))
        tk.Label(wrap, text=label, bg=PALETTE["surface"], fg=PALETTE["secondary"],
                 font=(FONT, 9, "bold"), anchor="w").pack(fill="x")
        var = tk.StringVar(value=value or "")
        ent = tk.Entry(wrap, textvariable=var, font=(FONT, 10), relief="flat", bd=0,
                       bg=PALETTE["input_bg"] if not readonly else PALETTE["accent_soft"],
                       fg=PALETTE["text"], highlightthickness=1,
                       highlightbackground=PALETTE["border"], highlightcolor=PALETTE["accent"],
                       insertbackground=PALETTE["text"], state="readonly" if readonly else "normal")
        ent.pack(fill="x", ipady=5, pady=(4, 0))
        if width:
            ent.config(width=width)
        if hint:
            tk.Label(wrap, text=hint, bg=PALETTE["surface"], fg=PALETTE["muted"],
                     font=(FONT, 8), anchor="w").pack(fill="x", pady=(3, 0))
        if state_key:
            self._detail_state[state_key] = var
        return var

    def _normalize_extension(self, text, file_type="代码"):
        text = _clean(text)
        if not text:
            return _default_extension_for_type(file_type)
        if not text.startswith("."):
            text = "." + text
        return text

    def _split_file_name_for_form(self, name, file_type):
        raw_name = _clean(name)
        base_name, ext_name = os.path.splitext(raw_name)
        if not ext_name:
            base_name = raw_name
            ext_name = _default_extension_for_type(file_type)
        if base_name == UNNAMED_PLACEHOLDER:
            base_name = ""
        return base_name, self._normalize_extension(ext_name, file_type)

    def _normalize_code_subdir(self, value):
        text = _clean(value)
        if text in ("", "."):
            return BLANK_OPTION_LABEL
        return text

    def _save_code_subdir(self, value):
        text = _clean(value)
        if text == BLANK_OPTION_LABEL:
            return ""
        return text

    def _placeholder_field(self, parent, label, value, placeholder, hint="", state_key=None):
        wrap = tk.Frame(parent, bg=PALETTE["surface"])
        wrap.pack(fill="x", pady=(0, 12))
        tk.Label(wrap, text=label, bg=PALETTE["surface"], fg=PALETTE["secondary"],
                 font=(FONT, 9, "bold"), anchor="w").pack(fill="x")
        text_value = _clean(value)
        state = {"placeholder": not bool(text_value)}
        var = tk.StringVar(value=text_value or placeholder)
        ent = tk.Entry(
            wrap,
            textvariable=var,
            font=(FONT, 10),
            relief="flat",
            bd=0,
            bg=PALETTE["input_bg"],
            fg=PALETTE["muted"] if state["placeholder"] else PALETTE["text"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["accent"],
            insertbackground=PALETTE["text"],
        )
        ent.pack(fill="x", ipady=5, pady=(4, 0))

        def _render():
            ent.configure(fg=PALETTE["muted"] if state["placeholder"] else PALETTE["text"])

        def _focus_in(_event):
            if state["placeholder"]:
                state["placeholder"] = False
                var.set("")
                _render()

        def _focus_out(_event):
            if _clean(var.get()):
                state["placeholder"] = False
            else:
                state["placeholder"] = True
                var.set(placeholder)
            _render()

        ent.bind("<FocusIn>", _focus_in, add="+")
        ent.bind("<FocusOut>", _focus_out, add="+")
        if hint:
            tk.Label(wrap, text=hint, bg=PALETTE["surface"], fg=PALETTE["muted"],
                     font=(FONT, 8), anchor="w").pack(fill="x", pady=(3, 0))

        payload = {
            "var": var,
            "entry": ent,
            "get": lambda: "" if state["placeholder"] else _clean(var.get()),
            "is_placeholder": lambda: state["placeholder"],
        }
        if state_key:
            self._detail_state[state_key] = payload
        return payload

    def _choice_field(self, parent, label, values, current="", hint="", state_key=None):
        wrap = tk.Frame(parent, bg=PALETTE["surface"])
        wrap.pack(fill="x", pady=(0, 12))
        tk.Label(wrap, text=label, bg=PALETTE["surface"], fg=PALETTE["secondary"],
                 font=(FONT, 9, "bold"), anchor="w").pack(fill="x")
        items = [str(v) for v in values]
        current_value = _clean(current)
        if current_value and current_value not in items:
            items.append(current_value)
        if not current_value and items:
            current_value = items[0]
        var = tk.StringVar(value=current_value)
        combo = ttk.Combobox(wrap, textvariable=var, values=items, state="readonly")
        combo.pack(fill="x", ipady=2, pady=(4, 0))
        if hint:
            tk.Label(wrap, text=hint, bg=PALETTE["surface"], fg=PALETTE["muted"],
                     font=(FONT, 8), anchor="w").pack(fill="x", pady=(3, 0))
        payload = {"var": var, "combo": combo, "values": items}
        if state_key:
            self._detail_state[state_key] = payload
        return payload

    def _next_available_number(self, usage_map, limit):
        for n in range(1, limit + 1):
            if n not in usage_map:
                return n
        used = sorted(n for n in usage_map.keys() if 1 <= int(n) <= limit)
        return min(limit, max(1, used[-1])) if used else 1

    def _build_number_choices(self, usage_map, limit, current_value):
        current_num = int(current_value) if str(current_value).isdigit() and 1 <= int(current_value) <= limit else None
        preferred_num = current_num or self._next_available_number(usage_map, limit)
        ordered = list(range(1, limit + 1))
        display_to_value = {}
        values = []
        for num in ordered:
            owners = usage_map.get(num, [])
            label = str(num)
            if owners:
                preview = "、".join(owners[:2])
                if len(owners) > 2:
                    preview += "..."
                label = f"{num} · 已占用：{preview}"
            values.append(label)
            display_to_value[label] = str(num)
        selected_num = str(current_num or preferred_num)
        selected_label = next((label for label, value in display_to_value.items() if value == selected_num), values[0] if values else "")
        return values, display_to_value, selected_label

    def _number_choice_field(self, parent, label, current_value, usage_map, limit, hint="", empty_hint="当前编号空闲。", state_key=None):
        wrap = tk.Frame(parent, bg=PALETTE["surface"])
        wrap.pack(fill="x", pady=(0, 12))
        tk.Label(wrap, text=label, bg=PALETTE["surface"], fg=PALETTE["secondary"],
                 font=(FONT, 9, "bold"), anchor="w").pack(fill="x")
        normalized_current = _clean(current_value)
        values, display_to_value, selected_label = self._build_number_choices(usage_map, limit, normalized_current)
        var = tk.StringVar(value=selected_label)
        recommended_num = str(self._next_available_number(usage_map, limit))
        recommended_label = next((label for label, value in display_to_value.items() if value == recommended_num), "")
        top_row = tk.Frame(wrap, bg=PALETTE["surface"])
        top_row.pack(fill="x", pady=(4, 0))
        style = ttk.Style(self)
        style_name = f"FSNumber{id(wrap)}.TCombobox"
        combo = ttk.Combobox(wrap, textvariable=var, values=values, state="readonly", style=style_name)
        combo.pack(in_=top_row, side="left", fill="x", expand=True, ipady=2)
        recommend_btn = tk.Button(
            top_row,
            text=f"推荐 {recommended_num}",
            font=(FONT, 8, "bold"),
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            bg=PALETTE["accent_soft"],
            fg=PALETTE["secondary"],
            activebackground=PALETTE["accent_tint"],
            activeforeground=PALETTE["text"],
            cursor="hand2",
            command=lambda: var.set(recommended_label or var.get()),
        )
        recommend_btn.pack(side="left", padx=(8, 0))
        status = tk.Label(wrap, text="", bg=PALETTE["surface"], fg=PALETTE["muted"],
                          font=(FONT, 8), anchor="w")
        status.pack(fill="x", pady=(3, 0))
        if hint:
            tk.Label(wrap, text=hint, bg=PALETTE["surface"], fg=PALETTE["muted"],
                     font=(FONT, 8), anchor="w").pack(fill="x", pady=(2, 0))

        def get_value():
            return display_to_value.get(var.get(), "")

        def refresh_status(*_args):
            value = get_value()
            if value.isdigit():
                owners = usage_map.get(int(value), [])
                if owners:
                    style.map(
                        style_name,
                        fieldbackground=[("readonly", "#FBEAEA")],
                        foreground=[("readonly", PALETTE["danger"])],
                    )
                    status.config(text=f"当前编号已被占用：{'、'.join(owners)}", fg=PALETTE["danger"])
                    return
            style.map(
                style_name,
                fieldbackground=[("readonly", PALETTE["input_bg"])],
                foreground=[("readonly", PALETTE["text"])],
            )
            if recommended_num and value == recommended_num:
                status.config(text=f"{empty_hint} 当前即推荐编号。", fg=PALETTE["muted"])
                return
            status.config(text=f"{empty_hint} 推荐编号：{recommended_num}", fg=PALETTE["muted"])

        var.trace_add("write", refresh_status)
        refresh_status()
        payload = {
            "var": var,
            "combo": combo,
            "get": get_value,
            "status": status,
            "recommended": recommended_num,
            "recommend_button": recommend_btn,
        }
        if state_key:
            self._detail_state[state_key] = payload
        return payload

    def _validate_before_save(self):
        duplicate_steps = []
        seen_steps = {}
        for path, node in self.model.index.items():
            if len(path) != 1:
                continue
            step_value = _clean((node or {}).get("step"))
            if not step_value or not step_value.isdigit():
                continue
            seen_steps.setdefault(step_value, []).append(path[0])
        for step_value, owners in seen_steps.items():
            if len(owners) > 1:
                duplicate_steps.append(f"步骤编号 {step_value} 重复：{'、'.join(owners)}")

        duplicate_orders = []
        seen_orders = {}
        for ri, row in enumerate(self.rows):
            if self.model.cell(row, "代码/说明") != "代码":
                continue
            order_value = _clean(self.model.cell(row, "运行顺序"))
            if not order_value or not order_value.isdigit():
                continue
            step_value = _clean(self._effective_step_for_row(ri))
            key = (step_value, order_value)
            seen_orders.setdefault(key, []).append(self.model.cell(row, "相应代码和说明文件") or f"第{ri + 2}行")
        for (step_value, order_value), owners in seen_orders.items():
            if len(owners) > 1:
                step_text = step_value or "未分配步骤"
                duplicate_orders.append(f"步骤 {step_text} 的运行顺序 {order_value} 重复：{'、'.join(owners)}")

        errors = duplicate_steps + duplicate_orders
        if errors:
            raise ValueError("保存前校验未通过：\n- " + "\n- ".join(errors))

    def _collect_run_order_usage(self, exclude_ri):
        usage = {}
        step_value = _clean(self._effective_step_for_row(exclude_ri))
        for ri, row in enumerate(self.rows):
            if ri == exclude_ri:
                continue
            if self.model.cell(row, "代码/说明") != "代码":
                continue
            if _clean(self._effective_step_for_row(ri)) != step_value:
                continue
            order_value = _clean(self.model.cell(row, "运行顺序"))
            if not order_value.isdigit():
                continue
            usage.setdefault(int(order_value), []).append(self.model.cell(row, "相应代码和说明文件") or f"第{ri + 2}行")
        return usage

    def _collect_step_usage(self, exclude_path=None):
        excluded = tuple(exclude_path or ())
        usage = {}
        for path, node in self.model.index.items():
            if len(path) != 1:
                continue
            if excluded and tuple(path) == excluded:
                continue
            step_value = _clean((node or {}).get("step"))
            if not step_value.isdigit():
                continue
            usage.setdefault(int(step_value), []).append(path[0])
        return usage

    def _form_file(self, ri):
        self.right_title.config(text="文件详情")
        f = self.model.file_fields(ri)
        pad = tk.Frame(self.detail, bg=PALETTE["surface"])
        pad.pack(fill="both", expand=True, padx=20, pady=16)

        current_type = f["代码/说明"] or "代码"
        base_name, ext_name = self._split_file_name_for_form(f["相应代码和说明文件"], current_type)
        type_var = tk.StringVar(value=current_type)
        self._detail_state["type_var"] = type_var
        trow = tk.Frame(pad, bg=PALETTE["surface"])
        trow.pack(fill="x", pady=(0, 12))
        tk.Label(trow, text="类型", bg=PALETTE["surface"], fg=PALETTE["secondary"],
                 font=(FONT, 9, "bold"), anchor="w").pack(fill="x")
        seg = tk.Frame(trow, bg=PALETTE["accent_soft"])
        seg.pack(anchor="w", pady=(4, 0))
        for t in ("代码", "说明"):
            tk.Radiobutton(seg, text=t, variable=type_var, value=t, indicatoron=False,
                           font=(FONT, 10, "bold"), bg=PALETTE["accent_soft"],
                           fg=PALETTE["secondary"], selectcolor=PALETTE["surface"],
                           activebackground=PALETTE["accent_soft"], bd=0, padx=18, pady=5,
                           cursor="hand2").pack(side="left", padx=2, pady=2)

        name_state = self._placeholder_field(
            pad,
            "部署文件名（名称）",
            base_name,
            UNNAMED_PLACEHOLDER,
            "默认占位为（未命名），保存时会自动拼接扩展名。",
            state_key="name_var",
        )
        ext_var = self._field(
            pad,
            "扩展名",
            ext_name,
            "默认：说明 .docx，代码 .py；可手工修改。",
            state_key="ext_var",
        )
        ext_state = {"programmatic": False, "manual_override": ext_name not in (".py", ".docx")}

        def _set_ext_value(value):
            ext_state["programmatic"] = True
            ext_var.set(self._normalize_extension(value, type_var.get()))
            ext_state["programmatic"] = False

        def _on_ext_change(*_args):
            normalized = self._normalize_extension(ext_var.get(), type_var.get())
            if normalized != ext_var.get():
                _set_ext_value(normalized)
                return
            if ext_state["programmatic"]:
                return
            ext_state["manual_override"] = normalized not in (".py", ".docx")

        sub_field = self._choice_field(
            pad,
            "代码子文件夹",
            CODE_SUBDIR_OPTIONS,
            self._normalize_code_subdir(f["代码子文件夹"]),
            f"可选：{BLANK_OPTION_LABEL}、工作区设置、更新代码、notebook；{BLANK_OPTION_LABEL} 表示保存在代码根目录。",
            state_key="sub_var",
        )
        sub_state = {"programmatic": False, "manual_override": self._normalize_code_subdir(f["代码子文件夹"]) not in (BLANK_OPTION_LABEL, "更新代码")}

        def _set_subdir_value(value):
            sub_state["programmatic"] = True
            sub_field["var"].set(value)
            sub_state["programmatic"] = False

        def _on_subdir_change(*_args):
            if sub_state["programmatic"]:
                return
            sub_state["manual_override"] = sub_field["var"].get() not in (BLANK_OPTION_LABEL, "更新代码")

        def _on_type_change(*_args):
            current_ext = self._normalize_extension(ext_var.get(), type_var.get())
            if not ext_state["manual_override"] and current_ext in (".py", ".docx"):
                _set_ext_value(_default_extension_for_type(type_var.get()))
            if not sub_state["manual_override"]:
                if type_var.get() == "说明":
                    _set_subdir_value(BLANK_OPTION_LABEL)
                elif sub_field["var"].get() == BLANK_OPTION_LABEL:
                    _set_subdir_value("更新代码")
            render_dynamic_section()

        ext_var.trace_add("write", _on_ext_change)
        type_var.trace_add("write", _on_type_change)
        sub_field["var"].trace_add("write", _on_subdir_change)

        src_var = self._field(
            pad,
            "保存在资料中的名称",
            f["保存在资料中的名称"],
            "资料里的源文件名。",
            state_key="src_var",
        )

        tk.Frame(pad, bg=PALETTE["border"], height=1).pack(fill="x", pady=10)
        adv = tk.Label(pad, text="流水线与配套（高级）", bg=PALETTE["surface"],
                       fg=PALETTE["secondary"], font=(FONT, 9, "bold"), anchor="w")
        adv.pack(fill="x", pady=(0, 6))
        order_field = self._number_choice_field(
            pad,
            "运行顺序（运行顺序）",
            f["运行顺序"],
            self._collect_run_order_usage(ri),
            RUN_ORDER_LIMIT,
            "从 1-100 中选择；优先给出当前可用序号。",
            empty_hint="当前序号空闲。",
            state_key="order_var",
        )
        note_var = self._field(
            pad,
            "备注（备注）",
            f["备注"],
            "⚠ 一旦填写，整行将被停用（不建文件夹/不部署）。",
            state_key="note_var",
        )

        dynamic_wrap = tk.Frame(pad, bg=PALETTE["surface"])
        dynamic_wrap.pack(fill="both", expand=False, pady=(8, 0))
        dynamic_state = {"lb": None, "code_ris": []}

        def render_dynamic_section():
            dynamic_state["lb"] = None
            dynamic_state["code_ris"] = []
            for child in dynamic_wrap.winfo_children():
                child.destroy()
            if type_var.get() == "说明":
                wrap = tk.Frame(dynamic_wrap, bg=PALETTE["surface"])
                wrap.pack(fill="both", expand=False)
                tk.Label(wrap, text="绑定代码（同 step）", bg=PALETTE["surface"], fg=PALETTE["secondary"],
                         font=(FONT, 9, "bold"), anchor="w").pack(fill="x")
                box = tk.Frame(wrap, bg=PALETTE["surface"])
                box.pack(fill="both", expand=False, pady=(4, 0))
                lb = tk.Listbox(
                    box,
                    selectmode="multiple",
                    height=8,
                    font=(FONT, 10),
                    bg=PALETTE["input_bg"],
                    fg=PALETTE["text"],
                    highlightthickness=1,
                    highlightbackground=PALETTE["border"],
                    selectbackground=PALETTE["accent"],
                    selectforeground="#FFFFFF",
                    activestyle="none",
                    exportselection=False,
                )
                sb = tk.Scrollbar(box, orient="vertical", command=lb.yview)
                lb.configure(yscrollcommand=sb.set)
                lb.pack(side="left", fill="both", expand=True)
                sb.pack(side="right", fill="y")
                dynamic_state["lb"] = lb
                self._detail_state["code_listbox"] = lb
                selected_codes = set(self._doc_to_codes.get(ri, set()))
                for idx, (cri, cname) in enumerate(self._codes_in_same_step(ri)):
                    dynamic_state["code_ris"].append(cri)
                    lb.insert("end", cname)
                    if cri in selected_codes:
                        lb.selection_set(idx)
            else:
                bound_docs = []
                for doc_ri, doc_name in self._docs_in_same_step(ri):
                    if ri in self._doc_to_codes.get(doc_ri, set()):
                        bound_docs.append(doc_name)
                self._field(dynamic_wrap, "绑定说明", "；".join(bound_docs) if bound_docs else "", readonly=True)
            self._detail_state["code_row_indices"] = list(dynamic_state["code_ris"])

        render_dynamic_section()

        def apply():
            new_src = (src_var.get() or "").strip()
            old_src = _clean(f.get("保存在资料中的名称"))
            if new_src and new_src != old_src:
                conflict = self._find_saved_name_conflict(new_src, exclude_ri=ri)
                if conflict and messagebox:
                    where = conflict.get("rel_dir") or "（工作区根目录）"
                    messagebox.showerror(
                        "名称冲突",
                        "『保存在资料中的名称』必须与现有文件名不同。\n\n"
                        f"你填写：{new_src}\n"
                        f"撞名：第 {conflict.get('sheet_row')} 行 · {where} · {conflict.get('label')}",
                        parent=self,
                    )
                    return

            self._push_undo()
            base_value = name_state["get"]() or UNNAMED_PLACEHOLDER
            full_name = f"{base_value}{self._normalize_extension(ext_var.get(), type_var.get())}"
            self.model.edit_file(ri, {
                "代码/说明": type_var.get(),
                "相应代码和说明文件": full_name,
                "代码子文件夹": self._save_code_subdir(sub_field["var"].get()),
                "保存在资料中的名称": new_src,
                "运行顺序": order_field["get"](),
                "备注": note_var.get(),
            })
            new_type = type_var.get()
            if new_type == "说明":
                chosen = set()
                if dynamic_state["lb"] is not None:
                    for i in dynamic_state["lb"].curselection():
                        if 0 <= i < len(dynamic_state["code_ris"]):
                            chosen.add(dynamic_state["code_ris"][i])
                allowed = {cri for cri, _ in self._codes_in_same_step(ri)}
                chosen = {c for c in chosen if c in allowed}
                self._doc_to_codes[ri] = chosen
            else:
                if ri in self._doc_to_codes:
                    self._doc_to_codes.pop(ri, None)
            self._recompute_and_write_binding_tokens()
            self.model.rebuild()
            self._mark_dirty("已更新文件详情（未保存）")
            self.populate_tree()
            self._reveal(("file", ri))
            self._update_undo_buttons()

        self._tk_button(pad, "应用修改", apply, primary=True).pack(anchor="w", pady=(8, 0))

    def _form_folder(self, path):
        self.right_title.config(text="文件夹属性")
        node = self.model.index.get(tuple(path))
        pad = tk.Frame(self.detail, bg=PALETTE["surface"])
        pad.pack(fill="both", expand=True, padx=20, pady=16)
        is_top = len(path) == 1
        name_var = self._field(
            pad,
            "文件夹名称",
            path[-1] if path else "",
            "改名后会自动同步到该文件夹下所有文件行。",
            state_key="folder_name_var",
        )
        step_var = None
        if is_top:
            step_var = self._number_choice_field(
                pad,
                "步骤编号（步骤）",
                (node or {}).get("step", ""),
                self._collect_step_usage(path),
                STEP_LIMIT,
                "步骤编号最多 20 个；下拉会优先定位到当前可用编号。",
                empty_hint="当前步骤编号空闲。",
                state_key="folder_step_var",
            )

        def apply():
            old_path = tuple(path)
            self._push_undo()
            if step_var is not None:
                self.model.set_top_step(old_path, step_var["get"]())
            new_name = name_var.get().strip()
            new_path = old_path
            if new_name and new_name != old_path[-1]:
                # set_top_step 已 rebuild，路径名未变，可继续按原名 rename
                self.model.rename_folder(old_path, new_name)
                new_path = old_path[:-1] + (new_name,)
            self._mark_dirty("已更新文件夹（未保存）")
            self.populate_tree()
            self._reveal(("folder", new_path))
            self._update_undo_buttons()

        self._tk_button(pad, "应用修改", apply, primary=True).pack(anchor="w", pady=(8, 0))

    def _form_output(self, ri):
        self.right_title.config(text="输出目标")
        f = self.model.output_fields(ri)
        pad = tk.Frame(self.detail, bg=PALETTE["surface"])
        pad.pack(fill="both", expand=True, padx=20, pady=16)
        marker_field = self._choice_field(
            pad,
            "输出标记（输出文件）",
            OUTPUT_MARKER_OPTIONS,
            f["输出文件"] or "ins",
            "只允许选择：全量 或 ins。",
            state_key="output_marker_var",
        )
        code_wrap = tk.Frame(pad, bg=PALETTE["surface"])
        code_wrap.pack(fill="x", pady=(0, 12))
        tk.Label(code_wrap, text="对应代码（对应代码）", bg=PALETTE["surface"], fg=PALETTE["secondary"],
                 font=(FONT, 9, "bold"), anchor="w").pack(fill="x")
        code_var = tk.StringVar(value=f["对应代码"] or "")
        self._detail_state["output_code_var"] = code_var
        choices = [""] + self._code_choices_in_same_step(ri)
        cur = (f["对应代码"] or "").strip()
        if cur and cur not in choices:
            choices.append(cur)
        combo = ttk.Combobox(code_wrap, textvariable=code_var, values=choices, state="readonly")
        combo.pack(fill="x", ipady=2, pady=(4, 0))
        self._detail_state["output_code_combo"] = combo
        tk.Label(code_wrap, text="该产物由哪段代码生成（从同 step 代码中选择）。",
                 bg=PALETTE["surface"], fg=PALETTE["muted"], font=(FONT, 8), anchor="w").pack(fill="x", pady=(3, 0))

        def apply():
            self._push_undo()
            self.model.edit_file(ri, {"输出文件": marker_field["var"].get(), "对应代码": code_var.get()})
            self._mark_dirty("已更新输出目标（未保存）")
            self.populate_tree()
            self._reveal(("output", ri))
            self._update_undo_buttons()

        self._tk_button(pad, "应用修改", apply, primary=True).pack(anchor="w", pady=(8, 0))

    # ---------- 增删 ----------
    def _selected_folder_path(self):
        if not self._selected:
            return ()
        kind, key = self._selected
        if kind == "folder":
            return tuple(key)
        if kind in ("file", "output"):
            return tuple(self.model._segments(self.rows[key]))
        return ()

    def on_add_file(self):
        path = self._selected_folder_path()
        default_name = f"{UNNAMED_PLACEHOLDER}.docx"
        default_type = "说明"
        if self._selected and self._selected[0] == "file":
            selected_row = self.rows[self._selected[1]]
            selected_type = self.model.cell(selected_row, "代码/说明")
            if selected_type == "代码":
                default_name = f"{UNNAMED_PLACEHOLDER}.py"
                default_type = "代码"
        self._push_undo()
        ri = self.model.add_file(path, default_name, default_type)
        if self._open_paths is not None:
            self._open_paths |= {tuple(path[:i + 1]) for i in range(len(path))}  # 展开到父文件夹
        self._mark_dirty("已新增文件（未保存）")
        self.populate_tree()
        self._reveal(("file", ri))   # 选中并滚动到新文件，避免“消失”
        self._update_undo_buttons()
        self.status_var.set("已新增文件，已为你定位到它，请在右侧填写名称与扩展名。")

    def on_add_step_folder(self):
        self._push_undo()
        path = self.model.add_folder((), "步骤")
        if self._open_paths is not None:
            self._open_paths |= {tuple(path[:i + 1]) for i in range(len(path))}
        self._mark_dirty("已新增步骤文件夹（未保存）")
        self.populate_tree()
        self._reveal(("folder", path))
        self._update_undo_buttons()
        self.status_var.set("已新增『步骤』，请在右侧填写名称和步骤编号。")

    def on_add_output_folder(self):
        parent = self._selected_folder_path()
        self._push_undo()
        folder_path = self.model.add_folder(parent, "输出文件")
        self.model.add_output(folder_path, marker="ins", code="")
        if self._open_paths is not None:
            self._open_paths |= {tuple(folder_path[:i + 1]) for i in range(len(folder_path))}
        self._mark_dirty("已新增输出文件夹（未保存）")
        self.populate_tree()
        self._reveal(("folder", folder_path))
        self._update_undo_buttons()
        self.status_var.set("已新增『输出文件』，输出项已一并创建。")

    def on_add_folder(self):
        path = self._selected_folder_path()
        self._push_undo()
        new_path = self.model.add_folder(path, "新文件夹")
        if self._open_paths is not None:
            self._open_paths |= {tuple(path[:i + 1]) for i in range(len(path))}
        self._mark_dirty("已新增文件夹（未保存）")
        self.populate_tree()
        self._reveal(("folder", new_path))
        self._update_undo_buttons()
        self.status_var.set("已新增『新文件夹』，已为你定位到它。")

    def on_delete(self):
        if not self._selected:
            return
        kind, key = self._selected
        if kind == "file" or kind == "output":
            if messagebox and not messagebox.askokcancel("确认删除", "删除此文件 / 条目？", parent=self):
                return
            self._push_undo()
            self.model.delete_file(key)
        elif kind == "folder":
            if messagebox and not messagebox.askokcancel(
                    "确认删除", "删除此文件夹及其下所有文件？", parent=self):
                return
            self._push_undo()
            self.model.delete_folder(key)
        else:
            return
        self._selected = None
        self._mark_dirty("已删除（未保存）")
        self.populate_tree()
        self._update_undo_buttons()

    # ---------- 保存 ----------
    def _mark_dirty(self, msg):
        self.dirty = True
        self.status_var.set(msg)

    def save(self):
        try:
            self._validate_before_save()
            self._recompute_and_write_binding_tokens()
            if self.model:
                self.model.rebuild()
            save_blueprint(self.workbook, self.sheet, self.header, self.rows, self.blueprint_xlsx_path)
        except Exception as exc:
            if messagebox:
                messagebox.showerror("保存失败", str(exc), parent=self)
            return
        self.dirty = False
        self.status_var.set(f"保存成功，已写回 {self.blueprint_xlsx_path}")
        if callable(self.on_saved):
            try:
                self.on_saved(self.blueprint_xlsx_path)
            except Exception:
                pass
        if messagebox:
            messagebox.showinfo("保存成功", f"已按标准格式写回：\n{self.blueprint_xlsx_path}", parent=self)

    def open_xlsx_file(self):
        if not self.blueprint_xlsx_path:
            return
        if not os.path.isfile(self.blueprint_xlsx_path):
            if messagebox:
                messagebox.showerror("未找到文件", f"未找到：\n{self.blueprint_xlsx_path}", parent=self)
            return
        try:
            os.startfile(self.blueprint_xlsx_path)
        except Exception as exc:
            if messagebox:
                messagebox.showerror("打开失败", str(exc), parent=self)

    def open_spreadsheet_view(self):
        """兜底：打开原表格编辑器（同一文件）。"""
        try:
            try:
                from .file_structure_editor import FileStructureEditorWindow as SheetEditor
            except Exception:
                from file_structure_editor import FileStructureEditorWindow as SheetEditor
        except Exception as exc:
            if messagebox:
                messagebox.showinfo("提示", f"未找到表格编辑器模块：{exc}", parent=self)
            return
        try:
            win = SheetEditor(self.master, self.award_name, self.year_text,
                              self.workspace_name, self.blueprint_xlsx_path, on_saved=self.on_saved)
            win.focus()
        except Exception as exc:
            if messagebox:
                messagebox.showerror("打开表格视图失败", str(exc), parent=self)


# ======================================================================
#  独立运行：python file_tree_editor.py 路径/文件结构.xlsx
# ======================================================================
if __name__ == "__main__" and tk is not None:
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "文件结构.xlsx"
    root = tk.Tk()
    root.withdraw()
    FileStructureEditorWindow(root, "私募", "2025", "私募", path, on_saved=lambda p: print("saved:", p))
    root.mainloop()
