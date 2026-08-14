# -*- coding: utf-8 -*-
"""
BrokerAM · 证券公司集合资管计划金牛奖 —— 按年存储的集中配置
================================================================
设计（与私募 prifund_config 完全同构）：
  DEFAULT      = 最新一届（2025 / 评奖截止 2024-12-31）的全部口径。
  PROFILES[yr] = 某评奖年份相对 DEFAULT 的“差异覆盖”。往年定稿、可定死。
  for_year(yr) -> 解析出该年份完整口径对象 CFG，业务脚本只用 CFG。

用法（脚本里）：
  from userlib import broker_am_config as C
  CFG = C.for_year(yr)               # yr 仍由原有 年份信息.txt 读取
  CFG.score_weight_shf               # 取常量：股票多头/混合/FOF 指标权重
  CFG.score_weight_for('债券型')      # 取推导值：按投资类型返回对应权重表
  CFG.setup_cutoff(3)                # 取推导日期：三年期设立截止日
  CFG.stat_period(5)                 # 取推导区间：五年期统计期间

年份语义：yr=评奖年份；考察期最近年 = 评价期末 = yr-1（方案称 T）。
  例：yr=2025 → 评价期末 2024-12-31；yr=2024 → 评价期末 2023-12-31。

方案来源：《2025证券公司集合资管计划金牛奖评选方案》
"""

# ============================================================
# DEFAULT —— 最新一届（2025，评价期末 2024-12-31）的完整口径
# ============================================================
DEFAULT = {'all_terms': [1, 3, 5],
 'terms': [1, 3, 5],
 'score_weight_shf': {'年化收益': 0.3, '风险调整后收益': 0.25, '超大盘收益率': 0.15, '最大回撤': 0.2, '机构占比': 0.1},
 'score_weight_bond': {'年化收益': 0.35, '风险调整后收益': 0.2, '超大盘收益率': 0.15, '最大回撤': 0.2, '机构占比': 0.1},
 'score_weight_quant': {'股票': 0.1, '混合': 0.25, '债券': 0.2, 'FOF': 0.15, '规模': 0.2, '规模增速': 0.1},
 'score_weight_qual': {'规范度': 0.2, '运营管理能力': 0.2, '投资绩效获取能力': 0.3, '产品线广度': 0.3},
 'score_weight_quant_qual': {'定量总分': 0.7, '定性总分': 0.3},
 'manager_optional_metrics': {'规范度': {'file_stem': '资产管理业务收入',
                                      'value_col': '资产管理业务收入',
                                      'sheet_name': '万得',
                                      'usecols': [1, 2]},
                              '运营管理能力': {'file_stem': '营业收入',
                                         'value_col': '营业收入',
                                         'sheet_name': '万得',
                                         'usecols': [1, 2]}},
 'metric_desc': {'年化收益': '周度收益率的年化值',
                 '风险调整后收益': '周度收益率的Sharpe指数',
                 '超大盘收益率': '周度收益率的Treynor指数',
                 '最大回撤': '区间单位净值回撤幅度的最大值',
                 '机构占比': '机构投资者（含券商自持）的占比'},
 'invest_types': ['股票多头型', '混合型', '债券型', 'FOF型'],
 'shf_types': ['股票多头型', '混合型', 'FOF型'],
 'bond_types': ['债券型'],
 'stock_name': '股票多头型',
 'fof_name': 'FOF',
 'min_scale_yi': 0.3,
 'scale_relax_ratio': 0.9,
 'scale_use_group_median_max': True,
 'top_rank_ratio': 0.4,
 'min_group_size': 10,
 'missing_rate_cut': 0.15,
 'setup_cutoff_year_offset': {1: 2, 3: 4, 5: 6},
 'setup_cutoff_md': {1: (12, 1), 3: (12, 21), 5: (12, 21)},
 'winner_ratio_product': 0.05,
 'winner_cap_product': 10,
 'winner_ratio_manager': 0.05,
 'manager_min_scale_yi': 2.0,
 'manager_min_products': 2,
 'manager_exclude_types': ['指数型', 'QDII型'],
 'split_big_small': False,
 'freq': '周度',
 'annual_factor': {'周度': 52, '月度': 12},
 'rf_from_data': True,
 'sharpe_col': '风险调整后收益',
 'treynor_col': '超大盘收益率',
 'score_method': '1',
 'abnormal_z_threshold': 2,
 'abnormal_method': 'median',
 'inspection_end_md': (12, 31),
 'nav_lookback_years': 8,
 'dataset_ingestion': {'bundle_parts': [],
                       'source_dirs': ['上传数据', '补充资料'],
                       'info_file': '报名表.xlsx',
                       'id_column': 'id',
                       'company_name_column': 'f_company_name',
                       'skiprows': [1]}}


