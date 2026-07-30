"""
生成 trade_days.xlsx —— 与项目中读取的结构一致（三个 sheet）：
    trade_days                 全部交易日
    weekly_last_trading_days   每周最后一个交易日
    monthly_last_trading_days  每月最后一个交易日

提取方式：exchange_calendars（XSHG 上交所日历）
提取区间：{yr-7}-01-01 ~ {yr}-3-31   （yr = 评奖当年）

下游（净值分组/净值填充/年期判定/可视化）通过：
    pd.read_excel(xls, sheet_name='trade_days')['trade_days'].tolist()
读取，故每个 sheet 的列名与 sheet 名同名，且为 datetime 格式。
"""
from datetime import datetime

import pandas as pd
import exchange_calendars as xcals
import os
import time
current = os.path.dirname(__file__)
os.chdir(current)



def build_trade_days(yr: int, exchange: str = "XSHG", date_fmt: str | None = None) -> dict:
    """
    根据评奖当年 yr 生成三类交易日序列。

    :param yr:       评奖当年（YR）
    :param exchange: 交易所日历代码，默认 'XSHG'（上交所）
    :return:         {'trade_days', 'weekly_last_trading_days',
                      'monthly_last_trading_days'}，值均为 datetime 列表
    """
    if yr != 999:
        start_date = datetime(yr - 8, 1, 1)   # {YR-7}-1-1
        end_date = datetime(yr, 3, 31)  if datetime.now().year >= yr else datetime(datetime.now().year, 12,31) # {YR}-3-31
    else:
        end_date  = datetime.now().replace(hour=0, minute=0, second=0)  # 清除小时分钟秒毫秒
        start_date = datetime(end_date.year - 6, 1, 1)   # {YR-7}-1-1

    cal = xcals.get_calendar(exchange)
    sessions = cal.sessions_in_range(start_date, end_date)

    # 去时区、归一化到日期，得到全部交易日
    trade_days = pd.DatetimeIndex(sessions).tz_localize(None).normalize()

    s = pd.Series(trade_days, index=trade_days)
    iso = trade_days.isocalendar()  # 跨自然年的周边界用 ISO 周处理
    # 如果yr = 999, 所有交易日格式化为%Y%m%d
    if date_fmt is None:
        date_fmt = "%Y%m%d"

    # 每周 / 每月最后一个交易日
    weekly_last = s.groupby([iso.year, iso.week]).max().sort_values()
    monthly_last = s.groupby([trade_days.year, trade_days.month]).max().sort_values()

    days = {
        "trade_days": list(trade_days),
        "weekly_last_trading_days": weekly_last.tolist(),
        "monthly_last_trading_days": monthly_last.tolist(),
    }
    
    if date_fmt:
        days = {k: [d.strftime(date_fmt) for d in v] for k, v in days.items()}
    return days


def save_trade_days(yr: int, out_path: str, exchange: str = "XSHG", date_fmt: str | None = None) -> None:
    """生成并写出 trade_days.xlsx（三个 sheet，列名与 sheet 名一致）。"""
    data = build_trade_days(yr, exchange, date_fmt)
    with pd.ExcelWriter(out_path) as writer:
        for name, days in data.items():
            pd.DataFrame({name: days}).to_excel(writer, sheet_name=name, index=False)
    print(f"已生成 {out_path}：交易日 {len(data['trade_days'])} 天，"
          f"周 {len(data['weekly_last_trading_days'])} 个，"
          f"月 {len(data['monthly_last_trading_days'])} 个")


if __name__ == "__main__":
    raw = input("请输入评奖当年（999 表示提取至今日）：").strip()

    try:
        yr = int(raw) if raw else 999
    except ValueError:
        print("输入不是有效年份，将使用 999（提取至今日）。")
        yr = 999
        
    max_year = datetime.now().year + 7
    if yr != 999 and yr > max_year:
        print(f"输入的 yr 不能大于 {max_year}！")
        time.sleep(3)
        raise ValueError(f"输入的 yr 不能大于 {max_year}！")
    
    # 如果yr过小, 自动退化为提取当日往前推6年的交易日历
    if yr <= 2020: 
        yr = 999

    if yr == 999:
        print(f'将生成{datetime.now().year-6}0101到{datetime.now().strftime("%Y%m%d")}范围内的交易日历')
    else:
        if yr > datetime.now().year: end_date = str(datetime.now().year)+'-12-31'
        else: end_date = str(yr) + '03-31'
        print(f'注意! 将生成{yr-8}-01-01到{end_date}范围内的交易日历')
        
    other = yr if yr != 999 else "other"
    appe = '' if other != 'other' else '_'+ datetime.now().strftime('%Y%m%d')[2:]
    if str(yr) not in os.listdir(current) and yr != 999:
        os.makedirs(str(yr), exist_ok=True)
    # save_trade_days(yr, f"{impt}其他文件/trade_days.xlsx")
    save_trade_days(yr, f"{other}/trade_days{appe}.xlsx", date_fmt = '%Y-%m-%d')
