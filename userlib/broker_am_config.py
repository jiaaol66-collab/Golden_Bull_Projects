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
DEFAULT = {
    # -------- 评奖期限（券商所有投资类型统一 1/3/5 年）--------
    'all_terms': [1, 3, 5],
    'terms': [1, 3, 5],

    # -------- 各奖项指标权重 --------
    # 股票多头型 / 混合型 / FOF型 —— 共用同一套指标（方案 1.1）
    'score_weight_shf': {'年化收益': 0.30, '风险调整后收益': 0.25,
                         '超大盘收益率': 0.15, '最大回撤': 0.20, '机构占比': 0.10},
    # 债券型 —— 单独一套（方案 1.2，年化收益更重、Sharpe 更轻）
    'score_weight_bond': {'年化收益': 0.35, '风险调整后收益': 0.20,
                          '超大盘收益率': 0.15, '最大回撤': 0.20, '机构占比': 0.10},
    # 管理人 · 定量维度（占管理人总分 70%，方案管理人指标体系）
    'score_weight_quant': {'股票': 0.10, '混合': 0.25, '债券': 0.20,
                           'FOF': 0.15, '规模': 0.20, '规模增速': 0.10},
    # 管理人 · 定性维度（占管理人总分 30%）
    'score_weight_qual': {'规范度': 0.20, '运营管理能力': 0.20,
                          '投资绩效获取能力': 0.30, '产品线广度': 0.30},
    # 管理人 · 定量/定性配比
    'score_weight_quant_qual': {'定量总分': 0.70, '定性总分': 0.30},

    # 指标口径解释（方案“指标解释”列，供注释/校验用，不参与计算）
    'metric_desc': {'年化收益': '周度收益率的年化值',
                    '风险调整后收益': '周度收益率的Sharpe指数',
                    '超大盘收益率': '周度收益率的Treynor指数',
                    '最大回撤': '区间单位净值回撤幅度的最大值',
                    '机构占比': '机构投资者（含券商自持）的占比'},

    # -------- 投资类型 / 命名（随年份可能改名，故进配置）--------
    'invest_types': ['股票多头型', '混合型', '债券型', 'FOF型'],
    'shf_types': ['股票多头型', '混合型', 'FOF型'],   # 用 score_weight_shf 的类型
    'bond_types': ['债券型'],                          # 用 score_weight_bond 的类型
    'stock_name': '股票多头型',                        # 股票类当年正式名
    'fof_name': 'FOF',                                 # FOF 类当年正式名（quant 键同名）

    # -------- 产品评选门槛（方案“评选方法”）--------
    # 注：规模门槛只在排名结果里“提示”，不做剔除；实际比较下限用放宽后的值。
    'min_scale_yi': 0.3,                 # 名义门槛：非货币计划资产净值 ≥ 3000万元
    'scale_relax_ratio': 0.9,            # 放宽至 90% → 实际比较下限 2700万
    'scale_use_group_median_max': True,  # 与“同类计划规模中位值”孰高者取高
    'top_rank_ratio': 0.4,               # 净值增长率为正 或 排同类前 40%
    'min_group_size': 10,                # 每个可比组别同类产品不少于 10 只

    # -------- 缺失率（数据完整性，方案“其他补充细则”）--------
    'missing_rate_cut': 0.15,            # 考察期总缺失率 > 15% 剔除

    # -------- 运作时间门槛（建仓期 10 天已折进日期）--------
    # 截至评价期末，实际运作不短于：13个月 / 36个月+10天 / 60个月+10天
    # 换算成“设立日不得晚于” 的截止日：yr-offset 年 的 (月, 日)
    'setup_cutoff_year_offset': {1: 2, 3: 4, 5: 6},
    'setup_cutoff_md': {1: (12, 1), 3: (12, 21), 5: (12, 21)},
    # 例 yr=2025：1年→2023-12-01，3年→2021-12-21，5年→2019-12-21

    # -------- 获奖名额（方案“获奖范围”）--------
    # 本项目不做“截断”，仅用于在排名结果里“高亮”名额内产品，供人工复核。
    'winner_ratio_product': 0.05,        # 计划：原则上 ≤ 参评计划数 5%
    'winner_cap_product': 10,            # 计划：10 只为上限
    'winner_ratio_manager': 0.05,        # 管理人：原则上 ≤ 参评公司数 5%

    # -------- 管理人参评门槛（方案“管理人评选范围”）--------
    # 本届暂不接入代码（保留备用）；如需启用见接入说明。
    'manager_min_scale_yi': 2.0,         # 评价期末总资产管理规模 ≥ 2亿元
    'manager_min_products': 2,           # 运作满1年集合计划 ≥ 2只
    'manager_exclude_types': ['指数型', 'QDII型'],  # 上一条统计时排除的类型

    # -------- 大集合 / 小集合 --------
    'split_big_small': False,            # 本届统一评选，不拆分大/小集合

    # -------- 计算口径 --------
    'freq': '周度',                       # 方案明确用周度收益率
    'annual_factor': {'周度': 52, '月度': 12},
    'rf_from_data': True,                # 无风险利率取数据均值（非固定 0）
    'sharpe_col': '风险调整后收益',        # Sharpe 落到的列名
    'treynor_col': '超大盘收益率',         # Treynor 落到的列名
    'score_method': '1',                  # 排名算法（对应工作区“算法1”）
    'abnormal_z_threshold': 2,            # Sharpe/Treynor |Z| ≥ 2 判异常
    'abnormal_method': 'median',          # 异常处理方式

    # -------- 关键日期基准 --------
    'inspection_end_md': (12, 31),        # 评价期末：T年(=yr-1) 12月31日
    'nav_lookback_years': 8,              # 净值回溯窗口（沿用私募口径）

    # -------- 原始数据集读取口径 --------
    # 由 terminal 侧指定 dataset_path 后，步骤脚本再按这里的 schema 去找报名表和上传目录。
    'dataset_ingestion': {
        'required_files': ['报名表.xlsx'],
        'required_dirs': ['上传数据', '补充资料'],
        'bundle_parts': [],
        'source_dirs': ['上传数据', '补充资料'],
        'info_file': '报名表.xlsx',
        'id_column': 'id',
        'company_name_column': 'f_company_name',
        'skiprows': [1],
    },
}


