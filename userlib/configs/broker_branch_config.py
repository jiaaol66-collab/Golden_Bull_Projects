# -*- coding: utf-8 -*-
"""
BrokerBranch · 证券公司营业部金牛奖 —— 按年存储的集中配置
========================================================
原始数据集根目录由 Terminal 的 ``dataset_path`` 指定；本文件只描述
数据集内部目录、索引表、关联键和 Excel 读取参数。

用法：
  from userlib.configs import broker_branch_config as C
  CFG = C.for_year(yr)
  CFG.dataset_ingestion
"""


# ============================================================
# DEFAULT —— 最新一届（2026）的完整配置
# ============================================================
DEFAULT = {
    "dataset_ingestion": {
        "bundle_parts": [],
        "source_dirs": ["goldenbull_yyb", "goldenbull_yyb_ex"],
        "info_file": "营业部_用户注册表.xlsx",
        "id_column": "f_user_id",
        "file_column": "f_file_name",
        "company_short_name_column": "f_company_name",
        "company_name_column": "f_company_name",
        "skiprows": [],
        "manifest_output_subdir": "提取数据",
        "manifest_tables": {
            "上传文件": {
                "source_dir": "goldenbull_yyb",
                "index_file": "营业部_报名资料表.xlsx",
                "sheet_name": "yyb_data_list",
                "id_column": "f_user_id",
                "file_column": "f_file_name",
                "time_column": "f_upload_time",
                "skiprows": [],
            },
            "补充数据": {
                "source_dir": "goldenbull_yyb_ex",
                "index_file": "营业部_补充资料表.xlsx",
                "sheet_name": "yyb_data_list_ex",
                "id_column": "f_user_id",
                "file_column": "f_file_name",
                "time_column": "f_upload_date",
                "skiprows": [],
            },
        },
    }
}


# ============================================================
# PROFILES —— 按年份覆盖（只写与 DEFAULT 不同的项）
# ============================================================
PROFILES = {2026: {}}


class _YearConfig:
    """绑定到某评奖年份的配置对象。"""

    def __init__(self, yr, data):
        self.yr = yr
        self._d = data
        for key, value in data.items():
            setattr(self, key, value)


def for_year(yr):
    """解析某评奖年份的完整配置（DEFAULT 叠加 PROFILES[yr]）。"""
    merged = dict(DEFAULT)
    merged.update(PROFILES.get(yr, {}))
    return _YearConfig(yr, merged)
