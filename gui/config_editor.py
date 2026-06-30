import ast
import copy
import json
import os
import pprint
import re
from tkinter import messagebox

try:
    import customtkinter as ctk
except ModuleNotFoundError:
    ctk = None

if ctk is not None:
    try:
        from .style_config import *
    except Exception:
        from style_config import *


FIELD_SPECS = [
    {"key": "post_visualization_mode", "label": "后置可视化模式", "kind": "bool", "help": "False 保持并行 open_file()；True 改为后置串行 run()。"},
    {"key": "manager_tenure_filter_in_step2", "label": "经理任职过滤前置", "kind": "bool", "help": "True：step2 即按任职窗口裁净值并据此算收益率/缺失率；False：保持旧逻辑在 step3 裁。"},
    {"key": "use_monthly", "label": "启用月度处理", "kind": "bool", "help": "是否处理并输出月度净值链路。"},
    {"key": "score_method", "label": "评分方法", "kind": "choice", "choices": ["1", "2", "3"], "help": "1=Zscore，2=归一化，3=排名。"},
    {"key": "abnormal_method", "label": "异常值方法", "kind": "choice", "choices": ["median", "mean3", "forbidden"], "help": "异常值处理口径。"},
    {"key": "missing_rate_fill_max", "label": "缺失率填充上限", "kind": "float", "help": "直接填小数，例如 0.15。"},
    {"key": "missing_rate_validation_cut", "label": "缺失率校验上限", "kind": "float", "help": "直接填小数，例如 0.50。"},
    {"key": "sigma_threshold", "label": "极值阈值", "kind": "int", "help": "直接填整数，例如 10。"},
    {"key": "all_terms", "label": "全部年期", "kind": "list_int", "help": "直接输入 1,3,5,7，用逗号隔开。"},
    {"key": "terms_stock", "label": "股票年期", "kind": "list_int", "help": "直接输入 1,3,5,7，用逗号隔开。"},
    {"key": "terms_other", "label": "其他策略年期", "kind": "list_int", "help": "直接输入 1,3，用逗号隔开。"},
    {"key": "annual_factor", "label": "年化因子", "kind": "mapping_int", "help": "点 + 新增一行，左边写名称，右边写整数。"},
    {"key": "score_weight_general", "label": "通用评分权重", "kind": "mapping_float", "help": "点 + 新增一行，左边写指标，右边写权重。"},
    {"key": "score_weight_mana", "label": "管理人评分权重", "kind": "mapping_float", "help": "点 + 新增一行，左边写指标，右边写权重。"},
    {"key": "score_weight_index", "label": "指数评分权重", "kind": "mapping_float", "help": "点 + 新增一行，左边写指标，右边写权重。"},
]

FORM_LABEL_COLUMN_WIDTH = 340
FORM_VALUE_COLUMN_MIN_WIDTH = 420
FORM_SCALAR_CELL_MIN_HEIGHT = 72


def _deepcopy_data(value):
    return copy.deepcopy(value)


def _read_utf8_text(path):
    with open(path, "r", encoding="utf-8") as fp:
        return fp.read()


def _write_utf8_text(path, content):
    with open(path, "w", encoding="utf-8", newline="") as fp:
        fp.write(content)


def _json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def _python_assignment(name, value):
    return f"{name} = {pprint.pformat(value, width=100, sort_dicts=False)}\n"


def _normalize_year_key(year_key):
    text = str(year_key).strip()
    if not text:
        raise ValueError("年份键不能为空。")
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"无法识别年份键: {year_key}") from exc


def _normalize_profiles(profiles):
    if profiles is None:
        return {}
    if not isinstance(profiles, dict):
        raise ValueError("PROFILES 必须是字典。")
    normalized = {}
    for raw_key, raw_value in profiles.items():
        if not isinstance(raw_value, dict):
            raise ValueError(f"PROFILES[{raw_key}] 必须是字典。")
        normalized[_normalize_year_key(raw_key)] = _deepcopy_data(raw_value)
    return normalized


def _parse_python_config_blocks(source_text):
    tree = ast.parse(source_text)
    values = {}
    ranges = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if name not in {"DEFAULT", "PROFILES"}:
            continue
        values[name] = ast.literal_eval(node.value)
        ranges[name] = (node.lineno, node.end_lineno)
    missing = [name for name in ("DEFAULT", "PROFILES") if name not in values or name not in ranges]
    if missing:
        raise ValueError(f"配置文件缺少必需区块: {', '.join(missing)}")
    return values, ranges


