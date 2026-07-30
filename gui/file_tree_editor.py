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
import sys
import copy
import re
import datetime
import threading
import subprocess
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
    "index", "工作区名", "步骤", "工作区文件夹", "子文件夹1", "子文件夹2", "子文件夹3", "子文件夹4",
    "运行顺序", "代码/说明", "代码子文件夹", "相应代码和说明文件", "保存在资料中的名称",
    "备注", "只运行一次", "其他", "输出文件", "对应代码",
]
ENSURE_TAIL_COLUMNS = ["index", "只运行一次", "其他", "输出文件", "对应代码"]
WORKSPACE_COLUMN_NAME = "工作区名"
INDEX_COLUMN_NAME = "index"
UNNAMED_PLACEHOLDER = "(未命名)"
DEFAULT_NEW_FILE_BASENAME = "未命名"
BLANK_OPTION_LABEL = "(空白)"
CODE_SUBDIR_OPTIONS = [BLANK_OPTION_LABEL, "工作区设置", "更新代码", "notebook"]
RUN_ONCE_OPTIONS = ["否", "是"]
OUTPUT_MARKER_OPTIONS = ["全量", "ins"]
RUN_ORDER_LIMIT = 100
STEP_LIMIT = 20
NAME_NUMBER_LIMIT = 9
README_NUMBER_LIMIT = 100
CODE_EXTENSION_OPTIONS = [".py", ".ipynb"]
DOC_EXTENSION_OPTIONS = [".docx", ".md"]


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


def _normalize_yes_no(value, default="否"):
    text = _clean(value)
    if text in {"是", "否"}:
        return text
    lowered = text.lower()
    if lowered in {"1", "true", "yes", "y"}:
        return "是"
    if lowered in {"0", "false", "no", "n"}:
        return "否"
    return default


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


