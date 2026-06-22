import os


AWARD_CONFIG = {
    "私募金牛奖": {
        "folder": "私募金牛奖步骤",
        "manifest_award": "私募",
    },
    "公募金牛奖": {
        "folder": "公募金牛奖步骤",
        "manifest_award": "公募",
    },
    "银行理财金牛奖(产品奖)": {
        "folder": os.path.join("银行理财金牛奖步骤", "银行理财产品奖步骤"),
        "manifest_award": "银行理财",
    },
    "银行理财金牛奖(其他奖)": {
        "folder": os.path.join("银行理财金牛奖步骤", "银行金牛奖(其他)步骤"),
        "manifest_award": "银理其他",
    },
    "分析师金牛奖": {
        "folder": "分析师金牛奖客观评价步骤",
        "manifest_award": "分析师",
    },
    "券商资管金牛奖": {
        "folder": "券商资管金牛奖步骤",
        "manifest_award": "券商资管",
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