def load_config_payload(config_file_path):
    source_text = _read_utf8_text(config_file_path)
    values, _ranges = _parse_python_config_blocks(source_text)
    default_obj = values["DEFAULT"]
    profiles_obj = _normalize_profiles(values["PROFILES"])
    if not isinstance(default_obj, dict):
        raise ValueError("DEFAULT 必须是字典。")
    return _deepcopy_data(default_obj), _deepcopy_data(profiles_obj)


def save_config_payload(config_file_path, default_obj, profiles_obj):
    if not isinstance(default_obj, dict):
        raise ValueError("DEFAULT 必须是字典。")
    normalized_profiles = _normalize_profiles(profiles_obj)
    source_text = _read_utf8_text(config_file_path)
    _values, ranges = _parse_python_config_blocks(source_text)
    lines = source_text.splitlines(keepends=True)
    replacements = {
        "DEFAULT": _python_assignment("DEFAULT", default_obj),
        "PROFILES": _python_assignment("PROFILES", normalized_profiles),
    }
    ordered = sorted(ranges.items(), key=lambda item: item[1][0], reverse=True)
    for name, (start_line, end_line) in ordered:
        lines[start_line - 1:end_line] = [replacements[name]]
    updated_text = "".join(lines)
    _write_utf8_text(config_file_path, updated_text)
    return config_file_path


def validate_config_payload(default_obj, profiles_obj):
    errors = []
    profiles_obj = _normalize_profiles(profiles_obj)
    if not isinstance(default_obj, dict):
        return ["DEFAULT 必须是字典。"]

    def _check_ratio(name, value):
        if value is None:
            return
        if not isinstance(value, (int, float)):
            errors.append(f"{name} 必须是数值。")
            return
        if not 0 <= float(value) <= 1:
            errors.append(f"{name} 必须位于 0~1。")

    def _check_terms(name, value):
        if value is None:
            return
        if not isinstance(value, list) or not all(isinstance(item, int) and item > 0 for item in value):
            errors.append(f"{name} 必须是正整数列表。")
            return
        if value != sorted(value):
            errors.append(f"{name} 需要按升序排列。")

    def _check_weights(name, value):
        if value is None:
            return
        if not isinstance(value, dict) or not value:
            errors.append(f"{name} 必须是非空字典。")
            return
        total = 0.0
        for key, item in value.items():
            if not isinstance(item, (int, float)):
                errors.append(f"{name}.{key} 必须是数值。")
                continue
            total += float(item)
        if abs(total - 1.0) > 1e-6:
            errors.append(f"{name} 权重和应为 1，当前为 {total:.6f}。")

    def _check_payload(prefix, payload):
        if not isinstance(payload, dict):
            errors.append(f"{prefix} 必须是字典。")
            return
        _check_ratio(f"{prefix}.missing_rate_fill_max", payload.get("missing_rate_fill_max"))
        _check_ratio(f"{prefix}.missing_rate_validation_cut", payload.get("missing_rate_validation_cut"))
        _check_terms(f"{prefix}.all_terms", payload.get("all_terms"))
        _check_terms(f"{prefix}.terms_stock", payload.get("terms_stock"))
        _check_terms(f"{prefix}.terms_other", payload.get("terms_other"))
        _check_weights(f"{prefix}.score_weight_general", payload.get("score_weight_general"))
        _check_weights(f"{prefix}.score_weight_mana", payload.get("score_weight_mana"))
        _check_weights(f"{prefix}.score_weight_index", payload.get("score_weight_index"))
        annual_factor = payload.get("annual_factor")
        if annual_factor is not None:
            if not isinstance(annual_factor, dict):
                errors.append(f"{prefix}.annual_factor 必须是字典。")
            else:
                for required in ("周度", "月度"):
                    if required not in annual_factor:
                        errors.append(f"{prefix}.annual_factor 缺少 {required}。")
        for bool_key in ("post_visualization_mode", "use_monthly", "manager_tenure_filter_in_step2"):
            if bool_key in payload and not isinstance(payload.get(bool_key), bool):
                errors.append(f"{prefix}.{bool_key} 必须是布尔值。")

    _check_payload("DEFAULT", default_obj)
    for year_key, profile in profiles_obj.items():
        _check_payload(f"PROFILES[{year_key}]", profile)
    return errors


