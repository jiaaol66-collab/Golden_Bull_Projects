# -*- coding: utf-8 -*-
"""
Analyst · 证券业分析师金牛奖 —— 按年存储的集中配置
==================================================
设计（与 broker_am_config 同构）：
  DEFAULT      = 最新一届的完整配置。
  PROFILES[yr] = 某评奖年份相对 DEFAULT 的差异覆盖。
  for_year(yr) -> 解析出绑定该年份的完整配置对象 CFG。

用法：
  from userlib.configs import analyst_config as C
  CFG = C.for_year(yr)
  CFG.dataset_ingestion

原始数据集根目录由 Terminal 的 ``dataset_path`` 指定；本文件仅描述
该目录内部的上传资料目录、注册表文件、关联键和 Excel 读取参数。
"""


# ============================================================
# DEFAULT —— 最新一届（2026）的完整配置
# ============================================================
DEFAULT = {'dataset_ingestion': {'bundle_parts': [],
                       'source_dirs': ['goldenbull_fxs', 'goldenbull_fxs_ex'],
                       'info_file': '分析师_用户注册表.xlsx',
                       'id_column': 'f_user_id',
                       'company_short_name_column': 'f_company',
                       'company_name_column': 'f_company_name',
                       'skiprows': []}}


# ============================================================
# PROFILES —— 按年份覆盖（只写与 DEFAULT 不同的项）
# ============================================================
PROFILES = {2025: {'dataset_ingestion': {'bundle_parts': [],
                              'source_dirs': ['分析师/数据资料', '分析师/数据资料补充'],
                              'info_file': '用户报名表.xlsx',
                              'id_column': 'id',
                              'company_short_name_column': 'f_company_name',
                              'company_name_column': 'f_company_name',
                              'skiprows': []}},
 2024: {'dataset_ingestion': {'bundle_parts': [],
                              'source_dirs': ['分析师/数据资料', '分析师/数据资料补充'],
                              'info_file': '用户报名表.xlsx',
                              'id_column': 'ID',
                              'company_short_name_column': 'company_name',
                              'company_name_column': 'company_name',
                              'skiprows': [1]}}}


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