# ============================================================
# PROFILES —— 按年份覆盖（只写与 DEFAULT 不同的项；往年可定死）
# ============================================================
PROFILES = {2025: {},
 2024: {'stock_name': '股票型',
        'fof_name': 'FOF/MOM',
        'invest_types': ['股票型', '混合型', '债券型', 'FOF/MOM型'],
        'shf_types': ['股票型', '混合型', 'FOF/MOM型'],
        'score_weight_shf': {'年化收益': 0.3,
                             '风险调整后收益': 0.25,
                             '超大盘收益率': 0.15,
                             '最大回撤': 0.15,
                             '机构占比': 0.075,
                             '券商自持': 0.075},
        'score_weight_bond': {'年化收益': 0.35,
                              '风险调整后收益': 0.2,
                              '超大盘收益率': 0.15,
                              '最大回撤': 0.15,
                              '机构占比': 0.075,
                              '券商自持': 0.075},
        'score_weight_quant': {'股票': 0.1,
                               '混合': 0.25,
                               '债券': 0.2,
                               'FOF/MOM': 0.15,
                               '规模': 0.2,
                               '规模增速': 0.1},
        'dataset_ingestion': {'bundle_parts': [],
                              'source_dirs': ['goldenbull_zqzg/upload_data',
                                              'goldenbull_zqzg/upload_data_ex'],
                              'info_file': '用户信息表.xlsx',
                              'id_column': 'ID',
                              'company_name_column': '公司名称',
                              'skiprows': [0]}},
 2026: {'score_weight_quant_qual': {'定量总分': 1.0, '定性总分': 0.0},
        'setup_cutoff_year_offset': {'1': 2, '3': 4, '5': 6},
        'setup_cutoff_md': {'1': (12, 1), '3': (12, 21), '5': (12, 21)},
        'dataset_ingestion': {'bundle_parts': [],
                              'source_dirs': ['goldenbull_zg', 'goldenbull_zg_ex'],
                              'info_file': '资管_用户注册表.xlsx',
                              'id_column': 'f_user_id',
                              'file_column': 'f_file_name',
                              'company_name_column': 'f_company',
                              'skiprows': [],
                              'manifest_output_subdir': '其他',
                              'manifest_tables': {
                                  '上传文件': {
                                      'source_dir': 'goldenbull_zg',
                                      'index_file': '资管_报名资料表.xlsx',
                                      'sheet_name': 'zg_data_list',
                                      'id_column': 'f_user_id',
                                      'file_column': 'f_file_name',
                                      'time_column': 'f_upload_time',
                                      'skiprows': []},
                                  '补充数据': {
                                      'source_dir': 'goldenbull_zg_ex',
                                      'index_file': '资管_补充资料表.xlsx',
                                      'sheet_name': 'zg_data_list_ex',
                                      'id_column': 'f_user_id',
                                      'file_column': 'f_file_name',
                                      'time_column': 'f_upload_date',
                                      'skiprows': []}}}}}


# ============================================================
# 解析为“某年口径”对象
# ============================================================
class _YearConfig:
    """绑定到某评奖年份 yr 的口径：常量直接当属性，推导值用方法。"""

    def __init__(self, yr, d):
        self.yr = yr
        self._d = d
        for k, v in d.items():
            setattr(self, k, v)

    # ---- 指标权重：按投资类型返回对应表 ----
    def score_weight_for(self, invest_type):
        """传入投资类型（如 '债券型' / '混合型'），返回对应指标权重字典。"""
        it = invest_type.replace('型', '')  # 容错：'债券型' / '债券' 都可
        if any(it in t for t in self.bond_types) or '债券' in invest_type:
            return self.score_weight_bond
        return self.score_weight_shf

    # ---- 设立截止日（含建仓期）----
    def setup_cutoff(self, term):
        import datetime as _dt
        m, day = self.setup_cutoff_md[term]
        y = self.yr - self.setup_cutoff_year_offset[term]
        return _dt.datetime(y, m, day)

    # ---- 统计期间：(区间起, 区间止) ----
    def stat_period(self, term):
        """term=1/3/5 → 自然年度区间。起=yr-term 年1月1日，止=评价期末。"""
        import datetime as _dt
        start = _dt.datetime(self.yr - term, 1, 1)
        return start, self.inspection_end()

    # ---- 评价期末（T年12月31日）----
    def inspection_end(self):
        import datetime as _dt
        m, day = self.inspection_end_md
        return _dt.datetime(self.yr - 1, m, day)

    # ---- 规模门槛：放宽后的绝对下限 ----
    def min_scale_relaxed(self):
        return self.min_scale_yi * self.scale_relax_ratio  # 0.3 * 0.9 = 0.27亿

    # ---- 产品获奖名额上限 ----
    def product_winner_cap(self, n_candidates):
        import math
        return min(math.ceil(n_candidates * self.winner_ratio_product),
                   self.winner_cap_product)

    # ---- 管理人获奖名额上限 ----
    def manager_winner_cap(self, n_companies):
        import math
        return math.ceil(n_companies * self.winner_ratio_manager)

    # ---- 年化因子 ----
    def annualize(self):
        return self.annual_factor[self.freq]


def for_year(yr):
    """解析某评奖年份的完整口径（DEFAULT 叠加 PROFILES[yr]）。"""
    merged = dict(DEFAULT)
    merged.update(PROFILES.get(yr, {}))
    return _YearConfig(yr, merged)