def _parse_structured_text(text):
    stripped = str(text or "").strip()
    if not stripped:
        raise ValueError("内容不能为空。")
    try:
        return json.loads(stripped)
    except Exception:
        try:
            return ast.literal_eval(stripped)
        except Exception as exc:
            raise ValueError(f"无法解析结构化内容: {exc}") from exc


def _split_csv_values(text):
    return [part.strip() for part in re.split(r"[，,;；\s]+", str(text or "").strip()) if part.strip()]


def _parse_int_list(text):
    parts = _split_csv_values(text)
    if not parts:
        raise ValueError("列表不能为空。")
    return [int(part) for part in parts]


def _build_effective_year_data(default_obj, profiles_obj, year_key):
    merged = _deepcopy_data(default_obj)
    merged.update(_deepcopy_data(profiles_obj.get(year_key, {})))
    return merged


def _build_profile_override(default_obj, effective_obj):
    override = {}
    for key, value in effective_obj.items():
        if key not in default_obj or default_obj.get(key) != value:
            override[key] = _deepcopy_data(value)
    return override


def _display_value(spec, value):
    if value is None:
        return "-"
    kind = spec["kind"]
    if kind == "bool":
        return "是" if bool(value) else "否"
    if kind == "list_int":
        return ", ".join(str(item) for item in value)
    if kind.startswith("mapping_"):
        if not isinstance(value, dict) or not value:
            return "-"
        return "\n".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