def _parse_run_order_value(value):
    """把可用的非负整数顺序统一解析为 int；空白/非法值返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if value == value and value.is_integer() and value >= 0:
            return int(value)
        return None
    text = _clean(value)
    if text.isdigit():
        return int(text)
    if re.fullmatch(r"\d+\.0+", text):
        return int(float(text))
    return None


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
        
        self._max_idx = 0
        for row in self.rows:
            rid = self.row_id(row)
            if rid and str(rid).isdigit():
                self._max_idx = max(self._max_idx, int(rid))
                
        self.rebuild()

    # ---- 单元格读写 ----
    def _ci(self, name):
        return self.col.get(name, -1)

    def cell(self, row, name):
        i = self._ci(name)
        return _clean(row[i]) if 0 <= i < len(row) else ""

    def row_id(self, row):
        return self.cell(row, INDEX_COLUMN_NAME)

    def _set_on(self, row, name, value):
        i = self._ci(name)
        if i < 0:
            return
        while len(row) <= i:
            row.append(None)
        row[i] = value if (value is not None and str(value) != "") else None

    def _next_row_index(self):
        self._max_idx += 1
        return str(self._max_idx)

    def reserve_new_row(self):
        row = [None] * len(self.header)
        self._set_on(row, INDEX_COLUMN_NAME, self._next_row_index())
        self.rows.append(row)
        return len(self.rows) - 1

    def ensure_row_ids(self):
        seen = set()
        changed = False
        for row in self.rows:
            rid = self.row_id(row)
            if not rid or rid in seen:
                self._set_on(row, INDEX_COLUMN_NAME, self._next_row_index())
                rid = self.row_id(row)
                changed = True
            seen.add(rid)
        if changed:
            self.rebuild()
        return changed

    def set_cell(self, ri, name, value):
        if 0 <= ri < len(self.rows):
            self._set_on(self.rows[ri], name, value)

    def normalize_run_orders(self, rebuild=True):
        """将代码运行顺序压紧为连续链。

        顺序链固定从 0 开始，规范为 0, 1, 2...。非法顺序视为未分配。
        返回实际被改写的单元格数量。
        """
        ordered = []
        changed = 0
        for ri, row in enumerate(self.rows):
            order_text = self.cell(row, "运行顺序")
            if self.cell(row, "代码/说明") != "代码":
                if order_text:
                    self._set_on(row, "运行顺序", None)
                    changed += 1
                continue
            order_num = _parse_run_order_value(order_text)
            if order_num is None:
                if order_text:
                    self._set_on(row, "运行顺序", None)
                    changed += 1
                continue
            ordered.append((order_num, ri))

        ordered.sort(key=lambda item: (item[0], item[1]))
        start_order = 0
        for offset, (_old_order, ri) in enumerate(ordered):
            expected = str(start_order + offset)
            if self.cell(self.rows[ri], "运行顺序") != expected:
                self._set_on(self.rows[ri], "运行顺序", expected)
                changed += 1

        if rebuild and changed:
            self.rebuild()
        return changed

    def set_run_order_position(self, ri, target_order, rebuild=True):
        """把一行代码抽出后插入目标顺序，并同时压紧整条链。"""
        if not (0 <= ri < len(self.rows)):
            return False
        target_num = _parse_run_order_value(target_order)
        if self.cell(self.rows[ri], "代码/说明") != "代码" or target_num is None:
            self._set_on(self.rows[ri], "运行顺序", None)
            self.normalize_run_orders(rebuild=False)
            if rebuild:
                self.rebuild()
            return True

        self.normalize_run_orders(rebuild=False)
        other_rows = []
        for other_ri, row in enumerate(self.rows):
            if other_ri == ri or self.cell(row, "代码/说明") != "代码":
                continue
            order_num = _parse_run_order_value(self.cell(row, "运行顺序"))
            if order_num is not None:
                other_rows.append((order_num, other_ri))
        other_rows.sort(key=lambda item: (item[0], item[1]))

        start_order = 0
        insert_at = max(0, min(target_num - start_order, len(other_rows)))
        chain_rows = [other_ri for _order_num, other_ri in other_rows]
        chain_rows.insert(insert_at, ri)
        for offset, chain_ri in enumerate(chain_rows):
            self._set_on(self.rows[chain_ri], "运行顺序", str(start_order + offset))
        if rebuild:
            self.rebuild()
        return True

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
            # 注意：不要遇到空就break！而是继续检查下一个子文件夹！
        return segs

    def _make_top_key(self, step, top_name):
        return ("__top__", _clean(step), _clean(top_name))

    def _is_top_key(self, item):
        return isinstance(item, tuple) and len(item) == 3 and item[0] == "__top__"

    def _display_seg(self, item):
        return item[2] if self._is_top_key(item) else item

    def _display_path(self, path):
        return tuple(self._display_seg(item) for item in tuple(path))

    def _path_step(self, path):
        path = tuple(path)
        if path and self._is_top_key(path[0]):
            return _clean(path[0][1])
        if path:
            return self._top_step(self._display_seg(path[0]))
        return ""

    def _path_keys(self, row):
        segs = self._segments(row)
        if not segs:
            return ()
        step_value = self.cell(row, "步骤")
        return (self._make_top_key(step_value, segs[0]),) + tuple(segs[1:])

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
        row_segs = self._path_keys(row)
        if len(path) > len(row_segs):
            return False
        for i in range(len(path)):
            if row_segs[i] != path[i]:
                return False
        return True

    def _top_step(self, top_name):
        if self._is_top_key(top_name):
            return _clean(top_name[1])
        for row in self.rows:
            if self.cell(row, "工作区文件夹") == self._display_seg(top_name):
                s = self.cell(row, "步骤")
                if s:
                    return s
        return ""

    # ---- 构建树 ----
    def rebuild(self):
        root = {"kind": "root", "name": "（工作区根目录）", "path": (),
                "children": [], "files": [], "outputs": [], "folder_rows": []}
        index = {(): root}

        def get_folder(path_keys, display_segs):
            node = root
            for d in range(len(path_keys)):
                key = tuple(path_keys[: d + 1])
                if key not in index:
                    parent = index[tuple(path_keys[:d])]
                    fn = {"kind": "folder", "name": display_segs[d], "path": key, "step": "",
                          "children": [], "files": [], "outputs": [], "folder_rows": []}
                    if d == 0 and self._is_top_key(path_keys[d]):
                        fn["step"] = _clean(path_keys[d][1])
                    index[key] = fn
                    parent["children"].append(fn)
                node = index[key]
            return node

        for ri, row in enumerate(self.rows):
            segs = self._segments(row)
            path_keys = self._path_keys(row)
            kind = self._classify(row)
            node = get_folder(path_keys, segs) if path_keys else root
            if kind == "file":
                node["files"].append(ri)
            elif kind == "output":
                node["outputs"].append(ri)
            else:
                node["folder_rows"].append(ri)

        self.tree = root
        self.index = index

    # ---- 编辑：均原地改 self.rows，再 rebuild ----
    def rename_folder(self, path, new_name):
        new_name = (new_name or "").strip()
        if not new_name or not path or tuple(path) == ():
            return False
        path = tuple(path)
        if self._display_seg(path[-1]) == new_name:
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
            if self._row_matches_path(row, path):
                self._set_on(row, "步骤", step)
        self.rebuild()
        return True

    def edit_file(self, ri, fields):
        if not (0 <= ri < len(self.rows)):
            return
        has_order_update = "运行顺序" in fields
        target_order = fields.get("运行顺序")
        for name, val in fields.items():
            if name == "运行顺序":
                continue
            self._set_on(self.rows[ri], name, val)
        if has_order_update:
            self.set_run_order_position(ri, target_order)
        elif not self.normalize_run_orders():
            self.rebuild()

    def add_file(self, folder_path, name="新文件.py", file_type="代码"):
        folder_path = tuple(folder_path)
        ri = self.reserve_new_row()
        row = self.rows[ri]
        for i, seg in enumerate(self._display_path(folder_path)):
            self._set_on(row, self._col_for_level(i), seg)
        if folder_path:
            self._set_on(row, "步骤", self._path_step(folder_path))
        self._set_on(row, "相应代码和说明文件", name)
        self._set_on(row, "代码/说明", file_type)
        self.rebuild()
        return ri

    def add_folder(self, parent_path, name="新文件夹"):
        parent_path = tuple(parent_path)
        full = parent_path + (name,)
        ri = self.reserve_new_row()
        row = self.rows[ri]
        for i, seg in enumerate(self._display_path(full)):
            self._set_on(row, self._col_for_level(i), seg)
        if full:
            step_value = self._path_step(parent_path) if parent_path else ""
            self._set_on(row, "步骤", step_value or None)
        self.rebuild()
        return tuple(self._path_keys(row)), ri

    def add_output(self, folder_path, marker="ins", code=""):
        folder_path = tuple(folder_path)
        ri = self.reserve_new_row()
        row = self.rows[ri]
        for i, seg in enumerate(self._display_path(folder_path)):
            self._set_on(row, self._col_for_level(i), seg)
        if folder_path:
            self._set_on(row, "步骤", self._path_step(folder_path))
        self._set_on(row, "输出文件", marker)
        self._set_on(row, "对应代码", code)
        self.rebuild()
        return ri

    def delete_file(self, ri):
        if 0 <= ri < len(self.rows):
            del self.rows[ri]
            if not self.normalize_run_orders():
                self.rebuild()

    def delete_folder(self, path):
        path = tuple(path)
        if path == ():
            return
        self.rows[:] = [row for row in self.rows if not self._row_matches_path(row, path)]
        if not self.normalize_run_orders():
            self.rebuild()

    def _apply_path_to_row(self, row, segs):
        segs = list(segs)
        display_segs = list(self._display_path(segs))
        for level in range(5):
            colname = self._col_for_level(level)
            value = display_segs[level] if level < len(display_segs) else None
            self._set_on(row, colname, value)
        self._set_on(row, "步骤", self._path_step(segs) or None)

    def move_file(self, ri, target_folder_path):
        if not (0 <= ri < len(self.rows)):
            return False
        target_folder_path = tuple(target_folder_path)
        row = self.rows.pop(ri)
        self._apply_path_to_row(row, target_folder_path)
        self._set_on(row, INDEX_COLUMN_NAME, self._next_row_index())
        self.rows.append(row)
        self.rebuild()
        return True

    def move_folder(self, source_path, target_parent_path):
        source_path = tuple(source_path)
        target_parent_path = tuple(target_parent_path)
        if not source_path:
            return None
        new_path = target_parent_path + (source_path[-1],)
        if source_path == new_path:
            return new_path
        
        moving_rows = []
        keep_rows = []
        for row in self.rows:
            if self._row_matches_path(row, source_path):
                moving_rows.append(row)
            else:
                keep_rows.append(row)
                
        self.rows[:] = keep_rows
        
        for row in moving_rows:
            current = tuple(self._path_keys(row))
            suffix = current[len(source_path):]
            self._apply_path_to_row(row, new_path + suffix)
            self._set_on(row, INDEX_COLUMN_NAME, self._next_row_index())
            self.rows.append(row)
            
        self.rebuild()
        return new_path

    # ---- 便捷读取（供 UI 表单用）----
    def file_fields(self, ri):
        row = self.rows[ri]
        return {name: self.cell(row, name) for name in (
            "相应代码和说明文件", "代码/说明", "代码子文件夹", "保存在资料中的名称",
            "运行顺序", "只运行一次", "其他", "备注",
        )}

    def output_fields(self, ri):
        row = self.rows[ri]
        return {"输出文件": self.cell(row, "输出文件"), "对应代码": self.cell(row, "对应代码")}


# ======================================================================
#  读 / 写 工作簿（与原编辑器同约定）
# ======================================================================
def load_blueprint(path):
    """读取 文件结构.xlsx -> (workbook, sheet, header, rows)。

    兼容旧表：
    1. 若缺少 index 列，则只补表头中的 index；
    2. 若 index 存在空白或重复，则只补/修正 index 单元格；
    3. 上述修复会立即原子写回原文件，避免后续基于脏 index 再做 concat/重排。
    """
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
    index_ci = header.index(INDEX_COLUMN_NAME)
    next_idx = 0
    seen = set()
    index_fixed = appended
    for row_idx in range(2, ws.max_row + 1):
        raw = _clean(ws.cell(row=row_idx, column=index_ci + 1).value)
        if raw.isdigit():
            next_idx = max(next_idx, int(raw))
        if raw and raw not in seen:
            seen.add(raw)
            continue
        next_idx += 1
        new_idx = str(next_idx)
        while new_idx in seen:
            next_idx += 1
            new_idx = str(next_idx)
        ws.cell(row=row_idx, column=index_ci + 1, value=new_idx)
        seen.add(new_idx)
        index_fixed = True
    if index_fixed:
        tmp_path = path + ".tmp"
        try:
            wb.save(tmp_path)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            raise
        # 重新打开，确保后续读取的是已经补好 index 的磁盘版本
        wb = load_workbook(path)
        ws = wb["工作区"]
    max_col = len(header)
    rows = [list(r) for r in ws.iter_rows(min_row=2, max_col=max_col, values_only=True)]
    return wb, ws, header, rows


def save_blueprint(wb, ws, header, rows, path):
    """根据 index 原地更新 Excel 行，保持原先行位置和格式不变；新增的行追加到末尾；删除的行被移除。"""
    max_col = len(header)
    for ci, name in enumerate(header, start=1):
        ws.cell(row=1, column=ci, value=name)

    index_ci = header.index(INDEX_COLUMN_NAME) if INDEX_COLUMN_NAME in header else -1
    if index_ci < 0:
        raise ValueError(f"保存失败：表头中未找到 {INDEX_COLUMN_NAME} 列")

    # 1. 收集 Excel 中现有的 index 及其行号
    existing_indexes = {}
    for row_idx in range(2, ws.max_row + 1):
        idx_val = _clean(ws.cell(row=row_idx, column=index_ci + 1).value)
        if idx_val:
            existing_indexes[idx_val] = row_idx

    # 2. 找出需要删除的行（在 Excel 中但不在当前 rows 中）
    current_indexes = set()
    for row in rows:
        idx_val = _clean(row[index_ci]) if index_ci < len(row) else ""
        if idx_val:
            current_indexes.add(idx_val)

    rows_to_delete = []
    for idx_val, row_idx in existing_indexes.items():
        if idx_val not in current_indexes:
            rows_to_delete.append(row_idx)

    # 从下往上删，避免行号偏移
    for row_idx in sorted(rows_to_delete, reverse=True):
        ws.delete_rows(row_idx)

    # 重新收集删除后的 index 映射，确保我们找准现在的真实行号
    existing_indexes = {}
    for row_idx in range(2, ws.max_row + 1):
        idx_val = _clean(ws.cell(row=row_idx, column=index_ci + 1).value)
        if idx_val:
            existing_indexes[idx_val] = row_idx

    # 3. 原地更新已有行，或在末尾追加新行
    # 这里非常重要：对于新增行，必须严格追加到目前 Excel 真实的末尾之后
    current_max_row = ws.max_row
    for row in rows:
        idx_val = _clean(row[index_ci]) if index_ci < len(row) else ""
        if idx_val in existing_indexes:
            target_row_idx = existing_indexes[idx_val]
        else:
            current_max_row += 1
            target_row_idx = current_max_row

        for ci in range(1, max_col + 1):
            v = row[ci - 1] if ci - 1 < len(row) else ""
            ws.cell(row=target_row_idx, column=ci, value=v if (v is not None and str(v) != "") else None)

    try:
        import os
        tmp_path = path + ".tmp"
        wb.save(tmp_path)
        # 使用 os.replace 进行原子替换，避免先删除导致的数据丢失风险
        os.replace(tmp_path, path)
    except Exception as exc:
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        raise exc


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
        self._selected_batch = []
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
        self._clipboard = None
        self._detail_canvas = None
        self._detail_window_id = None
        self._detail_action_btn = None
        self._active_detail_apply = None
        self._confirm_popup = None
        self._loading_overlay = None
        self._loading_label = None
        self.main_notebook = None
        self._editor_tab = None
        self._order_tab = None
        self._order_chain_canvas = None
        self._order_chain_inner = None
        self._order_chain_window_id = None
        self._order_chain_items = []
        self._order_chain_end_indicator = None
        self._order_unassigned_list = None
        self._order_unassigned_row_ids = []
        self._order_drag = None
        self._order_drag_ghost = None
        self._order_draft_row_ids = None
        self._order_draft_start_order = 0
        self._order_draft_dirty = False
        self._order_finish_btn = None
        self._order_discard_btn = None
        self._legacy_run_order_audit = None

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

    def _log(self, msg):
        if not hasattr(self, "log_text"):
            return
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _show_loading_overlay(self, message="正在保存..."):
        if self._loading_overlay:
            return
        # 创建半透明遮罩背景
        self._loading_overlay = tk.Frame(self, bg="gray50", bd=0)
        self._loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        # 创建带消息的容器
        content_frame = tk.Frame(self._loading_overlay, bg=PALETTE["surface"], bd=2, relief="solid")
        content_frame.place(relx=0.5, rely=0.5, anchor="center")
        self._loading_label = tk.Label(
            content_frame,
            text=message,
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            font=(FONT, 14, "bold"),
            padx=40,
            pady=30
        )
        self._loading_label.pack()
        self.update_idletasks()

    def _hide_loading_overlay(self):
        if self._loading_overlay:
            self._loading_overlay.destroy()
            self._loading_overlay = None
            self._loading_label = None

    def _on_tab_changed(self, event):
        selected_tab = event.widget.select()
        tab_text = event.widget.tab(selected_tab, "text")
        if tab_text == "全局映射视图":
            self._refresh_global_mapping_tab()

    def _on_main_tab_changed(self, event):
        try:
            selected_tab = event.widget.select()
            tab_text = event.widget.tab(selected_tab, "text")
        except Exception:
            return
        if tab_text == "顺序调整":
            self._refresh_order_tab()

    def _build_order_tab(self, parent):
        header = tk.Frame(parent, bg=PALETTE["surface"])
        header.pack(side="top", fill="x", padx=16, pady=(14, 8))
        tk.Label(
            header,
            text="顺序调整",
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            font=(FONT, 13, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            header,
            text="拖动左侧链条中的代码即可换位；双击可移入/移出。调整完成后点击“完成调整并应用”。",
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=(FONT, 9),
            anchor="w",
        ).pack(anchor="w", pady=(3, 0))

        split = tk.PanedWindow(
            parent,
            orient="horizontal",
            bg=PALETTE["border"],
            bd=0,
            sashwidth=6,
            sashrelief="flat",
        )
        split.pack(side="top", fill="both", expand=True, padx=16, pady=(0, 14))

        chain_panel = tk.Frame(
            split,
            bg=PALETTE["panel"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
        )
        unassigned_panel = tk.Frame(
            split,
            bg=PALETTE["panel"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
        )
        split.add(chain_panel, stretch="always", minsize=520, width=790)
        split.add(unassigned_panel, stretch="never", minsize=220, width=270)

        chain_head = tk.Frame(chain_panel, bg=PALETTE["panel"])
        chain_head.pack(side="top", fill="x", padx=12, pady=(10, 8))
        tk.Label(
            chain_head,
            text="已分配顺序 · 执行链",
            bg=PALETTE["panel"],
            fg=PALETTE["secondary"],
            font=(FONT, 10, "bold"),
        ).pack(side="left")
        self._order_chain_summary_var = tk.StringVar(value="")
        tk.Label(
            chain_head,
            textvariable=self._order_chain_summary_var,
            bg=PALETTE["panel"],
            fg=PALETTE["muted"],
            font=(FONT, 9),
        ).pack(side="right")
        self._order_finish_btn = self._tk_button(
            chain_head,
            "完成调整并应用",
            self._commit_order_draft,
            primary=True,
            small=True,
        )
        self._order_finish_btn.pack(side="right", padx=(8, 4))
        self._order_discard_btn = self._tk_button(
            chain_head,
            "放弃本次调整",
            self._discard_order_draft,
            small=True,
        )
        self._order_discard_btn.pack(side="right", padx=4)

        self._order_draft_status_var = tk.StringVar(value="当前顺序已同步到结构编辑。")
        tk.Label(
            chain_panel,
            textvariable=self._order_draft_status_var,
            bg=PALETTE["panel"],
            fg=PALETTE["muted"],
            font=(FONT, 8),
            anchor="w",
        ).pack(side="top", fill="x", padx=12, pady=(0, 6))

        chain_wrap = tk.Frame(chain_panel, bg=PALETTE["surface"])
        chain_wrap.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 10))
        self._order_chain_canvas = tk.Canvas(
            chain_wrap,
            bg=PALETTE["surface"],
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        chain_vsb = ttk.Scrollbar(
            chain_wrap,
            orient="vertical",
            command=self._order_chain_canvas.yview,
        )
        self._order_chain_canvas.configure(yscrollcommand=chain_vsb.set)
        chain_vsb.pack(side="right", fill="y")
        self._order_chain_canvas.pack(side="left", fill="both", expand=True)
        self._order_chain_inner = tk.Frame(self._order_chain_canvas, bg=PALETTE["surface"])
        self._order_chain_window_id = self._order_chain_canvas.create_window(
            (0, 0),
            window=self._order_chain_inner,
            anchor="nw",
        )
        self._order_chain_inner.bind("<Configure>", self._sync_order_chain_canvas, add="+")
        self._order_chain_canvas.bind("<Configure>", self._sync_order_chain_canvas, add="+")
        self._order_chain_canvas.bind("<MouseWheel>", self._on_order_chain_mousewheel, add="+")
        self._order_chain_inner.bind("<MouseWheel>", self._on_order_chain_mousewheel, add="+")

        right_head = tk.Frame(unassigned_panel, bg=PALETTE["panel"])
        right_head.pack(side="top", fill="x", padx=10, pady=(10, 6))
        tk.Label(
            right_head,
            text="未分配顺序",
            bg=PALETTE["panel"],
            fg=PALETTE["secondary"],
            font=(FONT, 10, "bold"),
        ).pack(side="left")
        self._order_unassigned_summary_var = tk.StringVar(value="")
        tk.Label(
            right_head,
            textvariable=self._order_unassigned_summary_var,
            bg=PALETTE["panel"],
            fg=PALETTE["muted"],
            font=(FONT, 9),
        ).pack(side="right")

        unassigned_wrap = tk.Frame(unassigned_panel, bg=PALETTE["surface"])
        unassigned_wrap.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 8))
        self._order_unassigned_list = tk.Listbox(
            unassigned_wrap,
            selectmode="extended",
            exportselection=False,
            activestyle="none",
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            selectbackground=PALETTE["accent"],
            selectforeground="#FFFFFF",
            highlightthickness=0,
            bd=0,
            font=(FONT, 9),
        )
        unassigned_vsb = ttk.Scrollbar(
            unassigned_wrap,
            orient="vertical",
            command=self._order_unassigned_list.yview,
        )
        unassigned_hsb = ttk.Scrollbar(
            unassigned_wrap,
            orient="horizontal",
            command=self._order_unassigned_list.xview,
        )
        self._order_unassigned_list.configure(
            yscrollcommand=unassigned_vsb.set,
            xscrollcommand=unassigned_hsb.set,
        )
        unassigned_hsb.pack(side="bottom", fill="x")
        unassigned_vsb.pack(side="right", fill="y")
        self._order_unassigned_list.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self._order_unassigned_list.bind(
            "<Double-Button-1>",
            self._on_unassigned_double_click,
            add="+",
        )

        assign_actions = tk.Frame(unassigned_panel, bg=PALETTE["panel"])
        assign_actions.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        self._tk_button(
            assign_actions,
            "加入链尾",
            self._assign_selected_order_rows,
            primary=True,
            small=True,
        ).pack(fill="x")
        tk.Label(
            assign_actions,
            text="可多选；先加入调整草稿，完成后统一应用。",
            bg=PALETTE["panel"],
            fg=PALETTE["muted"],
            font=(FONT, 8),
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(5, 0))

    def _sync_order_chain_canvas(self, _event=None):
        canvas = self._order_chain_canvas
        inner = self._order_chain_inner
        if not canvas or not inner:
            return
        try:
            canvas.itemconfigure(
                self._order_chain_window_id,
                width=max(1, canvas.winfo_width()),
            )
            canvas.configure(scrollregion=canvas.bbox("all"))
        except Exception:
            pass

    def _on_order_chain_mousewheel(self, event):
        if not self._order_chain_canvas:
            return
        delta = int(getattr(event, "delta", 0) or 0)
        if delta:
            self._order_chain_canvas.yview_scroll(-1 if delta > 0 else 1, "units")
        return "break"

    def _order_code_entries(self, use_draft=False):
        entries = []
        if not self.model:
            return [], []
        for ri, row in enumerate(self.rows):
            if self.model.cell(row, "代码/说明") != "代码":
                continue
            filename = self.model.cell(row, "相应代码和说明文件") or "（未命名代码）"
            row_id = self._row_id(row)
            if not row_id:
                continue
            step_value = _clean(self._effective_step_for_row(ri)) or "未分配"
            stem = os.path.splitext(filename)[0] or filename
            label = f"step_{step_value}_{stem}"
            entry = {
                "ri": ri,
                "row_id": row_id,
                "order": _parse_run_order_value(self.model.cell(row, "运行顺序")),
                "step": step_value,
                "filename": filename,
                "label": label,
            }
            entries.append(entry)
        assigned = [entry for entry in entries if entry["order"] is not None]
        unassigned = [entry for entry in entries if entry["order"] is None]
        assigned.sort(key=lambda item: (item["order"], item["ri"]))

        def unassigned_key(item):
            parts = re.split(r"(\d+)", item["step"])
            step_key = tuple((0, int(p)) if p.isdigit() else (1, p.lower()) for p in parts)
            return step_key, item["filename"].lower(), item["ri"]

        if use_draft:
            entry_by_id = {entry["row_id"]: entry for entry in entries}
            if self._order_draft_row_ids is None or not self._order_draft_dirty:
                self._order_draft_row_ids = [entry["row_id"] for entry in assigned]
                self._order_draft_start_order = 0
            else:
                self._order_draft_row_ids = [
                    row_id
                    for row_id in self._order_draft_row_ids
                    if row_id in entry_by_id
                ]
            draft_ids = set(self._order_draft_row_ids)
            draft_assigned = []
            for offset, row_id in enumerate(self._order_draft_row_ids):
                entry = dict(entry_by_id[row_id])
                entry["order"] = self._order_draft_start_order + offset
                draft_assigned.append(entry)
            unassigned = [
                entry
                for entry in entries
                if entry["row_id"] not in draft_ids
            ]
            assigned = draft_assigned

        unassigned.sort(key=unassigned_key)
        return assigned, unassigned

    def _refresh_order_tab(self):
        if not self.model or not self._order_chain_inner or not self._order_unassigned_list:
            return
        self._cancel_order_drag()
        for child in self._order_chain_inner.winfo_children():
            child.destroy()
        self._order_chain_items = []
        self._order_chain_end_indicator = None

        assigned, unassigned = self._order_code_entries(use_draft=True)
        self._order_chain_summary_var.set(f"{len(assigned)} 项")
        self._order_unassigned_summary_var.set(f"{len(unassigned)} 项")
        draft_state = "normal" if self._order_draft_dirty else "disabled"
        if self._order_finish_btn:
            self._order_finish_btn.config(state=draft_state)
        if self._order_discard_btn:
            self._order_discard_btn.config(state=draft_state)
        if self._order_draft_dirty:
            self._order_draft_status_var.set(
                "当前为调整草稿；点击“完成调整并应用”后才会更新到结构编辑。"
            )
        else:
            self._order_draft_status_var.set("当前顺序已同步到结构编辑。")

        if assigned:
            for index, entry in enumerate(assigned):
                self._create_order_chain_item(index, entry, index == len(assigned) - 1)
            self._order_chain_end_indicator = tk.Frame(
                self._order_chain_inner,
                bg=PALETTE["surface"],
                height=3,
            )
            self._order_chain_end_indicator.pack(fill="x", padx=(74, 14), pady=(0, 6))
        else:
            empty = tk.Frame(self._order_chain_inner, bg=PALETTE["surface"])
            empty.pack(fill="both", expand=True, padx=16, pady=36)
            tk.Label(
                empty,
                text="当前执行链为空",
                bg=PALETTE["surface"],
                fg=PALETTE["secondary"],
                font=(FONT, 11, "bold"),
            ).pack()
            tk.Label(
                empty,
                text="从右侧双击代码，或选中后点击“加入链尾”。",
                bg=PALETTE["surface"],
                fg=PALETTE["muted"],
                font=(FONT, 9),
            ).pack(pady=(5, 0))

        self._order_unassigned_list.delete(0, "end")
        self._order_unassigned_row_ids = []
        for entry in unassigned:
            self._order_unassigned_list.insert("end", entry["label"])
            self._order_unassigned_row_ids.append(entry["row_id"])
        if not unassigned:
            self._order_unassigned_list.insert("end", "（所有代码均已分配）")
            try:
                self._order_unassigned_list.itemconfig(0, fg=PALETTE["muted"])
            except Exception:
                pass
        self.after_idle(self._sync_order_chain_canvas)

    def _create_order_chain_item(self, index, entry, is_last):
        wrapper = tk.Frame(self._order_chain_inner, bg=PALETTE["surface"])
        wrapper.pack(fill="x")
        indicator = tk.Frame(wrapper, bg=PALETTE["surface"], height=3)
        indicator.pack(fill="x", padx=(74, 14), pady=(3, 1))

        row = tk.Frame(wrapper, bg=PALETTE["surface"])
        row.pack(fill="x")
        rail = tk.Frame(row, bg=PALETTE["surface"], width=72)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        tk.Label(
            rail,
            text=str(entry["order"]),
            bg=PALETTE["surface"],
            fg=PALETTE["secondary"],
            font=(FONT, 11, "bold"),
        ).pack(pady=(11, 0))
        if not is_last:
            tk.Label(
                rail,
                text="│",
                bg=PALETTE["surface"],
                fg=PALETTE["border"],
                font=("Consolas", 13),
            ).pack(fill="y", expand=True)

        card = tk.Frame(
            row,
            bg=PALETTE["input_bg"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            cursor="fleur",
        )
        card.pack(side="left", fill="x", expand=True, padx=(2, 14), pady=(2, 6), ipady=3)
        handle = tk.Label(
            card,
            text="≡",
            bg=PALETTE["input_bg"],
            fg=PALETTE["muted"],
            font=(FONT, 14, "bold"),
            cursor="fleur",
            padx=10,
        )
        handle.pack(side="left", fill="y")
        title = tk.Label(
            card,
            text=entry["label"],
            bg=PALETTE["input_bg"],
            fg=PALETTE["text"],
            font=(FONT, 10, "bold"),
            anchor="w",
            cursor="fleur",
        )
        title.pack(side="left", fill="x", expand=True, padx=(0, 8), pady=8)
        remove = self._tk_button(
            card,
            "移出",
            lambda rid=entry["row_id"]: self._unassign_order_row(rid),
            small=True,
        )
        remove.pack(side="right", padx=(4, 8), pady=5)

        item = {
            "wrapper": wrapper,
            "indicator": indicator,
            "card": card,
            "handle": handle,
            "title": title,
            "entry": entry,
        }
        self._order_chain_items.append(item)
        for widget in (card, handle, title):
            widget.bind(
                "<ButtonPress-1>",
                lambda event, idx=index: self._start_order_drag(idx, event),
                add="+",
            )
            widget.bind("<B1-Motion>", self._move_order_drag, add="+")
            widget.bind("<ButtonRelease-1>", self._finish_order_drag, add="+")
            widget.bind(
                "<Double-Button-1>",
                lambda _event, rid=entry["row_id"]: self._unassign_order_row(rid),
                add="+",
            )
        for widget in (wrapper, indicator, row, rail, card, handle, title, remove):
            widget.bind("<MouseWheel>", self._on_order_chain_mousewheel, add="+")

    def _create_order_drag_ghost(self, text_value):
        self._destroy_order_drag_ghost()
        try:
            ghost = tk.Toplevel(self)
            ghost.overrideredirect(True)
            try:
                ghost.attributes("-topmost", True)
                ghost.attributes("-alpha", 0.78)
            except Exception:
                pass
            frame = tk.Frame(
                ghost,
                bg=PALETTE["accent_tint"],
                highlightthickness=1,
                highlightbackground=PALETTE["accent"],
            )
            frame.pack(fill="both", expand=True)
            tk.Label(
                frame,
                text=f"≡  {text_value}",
                bg=PALETTE["accent_tint"],
                fg=PALETTE["text"],
                font=(FONT, 10, "bold"),
                anchor="w",
                justify="left",
                wraplength=520,
                padx=14,
                pady=10,
            ).pack(fill="both", expand=True)
            ghost.update_idletasks()
            self._order_drag_ghost = ghost
        except Exception:
            self._order_drag_ghost = None

    def _move_order_drag_ghost(self, x_root, y_root):
        ghost = self._order_drag_ghost
        if not ghost:
            return
        try:
            ghost.geometry(f"+{int(x_root) + 18}+{int(y_root) + 14}")
        except Exception:
            pass

    def _destroy_order_drag_ghost(self):
        if self._order_drag_ghost:
            try:
                self._order_drag_ghost.destroy()
            except Exception:
                pass
        self._order_drag_ghost = None

    def _start_order_drag(self, index, event):
        if not (0 <= index < len(self._order_chain_items)):
            return
        self._order_drag = {
            "from_index": index,
            "drop_index": index,
            "start_x": int(event.x_root),
            "start_y": int(event.y_root),
            "active": False,
        }

    def _activate_order_drag(self, event):
        if not self._order_drag or self._order_drag.get("active"):
            return
        index = self._order_drag["from_index"]
        entry = self._order_chain_items[index]["entry"]
        self._order_drag["active"] = True
        item = self._order_chain_items[index]
        item["card"].configure(bg=PALETTE["accent_soft"])
        item["handle"].configure(bg=PALETTE["accent_soft"], fg=PALETTE["border"])
        item["title"].configure(bg=PALETTE["accent_soft"], fg=PALETTE["muted"])
        self._create_order_drag_ghost(entry["label"])
        self._move_order_drag_ghost(event.x_root, event.y_root)
        self._set_order_drop_indicator(index)

    def _order_drop_index_from_pointer(self, y_root):
        for index, item in enumerate(self._order_chain_items):
            card = item["card"]
            try:
                midpoint = card.winfo_rooty() + card.winfo_height() / 2
            except Exception:
                continue
            if y_root < midpoint:
                return index
        return len(self._order_chain_items)

    def _auto_scroll_order_chain(self, y_root):
        canvas = self._order_chain_canvas
        if not canvas:
            return
        try:
            top = canvas.winfo_rooty()
            bottom = top + canvas.winfo_height()
            if y_root < top + 34:
                canvas.yview_scroll(-1, "units")
            elif y_root > bottom - 34:
                canvas.yview_scroll(1, "units")
        except Exception:
            pass

    def _set_order_drop_indicator(self, drop_index):
        for item in self._order_chain_items:
            item["indicator"].configure(bg=PALETTE["surface"])
        if self._order_chain_end_indicator:
            self._order_chain_end_indicator.configure(bg=PALETTE["surface"])
        if 0 <= drop_index < len(self._order_chain_items):
            self._order_chain_items[drop_index]["indicator"].configure(bg=PALETTE["accent"])
        elif drop_index == len(self._order_chain_items) and self._order_chain_end_indicator:
            self._order_chain_end_indicator.configure(bg=PALETTE["accent"])

    def _move_order_drag(self, event):
        if not self._order_drag:
            return
        if not self._order_drag.get("active"):
            dx = int(event.x_root) - self._order_drag.get("start_x", int(event.x_root))
            dy = int(event.y_root) - self._order_drag.get("start_y", int(event.y_root))
            if dx * dx + dy * dy < 25:
                return
            self._activate_order_drag(event)
        self._auto_scroll_order_chain(event.y_root)
        drop_index = self._order_drop_index_from_pointer(event.y_root)
        self._order_drag["drop_index"] = drop_index
        self._set_order_drop_indicator(drop_index)
        self._move_order_drag_ghost(event.x_root, event.y_root)
        return "break"

    def _finish_order_drag(self, _event=None):
        drag = dict(self._order_drag or {})
        from_index = drag.get("from_index")
        drop_index = drag.get("drop_index")
        row_ids = [item["entry"]["row_id"] for item in self._order_chain_items]
        self._cancel_order_drag()
        if not drag.get("active") or from_index is None or drop_index is None:
            return "break"
        if not (0 <= from_index < len(row_ids)):
            return "break"
        moved_id = row_ids.pop(from_index)
        if drop_index > from_index:
            drop_index -= 1
        drop_index = max(0, min(int(drop_index), len(row_ids)))
        row_ids.insert(drop_index, moved_id)
        if drop_index == from_index:
            return "break"
        self._update_order_draft(row_ids)
        return "break"

    def _cancel_order_drag(self):
        drag = self._order_drag or {}
        from_index = drag.get("from_index")
        if drag.get("active") and isinstance(from_index, int) and 0 <= from_index < len(self._order_chain_items):
            item = self._order_chain_items[from_index]
            try:
                item["card"].configure(bg=PALETTE["input_bg"])
                item["handle"].configure(bg=PALETTE["input_bg"], fg=PALETTE["muted"])
                item["title"].configure(bg=PALETTE["input_bg"], fg=PALETTE["text"])
            except Exception:
                pass
        self._set_order_drop_indicator(-1)
        self._destroy_order_drag_ghost()
        self._order_drag = None

    def _update_order_draft(self, row_ids):
        if not self.model:
            return
        unique_ids = []
        seen = set()
        for row_id in row_ids:
            row = self._find_row_by_id(row_id)
            if (
                row_id
                and row_id not in seen
                and row is not None
                and self.model.cell(row, "代码/说明") == "代码"
            ):
                seen.add(row_id)
                unique_ids.append(row_id)
        self._order_draft_row_ids = unique_ids
        self._order_draft_start_order = 0
        self._order_draft_dirty = True
        self.status_var.set("顺序调整为草稿状态；点击“完成调整并应用”后才会写入。")
        self._refresh_order_tab()

    def _apply_order_chain(self, row_ids, status_message):
        if not self.model:
            return
        unique_ids = []
        seen = set()
        for row_id in row_ids:
            if row_id and row_id not in seen:
                row = self._find_row_by_id(row_id)
                if row is not None and self.model.cell(row, "代码/说明") == "代码":
                    seen.add(row_id)
                    unique_ids.append(row_id)

        start_order = 0

        self._push_undo()
        assigned_set = set(unique_ids)
        for row in self.rows:
            if self.model.cell(row, "代码/说明") != "代码":
                continue
            row_id = self._row_id(row)
            if row_id not in assigned_set and _parse_run_order_value(self.model.cell(row, "运行顺序")) is not None:
                self.model._set_on(row, "运行顺序", None)
        for offset, row_id in enumerate(unique_ids):
            row = self._find_row_by_id(row_id)
            if row is not None:
                self.model._set_on(row, "运行顺序", str(start_order + offset))
        self.model.normalize_run_orders(rebuild=False)
        self._sort_rows()
        self.model.rebuild()
        # 当前链已经被用户明确确认并写入，打开文件时记录的旧缺口不再有效。
        self._legacy_run_order_audit = None
        self._mark_dirty(status_message)
        self._log("顺序链已更新：" + " → ".join(
            self.model.cell(self._find_row_by_id(row_id), "相应代码和说明文件")
            for row_id in unique_ids
            if self._find_row_by_id(row_id) is not None
        ))
        self.populate_tree()
        self._update_undo_buttons()

    def _commit_order_draft(self, switch_to_editor=True):
        if not self._order_draft_dirty:
            self.status_var.set("顺序没有待应用的调整。")
            return False
        row_ids = list(self._order_draft_row_ids or [])
        self._order_draft_dirty = False
        self._order_draft_row_ids = None
        self._apply_order_chain(
            row_ids,
            "顺序调整已应用到结构编辑（未保存）",
        )
        if switch_to_editor and self.main_notebook and self._editor_tab:
            try:
                self.main_notebook.select(self._editor_tab)
            except Exception:
                pass
        return True

    def _discard_order_draft(self):
        self._cancel_order_drag()
        self._order_draft_row_ids = None
        self._order_draft_start_order = 0
        self._order_draft_dirty = False
        self._refresh_order_tab()
        self.status_var.set("已放弃本次顺序调整；结构编辑中的顺序未改变。")

    def _unassign_order_row(self, row_id):
        self._cancel_order_drag()
        assigned, _unassigned = self._order_code_entries(use_draft=True)
        row_ids = [entry["row_id"] for entry in assigned if entry["row_id"] != row_id]
        if len(row_ids) == len(assigned):
            return "break"
        self._update_order_draft(row_ids)
        return "break"

    def _assign_order_rows(self, row_ids):
        assigned, _unassigned = self._order_code_entries(use_draft=True)
        current_ids = [entry["row_id"] for entry in assigned]
        append_ids = [row_id for row_id in row_ids if row_id and row_id not in current_ids]
        if not append_ids:
            return
        self._update_order_draft(current_ids + append_ids)

    def _assign_selected_order_rows(self):
        if not self._order_unassigned_list:
            return
        selected_ids = []
        for index in self._order_unassigned_list.curselection():
            if 0 <= index < len(self._order_unassigned_row_ids):
                selected_ids.append(self._order_unassigned_row_ids[index])
        self._assign_order_rows(selected_ids)

    def _on_unassigned_double_click(self, event):
        if not self._order_unassigned_list or not self._order_unassigned_row_ids:
            return "break"
        index = self._order_unassigned_list.nearest(event.y)
        if 0 <= index < len(self._order_unassigned_row_ids):
            self._assign_order_rows([self._order_unassigned_row_ids[index]])
        return "break"

    def _refresh_global_mapping_tab(self):
        if not hasattr(self, "mapping_text"):
            return
        self.mapping_text.config(state="normal")
        self.mapping_text.delete("1.0", "end")
        
        self.mapping_text.tag_configure("warn", foreground="#ffb86c") # 黄色警告
        self.mapping_text.tag_configure("error", foreground="#ff5555") # 红色错误
        
        # 1. 收集命名冲突
        conflict_row_ids = set()
        for conflict in self._collect_saved_name_conflicts():
            conflict_row_ids.update(conflict["row_ids"])
            
        # 2. 解析所有文件并分组
        codes = []
        docs = []
        for ri, row in enumerate(self.rows):
            file_type = _clean(self.model.cell(row, "代码/说明"))
            if file_type not in ("代码", "说明"):
                continue
            
            step_val = _clean(self._effective_step_for_row(ri))
            step_num = float('inf')
            if step_val and step_val.isdigit():
                step_num = int(step_val)
            
            order_val = _clean(self.model.cell(row, "运行顺序"))
            order_num = float('inf')
            if order_val and order_val.isdigit():
                order_num = int(order_val)
            
            name = _clean(self.model.cell(row, "相应代码和说明文件"))
            subfolder = _clean(self.model.cell(row, "代码子文件夹"))
            row_id = self._row_id(row)
            
            # 校验异常
            status = "normal"
            if file_type == "说明" and name.endswith(".docx"):
                if subfolder: status = "warn"
            elif file_type == "代码" and name.endswith(".py"):
                if subfolder in ("更新代码", "notebook"): status = "warn"
            elif file_type == "代码" and name.endswith(".ipynb"):
                if subfolder != "notebook": status = "warn"
                
            if row_id in conflict_row_ids:
                status = "error"
                
            item = {
                "row": row,
                "row_id": row_id,
                "step_val": step_val,
                "step_num": step_num,
                "order_val": order_val,
                "order_num": order_num,
                "ri": ri,
                "status": status,
                "name": name,
                "subfolder": subfolder,
                "file_type": file_type
            }
            if file_type == "代码":
                codes.append(item)
            else:
                docs.append(item)
                
        # 2. 建立说明到代码的映射，找出孤立说明
        doc_to_codes = self._build_doc_to_codes_from_rows()
        code_id_to_docs = {}
        for doc_id, c_ids in doc_to_codes.items():
            for c_id in c_ids:
                code_id_to_docs.setdefault(c_id, []).append(doc_id)
                
        # 3. 按规则生成显示列表
        # 规则：按代码的运行顺序排，说明紧跟在绑定的代码下方；无顺序代码或孤立说明放最后
        codes.sort(key=lambda x: (x["step_num"], x["order_num"], x["ri"]))
        
        display_blocks = []
        
        # 处理有顺序/步骤的代码，以及它们绑定的说明
        processed_doc_ids = set()
        for code in codes:
            block = [code]
            c_id = code["row_id"]
            # 找出绑定到这个代码的说明
            if c_id in code_id_to_docs:
                bound_doc_ids = code_id_to_docs[c_id]
                for doc in docs:
                    if doc["row_id"] in bound_doc_ids:
                        block.append(doc)
                        processed_doc_ids.add(doc["row_id"])
            display_blocks.append(block)
            
        # 处理孤立的说明（没有绑定到任何代码）
        isolated_docs = [doc for doc in docs if doc["row_id"] not in processed_doc_ids]
        isolated_docs.sort(key=lambda x: (x["step_num"], x["order_num"], x["ri"]))
        for doc in isolated_docs:
            display_blocks.append([doc])
            
        # 4. 渲染到界面，块之间空一行
        for i, block in enumerate(display_blocks):
            for item in block:
                row = item["row"]
                step_val = item["step_val"] or "无"
                
                segs = self.model._segments(row)
                subfolders = "/".join(segs[1:-1]) if len(segs) > 2 else ""
                if subfolders:
                    subfolders += "/"
                    
                name = item["name"]
                file_type = item["file_type"]
                # 只有代码类型且代码子文件夹真的不为空时，才加子文件夹路径
                code_subfolder = item["subfolder"]
                saved_name = _clean(self.model.cell(row, "保存在资料中的名称"))
                
                target_folder = f"资料/{file_type}"
                if file_type == "代码" and code_subfolder:
                    target_folder += f"/{code_subfolder}"
                    
                order_str = f"[{item['order_val']}] " if item['order_val'] else "[ ] "
                line = f"{order_str}step_{step_val} {subfolders}{name} → {target_folder} {saved_name}\n"
                
                tag = item["status"]
                self.mapping_text.insert("end", line, tag if tag != "normal" else ())
            
            # 块之间加空行
            if i < len(display_blocks) - 1:
                self.mapping_text.insert("end", "\n")
                
        self.mapping_text.config(state="disabled")

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

        # 主体：结构编辑 + 独立的顺序调整工作台
        body = tk.Frame(self, bg=PALETTE["app_bg"])
        body.pack(side="top", fill="both", expand=True)
        self.main_notebook = ttk.Notebook(body)
        self.main_notebook.pack(fill="both", expand=True)
        self._editor_tab = tk.Frame(self.main_notebook, bg=PALETTE["app_bg"])
        self.main_notebook.add(self._editor_tab, text="结构编辑")
        self._order_tab = tk.Frame(self.main_notebook, bg=PALETTE["surface"])
        self.main_notebook.add(self._order_tab, text="顺序调整")
        self.main_notebook.bind("<<NotebookTabChanged>>", self._on_main_tab_changed, add="+")

        # 左
        left = tk.Frame(self._editor_tab, bg=PALETTE["panel"], width=520)
        left.pack(side="left", fill="both")
        left.pack_propagate(False)
        ltool = tk.Frame(left, bg=PALETTE["panel"])
        ltool.pack(side="top", fill="x", padx=8, pady=8)
        tk.Label(ltool, text="文件夹树", bg=PALETTE["panel"], fg=PALETTE["secondary"],
                 font=(FONT, 10, "bold")).pack(side="left")
        ltool_actions = self._responsive_button_bar(
            ltool,
            [
                {"text": "＋ 步骤文件夹", "cmd": self.on_add_step_folder, "small": True},
                {"text": "＋ 输出文件夹", "cmd": self.on_add_output_folder, "small": True},
                {"text": "＋ 文件夹", "cmd": self.on_add_folder, "small": True},
                {"text": "＋ 文件", "cmd": self.on_add_file, "small": True},
                {"text": "展开全部", "cmd": self.on_expand_all, "small": True},
                {"text": "收起全部", "cmd": self.on_collapse_all, "small": True},
                {"text": "剪切", "cmd": self.on_cut, "small": True},
                {"text": "粘贴", "cmd": self.on_paste, "small": True},
                {"text": "删除", "cmd": self.on_delete, "small": True, "danger": True},
            ],
            small=True,
            min_button_width=92,
        )
        ltool_actions.pack(side="right", fill="x", expand=True, padx=(12, 0))

        treewrap = tk.Frame(left, bg=PALETTE["surface"], highlightthickness=1,
                            highlightbackground=PALETTE["border"])
        treewrap.pack(side="top", fill="both", expand=True, padx=8, pady=(0, 8))
        self.tree = ttk.Treeview(treewrap, style="FS.Treeview", show="tree headings",
                                 columns=("type", "order", "group"), selectmode="extended")
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

        # 右侧（用 Notebook 包装）
        self.notebook = ttk.Notebook(self._editor_tab)
        self.notebook.pack(side="left", fill="both", expand=True)

        right = tk.Frame(self.notebook, bg=PALETTE["surface"])
        self.notebook.add(right, text="详情与编辑")

        log_frame = tk.Frame(self.notebook, bg=PALETTE["surface"])
        self.notebook.add(log_frame, text="操作日志")
        
        self.log_text = tk.Text(log_frame, bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 10), state="disabled", wrap="word")
        log_vsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_vsb.set)
        log_vsb.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

        mapping_frame = tk.Frame(self.notebook, bg=PALETTE["surface"])
        self.notebook.add(mapping_frame, text="全局映射视图")
        
        self.mapping_text = tk.Text(mapping_frame, bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 10), state="disabled", wrap="none")
        mapping_vsb = ttk.Scrollbar(mapping_frame, orient="vertical", command=self.mapping_text.yview)
        mapping_hsb = ttk.Scrollbar(mapping_frame, orient="horizontal", command=self.mapping_text.xview)
        self.mapping_text.configure(yscrollcommand=mapping_vsb.set, xscrollcommand=mapping_hsb.set)
        mapping_vsb.pack(side="right", fill="y")
        mapping_hsb.pack(side="bottom", fill="x")
        self.mapping_text.pack(side="left", fill="both", expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        rhead = tk.Frame(right, bg=PALETTE["surface"])
        rhead.pack(side="top", fill="x")
        self.right_title = tk.Label(rhead, text="文件详情", bg=PALETTE["surface"],
                                    fg=PALETTE["secondary"], font=(FONT, 10, "bold"), anchor="w",
                                    padx=18, pady=10)
        self.right_title.pack(fill="x")
        detail_wrap = tk.Frame(right, bg=PALETTE["surface"])
        detail_wrap.pack(side="top", fill="both", expand=True)
        self._detail_canvas = tk.Canvas(
            detail_wrap,
            bg=PALETTE["surface"],
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        detail_vsb = ttk.Scrollbar(detail_wrap, orient="vertical", command=self._detail_canvas.yview)
        self._detail_canvas.configure(yscrollcommand=detail_vsb.set)
        detail_vsb.pack(side="right", fill="y")
        self._detail_canvas.pack(side="left", fill="both", expand=True)
        self.detail = tk.Frame(self._detail_canvas, bg=PALETTE["surface"])
        self._detail_window_id = self._detail_canvas.create_window((0, 0), window=self.detail, anchor="nw")
        self.detail.bind("<Configure>", self._sync_detail_canvas, add="+")
        self._detail_canvas.bind("<Configure>", self._sync_detail_canvas, add="+")
        self.detail.bind("<MouseWheel>", self._on_detail_mousewheel, add="+")
        self._detail_canvas.bind("<MouseWheel>", self._on_detail_mousewheel, add="+")

        detail_actions = tk.Frame(
            right,
            bg=PALETTE["surface"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
        )
        detail_actions.pack(side="bottom", fill="x")
        tk.Label(
            detail_actions,
            text="Shift+Enter：弹出确认，Enter 执行应用，点击别处取消。",
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=(FONT, 8),
            anchor="w",
            padx=18,
            pady=8,
        ).pack(side="left", fill="x", expand=True)
        self._detail_action_btn = self._tk_button(
            detail_actions,
            "应用修改",
            self._run_detail_apply,
            primary=True,
        )
        self._detail_action_btn.pack(side="right", padx=16, pady=10)
        self._detail_action_btn.config(state="disabled")
        self._build_order_tab(self._order_tab)

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
        self.bind("<Control-x>", lambda e: self.on_cut())
        self.bind("<Control-X>", lambda e: self.on_cut())
        self.bind("<Control-v>", lambda e: self.on_paste())
        self.bind("<Control-V>", lambda e: self.on_paste())
        self.bind("<Escape>", lambda _e: self._cancel_order_drag(), add="+")
        self.bind_all("<Shift-Return>", self._request_detail_apply, add="+")
        self.bind_all("<Shift-KP_Enter>", self._request_detail_apply, add="+")

    def _tk_button(self, parent, text, cmd, primary=False, small=False, danger=False):
        bg = PALETTE["accent"] if primary else PALETTE["surface"]
        fg = "#FFFFFF" if primary else (PALETTE["danger"] if danger else PALETTE["secondary"])
        b = tk.Button(parent, text=text, command=cmd, font=(FONT, 9 if small else 10, "bold"),
                      bg=bg, fg=fg, relief="flat", bd=0, cursor="hand2",
                      activebackground=PALETTE["accent_hover"] if primary else PALETTE["input_bg"],
                      activeforeground=fg, padx=10 if small else 14, pady=4 if small else 7,
                      highlightthickness=1, highlightbackground=PALETTE["border"])
        return b

    def _responsive_button_bar(self, parent, specs, small=False, min_button_width=96):
        wrap = tk.Frame(parent, bg=parent.cget("bg"))
        buttons = []
        for spec in specs:
            btn = self._tk_button(
                wrap,
                spec["text"],
                spec["cmd"],
                primary=spec.get("primary", False),
                small=small or spec.get("small", False),
                danger=spec.get("danger", False),
            )
            buttons.append(btn)

        def _relayout(_event=None):
            count = len(buttons)
            if count == 0:
                return
            width = max(wrap.winfo_width(), 1)
            columns = max(1, min(count, width // min_button_width))
            for child in buttons:
                child.grid_forget()
            for ci in range(count):
                wrap.grid_columnconfigure(ci, weight=0, uniform="")
            for ci in range(columns):
                wrap.grid_columnconfigure(ci, weight=1, uniform=f"btnbar_{id(wrap)}")
            for idx, btn in enumerate(buttons):
                row = idx // columns
                col = idx % columns
                btn.grid(row=row, column=col, sticky="ew", padx=3, pady=3)

        wrap.bind("<Configure>", _relayout, add="+")
        wrap.after(0, _relayout)
        return wrap

    def _sync_detail_canvas(self, _event=None):
        if not self._detail_canvas or not self._detail_window_id:
            return
        try:
            self._detail_canvas.itemconfigure(self._detail_window_id, width=self._detail_canvas.winfo_width())
            self._detail_canvas.configure(scrollregion=self._detail_canvas.bbox("all"))
        except Exception:
            pass

    def _on_detail_mousewheel(self, event):
        if not self._detail_canvas:
            return "break"
        try:
            delta = event.delta
            if delta:
                self._detail_canvas.yview_scroll(int(-delta / 120), "units")
        except Exception:
            pass
        return "break"

    def _bind_mousewheel_recursive(self, widget):
        widget.bind("<MouseWheel>", self._on_detail_mousewheel, add="+")
        for child in widget.winfo_children():
            # Don't bind to listbox/text if they need their own scroll, but here it's fine for simple listbox if it's small, 
            # or we just skip if it's a Listbox that has its own scrollbar.
            if not isinstance(child, (tk.Listbox, tk.Text)):
                self._bind_mousewheel_recursive(child)

    def _clear_detail_panel(self):
        self._detail_state = {}
        self._close_confirm_popup()
        self._set_detail_apply_action(None)
        for w in self.detail.winfo_children():
            w.destroy()
        if self._detail_canvas:
            try:
                self._detail_canvas.yview_moveto(0)
            except Exception:
                pass

    def _set_detail_apply_action(self, command):
        self._active_detail_apply = command if callable(command) else None
        if not self._detail_action_btn:
            return
        state = "normal" if self._active_detail_apply else "disabled"
        try:
            self._detail_action_btn.config(state=state)
        except Exception:
            pass

    def _close_confirm_popup(self):
        popup = self._confirm_popup
        self._confirm_popup = None
        if popup is None:
            return
        try:
            popup.destroy()
        except Exception:
            pass

    def _run_detail_apply(self):
        command = self._active_detail_apply
        self._close_confirm_popup()
        if not callable(command):
            self.status_var.set("当前没有可应用的详情修改。")
            return
        command()

    def _show_detail_confirm_popup(self):
        if not callable(self._active_detail_apply):
            self.status_var.set("当前没有可应用的详情修改。")
            return
        if self._confirm_popup is not None:
            try:
                self._confirm_popup.focus_force()
            except Exception:
                pass
            return
        popup = tk.Toplevel(self)
        popup.transient(self)
        popup.overrideredirect(True)  # 去除系统窗口边框，避免看起来像“蘑菇”
        popup.configure(bg=PALETTE["surface"])
        popup.attributes("-topmost", True)
        frame = tk.Frame(
            popup,
            bg=PALETTE["surface"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            padx=16,
            pady=16,
        )
        frame.pack(fill="both", expand=True)
        tk.Label(
            frame,
            text="确认应用当前修改吗？",
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            font=(FONT, 10, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            frame,
            text="按 Enter 确认\n点击其他地方或按 Esc 取消",
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=(FONT, 9),
            anchor="w",
            justify="left",
            pady=8,
        ).pack(fill="x")
        
        btn_wrap = tk.Frame(frame, bg=PALETTE["surface"])
        btn_wrap.pack(fill="x", pady=(4, 0))
        self._tk_button(btn_wrap, "确认 (Enter)", self._run_detail_apply, primary=True, small=True).pack(side="right")
        self._tk_button(btn_wrap, "取消 (Esc)", self._close_confirm_popup, small=True).pack(side="right", padx=8)

        def _on_focus_out(_event=None):
            popup.after(50, self._dismiss_confirm_if_focus_lost)

        popup.bind("<FocusOut>", _on_focus_out, add="+")
        popup.bind("<Escape>", lambda _e: self._close_confirm_popup())
        popup.bind("<Return>", lambda _e: self._run_detail_apply())
        popup.bind("<KP_Enter>", lambda _e: self._run_detail_apply())

        anchor = self._detail_action_btn or self
        try:
            popup.update_idletasks()
            x = anchor.winfo_rootx() + max(anchor.winfo_width() - popup.winfo_reqwidth(), 0)
            y = anchor.winfo_rooty() - popup.winfo_reqheight() - 8
            if y < self.winfo_rooty() + 40:
                y = anchor.winfo_rooty() + anchor.winfo_height() + 8
            popup.geometry(f"+{x}+{y}")
        except Exception:
            pass
        self._confirm_popup = popup
        try:
            popup.focus_force()
        except Exception:
            pass

    def _dismiss_confirm_if_focus_lost(self):
        popup = self._confirm_popup
        if popup is None:
            return
        try:
            focus_widget = popup.focus_displayof()
        except Exception:
            focus_widget = None
        if focus_widget is None or focus_widget.winfo_toplevel() is not popup:
            self._close_confirm_popup()

    def _request_detail_apply(self, event=None):
        if event is not None:
            try:
                if event.widget.winfo_toplevel() is not self:
                    return
            except Exception:
                return
        self._show_detail_confirm_popup()
        return "break"

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
        # 加载后先排序
        self._sort_rows()
        self.model = FileTreeModel(self.header, self.rows)
        self.model.ensure_row_ids()
        initial_order_audit = self._collect_run_order_save_audit()
        self._legacy_run_order_audit = (
            copy.deepcopy(initial_order_audit)
            if self._run_order_issue_lines(initial_order_audit)
            else None
        )
        normalized_orders = self.model.normalize_run_orders()
        # 重建 doc_to_codes 和绑定 tokens
        self._doc_to_codes = self._build_doc_to_codes_from_rows()
        self._recompute_and_write_binding_tokens()
        self.model.rebuild()
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
        if normalized_orders:
            self.dirty = True
            self.status_var.set(
                f"已加载 {len(self.rows)} 行 · 已自动补齐运行顺序（{normalized_orders} 处，未保存）"
            )
            self._log(f"加载时发现运行顺序空位或非法值，已自动连续化 {normalized_orders} 处。")
        else:
            self.status_var.set(f"已加载 {len(self.rows)} 行 · 工作区：{self.award_name}")

    def _row_id(self, row):
        if not self.model:
            return ""
        return self.model.row_id(row)

    def _find_row_index_by_id(self, row_id):
        if not row_id:
            return -1
        for ri, row in enumerate(self.rows):
            if self._row_id(row) == row_id:
                return ri
        return -1

    def _find_row_by_id(self, row_id):
        ri = self._find_row_index_by_id(row_id)
        if 0 <= ri < len(self.rows):
            return self.rows[ri]
        return None

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

    def _display_path(self, path):
        if not self.model:
            return tuple(path)
        return self.model._display_path(path)

    def _display_path_name(self, item):
        if not self.model:
            return item
        return self.model._display_seg(item)

    def _usage_owner_text(self, owner):
        if isinstance(owner, tuple):
            if self.model and self.model._is_top_key(owner):
                return str(self._display_path_name(owner))
            parts = [str(self._display_path_name(part)) for part in owner]
            return " / ".join(part for part in parts if part)
        return str(owner)

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

    def _suggest_saved_name_base(self, ri, file_type, selected_code_ids=None):
        if not (0 <= ri < len(self.rows)):
            return "readme" if file_type == "说明" else "code"
        row = self.rows[ri]
        deploy_name = self.model.cell(row, "相应代码和说明文件")
        deploy_base, _ = self._split_file_name_for_form(deploy_name, file_type)
        deploy_num, _ = self._split_numbered_name(deploy_base, count=1)
        sub_num = deploy_num[0] if deploy_num else ""
        if file_type == "说明":
            return f"readme{sub_num}" if sub_num else "readme"
        step_value = _clean(self._effective_step_for_row(ri))
        step_num = step_value if step_value.isdigit() and 0 <= int(step_value) <= NAME_NUMBER_LIMIT else ""
        return self._compose_numbered_name([step_num, sub_num], "code", fallback_name="code")

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
            doc_id = self._row_id(row)
            if not doc_id:
                continue
            tokens = _split_binding_tokens(self.model.cell(row, "其他"))
            if not tokens:
                continue
            doc_to_codes.setdefault(doc_id, set())
            for token in tokens:
                token_to_doc.setdefault(token, []).append(doc_id)
        for ri, row in enumerate(self.rows):
            if not self.model.cell(row, "相应代码和说明文件"):
                continue
            if self.model.cell(row, "代码/说明") != "代码":
                continue
            code_id = self._row_id(row)
            if not code_id:
                continue
            for token in _split_binding_tokens(self.model.cell(row, "其他")):
                for doc_id in token_to_doc.get(token, []):
                    doc_to_codes.setdefault(doc_id, set()).add(code_id)
        return doc_to_codes

    def _recompute_and_write_binding_tokens(self):
        doc_ids = {}
        id_iter = _iter_short_ids()
        for ri, row in enumerate(self.rows):
            if not self.model.cell(row, "相应代码和说明文件"):
                continue
            if self.model.cell(row, "代码/说明") != "说明":
                continue
            row_id = self._row_id(row)
            if not row_id:
                continue
            code_set = set(self._doc_to_codes.get(row_id, set()))
            allowed = {self._row_id(self.rows[cri]) for cri, _ in self._codes_in_same_step(ri)}
            code_set = {c for c in code_set if c in allowed}
            if not code_set:
                doc_ids[row_id] = ""
                continue
            doc_ids[row_id] = next(id_iter)
        code_to_doc_ids = {}
        for doc_row_id, token in doc_ids.items():
            if not token:
                continue
            for code_row_id in self._doc_to_codes.get(doc_row_id, set()):
                code_to_doc_ids.setdefault(code_row_id, set()).add(token)
        for ri, row in enumerate(self.rows):
            if not self.model.cell(row, "相应代码和说明文件"):
                continue
            typ = self.model.cell(row, "代码/说明")
            row_id = self._row_id(row)
            if typ == "说明":
                self.model._set_on(row, "其他", doc_ids.get(row_id, "") or None)
            elif typ == "代码":
                tokens = sorted(code_to_doc_ids.get(row_id, set()))
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

    def _collect_saved_name_conflicts(self):
        seen = {}
        conflicts = []
        for ri, row in enumerate(self.rows):
            saved_name = self.model.cell(row, "保存在资料中的名称")
            if not saved_name:
                continue
            seen.setdefault(saved_name.lower(), []).append((ri, row, saved_name))
        for _key, items in seen.items():
            if len(items) <= 1:
                continue
            labels = []
            row_ids = []
            saved_name = items[0][2]
            for ri, row, _ in items:
                deployed = self.model.cell(row, "相应代码和说明文件")
                segs = self.model._segments(row)
                rel_dir = "/".join([s for s in segs if s]) or "（工作区根目录）"
                labels.append(f"第 {ri + 2} 行 · {rel_dir} · {deployed or saved_name}")
                rid = self._row_id(row)
                if rid:
                    row_ids.append(rid)
            conflicts.append({
                "saved_name": saved_name,
                "items": labels,
                "row_ids": row_ids,
            })
        return conflicts

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
        self._sort_rows()
        self._doc_to_codes = self._build_doc_to_codes_from_rows()
        self._recompute_and_write_binding_tokens()
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

    def on_expand_all(self):
        self._preserve_manual_open_state = True
        self._open_paths = {tuple(meta[1]) for _iid, meta in self._item_meta.items() if meta[0] == "folder"}
        self.populate_tree()
        self.status_var.set("已展开全部文件夹。")

    def on_collapse_all(self):
        self._preserve_manual_open_state = True
        self._open_paths = set()
        self.populate_tree()
        self.status_var.set("已收起全部文件夹。")

    def populate_tree(self):
        # 重建前先记住展开状态，避免每次都全部展开
        if not self._first_populate and getattr(self, "_preserve_manual_open_state", False) is not True:
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
        self._preserve_manual_open_state = False
        self._refresh_order_tab()

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
            self._item_meta[iid] = ("file", self._row_id(row))

    def _insert_outputs(self, node, parent_iid):
        for ri in node["outputs"]:
            row = self.rows[ri]
            marker = self.model.cell(row, "输出文件")
            code = self.model.cell(row, "对应代码")
            label = f"输出文件 · {marker}" + (f" → {code}" if code else "")
            iid = self.tree.insert(parent_iid, "end", text="📤 " + label,
                                   values=("输出", "", ""), tags=("output",))
            self._item_meta[iid] = ("output", self._row_id(row))

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
        self._order_draft_row_ids = None
        self._order_draft_start_order = 0
        self._order_draft_dirty = False
        self.rows[:] = copy.deepcopy(snapshot)   # 原地替换内容（model 共享同一对象）
        self._sort_rows()
        self.model.normalize_run_orders(rebuild=False)
        self.model.rebuild()
        # 重建 doc_to_codes 映射关系（重要！每次 rows 变化后都要这样做！）
        self._doc_to_codes = self._build_doc_to_codes_from_rows()
        self._recompute_and_write_binding_tokens()
        self._selected = None
        self._selected_batch = []
        self.populate_tree()
        self._update_undo_buttons()

    def _sort_rows(self):
        """始终严格按步骤（step）排序所有行，不管多乱。"""
        step_ci = self.header.index("步骤") if "步骤" in self.header else -1

        def row_key(row):
            step_str = ""
            if step_ci >= 0 and step_ci < len(row):
                step_str = _clean(row[step_ci])
            try:
                return int(step_str)
            except (ValueError, TypeError):
                return float('inf')  # 没有 step 或无效的放最后
        self.rows.sort(key=row_key)

    def _find_row_index(self, target_row):
        for candidate_ri, candidate_row in enumerate(self.rows):
            if candidate_row is target_row:
                return candidate_ri
        return -1

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
            self._selected = None
            self._selected_batch = []
            return
        metas = [self._item_meta.get(iid) for iid in sel]
        metas = [meta for meta in metas if meta]
        if not metas:
            self._selected = None
            self._selected_batch = []
            return
        focus_iid = self.tree.focus()
        meta = self._item_meta.get(focus_iid) if focus_iid else None
        if not meta:
            meta = metas[0]
        self._selected = meta
        self._selected_batch = metas
        kind, key = meta
        self._clear_detail_panel()
        if len(metas) > 1:
            self.right_title.config(text=f"已选中 {len(metas)} 项")
            self._field(self.detail, "批量操作", f"当前已多选 {len(metas)} 项", readonly=True)
            self._field(self.detail, "提示", "可直接按 Delete/Backspace 或点击“删除”进行批量删除。", readonly=True)
            return
        if kind == "file":
            if hasattr(self, "notebook"):
                self.notebook.select(0)
            ri = self._find_row_index_by_id(key)
            if ri != -1:
                self._form_file(ri)
        elif kind == "folder":
            self._form_folder(key)
        elif kind == "output":
            ri = self._find_row_index_by_id(key)
            if ri != -1:
                self._form_output(ri)
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
            return ""
        if not text.startswith("."):
            text = "." + text
        return text

    def _extension_options(self, file_type, current_value=""):
        options = list(CODE_EXTENSION_OPTIONS if file_type == "代码" else DOC_EXTENSION_OPTIONS)
        current = self._normalize_extension(current_value, file_type)
        if current and current not in options:
            options.append(current)
        return options

    def _number_choice_values(self, limit=NAME_NUMBER_LIMIT):
        return [BLANK_OPTION_LABEL] + [str(i) for i in range(0, limit + 1)]

    def _normalize_number_choice(self, value, limit=NAME_NUMBER_LIMIT):
        text = _clean(value)
        if text.isdigit() and 0 <= int(text) <= limit:
            return text
        return BLANK_OPTION_LABEL

    def _save_number_choice(self, value):
        text = _clean(value)
        return "" if text == BLANK_OPTION_LABEL else text

    def _split_numbered_name(self, text, count=1):
        raw = _clean(text)
        if raw == UNNAMED_PLACEHOLDER:
            raw = DEFAULT_NEW_FILE_BASENAME
        numbers = [""] * max(1, int(count or 1))
        if not raw:
            return numbers, ""
        parts = raw.split("_")
        consumed = 0
        max_prefix_count = min(len(numbers), max(0, len(parts) - 1))
        for idx in range(max_prefix_count):
            part = _clean(parts[idx])
            if part.isdigit() and 0 <= int(part) <= NAME_NUMBER_LIMIT:
                numbers[idx] = part
                consumed += 1
            else:
                break
        if consumed > 0:
            remainder = "_".join(parts[consumed:])
            if remainder:
                return numbers, remainder
        return numbers, raw

    def _compose_numbered_name(self, numbers, name, fallback_name=""):
        base_name = _clean(name) or _clean(fallback_name)
        parts = [self._save_number_choice(num) for num in (numbers or [])]
        parts = [p for p in parts if p]
        if base_name:
            parts.append(base_name)
        return "_".join(parts)

    def _split_readme_name(self, text):
        raw = _clean(text)
        if not raw:
            return ""
        match = re.fullmatch(r"readme([0-9]{0,3})", raw, flags=re.IGNORECASE)
        if not match:
            return ""
        num = match.group(1) or ""
        if num.isdigit() and 0 <= int(num) <= README_NUMBER_LIMIT:
            return num
        return ""

    def _split_file_name_for_form(self, name, file_type):
        raw_name = _clean(name)
        base_name, ext_name = os.path.splitext(raw_name)
        if not ext_name:
            base_name = raw_name
            ext_name = ""
        if base_name == UNNAMED_PLACEHOLDER:
            base_name = DEFAULT_NEW_FILE_BASENAME
        return base_name, self._normalize_extension(ext_name, file_type)

    def _compose_file_name(self, base_name, ext_name, fallback_base=""):
        base = _clean(base_name)
        ext = self._normalize_extension(ext_name)
        if not base and fallback_base:
            base = fallback_base
        if not base:
            return ext
        return f"{base}{ext}" if ext else base

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

    def _numbered_name_field(self, parent, label, number_values, name_value, hint="", placeholder="", ext_value=None, ext_readonly=False, ext_choices=None, ext_file_type="代码"):
        wrap = tk.Frame(parent, bg=PALETTE["surface"])
        wrap.pack(fill="x", pady=(0, 12))
        tk.Label(wrap, text=label, bg=PALETTE["surface"], fg=PALETTE["secondary"],
                 font=(FONT, 9, "bold"), anchor="w").pack(fill="x")
        row = tk.Frame(wrap, bg=PALETTE["surface"])
        row.pack(fill="x", pady=(4, 0))
        number_vars = []
        number_combos = []
        col = 0
        for raw_value in (number_values or []):
            var = tk.StringVar(value=self._normalize_number_choice(raw_value))
            combo = ttk.Combobox(row, textvariable=var, values=self._number_choice_values(), state="readonly", width=7)
            combo.grid(row=0, column=col, sticky="w")
            number_vars.append(var)
            number_combos.append(combo)
            col += 1

        row.grid_columnconfigure(col, weight=1)
        text_value = _clean(name_value)
        state = {"placeholder": not bool(text_value)}
        base_var = tk.StringVar(value=text_value or placeholder)
        base_ent = tk.Entry(
            row,
            textvariable=base_var,
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
        base_ent.grid(row=0, column=col, sticky="ew", padx=(8, 0), ipady=5)
        col += 1

        ext_var = None
        ext_ent = None
        if ext_value is not None:
            ext_var = tk.StringVar(value=self._normalize_extension(ext_value))
            ext_items = list(ext_choices or self._extension_options(ext_file_type, ext_value))
            if ext_var.get() and ext_var.get() not in ext_items:
                ext_items.append(ext_var.get())
            ext_ent = ttk.Combobox(
                row,
                textvariable=ext_var,
                values=ext_items,
                state="readonly",
                width=10,
            )
            ext_ent.grid(row=0, column=col, sticky="ew", padx=(8, 0), ipady=5)

        def _render():
            base_ent.configure(fg=PALETTE["muted"] if state["placeholder"] else PALETTE["text"])

        def _focus_in(_event):
            if state["placeholder"]:
                state["placeholder"] = False
                base_var.set("")
                _render()

        def _focus_out(_event):
            if _clean(base_var.get()):
                state["placeholder"] = False
            else:
                state["placeholder"] = True
                base_var.set(placeholder)
            _render()

        def _set_name(value):
            value = _clean(value)
            state["placeholder"] = not bool(value)
            base_var.set(value or placeholder)
            _render()

        def _set_numbers(values):
            values = list(values or [])
            for i, var in enumerate(number_vars):
                raw = values[i] if i < len(values) else ""
                var.set(self._normalize_number_choice(raw))

        def _set_base(value):
            nums, parsed_name = self._split_numbered_name(value, count=len(number_vars))
            _set_numbers(nums)
            _set_name(parsed_name)

        base_ent.bind("<FocusIn>", _focus_in, add="+")
        base_ent.bind("<FocusOut>", _focus_out, add="+")
        if hint:
            tk.Label(wrap, text=hint, bg=PALETTE["surface"], fg=PALETTE["muted"],
                     font=(FONT, 8), anchor="w").pack(fill="x", pady=(3, 0))

        payload = {
            "number_vars": number_vars,
            "number_combos": number_combos,
            "base_var": base_var,
            "base_entry": base_ent,
            "ext_var": ext_var,
            "ext_entry": ext_ent,
            "get_name": lambda: "" if state["placeholder"] else _clean(base_var.get()),
            "get_number": lambda idx=0: self._save_number_choice(number_vars[idx].get()) if 0 <= idx < len(number_vars) else "",
            "get_numbers": lambda: [self._save_number_choice(var.get()) for var in number_vars],
            "get_base": lambda fallback="": self._compose_numbered_name(
                [self._save_number_choice(var.get()) for var in number_vars],
                "" if state["placeholder"] else _clean(base_var.get()),
                fallback_name=fallback,
            ),
            "get_ext": (lambda: self._normalize_extension(ext_var.get())) if ext_var is not None else (lambda: ""),
            "set_base": _set_base,
            "set_ext": (lambda value: ext_var.set(self._normalize_extension(value))) if ext_var is not None else (lambda value: None),
            "set_numbers": _set_numbers,
            "set_name": _set_name,
        }
        return payload

    def _readme_name_field(self, parent, label, number_value, ext_value, hint=""):
        wrap = tk.Frame(parent, bg=PALETTE["surface"])
        wrap.pack(fill="x", pady=(0, 12))
        tk.Label(wrap, text=label, bg=PALETTE["surface"], fg=PALETTE["secondary"],
                 font=(FONT, 9, "bold"), anchor="w").pack(fill="x")
        row = tk.Frame(wrap, bg=PALETTE["surface"])
        row.pack(fill="x", pady=(4, 0))

        prefix = tk.Label(
            row,
            text="readme",
            bg=PALETTE["accent_soft"],
            fg=PALETTE["text"],
            font=(FONT, 10),
            padx=10,
            pady=6,
        )
        prefix.grid(row=0, column=0, sticky="w")

        number_var = tk.StringVar(value=self._normalize_number_choice(number_value, README_NUMBER_LIMIT))
        number_combo = ttk.Combobox(row, textvariable=number_var, values=self._number_choice_values(README_NUMBER_LIMIT), state="readonly", width=7)
        number_combo.grid(row=0, column=1, sticky="w", padx=(8, 0))

        ext_var = tk.StringVar(value=self._normalize_extension(ext_value))
        ext_items = self._extension_options("说明", ext_value)
        ext_ent = ttk.Combobox(
            row,
            textvariable=ext_var,
            values=ext_items,
            state="readonly",
            width=10,
        )
        ext_ent.grid(row=0, column=2, sticky="ew", padx=(8, 0), ipady=5)
        row.grid_columnconfigure(2, weight=1)

        def _set_base(value):
            number_var.set(self._normalize_number_choice(self._split_readme_name(value), README_NUMBER_LIMIT))

        if hint:
            tk.Label(wrap, text=hint, bg=PALETTE["surface"], fg=PALETTE["muted"],
                     font=(FONT, 8), anchor="w").pack(fill="x", pady=(3, 0))

        return {
            "number_vars": [number_var],
            "number_combos": [number_combo],
            "ext_var": ext_var,
            "ext_entry": ext_ent,
            "get_base": lambda fallback="": "readme" + self._save_number_choice(number_var.get()),
            "get_ext": lambda: self._normalize_extension(ext_var.get()),
            "get_number": lambda idx=0: self._save_number_choice(number_var.get()),
            "set_base": _set_base,
            "set_ext": lambda value: ext_var.set(self._normalize_extension(value)),
        }

    def _filename_pair_field(self, parent, label, base_value, ext_value, hint="", placeholder="", ext_readonly=False):
        wrap = tk.Frame(parent, bg=PALETTE["surface"])
        wrap.pack(fill="x", pady=(0, 12))
        tk.Label(wrap, text=label, bg=PALETTE["surface"], fg=PALETTE["secondary"],
                 font=(FONT, 9, "bold"), anchor="w").pack(fill="x")
        row = tk.Frame(wrap, bg=PALETTE["surface"])
        row.pack(fill="x", pady=(4, 0))
        row.grid_columnconfigure(0, weight=5)
        row.grid_columnconfigure(1, weight=2)

        base_value = _clean(base_value)
        state = {"placeholder": not bool(base_value)}
        base_var = tk.StringVar(value=base_value or placeholder)
        base_ent = tk.Entry(
            row,
            textvariable=base_var,
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
        base_ent.grid(row=0, column=0, sticky="ew", ipady=5)

        ext_var = tk.StringVar(value=self._normalize_extension(ext_value))
        ext_ent = tk.Entry(
            row,
            textvariable=ext_var,
            font=(FONT, 10),
            relief="flat",
            bd=0,
            bg=PALETTE["accent_soft"] if ext_readonly else PALETTE["input_bg"],
            fg=PALETTE["text"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["accent"],
            insertbackground=PALETTE["text"],
            state="readonly" if ext_readonly else "normal",
            width=12,
        )
        ext_ent.grid(row=0, column=1, sticky="ew", padx=(8, 0), ipady=5)

        def _render():
            base_ent.configure(fg=PALETTE["muted"] if state["placeholder"] else PALETTE["text"])

        def _focus_in(_event):
            if state["placeholder"]:
                state["placeholder"] = False
                base_var.set("")
                _render()

        def _focus_out(_event):
            if _clean(base_var.get()):
                state["placeholder"] = False
            else:
                state["placeholder"] = True
                base_var.set(placeholder)
            _render()

        base_ent.bind("<FocusIn>", _focus_in, add="+")
        base_ent.bind("<FocusOut>", _focus_out, add="+")
        if hint:
            tk.Label(wrap, text=hint, bg=PALETTE["surface"], fg=PALETTE["muted"],
                     font=(FONT, 8), anchor="w").pack(fill="x", pady=(3, 0))
        return {
            "base_var": base_var,
            "ext_var": ext_var,
            "base_entry": base_ent,
            "ext_entry": ext_ent,
            "get_base": lambda: "" if state["placeholder"] else _clean(base_var.get()),
            "get_ext": lambda: self._normalize_extension(ext_var.get()),
            "set_base": lambda value: base_var.set(_clean(value)),
            "set_ext": lambda value: ext_var.set(self._normalize_extension(value)),
        }

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
        for n in range(0, limit + 1):
            if n not in usage_map:
                return n
        used = sorted(n for n in usage_map.keys() if 0 <= int(n) <= limit)
        return min(limit, max(0, used[-1])) if used else 0

    def _build_number_choices(self, usage_map, limit, current_value, allow_blank=False):
        current_num = int(current_value) if str(current_value).isdigit() and 0 <= int(current_value) <= limit else None
        preferred_num = current_num if current_num is not None else self._next_available_number(usage_map, limit)
        ordered = list(range(0, limit + 1))
        display_to_value = {}
        values = []
        if allow_blank:
            values.append(BLANK_OPTION_LABEL)
            display_to_value[BLANK_OPTION_LABEL] = ""
        for num in ordered:
            owners = usage_map.get(num, [])
            label = str(num)
            if owners:
                preview = "、".join(self._usage_owner_text(owner) for owner in owners[:2])
                if len(owners) > 2:
                    preview += "..."
                label = f"{num} · 已占用：{preview}"
            values.append(label)
            display_to_value[label] = str(num)
        if current_value == "" and allow_blank:
            selected_label = BLANK_OPTION_LABEL
        else:
            selected_num = str(current_num if current_num is not None else preferred_num)
            selected_label = next((label for label, value in display_to_value.items() if value == selected_num), values[0] if values else "")
        return values, display_to_value, selected_label

    def _number_choice_field(self, parent, label, current_value, usage_map, limit, hint="", empty_hint="当前编号空闲。", state_key=None, allow_blank=False):
        wrap = tk.Frame(parent, bg=PALETTE["surface"])
        wrap.pack(fill="x", pady=(0, 12))
        tk.Label(wrap, text=label, bg=PALETTE["surface"], fg=PALETTE["secondary"],
                 font=(FONT, 9, "bold"), anchor="w").pack(fill="x")
        normalized_current = _clean(current_value)
        values, display_to_value, selected_label = self._build_number_choices(usage_map, limit, normalized_current, allow_blank=allow_blank)
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
        occupied_status = tk.Label(wrap, text="", bg=PALETTE["surface"], fg=PALETTE["muted"],
                                   font=(FONT, 8), anchor="w", justify="left")
        occupied_status.pack(fill="x", pady=(2, 0))
        if hint:
            tk.Label(wrap, text=hint, bg=PALETTE["surface"], fg=PALETTE["muted"],
                     font=(FONT, 8), anchor="w").pack(fill="x", pady=(2, 0))

        def get_value():
            return display_to_value.get(var.get(), "")

        occupied_preview = []
        conflict_preview = []
        for num in sorted(usage_map):
            owners = usage_map.get(num, [])
            if not owners:
                continue
            preview = "、".join(self._usage_owner_text(owner) for owner in owners)
            occupied_preview.append(f"{num}: {preview}")
            if len(owners) > 1:
                conflict_preview.append(f"{num}: {preview}")
        occupied_text = "已占用：无" if not occupied_preview else "已占用：" + "；".join(occupied_preview)
        conflict_text = "" if not conflict_preview else "冲突中：" + "；".join(conflict_preview)

        def refresh_status(*_args):
            value = get_value()
            occupied_status.config(
                text=occupied_text if not conflict_text else occupied_text + "\n" + conflict_text,
                fg=PALETTE["danger"] if conflict_text else PALETTE["muted"],
            )
            if value == "":
                style.map(
                    style_name,
                    fieldbackground=[("readonly", PALETTE["input_bg"])],
                    foreground=[("readonly", PALETTE["text"])],
                )
                status.config(text="当前为空白，不写入编号。", fg=PALETTE["muted"])
                return
            if value.isdigit():
                owners = usage_map.get(int(value), [])
                if owners:
                    style.map(
                        style_name,
                        fieldbackground=[("readonly", "#FBEAEA")],
                        foreground=[("readonly", PALETTE["danger"])],
                    )
                    prefix = "当前编号存在冲突" if len(owners) > 1 else "当前编号已被占用"
                    status.config(text=f"{prefix}：{'、'.join(self._usage_owner_text(owner) for owner in owners)}", fg=PALETTE["danger"])
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
            "occupied_status": occupied_status,
            "recommended": recommended_num,
            "recommend_button": recommend_btn,
        }
        if state_key:
            self._detail_state[state_key] = payload
        return payload

    def _collect_run_order_save_audit(self):
        """收集保存前的未分配代码、空号和重复号，不修改任何数据。"""
        result = {
            "unassigned": [],
            "missing": [],
            "missing_details": [],
            "duplicates": [],
        }
        if not self.model:
            return result

        by_order = {}
        for ri, row in enumerate(self.rows):
            if self.model.cell(row, "代码/说明") != "代码":
                continue
            filename = self.model.cell(row, "相应代码和说明文件") or "（未命名代码）"
            step_value = _clean(self._effective_step_for_row(ri)) or "未分配"
            stem = os.path.splitext(filename)[0] or filename
            label = f"step_{step_value}_{stem}"
            order_text = self.model.cell(row, "运行顺序")
            order_num = _parse_run_order_value(order_text)
            if order_num is not None:
                by_order.setdefault(order_num, []).append(label)
                continue

            code_subdir = _clean(self.model.cell(row, "代码子文件夹")).replace("\\", "/").strip("/")
            disabled_note = _clean(self.model.cell(row, "备注"))
            is_update_code = code_subdir == "更新代码" or code_subdir.startswith("更新代码/")
            if not is_update_code and not disabled_note:
                result["unassigned"].append({
                    "label": label,
                    "order_text": order_text,
                    "code_subdir": code_subdir,
                })

        actual_orders = sorted(by_order)
        if actual_orders:
            start_order = 0
            result["missing"] = [
                order_num
                for order_num in range(start_order, actual_orders[-1] + 1)
                if order_num not in by_order
            ]
            for missing_order in result["missing"]:
                previous_orders = [order_num for order_num in actual_orders if order_num < missing_order]
                next_orders = [order_num for order_num in actual_orders if order_num > missing_order]
                if previous_orders:
                    previous_order = previous_orders[-1]
                    previous_text = f"[{previous_order}] {' / '.join(by_order[previous_order])}"
                else:
                    previous_text = "链首"
                if next_orders:
                    next_order = next_orders[0]
                    next_text = f"[{next_order}] {' / '.join(by_order[next_order])}"
                else:
                    next_text = "链尾"
                result["missing_details"].append(
                    f"缺少顺序 {missing_order}：{previous_text} → {next_text}"
                )

        for order_num in actual_orders:
            owners = by_order[order_num]
            if len(owners) > 1:
                result["duplicates"].append(
                    f"顺序 {order_num} 重复：{' / '.join(owners)}"
                )
        return result

    def _run_order_issue_lines(self, audit):
        lines = list((audit or {}).get("missing_details") or [])
        lines.extend((audit or {}).get("duplicates") or [])
        return lines

    def _format_warning_items(self, items, limit=30):
        items = [str(item) for item in items if str(item)]
        visible = items[:limit]
        text = "\n".join(f"- {item}" for item in visible)
        if len(items) > limit:
            text += f"\n- ……另有 {len(items) - limit} 项"
        return text

    def _confirm_run_order_save_checks(self):
        current_audit = self._collect_run_order_save_audit()
        legacy_lines = self._run_order_issue_lines(self._legacy_run_order_audit)
        current_lines = self._run_order_issue_lines(current_audit)
        issue_lines = []
        seen = set()
        for line in legacy_lines + current_lines:
            if line not in seen:
                seen.add(line)
                issue_lines.append(line)

        if issue_lines and messagebox:
            message = (
                "检测到运行顺序存在遗留空位或重复号：\n"
                + self._format_warning_items(issue_lines)
                + "\n\n继续后将自动按当前代码先后补齐为连续顺序，并写回文件。是否继续？"
            )
            if not messagebox.askyesno("运行顺序将自动补位", message, parent=self):
                self.status_var.set("保存已取消：尚未确认运行顺序自动补位。")
                self._log("保存已取消：用户拒绝自动补齐运行顺序。")
                return False

        unassigned_labels = [item["label"] for item in current_audit["unassigned"]]
        if unassigned_labels and messagebox:
            message = (
                "以下非“更新代码”代码尚未分配运行顺序：\n"
                + self._format_warning_items(unassigned_labels)
                + "\n\n这些代码不会进入顺序执行链。是否仍要继续保存？"
            )
            if not messagebox.askyesno("存在未分配顺序的代码", message, parent=self):
                self.status_var.set("保存已取消：仍有代码未分配运行顺序。")
                self._log("保存已取消：用户未确认未分配顺序代码警告。")
                return False
        return True

    def _validate_before_save(self):
        duplicate_steps = []
        seen_steps = {}
        for path, node in self.model.index.items():
            if len(path) != 1:
                continue
            step_value = _clean((node or {}).get("step"))
            if not step_value or not step_value.isdigit():
                continue
            seen_steps.setdefault(step_value, []).append(self._usage_owner_text(path[0]))
        for step_value, owners in seen_steps.items():
            if len(owners) > 1:
                duplicate_steps.append(f"步骤编号 {step_value} 重复：{'、'.join(owners)}")

        duplicate_orders = []
        seen_orders = {}
        order_numbers = []
        path_warnings = []
        
        for ri, row in enumerate(self.rows):
            file_type = self.model.cell(row, "代码/说明")
            name = _clean(self.model.cell(row, "相应代码和说明文件"))
            subfolder = _clean(self.model.cell(row, "代码子文件夹"))
            
            # 扩展名与子文件夹验证（全部改为警告）
            if file_type == "说明" and name.endswith(".docx"):
                if subfolder:
                    path_warnings.append(f"说明文件 {name} 建议保存在根目录，当前保存在：{subfolder}")
            elif file_type == "代码" and name.endswith(".py"):
                if subfolder in ("更新代码", "notebook"):
                    path_warnings.append(f"代码文件 {name} 建议不要保存在 {subfolder} 文件夹")
            elif file_type == "代码" and name.endswith(".ipynb"):
                if subfolder != "notebook":
                    path_warnings.append(f"Notebook文件 {name} 建议保存在 notebook 文件夹，当前保存在：{subfolder or '根目录'}")
            
            if file_type != "代码":
                continue
            order_value = _clean(self.model.cell(row, "运行顺序"))
            order_num = _parse_run_order_value(order_value)
            if order_num is None:
                continue
            order_numbers.append(order_num)
            seen_orders.setdefault(order_num, []).append(
                self.model.cell(row, "相应代码和说明文件") or f"第{ri + 2}行"
            )
        for order_value, owners in seen_orders.items():
            if len(owners) > 1:
                duplicate_orders.append(f"运行顺序 {order_value} 重复：{'、'.join(owners)}")

        if order_numbers:
            actual_orders = sorted(set(order_numbers))
            start_order = 0
            expected_orders = list(range(start_order, start_order + len(actual_orders)))
            if actual_orders != expected_orders:
                duplicate_orders.append(
                    "运行顺序存在空位：当前为 "
                    + ",".join(str(v) for v in actual_orders)
                    + "；应连续为 "
                    + ",".join(str(v) for v in expected_orders)
                )

        duplicate_saved_names = []
        for conflict in self._collect_saved_name_conflicts():
            duplicate_saved_names.append(
                f"『保存在资料中的名称』重复：{conflict['saved_name']} -> " + "；".join(conflict["items"])
            )

        errors = duplicate_steps + duplicate_orders + duplicate_saved_names
        if errors:
            raise ValueError("保存前校验未通过：\n- " + "\n- ".join(errors))
            
        return path_warnings

    def _collect_run_order_usage(self, exclude_ri):
        usage = {}
        for ri, row in enumerate(self.rows):
            if ri == exclude_ri:
                continue
            if self.model.cell(row, "代码/说明") != "代码":
                continue
            current_step = _clean(self._effective_step_for_row(ri))
            order_value = _parse_run_order_value(self.model.cell(row, "运行顺序"))
            if order_value is None:
                continue
            step_text = current_step or "无步骤"
            filename = self.model.cell(row, "相应代码和说明文件") or f"第{ri + 2}行"
            label = f"[{step_text}] {filename}"
            usage.setdefault(order_value, []).append(label)
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
            usage.setdefault(int(step_value), []).append(self._usage_owner_text(path[0]))
        return usage

    def _form_file(self, ri):
        self.right_title.config(text="文件详情")
        f = self.model.file_fields(ri)
        pad = tk.Frame(self.detail, bg=PALETTE["surface"])
        pad.pack(fill="both", expand=True, padx=20, pady=16)

        current_type = f["代码/说明"] or "代码"
        base_name, ext_name = self._split_file_name_for_form(f["相应代码和说明文件"], current_type)
        name_numbers, name_stem = self._split_numbered_name(base_name, count=1)
        if not name_stem:
            name_stem = DEFAULT_NEW_FILE_BASENAME
        existing_src_base, existing_src_ext = self._split_file_name_for_form(f["保存在资料中的名称"], current_type)
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

        default_deploy_num = name_numbers[0] if name_numbers and name_numbers[0] else ""
        name_state = self._numbered_name_field(
            pad,
            "部署文件名",
            [default_deploy_num],
            name_stem,
            "格式：数字_名称 + 扩展名。数字可留空；名称里不要填写后缀。",
            placeholder=DEFAULT_NEW_FILE_BASENAME,
            ext_value=ext_name,
            ext_choices=self._extension_options(current_type, ext_name),
            ext_file_type=current_type,
        )
        ext_state = {"programmatic": False, "manual_override": bool(ext_name) and ext_name != _default_extension_for_type(current_type)}

        def _set_ext_value(value):
            ext_state["programmatic"] = True
            name_state["set_ext"](value)
            ext_state["programmatic"] = False

        def _on_ext_change(*_args):
            raw_ext = name_state["ext_var"].get()
            normalized = self._normalize_extension(raw_ext, type_var.get())
            if normalized != raw_ext:
                _set_ext_value(normalized)
                return
            if ext_state["programmatic"]:
                return
            ext_state["manual_override"] = bool(normalized) and normalized != _default_extension_for_type(type_var.get())

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

        def _sync_subdir_widget(force_actual=False):
            # 说明文件不应该有代码子文件夹，始终显示为空白并禁用选择。
            desired = self._normalize_code_subdir(f["代码子文件夹"])
            if type_var.get() == "说明":
                desired = BLANK_OPTION_LABEL
            elif not sub_state["manual_override"] and not force_actual:
                desired = sub_field["var"].get()
            _set_subdir_value(desired)
            sub_field["combo"].config(state="disabled" if type_var.get() == "说明" else "readonly")

        src_meta = {"manual_override": bool(existing_src_base), "programmatic": False}
        src_state = {}
        src_warning = tk.Label(pad, text="", bg=PALETTE["surface"], fg=PALETTE["danger"],
                               font=(FONT, 8), anchor="w", justify="left")

        def _current_step_small_number():
            step_value = _clean(self._effective_step_for_row(ri))
            return step_value if step_value.isdigit() and 0 <= int(step_value) <= NAME_NUMBER_LIMIT else ""

        def _suggest_saved_base_from_current():
            deploy_num = name_state["get_number"]()
            if type_var.get() == "说明":
                return f"readme{deploy_num}" if deploy_num else "readme"
            return self._compose_numbered_name(
                [_current_step_small_number(), deploy_num],
                "code",
                fallback_name="code",
            )

        src_wrap = tk.Frame(pad, bg=PALETTE["surface"])
        src_wrap.pack(fill="x", pady=(0, 0))
        src_warning.pack(fill="x", pady=(0, 8))

        def _set_src_base(value):
            src_meta["programmatic"] = True
            src_state["field"]["set_base"](value)
            src_meta["programmatic"] = False

        def _set_src_ext(value):
            src_meta["programmatic"] = True
            src_state["field"]["set_ext"](value)
            src_meta["programmatic"] = False

        def refresh_src_warning(*_args):
            candidate = self._compose_file_name(src_state["field"]["get_base"](), src_state["field"]["get_ext"]())
            conflict = self._find_saved_name_conflict(candidate, exclude_ri=ri)
            if not candidate:
                src_warning.config(text="", fg=PALETTE["danger"])
                return
            if conflict:
                where = conflict.get("rel_dir") or "（工作区根目录）"
                src_warning.config(
                    text=f"警告：资料文件名冲突。当前为 {candidate}；重复于第 {conflict.get('sheet_row')} 行 · {where} · {conflict.get('label')}。可先继续编辑，但保存时会失败。",
                    fg=PALETTE["danger"],
                )
                return
            src_warning.config(text="当前资料文件名未发现冲突。", fg=PALETTE["muted"])

        def _bind_saved_field_traces(field):
            def _mark_manual(*_args):
                if src_meta["programmatic"]:
                    return
                src_meta["manual_override"] = True
                refresh_src_warning()

            for number_var in field.get("number_vars", []):
                number_var.trace_add("write", _mark_manual)
            if field.get("base_var") is not None:
                field["base_var"].trace_add("write", _mark_manual)
            if field.get("ext_var") is not None:
                field["ext_var"].trace_add("write", lambda *_args: refresh_src_warning())

        def render_saved_name_field():
            for child in src_wrap.winfo_children():
                child.destroy()
            current_base = existing_src_base or _suggest_saved_base_from_current()
            current_ext = existing_src_ext or name_state["get_ext"]()
            if src_state.get("field"):
                current_base = src_state["field"]["get_base"]() or current_base
                current_ext = src_state["field"]["get_ext"]() or current_ext
            if type_var.get() == "说明":
                current_num = self._split_readme_name(current_base)
                field = self._readme_name_field(
                    src_wrap,
                    "保存在资料中的名称",
                    current_num or name_state["get_number"](),
                    current_ext,
                    "格式：readmeN + 扩展名。N 默认跟随部署文件序号；扩展名与部署文件保持一致。",
                )
            else:
                src_numbers, src_stem = self._split_numbered_name(current_base, count=2)
                use_existing_prefixes = bool(existing_src_base)
                field = self._numbered_name_field(
                    src_wrap,
                    "保存在资料中的名称",
                    [
                        src_numbers[0] if use_existing_prefixes else (src_numbers[0] if src_numbers and src_numbers[0] else _current_step_small_number()),
                        src_numbers[1] if use_existing_prefixes else (src_numbers[1] if len(src_numbers) > 1 and src_numbers[1] else name_state["get_number"]()),
                    ],
                    src_stem or "code",
                    "格式：步骤号_子文件号_名称 + 扩展名。默认名称为 code；扩展名与部署文件保持一致。",
                    placeholder="code",
                    ext_value=current_ext,
                    ext_readonly=True,
                )
            src_state["field"] = field
            _bind_saved_field_traces(field)
            if not src_meta["manual_override"]:
                _set_src_base(_suggest_saved_base_from_current())
            _set_src_ext(name_state["get_ext"]())
            refresh_src_warning()

        def _on_type_change(*_args):
            current_ext = name_state["get_ext"]()
            name_state["ext_entry"].configure(values=self._extension_options(type_var.get(), current_ext))
            if not ext_state["manual_override"] and current_ext in ("", ".py", ".docx", ".ipynb", ".md"):
                _set_ext_value(_default_extension_for_type(type_var.get()))
            _sync_subdir_widget(force_actual=True)
            render_saved_name_field()
            render_order_field()  # 重新渲染运行顺序字段
            render_run_once_field()
            render_dynamic_section()

        name_state["ext_var"].trace_add("write", _on_ext_change)
        type_var.trace_add("write", _on_type_change)
        sub_field["var"].trace_add("write", _on_subdir_change)
        _sync_subdir_widget(force_actual=True)
        name_state["base_var"].trace_add("write", lambda *_args: (not src_meta["manual_override"]) and render_saved_name_field())
        for num_var in name_state.get("number_vars", []):
            num_var.trace_add("write", lambda *_args: (not src_meta["manual_override"]) and render_saved_name_field())
        name_state["ext_var"].trace_add("write", lambda *_args: (_set_src_ext(name_state["get_ext"]()), refresh_src_warning()))
        render_saved_name_field()

        tk.Frame(pad, bg=PALETTE["border"], height=1).pack(fill="x", pady=10)
        adv = tk.Label(pad, text="流水线与配套（高级）", bg=PALETTE["surface"],
                       fg=PALETTE["secondary"], font=(FONT, 9, "bold"), anchor="w")
        adv.pack(fill="x", pady=(0, 6))
        
        order_wrap = tk.Frame(pad, bg=PALETTE["surface"])
        order_wrap.pack(fill="x", pady=(0, 0))
        order_field = None
        run_once_wrap = tk.Frame(pad, bg=PALETTE["surface"])
        run_once_wrap.pack(fill="x", pady=(0, 0))
        run_once_field = None
        
        def render_order_field():
            for child in order_wrap.winfo_children():
                child.destroy()
            if type_var.get() == "代码":
                nonlocal order_field
                order_field = self._number_choice_field(
                    order_wrap,
                    "运行顺序（运行顺序）",
                    f["运行顺序"],
                    self._collect_run_order_usage(ri),
                    RUN_ORDER_LIMIT,
                    "可选（空白）、0-100；顺序链固定从 0 开始，保存及删除后会自动压紧为连续链。",
                    empty_hint="当前序号空闲。",
                    state_key="order_var",
                    allow_blank=True,
                )
                self._detail_state["order_field"] = order_field
            else:
                # 说明类型不需要运行顺序
                tk.Label(order_wrap, text="说明类型文件不需要运行顺序", bg=PALETTE["surface"],
                         fg=PALETTE["muted"], font=(FONT, 9), anchor="w").pack(fill="x", pady=(4, 0))
                if "order_var" in self._detail_state:
                    del self._detail_state["order_var"]
                if "order_field" in self._detail_state:
                    del self._detail_state["order_field"]
        
        render_order_field()

        def render_run_once_field():
            for child in run_once_wrap.winfo_children():
                child.destroy()
            if type_var.get() == "代码":
                nonlocal run_once_field
                run_once_field = self._choice_field(
                    run_once_wrap,
                    "只运行一次（只运行一次）",
                    RUN_ONCE_OPTIONS,
                    _normalize_yes_no(f.get("只运行一次", "")),
                    "仅用于调度提示：若历史上已成功运行过，主界面会提示通常可跳过，但仍允许继续运行。",
                    state_key="run_once_field",
                )
            else:
                tk.Label(
                    run_once_wrap,
                    text="说明类型文件不需要设置“只运行一次”",
                    bg=PALETTE["surface"],
                    fg=PALETTE["muted"],
                    font=(FONT, 9),
                    anchor="w",
                ).pack(fill="x", pady=(4, 0))
                if "run_once_field" in self._detail_state:
                    del self._detail_state["run_once_field"]

        render_run_once_field()
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
                selected_codes = set(self._doc_to_codes.get(self._row_id(self.rows[ri]), set()))
                has_choices = False
                for idx, (cri, cname) in enumerate(self._codes_in_same_step(ri)):
                    has_choices = True
                    dynamic_state["code_ris"].append(self._row_id(self.rows[cri]))
                    lb.insert("end", cname)
                    if self._row_id(self.rows[cri]) in selected_codes:
                        lb.selection_set(idx)
                if not has_choices:
                    tk.Label(
                        wrap,
                        text="当前 step 下还没有可绑定的代码文件。",
                        bg=PALETTE["surface"],
                        fg=PALETTE["muted"],
                        font=(FONT, 8),
                        anchor="w",
                    ).pack(fill="x", pady=(4, 0))
            else:
                bound_docs = []
                for doc_ri, doc_name in self._docs_in_same_step(ri):
                    if self._row_id(self.rows[ri]) in self._doc_to_codes.get(self._row_id(self.rows[doc_ri]), set()):
                        bound_docs.append(doc_name)
                self._field(dynamic_wrap, "绑定说明", "；".join(bound_docs) if bound_docs else "", readonly=True)
            self._detail_state["code_row_indices"] = list(dynamic_state["code_ris"])
            if dynamic_state["lb"] is not None:
                dynamic_state["lb"].bind("<<ListboxSelect>>", refresh_src_warning, add="+")

        render_dynamic_section()
        refresh_src_warning()

        def apply():
            chosen = set()
            if type_var.get() == "说明" and dynamic_state["lb"] is not None:
                for i in dynamic_state["lb"].curselection():
                    if 0 <= i < len(dynamic_state["code_ris"]):
                        chosen.add(dynamic_state["code_ris"][i])
            if not src_meta["manual_override"]:
                _set_src_base(_suggest_saved_base_from_current())
            new_src = self._compose_file_name(src_state["field"]["get_base"](), src_state["field"]["get_ext"]())
            refresh_src_warning()

            self._push_undo()
            target_row = self.rows[ri]
            full_name = self._compose_file_name(name_state["get_base"](DEFAULT_NEW_FILE_BASENAME), name_state["get_ext"](), fallback_base=DEFAULT_NEW_FILE_BASENAME)
            update_fields = {
                "代码/说明": type_var.get(),
                "相应代码和说明文件": full_name,
                "代码子文件夹": self._save_code_subdir(sub_field["var"].get()),
                "保存在资料中的名称": new_src,
                "备注": note_var.get(),
            }
            # 只有代码类型才设置运行顺序和单次运行提示
            if type_var.get() == "代码" and "order_field" in self._detail_state:
                update_fields["运行顺序"] = self._detail_state["order_field"]["get"]()
                run_once_payload = self._detail_state.get("run_once_field") or {}
                update_fields["只运行一次"] = _normalize_yes_no((run_once_payload.get("var").get() if run_once_payload.get("var") else "否"))
            else:
                update_fields["运行顺序"] = ""
                update_fields["只运行一次"] = ""
            self.model.edit_file(ri, update_fields)
            self._legacy_run_order_audit = None
            self._sort_rows()
            # 重建 doc_to_codes 映射关系（重要！每次 rows 变化后都要这样做！）
            self._doc_to_codes = self._build_doc_to_codes_from_rows()
            current_ri = self._find_row_index(target_row)
            current_row_id = self._row_id(target_row)
            # 现在处理用户新选择的绑定
            new_type = type_var.get()
            if new_type == "说明":
                if current_ri != -1:
                    allowed = {self._row_id(self.rows[cri]) for cri, _ in self._codes_in_same_step(current_ri)}
                    chosen = {c for c in chosen if c in allowed}
                    self._doc_to_codes[current_row_id] = chosen
            else:
                if current_row_id in self._doc_to_codes:
                    self._doc_to_codes.pop(current_row_id, None)
            self._recompute_and_write_binding_tokens()
            self.model.rebuild()
            self._mark_dirty("已更新文件详情（未保存）")
            self._log(f"修改了文件详情：{full_name}")
            self.populate_tree()
            if current_row_id:
                self._reveal(("file", current_row_id))
            self._update_undo_buttons()

        self._tk_button(pad, "应用修改", apply, primary=True).pack(anchor="w", pady=(8, 0))
        self._set_detail_apply_action(apply)
        self._bind_mousewheel_recursive(self.detail)

    def _form_folder(self, path):
        self.right_title.config(text="文件夹属性")
        node = self.model.index.get(tuple(path))
        pad = tk.Frame(self.detail, bg=PALETTE["surface"])
        pad.pack(fill="both", expand=True, padx=20, pady=16)
        is_top = len(path) == 1
        current_folder_name = self._display_path_name(path[-1]) if path else ""
        if is_top:
            name_var = self._field(
                pad,
                "文件夹名称",
                current_folder_name,
                "改名后会自动同步到该文件夹下所有文件行。",
                state_key="folder_name_var",
            )
        else:
            folder_numbers, folder_stem = self._split_numbered_name(current_folder_name, count=1)
            name_var = self._numbered_name_field(
                pad,
                "文件夹名称",
                [folder_numbers[0] if folder_numbers else ""],
                folder_stem or current_folder_name,
                "格式：数字_名称。数字可选 0-9，也可留空；留空时不带前缀。",
                placeholder="新文件夹",
            )
        step_var = None
        if is_top:
            step_var = self._number_choice_field(
                pad,
                "步骤编号（步骤）",
                (node or {}).get("step", ""),
                self._collect_step_usage(path),
                STEP_LIMIT,
                "可选 （空白）、0-20；0 也是合法步骤编号。",
                empty_hint="当前步骤编号空闲。",
                state_key="folder_step_var",
                allow_blank=True,
            )

        def apply():
            old_path = tuple(path)
            self._push_undo()
            if step_var is not None:
                self.model.set_top_step(old_path, step_var["get"]())
            new_name = name_var.get().strip() if is_top else name_var["get_base"]("新文件夹")
            new_path = old_path
            if new_name and new_name != self._display_path_name(old_path[-1]):
                # set_top_step 已 rebuild，路径名未变，可继续按原名 rename
                self.model.rename_folder(old_path, new_name)
                if len(old_path) == 1 and self.model and self.model._is_top_key(old_path[0]):
                    new_path = (self.model._make_top_key(step_var["get"]() if step_var is not None else self.model._path_step(old_path), new_name),)
                else:
                    new_path = old_path[:-1] + (new_name,)
            self._sort_rows()
            self._doc_to_codes = self._build_doc_to_codes_from_rows()
            self._recompute_and_write_binding_tokens()
            self.model.rebuild()
            self._mark_dirty("已更新文件夹（未保存）")
            self._log(f"修改了文件夹属性：{'/'.join(self._display_path(new_path))}")
            self.populate_tree()
            self._reveal(("folder", new_path))
            self._update_undo_buttons()

        self._tk_button(pad, "应用修改", apply, primary=True).pack(anchor="w", pady=(8, 0))
        self._set_detail_apply_action(apply)
        self._bind_mousewheel_recursive(self.detail)

    def _form_output(self, ri):
        self.right_title.config(text="输出目标")
        f = self.model.output_fields(ri)
        pad = tk.Frame(self.detail, bg=PALETTE["surface"])
        pad.pack(fill="both", expand=True, padx=20, pady=16)
        marker_field = self._choice_field(
            pad,
            "输出标记（输出文件）",
            OUTPUT_MARKER_OPTIONS,
            f["输出文件"] or "全量",
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
            target_row = self.rows[ri]
            self._sort_rows()
            self._doc_to_codes = self._build_doc_to_codes_from_rows()
            self._recompute_and_write_binding_tokens()
            self.model.rebuild()
            self._mark_dirty("已更新输出目标（未保存）")
            self._log(f"修改了输出项属性：{marker_field['var'].get()}")
            self.populate_tree()
            current_row_id = self._row_id(target_row)
            if current_row_id:
                self._reveal(("output", current_row_id))
            self._update_undo_buttons()

        self._tk_button(pad, "应用修改", apply, primary=True).pack(anchor="w", pady=(8, 0))
        self._set_detail_apply_action(apply)
        self._bind_mousewheel_recursive(self.detail)

    # ---------- 增删 ----------
    def _selected_folder_path(self):
        if not self._selected:
            return ()
        kind, key = self._selected
        if kind == "folder":
            return tuple(key)
        if kind in ("file", "output"):
            row = self._find_row_by_id(key)
            return tuple(self.model._path_keys(row)) if row is not None else ()
        return ()

    def _selected_parent_folder_for_paste(self):
        if not self._selected:
            return ()
        kind, key = self._selected
        if kind == "folder":
            return tuple(key)
        if kind in ("file", "output"):
            row = self._find_row_by_id(key)
            return tuple(self.model._path_keys(row)) if row is not None else ()
        return ()

    def _can_paste_to(self, clip_kind, source_key, target_folder_path):
        target_folder_path = tuple(target_folder_path)
        if clip_kind == "output":
            if not target_folder_path or self._display_path_name(target_folder_path[-1]) != "输出文件":
                raise ValueError("输出项只能粘贴到『输出文件』文件夹下。")
            return
        if target_folder_path and self._display_path_name(target_folder_path[-1]) == "输出文件":
            raise ValueError("普通文件或文件夹不能粘贴到『输出文件』文件夹下。")
        if clip_kind == "folder":
            source_path = tuple(source_key)
            if target_folder_path[:len(source_path)] == source_path:
                raise ValueError("不能把文件夹粘贴到它自己或其子文件夹中。")
            if len(target_folder_path) + 1 > 5:
                raise ValueError("目标层级过深，最多支持 5 层文件夹路径。")
        elif len(target_folder_path) > 5:
            raise ValueError("目标层级过深，最多支持 5 层文件夹路径。")

    def on_cut(self):
        if not self._selected:
            self.status_var.set("请先选中要剪切的文件、输出项或文件夹。")
            return
        kind, key = self._selected
        if kind not in ("file", "output", "folder"):
            self.status_var.set("当前选中项不支持剪切。")
            return
        self._clipboard = {"kind": kind, "key": key}
        kind_name = {"file": "文件", "output": "输出项", "folder": "文件夹"}[kind]
        self.status_var.set(f"已剪切{kind_name}，请选择目标文件夹后点击“粘贴”。")

    def on_paste(self):
        if not self._clipboard:
            self.status_var.set("剪贴板为空，请先剪切一个文件、输出项或文件夹。")
            return
        target_folder_path = self._selected_parent_folder_for_paste()
        clip_kind = self._clipboard["kind"]
        clip_key = self._clipboard["key"]
        try:
            self._can_paste_to(clip_kind, clip_key, target_folder_path)
        except Exception as exc:
            if messagebox:
                messagebox.showerror("无法粘贴", str(exc), parent=self)
            else:
                self.status_var.set(str(exc))
            return

        self._push_undo()
        reveal_meta = None
        if clip_kind in ("file", "output"):
            clip_ri = self._find_row_index_by_id(clip_key)
            if clip_ri == -1:
                self.status_var.set("原始条目已不存在，请重新剪切。")
                self._clipboard = None
                return
            target_row = self.rows[clip_ri]
            self.model.move_file(clip_ri, target_folder_path)
            self._sort_rows()
            self._doc_to_codes = self._build_doc_to_codes_from_rows()
            self._recompute_and_write_binding_tokens()
            self.model.rebuild()
            current_row_id = self._row_id(target_row)
            if current_row_id:
                reveal_meta = (clip_kind, current_row_id)
        else:
            source_path = tuple(clip_key)
            new_path = self.model.move_folder(source_path, target_folder_path)
            self._sort_rows()
            self._doc_to_codes = self._build_doc_to_codes_from_rows()
            self._recompute_and_write_binding_tokens()
            self.model.rebuild()
            reveal_meta = ("folder", new_path)

        self._clipboard = None
        self._mark_dirty("已剪切粘贴（未保存）")
        moved_display = "/".join(self._display_path(clip_key)) if clip_kind == "folder" else str(clip_key)
        target_display = "/".join(self._display_path(target_folder_path)) if target_folder_path else "根目录"
        self._log(f"执行粘贴操作：将 {moved_display} 移动到 {target_display}")
        self.populate_tree()
        if reveal_meta is not None:
            self._reveal(reveal_meta)
        self._update_undo_buttons()
        self.status_var.set("已完成粘贴，请检查位置后保存。")

    def on_add_file(self):
        path = self._selected_folder_path()
        default_name = f"0_{DEFAULT_NEW_FILE_BASENAME}.docx"
        default_type = "说明"
        if self._selected and self._selected[0] == "file":
            selected_row = self._find_row_by_id(self._selected[1])
            if selected_row is not None:
                selected_type = self.model.cell(selected_row, "代码/说明")
                if selected_type == "代码":
                    default_name = f"1_{DEFAULT_NEW_FILE_BASENAME}.py"
                    default_type = "代码"
        self._push_undo()
        ri = self.model.add_file(path, default_name, default_type)
        target_row = self.rows[ri]
        self._sort_rows()
        self._doc_to_codes = self._build_doc_to_codes_from_rows()
        self._recompute_and_write_binding_tokens()
        self.model.rebuild()
        if self._open_paths is not None:
            self._open_paths |= {tuple(path[:i + 1]) for i in range(len(path))}  # 展开到父文件夹
        self._mark_dirty("已新增文件（未保存）")
        self._log(f"执行新增文件：在 {'/'.join(self._display_path(path)) if path else '根目录'} 新增了文件")
        self.populate_tree()
        current_row_id = self._row_id(target_row)
        if current_row_id:
            self._reveal(("file", current_row_id))
        self._update_undo_buttons()
        self.status_var.set("已新增文件，已为你定位到它，请在右侧填写名称与扩展名。")

    def on_add_step_folder(self):
        self._push_undo()
        temp_path, _ = self.model.add_folder((), "步骤")
        self._sort_rows()
        self._doc_to_codes = self._build_doc_to_codes_from_rows()
        self._recompute_and_write_binding_tokens()
        self.model.rebuild()
        step_value = str(self._next_available_number(self._collect_step_usage(), STEP_LIMIT))
        self.model.set_top_step(temp_path, step_value)
        path = (self.model._make_top_key(step_value, "步骤"),)
        self._sort_rows()
        self._doc_to_codes = self._build_doc_to_codes_from_rows()
        self._recompute_and_write_binding_tokens()
        self.model.rebuild()
        if self._open_paths is not None:
            self._open_paths |= {tuple(path[:i + 1]) for i in range(len(path))}
        self._mark_dirty("已新增步骤文件夹（未保存）")
        self.populate_tree()
        self._reveal(("folder", path))
        self._update_undo_buttons()
        self.status_var.set("已新增『步骤』文件夹；文件夹行与文件行已分离，请按需再新增文件。")

    def on_add_output_folder(self):
        parent = self._selected_folder_path()
        self._push_undo()
        folder_path = parent + ("输出文件",)
        self.model.add_folder(parent, "输出文件")
        self.model.add_output(folder_path, marker="全量", code="")
        self._sort_rows()
        self._doc_to_codes = self._build_doc_to_codes_from_rows()
        self._recompute_and_write_binding_tokens()
        self.model.rebuild()
        if self._open_paths is not None:
            self._open_paths |= {tuple(folder_path[:i + 1]) for i in range(len(folder_path))}
        self._mark_dirty("已新增输出文件夹（未保存）")
        self.populate_tree()
        self._reveal(("folder", folder_path))
        self._update_undo_buttons()
        self.status_var.set("已新增『输出文件』文件夹，并在另一行新增了输出项。")

    def on_add_folder(self):
        path = self._selected_folder_path()
        self._push_undo()
        new_path, _ = self.model.add_folder(path, "新文件夹")
        self._sort_rows()
        self._doc_to_codes = self._build_doc_to_codes_from_rows()
        self._recompute_and_write_binding_tokens()
        self.model.rebuild()
        if self._open_paths is not None:
            self._open_paths |= {tuple(path[:i + 1]) for i in range(len(path))}
            self._open_paths |= {tuple(new_path[:i + 1]) for i in range(len(new_path))}
        self._mark_dirty("已新增文件夹（未保存）")
        self._log(f"执行新增文件夹：在 {'/'.join(self._display_path(path)) if path else '根目录'} 新增了文件夹")
        self.populate_tree()
        self._reveal(("folder", new_path))
        self._update_undo_buttons()
        self.status_var.set("已新增『新文件夹』；文件夹行与文件行已分离，请按需再新增文件。")

    def on_delete(self):
        selected_metas = list(self._selected_batch) if self._selected_batch else ([self._selected] if self._selected else [])
        selected_metas = [meta for meta in selected_metas if meta]
        if not selected_metas:
            return
        if len(selected_metas) == 1:
            kind, key = selected_metas[0]
            if kind == "file" or kind == "output":
                if messagebox and not messagebox.askokcancel("确认删除", "删除此文件 / 条目？", parent=self):
                    return
            elif kind == "folder":
                if messagebox and not messagebox.askokcancel(
                        "确认删除", "删除此文件夹及其下所有文件？", parent=self):
                    return
            else:
                return
        else:
            if messagebox and not messagebox.askokcancel(
                    "确认删除", f"删除当前选中的 {len(selected_metas)} 项？", parent=self):
                return

        folder_paths = []
        row_ids = []
        for kind, key in selected_metas:
            if kind == "folder":
                folder_paths.append(tuple(key))
            elif kind in ("file", "output"):
                row_ids.append(key)

        covered_row_ids = set()
        for row in self.rows:
            segs = tuple(self.model._path_keys(row))
            if any(segs[:len(path)] == path for path in folder_paths):
                rid = self._row_id(row)
                if rid:
                    covered_row_ids.add(rid)
        row_ids = [rid for rid in row_ids if rid not in covered_row_ids]

        self._push_undo()
        for path in sorted(set(folder_paths), key=lambda p: len(p), reverse=True):
            self.model.delete_folder(path)
        for row_id in row_ids:
            delete_ri = self._find_row_index_by_id(row_id)
            if delete_ri != -1:
                self.model.delete_file(delete_ri)
        self._legacy_run_order_audit = None
        self._sort_rows()
        self._doc_to_codes = self._build_doc_to_codes_from_rows()
        self._recompute_and_write_binding_tokens()
        self.model.rebuild()
        self._selected = None
        self._selected_batch = []
        self._mark_dirty("已删除（未保存）")
        
        log_msgs = []
        if folder_paths:
            log_msgs.append(f"删除了 {len(folder_paths)} 个文件夹")
        if row_ids:
            log_msgs.append(f"删除了 {len(row_ids)} 个文件/输出项")
        self._log("执行删除操作：" + "，".join(log_msgs))
        
        self.populate_tree()
        self._update_undo_buttons()

    # ---------- 保存 ----------
    def _mark_dirty(self, msg):
        self.dirty = True
        self.status_var.set(msg)

    def _find_workspace_step0_runner(self):
        base_path = os.path.abspath(self.blueprint_xlsx_path or "")
        if not base_path:
            return ""
        current_dir = os.path.dirname(base_path)
        visited = set()
        for _ in range(8):
            if not current_dir or current_dir in visited:
                break
            visited.add(current_dir)
            runner_path = os.path.join(current_dir, "step_0_前期准备", "setup.py")
            if os.path.isfile(runner_path):
                return runner_path
            parent_dir = os.path.dirname(current_dir)
            if parent_dir == current_dir:
                break
            current_dir = parent_dir
        return ""

    def _find_workspace_update_all_code(self):
        workspace_root = self._find_workspace_root()
        if not workspace_root:
            return ""
        script_path = os.path.join(workspace_root, "update_all_code.py")
        return script_path if os.path.isfile(script_path) else ""

    def _find_workspace_root(self):
        base_path = os.path.abspath(self.blueprint_xlsx_path or "")
        if not base_path:
            return ""
        current_dir = os.path.dirname(base_path)
        visited = set()
        for _ in range(8):
            if not current_dir or current_dir in visited:
                break
            visited.add(current_dir)
            if os.path.isdir(os.path.join(current_dir, "参评信息")):
                return current_dir
            parent_dir = os.path.dirname(current_dir)
            if parent_dir == current_dir:
                break
            current_dir = parent_dir
        return ""

    def _get_workspace_python_executable(self):
        project_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        venv_python = os.path.join(project_root, "myenv", "Scripts", "python.exe")
        if os.path.isfile(venv_python):
            return venv_python
        return sys.executable

    def _run_workspace_script_sync(self, script_path, workspace_root, extra_env=None):
        if not script_path or not os.path.isfile(script_path):
            raise FileNotFoundError(script_path or "缺少脚本路径")
        workspace_root = os.path.abspath(workspace_root or os.path.dirname(script_path))
        project_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        runtime_patch_dir = os.path.join(project_root, "gb_runtime_patch")
        step_entry_script = os.path.join(runtime_patch_dir, "step_process_entry.py")
        env = os.environ.copy()
        existing_pythonpath = str(env.get("PYTHONPATH", "")).strip()
        pythonpath_parts = [part for part in existing_pythonpath.split(os.pathsep) if part]
        if runtime_patch_dir not in pythonpath_parts:
            pythonpath_parts.insert(0, runtime_patch_dir)
        env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["GB_SCRIPT_PATH"] = os.path.abspath(script_path)
        if extra_env:
            env.update({str(k): str(v) for k, v in extra_env.items() if v is not None})
        python_executable = self._get_workspace_python_executable()
        rel_script_path = os.path.relpath(os.path.abspath(script_path), workspace_root)
        return subprocess.run(
            [python_executable, step_entry_script, rel_script_path],
            cwd=workspace_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

    def _build_process_output_preview(self, result, tail_lines=10):
        if result is None:
            return ""
        combined_output = "\n".join(
            part.strip()
            for part in (getattr(result, "stdout", "") or "", getattr(result, "stderr", "") or "")
            if str(part or "").strip()
        ).strip()
        if not combined_output:
            return ""
        return "\n".join(combined_output.splitlines()[-tail_lines:])

    def _finish_post_save_sequence(self, post_save_info, result_info):
        self._hide_loading_overlay()
        if callable(self.on_saved):
            try:
                self.on_saved(self.blueprint_xlsx_path)
            except Exception:
                pass
        if not messagebox:
            return
        if result_info.get("status") == "success":
            msg = f"已按标准格式写回：\n{self.blueprint_xlsx_path}"
            if post_save_info.get("update_script_path"):
                msg += f"\n\n已执行：\n{post_save_info['update_script_path']}"
            if post_save_info.get("runner_path"):
                msg += f"\n\n已执行：\n{post_save_info['runner_path']}"
            messagebox.showinfo("保存成功", msg, parent=self)
            return
        failed_step = result_info.get("failed_step") or "自动执行"
        msg = f"已保存文件，但 {failed_step} 执行失败"
        return_code = result_info.get("returncode")
        if return_code not in (None, ""):
            msg += f"，退出码: {return_code}"
        output_preview = result_info.get("output_preview") or ""
        if output_preview:
            msg += f"\n\n最近输出：\n{output_preview}"
        messagebox.showwarning("自动执行失败", msg, parent=self)

    def _run_post_save_sequence_worker(self, update_script_path, runner_path):
        workspace_root = self._find_workspace_root()
        if update_script_path:
            self._log(f"保存后开始执行 update_all_code.py：{update_script_path}")
            try:
                result = self._run_workspace_script_sync(
                    update_script_path,
                    workspace_root,
                    extra_env={"GB_AUTO_CONFIRM_DIALOGS": "1"},
                )
            except Exception as exc:
                self._log(f"执行 update_all_code.py 失败：{exc}")
                self.after(0, lambda: self._finish_post_save_sequence(
                    {"update_script_path": update_script_path, "runner_path": runner_path, "started": True},
                    {"status": "failed", "failed_step": "update_all_code.py", "returncode": "", "output_preview": str(exc)},
                ))
                return
            update_preview = self._build_process_output_preview(result, tail_lines=12)
            if update_preview:
                self._log("update_all_code.py 输出摘要：\n" + update_preview)
            if result.returncode != 0:
                self._log(f"update_all_code.py 执行失败，退出码：{result.returncode}")
                self.after(0, lambda: self._finish_post_save_sequence(
                    {"update_script_path": update_script_path, "runner_path": runner_path, "started": True},
                    {"status": "failed", "failed_step": "update_all_code.py", "returncode": result.returncode, "output_preview": self._build_process_output_preview(result)},
                ))
                return
            self._log("update_all_code.py 执行完成，准备运行 step_0。")
        elif runner_path:
            self._log("保存后未找到 update_all_code.py，继续按原逻辑运行 step_0。")
        if runner_path:
            self._log(f"保存后开始执行 step_0：{runner_path}")
            try:
                result = self._run_workspace_script_sync(runner_path, workspace_root)
            except Exception as exc:
                self._log(f"执行 step_0_前期准备/setup.py 失败：{exc}")
                self.after(0, lambda: self._finish_post_save_sequence(
                    {"update_script_path": update_script_path, "runner_path": runner_path, "started": True},
                    {"status": "failed", "failed_step": "step_0_前期准备/setup.py", "returncode": "", "output_preview": str(exc)},
                ))
                return
            step0_preview = self._build_process_output_preview(result, tail_lines=12)
            if step0_preview:
                self._log("step_0 输出摘要：\n" + step0_preview)
            if result.returncode != 0:
                self._log(f"step_0_前期准备/setup.py 执行失败，退出码：{result.returncode}")
                self.after(0, lambda: self._finish_post_save_sequence(
                    {"update_script_path": update_script_path, "runner_path": runner_path, "started": True},
                    {"status": "failed", "failed_step": "step_0_前期准备/setup.py", "returncode": result.returncode, "output_preview": self._build_process_output_preview(result)},
                ))
                return
            self._log("step_0_前期准备/setup.py 执行完成。")
        self.after(0, lambda: self._finish_post_save_sequence(
            {"update_script_path": update_script_path, "runner_path": runner_path, "started": True},
            {"status": "success"},
        ))

    def _run_post_save_sequence(self):
        update_script_path = self._find_workspace_update_all_code()
        runner_path = self._find_workspace_step0_runner()
        if not update_script_path and not runner_path:
            self._log("保存后未找到 update_all_code.py 或 step_0_前期准备/setup.py，跳过自动触发。")
            post_save_info = {"update_script_path": "", "runner_path": "", "started": False}
            self.after(0, lambda: self._finish_post_save_sequence(post_save_info, {"status": "success"}))
            return post_save_info
        threading.Thread(
            target=self._run_post_save_sequence_worker,
            args=(update_script_path, runner_path),
            daemon=True,
        ).start()
        return {
            "update_script_path": update_script_path,
            "runner_path": runner_path,
            "started": True,
        }

    def save(self):
        try:
            if self.model:
                if self._order_draft_dirty:
                    if messagebox and not messagebox.askyesno(
                        "顺序调整尚未完成",
                        "“顺序调整”中还有未应用的草稿。\n\n是否先完成调整、写入结构编辑并继续保存？",
                        parent=self,
                    ):
                        self.status_var.set("保存已取消：顺序调整草稿尚未应用。")
                        self._log("保存已取消：用户未应用顺序调整草稿。")
                        return
                    self._commit_order_draft(switch_to_editor=False)
                self.model.ensure_row_ids()
                if not self._confirm_run_order_save_checks():
                    return
                normalized_orders = self.model.normalize_run_orders()
                if normalized_orders:
                    self._sort_rows()
                    self.model.rebuild()
                    self.populate_tree()
                    self._log(f"保存前已自动补齐运行顺序 {normalized_orders} 处。")
            path_warnings = self._validate_before_save()
            if path_warnings and messagebox:
                msg = "检测到以下文件保存位置可能不当：\n- " + "\n- ".join(path_warnings) + "\n\n是否忽略警告并强制写回？"
                if not messagebox.askyesno("保存警告", msg, parent=self):
                    self._log("保存已取消：用户拒绝忽略路径警告")
                    return
                    
            self._recompute_and_write_binding_tokens()
            if self.model:
                self.model.rebuild()
            save_blueprint(self.workbook, self.sheet, self.header, self.rows, self.blueprint_xlsx_path)
        except Exception as exc:
            if messagebox:
                messagebox.showerror("保存失败", str(exc), parent=self)
            self._log(f"保存失败: {str(exc)}")
            return
        self.dirty = False
        self._legacy_run_order_audit = None
        self.status_var.set(f"保存成功，已写回 {self.blueprint_xlsx_path}")
        self._log(f"保存成功，已将更新写入 Excel，物理行原位更新，新行已追加至末尾。")
        # 显示加载遮罩
        self._show_loading_overlay("正在保存...")
        self._run_post_save_sequence()

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
