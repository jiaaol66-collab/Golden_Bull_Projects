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
DEFAULT = {'all_terms': [1, 3, 5, 7],
 'terms_stock': [1, 3, 5, 7],
 'terms_other': [1, 3],
 'year_weights_by_offset': {3: {0: 0.4, 1: 0.3, 2: 0.3},
                            5: {0: 0.3, 1: 0.2, 2: 0.2, 3: 0.15, 4: 0.15},
                            7: {0: 0.26, 1: 0.2, 2: 0.16, 3: 0.14, 4: 0.1, 5: 0.08, 6: 0.06}},
 'score_weight_general': {'收益率评分': 0.5, '最大回撤评分': 0.3, '下行风险评分': 0.2},
 'score_weight_mana': {'收益率评分': 0.45, '最大回撤评分': 0.2, '下行风险评分': 0.15, '收益回撤比评分': 0.2},
 'score_weight_index': {'信息比率评分': 0.4, '超额收益评分': 0.3, '超额最大回撤评分': 0.3},
 'setup_cutoff_md': (7, 1),
 'min_annual_scale_yi': 0.1,
 'missing_rate_fill_max': 0.15,
 'missing_rate_validation_cut': 0.5,
 'liquidation_cutoff_md': (12, 31),
 'tenure_threshold_years': {'五年期': 5, '三年期': 3, '年度': 1},
 'scale_threshold_company_yi': {'股票策略': 5,
                                '指数增强': 5,
                                '债券策略': 10,
                                '相对价值': 1,
                                '宏观对冲': 1,
                                '管理期货': 1,
                                '多策略': 1,
                                'FOF/MOM': 1},
 'scale_threshold_manager_yi': 1,
 'top_rank_ratio': 0.4,
 'top_rank_exclude': ['指数增强'],
 'use_monthly': True,
 'strategy_map': {'相对价值': ('相对价值', '相对价值', '相对价值'),
                  '宏观对冲': ('宏观对冲', '宏观对冲', '宏观对冲'),
                  '多策略': ('多策略', '多策略', '多策略'),
                  '债券策略': ('债券策略', '债券策略', '债券'),
                  'fof/mom': ('fofmom', '组合基金', '组合基金')},
 'index_tracking': ['沪深300指数', '中证500指数', '中证1000指数'],
 'index_exclude_name': '其他指数或合成指数',
 'mana_annualize_n': {1: 1, 3: 3, 5: 5, 7: 7},
 'annual_factor': {'周度': 52, '月度': 12},
 'manager_tenure_filter_in_step2': False,
 'post_visualization_mode': False,
 'sigma_threshold': 10,
 'abnormal_method': 'median',
 'rf': 0.0,
 'cr_zero_mdd_use_group_max': True,
 'score_method': '1',
 'nav_lookback_years': 8}


# ============================================================
# PROFILES —— 按年份覆盖（只写与 DEFAULT 不同的项；往年可定死）
# ============================================================
PROFILES = {2026: {'all_terms': [1, 3, 5], 'terms_stock': [1, 3, 5], 'post_visualization_mode': True},
 2025: {},
 2024: {}}


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
