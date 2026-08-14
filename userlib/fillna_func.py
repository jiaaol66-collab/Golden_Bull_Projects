import pandas as pd
from joblib import Parallel, delayed
from tqdm import tqdm
import numpy as np
from datetime import datetime, timedelta


def create_stage_progress(total, desc):
    return tqdm(total=max(0, int(total or 0)), desc=desc, unit='stage', leave=True, dynamic_ncols=True)


def advance_stage_progress(progress, item_label, stage_label):
    if progress is None:
        return
    item_text = str(item_label or '').strip()
    stage_text = str(stage_label or '').strip()
    desc_text = str(getattr(progress, 'desc', '') or '').strip().rstrip(':').strip()
    if item_text and desc_text == item_text:
        item_text = ''
    if item_text and stage_text:
        progress.set_postfix_str(f'{item_text} | {stage_text}')
    elif stage_text:
        progress.set_postfix_str(stage_text)
    elif item_text:
        progress.set_postfix_str(item_text)
    progress.update(1)


def get_period_net_value(df, last_trading_days, freq, all_products, invariant, code):
    df = df.copy()
    df['净值日期'] = pd.to_datetime(df['净值日期'], errors='coerce')
    target_dates = pd.to_datetime(pd.Series(list(last_trading_days)), errors='coerce').dropna()
    target_dates = target_dates.drop_duplicates().sort_values().reset_index(drop=True)
    if invariant == ['产品编号', '产品名称', '产品策略', '子策略', '跟踪指数']:
        n = m = 10
    else:
        n = 28
        m = 2

    freq_config = {
        'daily': {
            'desc': '产品日度净值',
            'unit_col': '单位净值',
            'accum_col': '累计净值',
            'date_range': lambda date: (date, date),  # 严格的单日区间
            'get_nearest_date': lambda dates, target: dates.unique()[0] if len(dates) == 1 else None
        },
        'weekly': {
            'desc': '产品周度净值',                    
            'unit_col': '周度单位净值',                
            'accum_col': '周度累计净值',                
            'date_range': lambda date: (
                date - timedelta(days=date.weekday()),
                date + timedelta(days=6 - date.weekday())
            ),
            'get_nearest_date': lambda dates, target: min(dates, key=lambda d: abs(d - target))
        },
        'monthly': {
            'desc': "产品月度净值",
            'unit_col': '月度单位净值',
            'accum_col': '月度累计净值',
            'date_range': lambda date: (
                date - timedelta(days=n),  # 前10天
                date + timedelta(days=m)  # 后10天
            ),
            # 月度取绝对最近日期
            'get_nearest_date': lambda dates, target: min(
                dates,
                key=lambda d: abs(d - target)
            )
        }
    }
    cfg = freq_config[freq]

    base_cols = invariant
    all_products = all_products.drop_duplicates(code)

    product_codes = all_products[code].drop_duplicates().to_numpy()
    target_np = target_dates.to_numpy()
    if len(product_codes) == 0 or len(target_np) == 0:
        full_grid = pd.DataFrame({code: product_codes, '净值日期': pd.to_datetime([])})
    else:
        full_grid = pd.DataFrame(
            {
                code: np.repeat(product_codes, len(target_np)),
                '净值日期': np.tile(target_np, len(product_codes)),
            }
        )

    result = full_grid.merge(all_products[base_cols], on=code, how='left')

    keep_cols = [code, '净值日期', '单位净值', '累计净值']
    if '净值编号' in df.columns:
        keep_cols.append('净值编号')
    keep_cols = [c for c in keep_cols if c in df.columns]
    df = df[keep_cols].sort_values(['净值日期'])
    if code in df.columns:
        df = df.drop_duplicates([code, '净值日期'], keep='last')
    else:
        df = df.drop_duplicates(['净值日期'], keep='last')

    picked = pd.DataFrame()

    if freq == 'daily':
        if len(df) and len(target_dates):
            daily = df.copy()
            daily['原始净值日期'] = daily['净值日期']
            daily = daily.rename(
                columns={
                    '单位净值': cfg['unit_col'],
                    '累计净值': cfg['accum_col'],
                }
            )
            pick_cols = [code, '净值日期', '原始净值日期', cfg['unit_col'], cfg['accum_col']]
            if '净值编号' in daily.columns:
                pick_cols.append('净值编号')
            picked = daily[pick_cols]

    elif freq == 'weekly':
        if len(df) and len(target_dates):
            nav = df.copy()
            nav['_wkstart'] = nav['净值日期'] - pd.to_timedelta(nav['净值日期'].dt.weekday, unit='D')
            cal = pd.DataFrame({'target_date': target_dates})
            cal['_wkstart'] = cal['target_date'] - pd.to_timedelta(cal['target_date'].dt.weekday, unit='D')
            cal = cal.drop_duplicates(['_wkstart'], keep='last')
            merged = nav.merge(cal, on='_wkstart', how='inner')
            if len(merged):
                merged['abs_diff'] = (merged['净值日期'] - merged['target_date']).abs()
                merged = merged.sort_values([code, 'target_date', 'abs_diff', '净值日期'], ascending=True)
                merged = merged.drop_duplicates([code, 'target_date'], keep='first')
                merged = merged.rename(
                    columns={
                        'target_date': '净值日期',
                        '净值日期': '原始净值日期',
                        '单位净值': cfg['unit_col'],
                        '累计净值': cfg['accum_col'],
                    }
                )
                pick_cols = [code, '净值日期', '原始净值日期', cfg['unit_col'], cfg['accum_col']]
                if '净值编号' in merged.columns:
                    pick_cols.append('净值编号')
                picked = merged[pick_cols]

    elif freq == 'monthly':
        if len(df) and len(target_dates):
            targets = target_dates.reset_index(drop=True)
            starts = targets - pd.Timedelta(days=int(n))
            ends = targets + pd.Timedelta(days=int(m))
            overlap = False
            if len(targets) > 1:
                overlap = bool((starts.iloc[1:].reset_index(drop=True) <= ends.iloc[:-1].reset_index(drop=True)).any())

            nav = df.copy()
            if not overlap:
                intervals = pd.IntervalIndex.from_arrays(starts, ends, closed='both')
                hit = intervals.get_indexer(nav['净值日期'])
                keep_mask = hit >= 0
                if keep_mask.any():
                    nav = nav.loc[keep_mask].copy()
                    nav['target_date'] = targets.to_numpy()[hit[keep_mask]]
                    nav['abs_diff'] = (nav['净值日期'] - nav['target_date']).abs()
                    nav = nav.sort_values([code, 'target_date', 'abs_diff', '净值日期'], ascending=True)
                    nav = nav.drop_duplicates([code, 'target_date'], keep='first')
                    nav = nav.rename(
                        columns={
                            'target_date': '净值日期',
                            '净值日期': '原始净值日期',
                            '单位净值': cfg['unit_col'],
                            '累计净值': cfg['accum_col'],
                        }
                    )
                    pick_cols = [code, '净值日期', '原始净值日期', cfg['unit_col'], cfg['accum_col']]
                    if '净值编号' in nav.columns:
                        pick_cols.append('净值编号')
                    picked = nav[pick_cols]
            else:
                nav_dates = nav['净值日期']
                parts = []
                for t, s, e in zip(targets.to_list(), starts.to_list(), ends.to_list()):
                    mask = (nav_dates >= s) & (nav_dates <= e)
                    if not mask.any():
                        continue
                    chunk = nav.loc[mask].copy()
                    chunk['target_date'] = t
                    chunk['abs_diff'] = (chunk['净值日期'] - chunk['target_date']).abs()
                    parts.append(chunk)
                if parts:
                    merged = pd.concat(parts, ignore_index=True)
                    merged = merged.sort_values([code, 'target_date', 'abs_diff', '净值日期'], ascending=True)
                    merged = merged.drop_duplicates([code, 'target_date'], keep='first')
                    merged = merged.rename(
                        columns={
                            'target_date': '净值日期',
                            '净值日期': '原始净值日期',
                            '单位净值': cfg['unit_col'],
                            '累计净值': cfg['accum_col'],
                        }
                    )
                    pick_cols = [code, '净值日期', '原始净值日期', cfg['unit_col'], cfg['accum_col']]
                    if '净值编号' in merged.columns:
                        pick_cols.append('净值编号')
                    picked = merged[pick_cols]

    if not picked.empty:
        result = result.merge(picked, on=[code, '净值日期'], how='left')
    else:
        result[cfg['unit_col']] = np.nan
        result[cfg['accum_col']] = np.nan
        result['原始净值日期'] = pd.NaT
        if '净值编号' in df.columns and '净值编号' not in result.columns:
            result['净值编号'] = np.nan

    return result


