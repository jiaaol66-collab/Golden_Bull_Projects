# -*- coding: utf-8 -*-
"""
私募金牛奖 —— 按年存储的集中配置
================================================================
设计：
  DEFAULT      = 最新一届（2026 / 细则 20260601）的全部口径。
  PROFILES[yr] = 某评奖年份相对 DEFAULT 的"差异覆盖"。往年定稿、可定死。
  C.for_year(yr) -> 解析出该年份的完整口径对象 CFG，业务脚本只用 CFG。

用法（脚本里）：
  from userlib import config as C
  CFG = C.for_year(yr)            # yr 仍由 get_year(rel) 读取
  CFG.score_weight_mana           # 取常量
  CFG.year_weights(3)             # 取推导值（按 yr 算出绝对年份）
  CFG.six_month_cutoff()          # 取推导日期

年份语义：yr=评奖年份；考察期最近年=yr-1（细则称 T）。
  例：yr=2026 今年 / 2025 去年 / 2024 前年。
"""

# ============================================================
# DEFAULT —— 最新一届（2026，细则 20260601）的完整口径
# ============================================================
DEFAULT = {
    # ---- 年期 与 年度权重 ----
    'all_terms':   [1, 3, 5, 7],
    'terms_stock': [1, 3, 5, 7],     # 股票/经理
    'terms_other': [1, 3],           # 其余策略
    'year_weights_by_offset': {      # 表五，offset 0=T=yr-1，距今越近越高
        3: {0: 0.40, 1: 0.30, 2: 0.30},
        5: {0: 0.30, 1: 0.20, 2: 0.20, 3: 0.15, 4: 0.15},
        7: {0: 0.26, 1: 0.20, 2: 0.16, 3: 0.14, 4: 0.10, 5: 0.08, 6: 0.06},
    },

    # ---- 指标权重（表四 / 表六 / 表七）----
    'score_weight_general': {'收益率评分': 0.50, '最大回撤评分': 0.30, '下行风险评分': 0.20},
    'score_weight_mana':    {'收益率评分': 0.45, '最大回撤评分': 0.20, '下行风险评分': 0.15, '收益回撤比评分': 0.20},
    'score_weight_index':   {'信息比率评分': 0.40, '超额收益评分': 0.30, '超额最大回撤评分': 0.30},

    # ---- 产品入选 / 资格（细则二）----
    'setup_cutoff_md': (7, 1),           # 成立满6个月：yr-1 年 7/1（含）之后成立的不纳入
    'min_annual_scale_yi': 0.1,          # 某年度平均规模 <1000万(0.1亿) 该年不计业绩
    'missing_rate_fill_max': 0.15,       # 缺失率 ≤15% 填充；>15% 剔除当年
    'missing_rate_validation_cut': 0.50,
    'liquidation_cutoff_md': (12, 31),   # 规模样本不含 yr-1 年底前清盘的产品（细则一）

    # ---- 参评门槛（细则一，应用在上游机构筛选）----
    'tenure_threshold_years': {'五年期': 5, '三年期': 3, '年度': 1},   # 表一/二
    'scale_threshold_company_yi': {                                    # 表三
        '股票策略': 5, '指数增强': 5, '债券策略': 10,
        '相对价值': 1, '宏观对冲': 1, '管理期货': 1, '多策略': 1, 'FOF/MOM': 1,
    },
    'scale_threshold_manager_yi': 1,
    'top_rank_ratio': 0.40,
    'top_rank_exclude': ['指数增强'],

    # ---- 策略 与 指数 ----
    'use_monthly': True,            # 是否处理/输出月度净值（都需要单独计算月度净值）
    'strategy_map': {                # (文件缩写, 策略名称, sheet名)
        '相对价值': ('相对价值', '相对价值', '相对价值'),
        '宏观对冲': ('宏观对冲', '宏观对冲', '宏观对冲'),
        '多策略':  ('多策略',  '多策略',  '多策略'),
        '债券策略': ('债券策略', '债券策略', '债券'),
        'fof/mom': ('fofmom', '组合基金', '组合基金'),
    },
    'index_tracking': ['沪深300指数', '中证500指数', '中证1000指数'],
    'index_exclude_name': '其他指数或合成指数',
    'mana_annualize_n': {1: 1, 3: 3, 5: 5, 7: 7},
    'annual_factor': {'周度': 52, '月度': 12},

    # ---- 极值 与 计算细节（细则三·6、二·收益回撤）----
    'sigma_threshold': 10,
    'abnormal_method': 'median',     # 'median'细则 / 'mean3'均值±3σ / 'forbidden'仅检测
    'rf': 0.0,
    'cr_zero_mdd_use_group_max': True,
    'score_method': '1',             # '1'Zscore / '2'归一化 / '3'排名

    # ---- 净值对齐网格 ----
    'nav_lookback_years': 8,         # 网格起点 = yr - 8 年底（覆盖7年期+基期）
}


# ============================================================
# PROFILES —— 按年份覆盖（只写与 DEFAULT 不同的项；往年可定死）
# ============================================================
PROFILES = {
    2026: {},        # 今年：完全采用 DEFAULT（即 20260601 细则）

    2025: {          # 去年：按 2025 年细则核对差异项后填写（示例占位）
        # 'score_weight_mana': {'收益率评分': 0.50, '最大回撤评分': 0.25, '下行风险评分': 0.15, '收益回撤比评分': 0.10},
        # 'abnormal_method': 'mean3',
        # 'liquidation_cutoff_md': (12, 30),
    },

    2024: {          # 前年：同上，按当年细则填写
        # ...
    },
}


# ============================================================
# 解析为"某年口径"对象
# ============================================================
class _YearConfig:
    """绑定到某评奖年份 yr 的口径：常量直接当属性，推导值用方法。"""

    def __init__(self, yr, d):
        self.yr = yr
        self._d = d
        for k, v in d.items():
            setattr(self, k, v)

    def year_weights(self, term):
        """{绝对年份: 权重}，offset 0 = T = yr-1。"""
        return {self.yr - 1 - off: w
                for off, w in self.year_weights_by_offset[term].items()}

    def terms_for(self, is_stock):
        return self.terms_stock if is_stock else self.terms_other

    def _md(self, key, year):
        import datetime as _dt
        m, day = getattr(self, key)
        return _dt.datetime(year, m, day)

    def six_month_cutoff(self):
        return self._md('setup_cutoff_md', self.yr - 1)

    def liquidation_cutoff(self):
        return self._md('liquidation_cutoff_md', self.yr - 1)

    def inspection_end(self):
        import datetime as _dt
        return _dt.datetime(self.yr - 1, 12, 31)

    def q1_end(self):
        import datetime as _dt
        return _dt.datetime(self.yr, 3, 31)

    def nav_grid_window(self):
        import datetime as _dt
        return _dt.datetime(self.yr - self.nav_lookback_years, 12, 31), self.q1_end()


def for_year(yr):
    """解析某评奖年份的完整口径（DEFAULT 叠加 PROFILES[yr]）。"""
    merged = dict(DEFAULT)
    merged.update(PROFILES.get(yr, {}))
    return _YearConfig(yr, merged)
