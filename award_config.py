import os


AWARD_CONFIG = {
    "私募金牛奖": {
        "folder": "私募金牛奖步骤",
        "manifest_award": "私募",
        "config_module": "userlib.prifund_config",
        "config_file": os.path.join("userlib", "prifund_config.py"),
        "config_label": "私募配置",
    },
    "公募金牛奖": {
        "folder": "公募金牛奖步骤",
        "manifest_award": "公募",
        "config_module": "",
        "config_file": "",
        "config_label": "",
    },
    "银行理财金牛奖(产品奖)": {
        "folder": os.path.join("银行理财金牛奖步骤", "银行理财产品奖步骤"),
        "manifest_award": "银行理财",
        "config_module": "",
        "config_file": "",
        "config_label": "",
    },
    "银行理财金牛奖(其他奖)": {
        "folder": os.path.join("银行理财金牛奖步骤", "银行金牛奖(其他)步骤"),
        "manifest_award": "银理其他",
        "config_module": "",
        "config_file": "",
        "config_label": "",
    },
    "分析师金牛奖": {
        "folder": "分析师金牛奖客观评价步骤",
        "manifest_award": "分析师",
        "config_module": "",
        "config_file": "",
        "config_label": "",
    },
    "券商资管金牛奖": {
        "folder": "券商资管金牛奖步骤",
        "manifest_award": "券商资管",
        "config_module": "",
        "config_file": "",
        "config_label": "",
    },
}

AWARD_FOLDER_MAP = {label: payload["folder"] for label, payload in AWARD_CONFIG.items()}


def get_award_labels():
    return list(AWARD_CONFIG.keys())


def get_award_folder(award_name):
    payload = AWARD_CONFIG.get(str(award_name or "").strip(), {})
    return payload.get("folder", "")


def get_manifest_award(award_name):
    payload = AWARD_CONFIG.get(str(award_name or "").strip(), {})
    return payload.get("manifest_award", str(award_name or "").strip())


def get_award_config_module(award_name):
    payload = AWARD_CONFIG.get(str(award_name or "").strip(), {})
    return payload.get("config_module", "")


def get_award_config_label(award_name):
    payload = AWARD_CONFIG.get(str(award_name or "").strip(), {})
    return payload.get("config_label", "")


def get_award_config_file(award_name, project_root=None):
    payload = AWARD_CONFIG.get(str(award_name or "").strip(), {})
    config_file = payload.get("config_file", "")
    if not config_file:
        return ""
    base_dir = project_root or os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(base_dir, config_file))


def has_award_config(award_name, project_root=None):
    config_file = get_award_config_file(award_name, project_root=project_root)
    return bool(config_file and os.path.isfile(config_file))