# 特定频率的封装函数
def get_daily_net_value(df, td, invariant=None, code='产品编号'):
    if invariant is None:
        invariant = ['产品编号', '产品名称', '产品策略', '子策略', '跟踪指数']
    all_product = df[invariant].drop_duplicates().copy()
    return get_period_net_value(df, td, 'daily', all_product, invariant, code)


def get_weekly_net_value(df, td, invariant=None, code='产品编号'):
    if invariant is None:
        invariant = ['产品编号', '产品名称', '产品策略', '子策略', '跟踪指数']
    all_product = df[invariant].drop_duplicates().copy()
    #df = df[df['净值日期'].isin(trade_days)]
    return get_period_net_value(df, td, 'weekly', all_product, invariant, code)


def get_monthly_net_value(df, td, invariant=None, code='产品编号'):
    if invariant is None:
        invariant = ['产品编号', '产品名称', '产品策略', '子策略', '跟踪指数']
    all_product = df[invariant].drop_duplicates().copy()
    return get_period_net_value(df, td, 'monthly', all_product, invariant, code)

def classify_detailed_frequency(series):
    """
    更精细的频率分类（六类）
    :param series: 净值日期序列（datetime格式）
    :return: 分类结果
    """
    # 1. 基本数据验证
    if series.empty:
        return "错误：无净值数据"

    # 处理唯一值 - 需要至少两个非重复日期
    unique_dates = series.drop_duplicates().sort_values()
    if len(unique_dates) < 2:
        return "错误：至少需要两个非重复日期"

    # 2. 计算时间间隔
    intervals = unique_dates.diff().dropna().dt.days.values

    # 3. 计算关键指标
    min_int = min(intervals)
    max_int = max(intervals)
    time_span = (unique_dates.iloc[-1] - unique_dates.iloc[0]).days
    avg_int = time_span / (len(unique_dates) - 1)
    std_int = np.std(intervals) if len(intervals) > 1 else 0

    # 4. 错误检测（放宽条件，只检测真正异常）
    if min_int <= 0:
        return "错误：日期重复或逆序"
    if avg_int > 365:
        return "错误：更新频率过低（年频）"

    # 5. 频率分类（更全面的区间覆盖）
    # 日频产品（包括工作日模式）
    if min_int == 1 and max_int <= 3:
        if std_int < 1.0:  # 放宽标准差限制
            return f"日频, 平均间隔&最大间隔&间隔标准差_{avg_int}_{max_int}_{std_int}"
        else:
            return f"周频以下, 平均间隔&最大间隔&间隔标准差_{avg_int}_{max_int}_{std_int}"

    # 周频产品（考虑节假日可能造成间隔变化）
    if min_int >= 4 and max_int <= 9:
        if 6 <= avg_int <= 8 and std_int < 2.0:  # 放宽标准差限制
            return f"周频, 平均间隔&最大间隔&间隔标准差_{avg_int}_{max_int}_{std_int}"
        else:
            return f"周频以下, 平均间隔&最大间隔&间隔标准差_{avg_int}_{max_int}_{std_int}"

    # 介于周频月频之间（双周、三周等）
    if min_int >= 10 and max_int <= 24:
        return f"月频以下, 平均间隔&最大间隔&间隔标准差_{avg_int}_{max_int}_{std_int}"

    # 月频产品（考虑大小月差异）
    if min_int >= 25 and max_int <= 55:
        if 28 <= avg_int <= 32 and std_int < 3.5:  # 放宽标准差限制
            return f"月频, 平均间隔&最大间隔&间隔标准差_{avg_int}_{max_int}_{std_int}"
        else:
            return f"月频以下, 平均间隔&最大间隔&间隔标准差_{avg_int}_{max_int}_{std_int}"

    # 介于月频季频之间
    if min_int > 55:
        return f"月频以上, 平均间隔&最大间隔&间隔标准差_{avg_int}_{max_int}_{std_int}"

    # 6. 无法分类但非错误的情况
    # 尝试使用平均间隔进行最后分类
    if avg_int <= 4:
        return f"周频以下, 平均间隔&最大间隔&间隔标准差_{avg_int}_{max_int}_{std_int}"
    elif avg_int <= 31:
        return f"月频以下, 平均间隔&最大间隔&间隔标准差_{avg_int}_{max_int}_{std_int}"
    elif avg_int > 31:
        return f"月频以上, 平均间隔&最大间隔&间隔标准差_{avg_int}_{max_int}_{std_int}"

    # 7. 真正无法分类的情况
    return "警告：非标准频率（需人工核查）"


