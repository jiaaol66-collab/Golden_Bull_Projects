import inspect
import json
import os

def _clean_text(value):
    return str(value or "").strip()

def _normalize_rel_path(path_text):
    text = _clean_text(path_text).replace("\\", "/")
    return "/".join(part for part in text.split("/") if part)

AWARD_CONFIG = {
    "私募金牛奖": {
        "folder": "GB_PriFund",
        "manifest_award": "私募",
        "config_module": "userlib.configs.prifund_config",
        "config_file": "userlib/configs/prifund_config.py",
        "config_label": "私募配置"
    },
    "公募金牛奖": {
        "folder": "GB_PubFund",
        "manifest_award": "公募",
        "config_module": "",
        "config_file": "",
        "config_label": ""
    },
    "银行理财金牛奖(产品奖)": {
        "folder": "GB_BankWM/银行理财产品奖步骤",
        "manifest_award": "银行理财",
        "config_module": "",
        "config_file": "",
        "config_label": ""
    },
    "银行理财金牛奖(其他奖)": {
        "folder": "GB_BankWM/银行金牛奖(其他)步骤",
        "manifest_award": "银理其他",
        "config_module": "",
        "config_file": "",
        "config_label": ""
    },
    "分析师金牛奖": {
        "folder": "GB_Analyst",
        "manifest_award": "分析师",
        "config_module": "userlib.configs.analyst_config",
        "config_file": "userlib/configs/analyst_config.py",
        "config_label": "分析师配置"
    },
    "券商资管金牛奖": {
        "folder": "GB_BrokerAM",
        "manifest_award": "券商资管",
        "config_module": "userlib.configs.broker_am_config",
        "config_file": "userlib/configs/broker_am_config.py",
        "config_label": "券商资管配置"
    },
    "测试流程": {
        "folder": "GB_Test",
        "manifest_award": "测试",
        "config_module": "",
        "config_file": "",
        "config_label": ""
    },
    "证券公司金牛奖(营业部)": {
        "folder": "GB_BrokerBranch",
        "manifest_award": "营业部",
        "config_module": "userlib.configs.broker_branch_config",
        "config_file": "userlib/configs/broker_branch_config.py",
        "config_label": "营业部配置"
    }
}

def _norm_payload(payload):
    payload = payload or {}
    return {
        "folder": _normalize_rel_path(payload.get("folder", "")),
        "manifest_award": _clean_text(payload.get("manifest_award", "")),
        "config_module": _clean_text(payload.get("config_module", "")),
        "config_file": _normalize_rel_path(payload.get("config_file", "")),
        "config_label": _clean_text(payload.get("config_label", "")),
    }

def _build_award_folder_map():
    mapping = {}
    for label, payload in AWARD_CONFIG.items():
        folder = _normalize_rel_path(payload.get("folder", ""))
        if not folder:
            continue
        mapping[label] = folder

        manifest_award = _clean_text(payload.get("manifest_award", ""))
        if manifest_award and manifest_award not in mapping:
            mapping[manifest_award] = folder

        stripped_label = _clean_text(label.replace("金牛奖", ""))
        if stripped_label and stripped_label not in mapping:
            mapping[stripped_label] = folder
    return mapping

AWARD_FOLDER_MAP = _build_award_folder_map()

def get_award_labels():
    return list(AWARD_CONFIG.keys())

def get_award_folder(award_name):
    award_key = _clean_text(award_name)
    payload = AWARD_CONFIG.get(award_key, {})
    folder = payload.get("folder", "")
    if not folder:
        folder = AWARD_FOLDER_MAP.get(award_key, "")
    return os.path.normpath(folder) if folder else ""

def get_manifest_award(award_name):
    payload = AWARD_CONFIG.get(_clean_text(award_name), {})
    return payload.get("manifest_award", _clean_text(award_name))

def get_award_config_module(award_name):
    payload = AWARD_CONFIG.get(_clean_text(award_name), {})
    return payload.get("config_module", "")

def get_award_config_label(award_name):
    payload = AWARD_CONFIG.get(_clean_text(award_name), {})
    return payload.get("config_label", "")