# ============================================================
# PROFILES —— 按年份覆盖（只写与 DEFAULT 不同的项；往年可定死）
# ============================================================
PROFILES = {
    2025: {},   # 与 DEFAULT 完全一致

    2024: {
        # 2024 届命名不同：股票型 / FOF/MOM
        'stock_name': '股票型',
        'fof_name': 'FOF/MOM',
        'invest_types': ['股票型', '混合型', '债券型', 'FOF/MOM型'],
        'shf_types': ['股票型', '混合型', 'FOF/MOM型'],
        # 2024 届把 机构占比 拆成 机构占比 + 券商自持 各 7.5%，回撤 15%
        'score_weight_shf': {'年化收益': 0.30, '风险调整后收益': 0.25, '超大盘收益率': 0.15,
                             '最大回撤': 0.15, '机构占比': 0.075, '券商自持': 0.075},
        'score_weight_bond': {'年化收益': 0.35, '风险调整后收益': 0.20, '超大盘收益率': 0.15,
                              '最大回撤': 0.15, '机构占比': 0.075, '券商自持': 0.075},
        # 定量维度 FOF 键随命名改为 FOF/MOM
        'score_weight_quant': {'股票': 0.10, '混合': 0.25, '债券': 0.20,
                               'FOF/MOM': 0.15, '规模': 0.20, '规模增速': 0.10},
        'dataset_ingestion': {
            'required_files': ['用户信息表.xlsx'],
            'required_dirs': ['goldenbull_zqzg'],
            'bundle_parts': [],
            'source_dirs': ['goldenbull_zqzg/upload_data', 'goldenbull_zqzg/upload_data_ex'],
            'info_file': '用户信息表.xlsx',
            'id_column': 'ID',
            'company_name_column': '公司名称',
            'skiprows': [0],
        },
    },

    2026: {
        # 先沿用最新一届业务口径，仅把原始数据集读取 schema 留成占位，后续按实情补齐。
        'dataset_ingestion': {
            'required_files': ['TODO_报名表文件名.xlsx'],
            'required_dirs': ['TODO_上传数据目录', 'TODO_补充资料目录'],
            'bundle_parts': [],
            'source_dirs': ['TODO_上传数据目录', 'TODO_补充资料目录'],
            'info_file': 'TODO_报名表文件名.xlsx',
            'id_column': 'TODO_机构编号列名',
            'company_name_column': 'TODO_公司名称列名',
            'skiprows': [],
        },
    },
}


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