def merge_freq_info(nv, prod_code):
    """
    分析数据集的序列给出暂定频率、平均间隔、最大间隔、间隔标准差供参考。
    返回：同样大小的df, merged信息。
    """
    nv['年份'] = nv['净值日期'].dt.year
    nv['月份'] = nv['净值日期'].dt.month
    freq = nv.groupby([prod_code, '年份'])['净值日期'].apply(classify_detailed_frequency).reset_index(name='频率分布')
    freq['平均间隔'] = freq['频率分布'].apply(lambda x: float(x.split('_')[1]) if '_' in x else x)
    freq['最大间隔'] = freq['频率分布'].apply(lambda x: float(x.split('_')[2]) if '_' in x else x)
    freq['间隔标准差'] = freq['频率分布'].apply(lambda x: float(x.split('_')[3]) if '_' in x else x)
    freq['暂定频率'] = freq['平均间隔'].apply(lambda x:
                                              "无净值数据" if not x else
                                              "错误" if not isinstance(x, float) else
                                              "月频" if x >= 9 else
                                              "周频" if x >= 2 else
                                              "日频")

    freq.loc[freq['暂定频率'] == '错误', '平均间隔'] = 365
    freq.loc[freq['暂定频率'] == '错误', '最大间隔'] = 365

    nv = nv.merge(freq[['暂定频率', '平均间隔', '最大间隔', prod_code, '年份']], on=[prod_code, '年份'], how='left')
    nv['数据量'] = nv.groupby([prod_code, '年份'])['累计净值'].transform('count')

    nv.info()
    print(nv[[prod_code, '暂定频率', '年份', '平均间隔','最大间隔','数据量']].drop_duplicates().head(50))

    # nv = nv[nv['平均间隔'] <= 31]
    nv = nv[nv['最大间隔'] <= 180]  # 超过半年间隔的直接去除。
    nv = nv[nv['数据量'] > 6]    # 保留数据量大于6的。

    return nv