def get_award_config_file(award_name, project_root=None):
    payload = AWARD_CONFIG.get(_clean_text(award_name), {})
    config_file = payload.get("config_file", "")
    if not config_file:
        return ""
    base_dir = project_root or os.path.dirname(os.path.abspath(__file__))
    configured_path = os.path.normpath(os.path.join(base_dir, config_file))
    if os.path.isfile(configured_path):
        return configured_path

    normalized_file = _normalize_rel_path(config_file)
    path_parts = normalized_file.split("/")
    if len(path_parts) == 2 and path_parts[0] == "userlib":
        fallback_path = os.path.normpath(
            os.path.join(base_dir, "userlib", "configs", path_parts[-1])
        )
        if os.path.isfile(fallback_path):
            return fallback_path
    return configured_path

def has_award_config(award_name, project_root=None):
    config_file = get_award_config_file(award_name, project_root=project_root)
    return bool(config_file and os.path.isfile(config_file))

def _get_project_root(project_root=None):
    return os.path.abspath(project_root or os.path.dirname(os.path.abspath(__file__)))

def _render_module(config_map):
    normalized = {label: _norm_payload(payload) for label, payload in config_map.items()}
    pieces = [
        "import inspect",
        "import json",
        "import os",
        "",
        inspect.getsource(_clean_text).rstrip(),
        "",
        inspect.getsource(_normalize_rel_path).rstrip(),
        "",
        "AWARD_CONFIG = " + json.dumps(normalized, ensure_ascii=False, indent=4),
        "",
        inspect.getsource(_norm_payload).rstrip(),
        "",
        inspect.getsource(_build_award_folder_map).rstrip(),
        "",
        "AWARD_FOLDER_MAP = _build_award_folder_map()",
        "",
        inspect.getsource(get_award_labels).rstrip(),
        "",
        inspect.getsource(get_award_folder).rstrip(),
        "",
        inspect.getsource(get_manifest_award).rstrip(),
        "",
        inspect.getsource(get_award_config_module).rstrip(),
        "",
        inspect.getsource(get_award_config_label).rstrip(),
        "",
        inspect.getsource(get_award_config_file).rstrip(),
        "",
        inspect.getsource(has_award_config).rstrip(),
        "",
        inspect.getsource(_get_project_root).rstrip(),
        "",
        inspect.getsource(_render_module).rstrip(),
        "",
        inspect.getsource(_write_award_config_file).rstrip(),
        "",
        inspect.getsource(register_award_template).rstrip(),
        "",
    ]
    return "\n".join(pieces).rstrip() + "\n"

def _write_award_config_file(config_map, project_root=None):
    target_path = os.path.join(_get_project_root(project_root), "award_config.py")
    content = _render_module(config_map)
    with open(target_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return target_path

def register_award_template(
    award_name,
    english_award_name="",
    folder="",
    manifest_award="",
    config_module="",
    config_file="",
    config_label="",
    project_root=None,
):
    award_label = _clean_text(award_name)
    folder_rel = _normalize_rel_path(folder or english_award_name)
    if not award_label:
        raise ValueError("award_name 不能为空")
    if not folder_rel:
        raise ValueError("folder 或 english_award_name 至少提供一个")

    updated_config = dict(AWARD_CONFIG)
    existing = updated_config.get(award_label, {})
    payload = _norm_payload(
        {
            "folder": folder_rel,
            "manifest_award": manifest_award or existing.get("manifest_award", "") or award_label,
            "config_module": config_module or existing.get("config_module", ""),
            "config_file": config_file or existing.get("config_file", ""),
            "config_label": config_label or existing.get("config_label", ""),
        }
    )
    if _norm_payload(existing) == payload:
        return dict(payload)

    updated_config[award_label] = payload
    _write_award_config_file(updated_config, project_root=project_root)
    AWARD_CONFIG.clear()
    AWARD_CONFIG.update(updated_config)
    AWARD_FOLDER_MAP.clear()
    AWARD_FOLDER_MAP.update(_build_award_folder_map())
    return dict(payload)