class ConfigEditorWindow(ctk.CTkToplevel if ctk is not None else object):
    def __init__(self, master, award_name, year_text, config_file_path, config_label="", on_saved=None):
        if ctk is None:
            raise RuntimeError("当前环境缺少 customtkinter，无法打开配置编辑界面。")
        super().__init__(master)
        self.master = master
        self.award_name = award_name
        self.year_text = str(year_text or "").strip()
        self.year_key = _normalize_year_key(self.year_text)
        self.config_file_path = os.path.normpath(os.path.abspath(config_file_path))
        self.config_label = config_label or "配置文件"
        self.on_saved = on_saved

        self.default_data = {}
        self.profiles_data = {}
        self.year_effective_data = {}
        self.field_widgets = {}

        self.status_var = ctk.StringVar(value="读取中...")
        self.json_status_var = ctk.StringVar(value="JSON 仅作为第二个 tab 的高级参考与导入入口。")
        self.current_json_source_var = ctk.StringVar(value="未导入外部 JSON")

        self.title(f"{self.config_label} - {self.award_name} {self.year_text}")
        self.geometry("1460x900")
        self.minsize(1240, 760)
        self.configure(fg_color=APP_BG)
        self.attributes("-topmost", True)
        self.resizable(True, True)
        try:
            self.after(0, lambda: self.state("zoomed"))
        except Exception:
            pass

        self.load_from_config_file()
        self.build_layout()
        self.populate_form()
        self.refresh_json_tab()

        self.lift()
        self.focus_force()
        self.after(1200, lambda: self.attributes("-topmost", False))

    def build_layout(self):
        header = ctk.CTkFrame(self, **outer_panel_style())
        header.pack(fill="x", padx=18, pady=(18, 10))
        ctk.CTkLabel(header, text=f"{self.award_name} · {self.year_text} · {self.config_label}", font=ui_font(24, "bold"), text_color=TEXT_PRIMARY).pack(anchor="w", padx=18, pady=(16, 4))
        ctk.CTkLabel(header, text=self.config_file_path, font=ui_font(12), text_color=TEXT_MUTED).pack(anchor="w", padx=18, pady=(0, 4))
        ctk.CTkLabel(header, text="左边是默认值，只读；右边是当前年份配置，默认已按 DEFAULT 预填，可以直接改。", font=ui_font(12), text_color=TEXT_MUTED).pack(anchor="w", padx=18, pady=(0, 4))
        ctk.CTkLabel(header, textvariable=self.status_var, font=ui_font(12), text_color=TEXT_MUTED).pack(anchor="w", padx=18, pady=(0, 16))

        toolbar = ctk.CTkFrame(self, **panel_card_style())
        toolbar.pack(fill="x", padx=18, pady=(0, 10))
        ctk.CTkLabel(toolbar, textvariable=self.current_json_source_var, text_color=TEXT_MUTED, font=ui_font(11)).pack(side="left", padx=14, pady=10)
        action_bar = ctk.CTkFrame(toolbar, fg_color="transparent")
        action_bar.pack(side="right", padx=12, pady=8)
        ctk.CTkButton(action_bar, text="从配置重载", command=self.reload_from_disk, width=110, height=30, font=ui_font(12, "bold"), **button_secondary_style()).pack(side="left", padx=(0, 8))
        ctk.CTkButton(action_bar, text="校验", command=self.run_validation, width=78, height=30, font=ui_font(12, "bold"), **button_soft_style()).pack(side="left", padx=(0, 8))
        ctk.CTkButton(action_bar, text="保存到配置文件", command=self.save_to_config_file, width=138, height=30, font=ui_font(12, "bold"), **button_primary_style()).pack(side="left")

        self.tabview = ctk.CTkTabview(self, **tabview_style(fg_color="transparent"))
        self.tabview.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.tabview.add("表单编辑")
        self.tabview.add("JSON 参考")

        self._build_form_tab(self.tabview.tab("表单编辑"))
        self._build_json_tab(self.tabview.tab("JSON 参考"))
        self._bind_tab_refresh_events()

    def _build_form_tab(self, parent):
        form_card = ctk.CTkFrame(parent, **outer_panel_style())
        form_card.pack(fill="both", expand=True, padx=4, pady=4)

        header_row = ctk.CTkFrame(form_card, fg_color="transparent")
        header_row.pack(fill="x", padx=16, pady=(16, 8))
        header_row.grid_columnconfigure(0, weight=0, minsize=FORM_LABEL_COLUMN_WIDTH, uniform="config_cols")
        header_row.grid_columnconfigure(1, weight=1, minsize=FORM_VALUE_COLUMN_MIN_WIDTH, uniform="config_cols")
        header_row.grid_columnconfigure(2, weight=1, minsize=FORM_VALUE_COLUMN_MIN_WIDTH, uniform="config_cols")
        ctk.CTkLabel(header_row, text="配置项", font=ui_font(14, "bold"), text_color=TEXT_PRIMARY).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(header_row, text="DEFAULT（只读）", font=ui_font(14, "bold"), text_color=TEXT_PRIMARY).grid(row=0, column=1, sticky="w", padx=(12, 6))
        ctk.CTkLabel(header_row, text=f"{self.year_text} 配置", font=ui_font(14, "bold"), text_color=TEXT_PRIMARY).grid(row=0, column=2, sticky="w", padx=(12, 0))

        self.form_scroll = ctk.CTkScrollableFrame(form_card, **scrollable_style())
        self.form_scroll.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._build_form_fields()

    def _build_json_tab(self, parent):
        json_card = ctk.CTkFrame(parent, **outer_panel_style())
        json_card.pack(fill="both", expand=True, padx=4, pady=4)
        ctk.CTkLabel(json_card, text="JSON 高级参考", text_color=TEXT_PRIMARY, font=ui_font(18, "bold")).pack(anchor="w", padx=16, pady=(16, 2))
        ctk.CTkLabel(json_card, textvariable=self.json_status_var, text_color=TEXT_MUTED, font=ui_font(11)).pack(anchor="w", padx=16, pady=(0, 8))

        json_toolbar = ctk.CTkFrame(json_card, fg_color="transparent")
        json_toolbar.pack(fill="x", padx=14, pady=(0, 8))
        ctk.CTkButton(json_toolbar, text="表单 -> JSON 预览", command=self.sync_form_to_json, width=120, height=30, font=ui_font(12, "bold"), **button_secondary_style()).pack(side="left", padx=(0, 8))
        ctk.CTkButton(json_toolbar, text="应用当前 JSON", command=self.apply_json_editor_to_target, width=120, height=30, font=ui_font(12, "bold"), **button_soft_style()).pack(side="left", padx=(0, 8))
        ctk.CTkButton(json_toolbar, text="复制合并 JSON", command=self.copy_current_json_to_clipboard, width=120, height=30, font=ui_font(12, "bold"), **button_secondary_style()).pack(side="left")

        panes = ctk.CTkFrame(json_card, fg_color="transparent")
        panes.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        panes.grid_columnconfigure(0, weight=1)
        panes.grid_columnconfigure(1, weight=1)
        panes.grid_rowconfigure(0, weight=1)
        panes.grid_rowconfigure(1, weight=1)

        import_card = ctk.CTkFrame(panes, **panel_card_style())
        import_card.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 8))
        ctk.CTkLabel(import_card, text="导入 / 编辑 JSON", text_color=TEXT_PRIMARY, font=ui_font(14, "bold")).pack(anchor="w", padx=12, pady=(12, 6))
        self.json_editor = ctk.CTkTextbox(import_card, wrap="none", font=ui_font(11), **input_box_style())
        self.json_editor.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        profile_card = ctk.CTkFrame(panes, **panel_card_style())
        profile_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 8))
        ctk.CTkLabel(profile_card, text=f"{self.year_text} 覆盖 JSON", text_color=TEXT_PRIMARY, font=ui_font(14, "bold")).pack(anchor="w", padx=12, pady=(12, 6))
        self.profile_preview = ctk.CTkTextbox(profile_card, wrap="none", font=ui_font(11), **input_box_style())
        self.profile_preview.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.profile_preview.configure(state="disabled")

        merged_card = ctk.CTkFrame(panes, **panel_card_style())
        merged_card.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(8, 0))
        ctk.CTkLabel(merged_card, text=f"{self.year_text} 合并预览", text_color=TEXT_PRIMARY, font=ui_font(14, "bold")).pack(anchor="w", padx=12, pady=(12, 6))
        self.merged_preview = ctk.CTkTextbox(merged_card, wrap="none", font=ui_font(11), **input_box_style())
        self.merged_preview.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.merged_preview.configure(state="disabled")

    def _bind_tab_refresh_events(self):
        segmented = getattr(self.tabview, "_segmented_button", None)
        buttons_dict = getattr(segmented, "_buttons_dict", {}) if segmented else {}
        for tab_name, button_widget in buttons_dict.items():
            if getattr(button_widget, "_gb_config_refresh_bound", False):
                continue
            button_widget._gb_config_refresh_bound = True
            button_widget.bind("<ButtonRelease-1>", lambda _event, name=tab_name: self.after(10, lambda n=name: self._handle_tab_open(n)), add="+")

    def _handle_tab_open(self, tab_name):
        if tab_name != "JSON 参考":
            return
        self.refresh_json_reference_from_form()

    def _build_form_fields(self):
        for spec in FIELD_SPECS:
            card = ctk.CTkFrame(self.form_scroll, **surface_card_style())
            card.pack(fill="x", padx=4, pady=(0, 10))
            card.grid_columnconfigure(0, weight=0, minsize=FORM_LABEL_COLUMN_WIDTH, uniform="config_cols")
            card.grid_columnconfigure(1, weight=1, minsize=FORM_VALUE_COLUMN_MIN_WIDTH, uniform="config_cols")
            card.grid_columnconfigure(2, weight=1, minsize=FORM_VALUE_COLUMN_MIN_WIDTH, uniform="config_cols")

            label_frame = ctk.CTkFrame(card, fg_color="transparent")
            label_frame.grid(row=0, column=0, sticky="nsew", padx=(12, 8), pady=12)
            ctk.CTkLabel(label_frame, text=spec["label"], text_color=TEXT_PRIMARY, font=ui_font(13, "bold")).pack(anchor="w")
            helper_label = ctk.CTkLabel(label_frame, text=spec.get("help", ""), text_color=TEXT_MUTED, font=ui_font(11), justify="left", wraplength=FORM_LABEL_COLUMN_WIDTH - 36)
            helper_label.pack(anchor="w", pady=(4, 0))
            status_label = ctk.CTkLabel(label_frame, text="", text_color=TEXT_MUTED, font=ui_font(11))
            status_label.pack(anchor="w", pady=(6, 0))

            default_frame = ctk.CTkFrame(card, **panel_card_style())
            default_frame.grid(row=0, column=1, sticky="nsew", padx=8, pady=10)
            default_label = ctk.CTkLabel(default_frame, text="-", justify="left", anchor="w", text_color=TEXT_MUTED, font=ui_font(12), wraplength=FORM_VALUE_COLUMN_MIN_WIDTH - 48)
            default_label.pack(fill="x", padx=12, pady=12)

            edit_frame = ctk.CTkFrame(card, **panel_card_style())
            edit_frame.grid(row=0, column=2, sticky="nsew", padx=(8, 12), pady=10)

            info = {
                "spec": spec,
                "helper": helper_label,
                "status": status_label,
                "default_label": default_label,
                "edit_frame": edit_frame,
                "rows": [],
            }

            if spec["kind"] == "bool":
                default_frame.configure(height=FORM_SCALAR_CELL_MIN_HEIGHT)
                default_frame.pack_propagate(False)
                edit_frame.configure(height=FORM_SCALAR_CELL_MIN_HEIGHT)
                edit_frame.pack_propagate(False)
                widget = ctk.CTkOptionMenu(edit_frame, values=["是", "否"], font=ui_font(12), **option_menu_style())
                widget.pack(fill="x", padx=12, pady=12)
                info["widget"] = widget
            elif spec["kind"] == "choice":
                default_frame.configure(height=FORM_SCALAR_CELL_MIN_HEIGHT)
                default_frame.pack_propagate(False)
                edit_frame.configure(height=FORM_SCALAR_CELL_MIN_HEIGHT)
                edit_frame.pack_propagate(False)
                widget = ctk.CTkOptionMenu(edit_frame, values=list(spec.get("choices", [])), font=ui_font(12), **option_menu_style())
                widget.pack(fill="x", padx=12, pady=12)
                info["widget"] = widget
            elif spec["kind"] in {"int", "float", "list_int"}:
                default_frame.configure(height=FORM_SCALAR_CELL_MIN_HEIGHT)
                default_frame.pack_propagate(False)
                edit_frame.configure(height=FORM_SCALAR_CELL_MIN_HEIGHT)
                edit_frame.pack_propagate(False)
                widget = ctk.CTkEntry(edit_frame, font=ui_font(12), **input_box_style())
                widget.pack(fill="x", padx=12, pady=12)
                info["widget"] = widget
            elif spec["kind"].startswith("mapping_"):
                row_toolbar = ctk.CTkFrame(edit_frame, fg_color="transparent")
                row_toolbar.pack(fill="x", padx=12, pady=(10, 6))
                ctk.CTkLabel(row_toolbar, text="左边键名，右边数值", text_color=TEXT_MUTED, font=ui_font(11)).pack(side="left")
                ctk.CTkButton(row_toolbar, text="+", width=30, height=26, font=ui_font(14, "bold"), command=lambda key=spec["key"]: self.add_mapping_row(key), **button_soft_style()).pack(side="right")
                rows_container = ctk.CTkFrame(edit_frame, fg_color="transparent")
                rows_container.pack(fill="x", padx=12, pady=(0, 10))
                info["rows_container"] = rows_container
            self.field_widgets[spec["key"]] = info

    def add_mapping_row(self, field_key, key_text="", value_text=""):
        info = self.field_widgets[field_key]
        row_frame = ctk.CTkFrame(info["rows_container"], fg_color="transparent")
        row_frame.pack(fill="x", pady=(0, 6))
        key_entry = ctk.CTkEntry(row_frame, font=ui_font(12), width=200, **input_box_style())
        key_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        value_entry = ctk.CTkEntry(row_frame, font=ui_font(12), width=110, **input_box_style())
        value_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        remove_btn = ctk.CTkButton(row_frame, text="-", width=30, height=26, font=ui_font(14, "bold"), command=lambda: self.remove_mapping_row(field_key, row_frame), **button_warning_style())
        remove_btn.pack(side="left")
        if key_text:
            key_entry.insert(0, str(key_text))
        if value_text not in (None, ""):
            value_entry.insert(0, str(value_text))
        info["rows"].append({"frame": row_frame, "key_entry": key_entry, "value_entry": value_entry})

    def remove_mapping_row(self, field_key, row_frame):
        info = self.field_widgets[field_key]
        info["rows"] = [row for row in info["rows"] if row["frame"] != row_frame]
        row_frame.destroy()

    def _clear_mapping_rows(self, field_key):
        info = self.field_widgets[field_key]
        for row in info["rows"]:
            row["frame"].destroy()
        info["rows"] = []

    def _set_editor_value(self, spec, value):
        info = self.field_widgets[spec["key"]]
        kind = spec["kind"]
        if kind == "bool":
            info["widget"].set("是" if bool(value) else "否")
        elif kind == "choice":
            info["widget"].set(str(value))
        elif kind == "int":
            info["widget"].delete(0, "end")
            info["widget"].insert(0, str(int(value)))
        elif kind == "float":
            info["widget"].delete(0, "end")
            info["widget"].insert(0, str(float(value)))
        elif kind == "list_int":
            info["widget"].delete(0, "end")
            info["widget"].insert(0, ", ".join(str(item) for item in value))
        elif kind.startswith("mapping_"):
            self._clear_mapping_rows(spec["key"])
            if isinstance(value, dict):
                for k, v in value.items():
                    self.add_mapping_row(spec["key"], key_text=k, value_text=v)
            if not info["rows"]:
                self.add_mapping_row(spec["key"])

    def _get_editor_value(self, spec):
        info = self.field_widgets[spec["key"]]
        kind = spec["kind"]
        if kind == "bool":
            return info["widget"].get().strip() == "是"
        if kind == "choice":
            return info["widget"].get().strip()
        if kind == "int":
            return int(info["widget"].get().strip())
        if kind == "float":
            return float(info["widget"].get().strip())
        if kind == "list_int":
            return _parse_int_list(info["widget"].get().strip())
        if kind.startswith("mapping_"):
            result = {}
            for row in info["rows"]:
                raw_key = row["key_entry"].get().strip()
                raw_value = row["value_entry"].get().strip()
                if not raw_key and not raw_value:
                    continue
                if not raw_key:
                    raise ValueError(f"{spec['label']} 存在空键名。")
                if not raw_value:
                    raise ValueError(f"{spec['label']} 的 `{raw_key}` 缺少数值。")
                if kind == "mapping_int":
                    result[raw_key] = int(raw_value)
                else:
                    result[raw_key] = float(raw_value)
            if not result:
                raise ValueError(f"{spec['label']} 至少保留一行。")
            return result
        raise ValueError(f"未支持的字段类型: {kind}")

    def populate_form(self):
        for spec in FIELD_SPECS:
            default_value = self.default_data.get(spec["key"])
            year_value = self.year_effective_data.get(spec["key"])
            info = self.field_widgets[spec["key"]]
            info["default_label"].configure(text=_display_value(spec, default_value))
            self._set_editor_value(spec, year_value)
            status_text = "与 DEFAULT 一致" if default_value == year_value else "当前年份已覆盖"
            info["status"].configure(text=status_text, text_color=TEXT_MUTED if default_value == year_value else ACCENT)

    def apply_form_to_current_year(self):
        updated = _deepcopy_data(self.year_effective_data)
        try:
            for spec in FIELD_SPECS:
                updated[spec["key"]] = self._get_editor_value(spec)
        except Exception as exc:
            messagebox.showerror("表单解析失败", str(exc), parent=self)
            return False
        self.year_effective_data = updated
        self.populate_form()
        self.refresh_json_tab()
        self.status_var.set(f"已同步 {self.year_text} 配置，尚未写回文件。")
        return True

    def _build_profiles_for_save(self):
        profiles = _deepcopy_data(self.profiles_data)
        current_override = _build_profile_override(self.default_data, self.year_effective_data)
        if current_override:
            profiles[self.year_key] = current_override
        else:
            profiles.pop(self.year_key, None)
        return profiles

    def refresh_json_tab(self):
        current_override = _build_profile_override(self.default_data, self.year_effective_data)
        self.profile_preview.configure(state="normal")
        self.profile_preview.delete("1.0", "end")
        self.profile_preview.insert("1.0", _json_text(current_override))
        self.profile_preview.configure(state="disabled")

        self.merged_preview.configure(state="normal")
        self.merged_preview.delete("1.0", "end")
        self.merged_preview.insert("1.0", _json_text(self.year_effective_data))
        self.merged_preview.configure(state="disabled")

        self.json_editor.delete("1.0", "end")
        self.json_editor.insert("1.0", _json_text({"PROFILES": {self.year_text: current_override}}))

    def refresh_json_reference_from_form(self):
        if self.tabview.get() != "JSON 参考":
            return True
        if self.apply_form_to_current_year():
            return True
        self.after(10, lambda: self.tabview.set("表单编辑"))
        return False

    def sync_form_to_json(self):
        if self.apply_form_to_current_year():
            self.tabview.set("JSON 参考")

    def apply_import_payload(self, payload, source_label="外部 JSON"):
        try:
            if isinstance(payload, dict) and ("DEFAULT" in payload or "PROFILES" in payload):
                if "DEFAULT" in payload:
                    if not isinstance(payload["DEFAULT"], dict):
                        raise ValueError("DEFAULT 必须是字典。")
                    merged_default = _deepcopy_data(self.default_data)
                    merged_default.update(_deepcopy_data(payload["DEFAULT"]))
                    self.default_data = merged_default
                if "PROFILES" in payload:
                    merged_profiles = _deepcopy_data(self.profiles_data)
                    imported_profiles = _normalize_profiles(payload["PROFILES"])
                    for year_key, override_payload in imported_profiles.items():
                        current_payload = merged_profiles.get(year_key, {})
                        current_payload = _deepcopy_data(current_payload) if isinstance(current_payload, dict) else {}
                        current_payload.update(_deepcopy_data(override_payload))
                        merged_profiles[year_key] = current_payload
                    self.profiles_data = merged_profiles
                self.year_effective_data = _build_effective_year_data(self.default_data, self.profiles_data, self.year_key)
            elif isinstance(payload, dict):
                merged_effective = _deepcopy_data(self.year_effective_data)
                merged_effective.update(_deepcopy_data(payload))
                self.year_effective_data = merged_effective
            else:
                raise ValueError("导入内容必须是对象。")
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc), parent=self)
            return False

        self.current_json_source_var.set(f"最近导入: {source_label}")
        self.populate_form()
        self.refresh_json_tab()
        self.status_var.set(f"已导入 {source_label}，尚未写回文件。")
        return True

    def apply_json_editor_to_target(self):
        raw = self.json_editor.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning("提示", "当前 JSON 为空。", parent=self)
            return False
        try:
            payload = _parse_structured_text(raw)
        except Exception as exc:
            messagebox.showerror("JSON 解析失败", str(exc), parent=self)
            return False
        return self.apply_import_payload(payload, source_label="JSON 参考页")

    def load_json_file(self, json_path):
        if not json_path or not os.path.isfile(json_path):
            messagebox.showwarning("提示", f"未找到 JSON 文件:\n{json_path}", parent=self)
            return False
        try:
            with open(json_path, "r", encoding="utf-8") as fp:
                payload = json.load(fp)
        except Exception as exc:
            messagebox.showerror("读取 JSON 失败", f"{json_path}\n\n{exc}", parent=self)
            return False
        return self.apply_import_payload(payload, source_label=os.path.basename(json_path))

    def load_from_config_file(self):
        default_obj, profiles_obj = load_config_payload(self.config_file_path)
        self.default_data = default_obj
        self.profiles_data = profiles_obj
        self.year_effective_data = _build_effective_year_data(default_obj, profiles_obj, self.year_key)
        self.status_var.set("已从配置文件读取当前内容。")

    def reload_from_disk(self):
        try:
            self.load_from_config_file()
        except Exception as exc:
            messagebox.showerror("重载失败", str(exc), parent=self)
            return
        self.current_json_source_var.set("未导入外部 JSON")
        self.populate_form()
        self.refresh_json_tab()

    def run_validation(self):
        if not self.apply_form_to_current_year():
            return False
        profiles_for_save = self._build_profiles_for_save()
        errors = validate_config_payload(self.default_data, profiles_for_save)
        if errors:
            messagebox.showwarning("校验未通过", "\n".join(errors[:20]), parent=self)
            self.status_var.set(f"校验发现 {len(errors)} 个问题。")
            return False
        messagebox.showinfo("校验通过", "当前配置结构校验通过。", parent=self)
        self.status_var.set("校验通过，可保存。")
        return True

    def copy_current_json_to_clipboard(self):
        self.clipboard_clear()
        self.clipboard_append(_json_text(self.year_effective_data))
        self.status_var.set("当前年份合并 JSON 已复制到剪贴板。")

    def save_to_config_file(self):
        if not self.apply_form_to_current_year():
            return
        profiles_for_save = self._build_profiles_for_save()
        errors = validate_config_payload(self.default_data, profiles_for_save)
        if errors:
            messagebox.showwarning("保存前校验未通过", "\n".join(errors[:20]), parent=self)
            self.status_var.set(f"保存取消，校验发现 {len(errors)} 个问题。")
            return
        confirmed = messagebox.askokcancel(
            "确认保存",
            f"将直接改写以下配置文件：\n{self.config_file_path}\n\n确认继续吗？",
            parent=self,
        )
        if not confirmed:
            self.status_var.set("已取消保存。")
            return
        try:
            save_config_payload(self.config_file_path, self.default_data, profiles_for_save)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            self.status_var.set("保存失败，请查看报错。")
            return
        self.profiles_data = _deepcopy_data(profiles_for_save)
        self.status_var.set(f"保存成功，已直接写回 {self.config_file_path}")
        messagebox.showinfo("保存成功", f"配置已直接写回：\n{self.config_file_path}", parent=self)
        if callable(self.on_saved):
            try:
                self.on_saved(self.config_file_path)
            except Exception:
                pass