if __name__ == '__main__':
    nv = pd.read_csv('test/test.csv', parse_dates=['净值日期'])
    nv_processed = merge_freq_info(nv)
    nv_processed.info()

def generate_weekly_calendar(trade_days):
    """生成全局周历（确保覆盖所有自然周）"""
    return (
        trade_days.groupby([
            trade_days["交易日期"].dt.isocalendar().year.rename("年"),
            trade_days["交易日期"].dt.isocalendar().week.rename("周")
        ])
        ["交易日期"].max()
        .reset_index(name="对齐日期")
        .astype({"年": "uint16", "周": "uint8"})
    )

"""if __name__ == '__main__':
    weekly = generate_weekly_calendar(trade_days)
    weekly.info()
    print(weekly.tail())"""


def process_product(product_name, product_data, weekly_calendar):
    """单产品处理逻辑（修复缺失周问题）"""
    # 生成产品的周数据（可能缺失某些周）
    product_weekly = (
        product_data
        .groupby(["年", "周"], as_index=False, group_keys=False)
        .last()
    )

    # 关键修复：左连接时必须重置索引
    aligned = pd.merge(
        weekly_calendar[["年", "周", "对齐日期"]],
        product_weekly,
        on=["年", "周"],
        how="left",  # 必须左连接
        validate="one_to_one"
    )

    # 强制使用全局周历日期（覆盖产品原日期）
    aligned["净值日期"] = aligned["净值日期"].fillna(aligned["对齐日期"])
    aligned["产品全称"] = product_name  # 确保产品名称存在

    # 静态字段前向填充（非净值字段）
    static_cols = ['公司名称', '投资策略', '成立日期', '清盘日期', '投资类型', '净值起始日期', '净值终止日期']
    for col in static_cols:
        if col in aligned:
            aligned[col] = aligned[col].ffill()

    # 动态字段（净值）保留NaN
    return aligned.drop(columns="对齐日期")


