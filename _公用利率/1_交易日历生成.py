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


def build_trade_days(yr: int, exchange: str = "XSHG", date_fmt: str | None = None) -> dict:
    """
    根据评奖当年 yr 生成三类交易日序列。

    :param yr:       评奖当年（YR）
    :param exchange: 交易所日历代码，默认 'XSHG'（上交所）
    :return:         {'trade_days', 'weekly_last_trading_days',
                      'monthly_last_trading_days'}，值均为 datetime 列表
    """
    start_date = datetime(yr - 7, 1, 1)   # {YR-7}-1-1
    end_date = datetime(yr, 3, 31)   # {YR}-3-31

    cal = xcals.get_calendar(exchange)
    sessions = cal.sessions_in_range(start_date, end_date)

    # 去时区、归一化到日期，得到全部交易日
    trade_days = pd.DatetimeIndex(sessions).tz_localize(None).normalize()

    s = pd.Series(trade_days, index=trade_days)
    iso = trade_days.isocalendar()  # 跨自然年的周边界用 ISO 周处理

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
    yr = 2026  # 评奖当年，按需替换（项目里可用 get_year(rel) 取得）
    # impt 为项目中“重要文件”路径，例如：
    # save_trade_days(yr, f"{impt}其他文件/trade_days.xlsx")
    save_trade_days(yr, f"{yr}/trade_days.xlsx")