def parallel_align(nv, trade_days, n_jobs=4):
    """并行对齐主流程"""
    # 生成全局周历
    weekly_calendar = generate_weekly_calendar(trade_days)

    # 预处理：确保年周字段与周历完全一致
    nv = nv.assign(
        年=nv["净值日期"].dt.isocalendar().year.astype("uint16"),
        周=nv["净值日期"].dt.isocalendar().week.astype("uint8")
    )

    # 按产品分组并行处理
    grouped = nv.groupby("产品全称")
    results = Parallel(n_jobs=n_jobs)(
        delayed(process_product)(name, group.copy(), weekly_calendar)
        for name, group in tqdm(grouped, desc="处理产品", unit="只")
    )

    return pd.concat(results, ignore_index=True)


# 数据验证 -------------------------------------------------
def validate_output(final_df, trade_days):
    """正确验证年周组合一致性的方法"""
    # 获取交易日历的年周组合（忽略顺序）
    calendar_weeks = (
        trade_days["交易日期"].dt.isocalendar()[["year", "week"]]
        .drop_duplicates()
        .rename(columns={"year": "年", "week": "周"})
        .astype({"年": int, "周": int})  # 统一为int类型
    )

    # 获取处理结果的年周组合
    result_weeks = (
        final_df[["年", "周"]]
        .drop_duplicates()
        .astype({"年": int, "周": int})
    )

    # 转换为集合比较（忽略顺序）
    calendar_set = set(tuple(row) for row in calendar_weeks.values)
    result_set = set(tuple(row) for row in result_weeks.values)

    # 验证无差异
    assert calendar_set == result_set, \
        f"差异：缺少 {calendar_set - result_set}，多余 {result_set - calendar_set}"

def fill_returns(group):
    returns = pd.to_numeric(group['收益率'], errors='coerce')
    locked = group['锁定收益率不填充'].fillna(False) if '锁定收益率不填充' in group.columns else False
    # 仅用有效数值收益率计算下五分位数
    tail = returns.dropna().quantile(0.20)
    # 被显式锁定的首行不参与填充
    is_filled = returns.isna() & ~locked
    group['收益率'] = returns
    if pd.notna(tail):
        group.loc[is_filled, '收益率'] = tail
    group['是否填充_收益率'] = is_filled.astype('int8')  # 暂时用1表示填充，0表示原有值
    return group


def backward_fill_nv(group, tag=None):
    """
    优化后的后向填充累计净值函数，支持连续填充
    核心逻辑：利用未来的有效净值和收益率，递归计算历史缺失值
    """
    # 设置标签列
    labels = {
        None: '累计净值',
        0: '周度累计净值',
        1: '月度累计净值'
    }
    label = labels.get(tag, '累计净值')

    # 按日期升序排列（旧日期在前）
    group = group.sort_values('净值日期', ascending=True).reset_index(drop=True)

    # 创建填充标记
    filled_flags = np.zeros(len(group), dtype=int)
    original_nv = group['累计净值'].copy()

    # 获取数值数组
    nv = group['累计净值'].to_numpy().copy()
    returns = group['收益率'].to_numpy()

    # 反向遍历处理（从最新到最旧）
    for i in range(len(nv) - 1, -1, -1):
        # 跳过已有净值的位置
        if not pd.isna(nv[i]):
            continue

        # 寻找下一个有效净值位置
        next_idx = i + 1
        valid_next_idx = None

        while next_idx < len(nv):
            if not pd.isna(nv[next_idx]) and not pd.isna(returns[next_idx]):
                valid_next_idx = next_idx
                break
            next_idx += 1

        # 找到有效未来值，进行递归计算
        if valid_next_idx is not None:
            # 计算中间所有缺失位置的净值
            for j in range(valid_next_idx - 1, i - 1, -1):
                if j < 0:
                    break

                nv[j] = round(nv[j + 1] / (1 + returns[j + 1]), 4)
                filled_flags[j] = 1  # 标记为填充值

    # 更新填充的累计净值
    group['累计净值'] = nv
    group[label] = group[label].fillna(group['累计净值'])
    group['是否填充_累计净值'] = filled_flags.astype('int8')

    return group.sort_values('净值日期')


def calculate_missing_rate(nv, last_trading_days, tag=None):
    """
    计算缺失率
    """
    missing_rates = []
    if not tag:
        label = '累计净值'
    else:
        if tag == 0:
            label = '周度累计净值'
        elif tag == 1:
            label = '月度累计净值'

    for prod_code, group in nv.groupby('产品编号'):
        prod_start_date = group['净值日期'].min().date()
        prod_end_date = group['净值日期'].max().date()
        prod_name = group['产品名称'].iloc[0]

        years = range(prod_start_date.year, prod_end_date.year + 1)

        for year0 in years:
            year_start = datetime(year0, 1, 1).date()
            year_end = datetime(year0, 12, 31).date()

            # 按照给定规则计算区间的起始和结束日期
            interval_start_date = max(prod_start_date, year_start, group['净值日期'].min().date())
            interval_end_date = min(prod_end_date, year_end, group['净值日期'].max().date())

            # 获取该区间内的交易日和最后一个交易日
            last_trading_days_interval = [day for day in last_trading_days
                                                  if interval_start_date <= day.date() <= interval_end_date]
            complete_periods = len(last_trading_days_interval)

            actual_periods_df = group[(pd.to_datetime(interval_start_date) <= group['净值日期'])
                                      & (group['净值日期'] <= pd.to_datetime(interval_end_date))]

            if label in actual_periods_df.columns:
                actual_periods = actual_periods_df[actual_periods_df[label].notnull()]['净值日期'].nunique()
            else:
                actual_periods = 0

            missing_rate = 1 - actual_periods / complete_periods if complete_periods > 0 else 0
            missing_rates.append({'产品编号': prod_code, '产品名称':prod_name, '年份': year0,
                                  '缺失率': missing_rate, '该年实际披露':actual_periods,'有效交易日数量':complete_periods
                                  })

    return pd.DataFrame(missing_rates)
