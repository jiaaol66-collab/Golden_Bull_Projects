# -*- coding: utf-8 -*-
"""
trade_calendar.py —— 交易日历生成器（命令行版）

输出结构沿用下游约定 —— trade_days.xlsx 三个 sheet：
    trade_days                 全部交易日
    weekly_last_trading_days   每周最后一个交易日
    monthly_last_trading_days  每月最后一个交易日
下游读取：pd.read_excel(xls, sheet_name='trade_days')['trade_days'].tolist()
因此每个 sheet 的列名与 sheet 名同名。

【两种范围模式，二选一】
  A 评奖年模式    --yr YYYY            按评奖当年自动推算起止（沿用原规则）
  B 自由起止模式  --start --end        直接给日期，优先级高于 A

评奖年模式的推算规则（与原脚本一致）：
    yr != 999 : 起点 (yr-8)-01-01
                终点 yr-03-31；若 yr 尚未到来，则终点为 今年-12-31
    yr == 999 : 终点 = 今天，起点 = (今年-6)-01-01
    另：yr <= 2020 自动退化为 999 模式；yr > 今年+7 直接报错

【保存路径】沿用原脚本规则（相对脚本所在目录）
    评奖年模式        <脚本目录>/<yr>/trade_days.xlsx
    999 / 自由起止    <脚本目录>/other/trade_days_<YYMMDD>.xlsx
    需要换地方时用 --out 显式指定即可

【两种用法】
  1) 交互式：直接运行 python trade_calendar.py（不带任何参数）
     会依次询问 范围模式 / 起止 / 交易所 / 日期格式 / 输出路径，
     方括号内为默认值，直接回车即采用。结束时会等你按回车再关窗口。
  2) 命令行：带参数运行，适合批量或定时任务

【示例】
    python trade_calendar.py                        # 交互式提问
    python trade_calendar.py --yr 2026
    python trade_calendar.py --yr 999
    python trade_calendar.py --start 2018-01-01 --end 2026-03-31
    python trade_calendar.py --yr 2026 --date-fmt "%Y-%m-%d"
    python trade_calendar.py --yr 2026 --date-fmt datetime
    python trade_calendar.py --start 2020-01-01 --end 2025-12-31 --exchange XSHG
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent

# ======================= 默认参数区（改这里最省事） =======================
# 命令行传参时，同名参数会覆盖这里的默认值
YR = 999            # 评奖当年；999 = 提取至今日（往前推 6 个自然年）
START = ""          # 自由起止模式起点，如 "2018-01-01"；留空则走评奖年模式
END = ""            # 自由起止模式终点，如 "2026-03-31"；留空则走评奖年模式
EXCHANGE = "XSHG"   # 交易所日历代码：XSHG 上交所 / XHKG 港交所（该库无深交所日历）
DATE_FMT = "%Y%m%d" # 日期格式；写 datetime / date / raw 则输出真正的日期类型单元格
OUT = ""            # 自定义输出文件路径；留空则按上面的默认路径规则走
# ========================================================================

# 评奖年模式的边界规则
FALLBACK_YEAR = 2020   # yr <= 该值时退化为 999 模式
MAX_AHEAD = 7          # yr 最多允许超出当前年份几年

# 日历可用下界（XSHG 实测 first_session）；起点早于它会被截断。换交易所需自行核对
CAL_FIRST = "2006-09-15"

# date_fmt 取这些值时不做字符串化，直接写 datetime 类型
RAW_DATE_TOKENS = {"datetime", "date", "raw", "native"}


# ---------------------------------------------------------------- 范围解析
def _clamp_end(e: datetime, today: datetime) -> datetime:
    """end 不允许超过「今年 12-31」（日历对未来的数据到此为止），超出则截断并提示。"""
    hard_end = datetime(today.year, 12, 31)
    if e > hard_end:
        print(f"[提示] 终点 {e:%Y-%m-%d} 超出日历可用范围，已截断为 {hard_end:%Y-%m-%d}")
        return hard_end
    return e


def _clamp_start(s: datetime) -> datetime:
    """start 不允许早于日历起始日 CAL_FIRST，早于则截断并提示。"""
    floor = datetime.strptime(CAL_FIRST, "%Y-%m-%d")
    if s < floor:
        print(f"[提示] 起点 {s:%Y-%m-%d} 早于日历可用范围，已截断为 {floor:%Y-%m-%d}")
        return floor
    return s


def _parse_date(text: str, field: str) -> datetime:
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d")
    except ValueError:
        sys.exit(f"[错误] {field} 日期格式不对：{text!r}，应为 YYYY-MM-DD")


def resolve_range(yr: int, start: str, end: str):
    """返回 (start_dt, end_dt, 模式说明, yr_effective)

    yr_effective 为 None 表示非评奖年模式（999 或自由起止），
    输出路径据此走 other/ 目录。
    """
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if yr is None:            # 自由起止模式下 yr 无意义，兜个底
        yr = 999

    # ---- 自由起止模式 ----
    if start or end:
        if not (start and end):
            sys.exit("[错误] 自由起止模式下 START/END（--start/--end）必须成对给出")
        s = _parse_date(start, "--start")
        e = _parse_date(end, "--end")
        if s > e:
            sys.exit(f"[错误] 起点 {s:%Y-%m-%d} 晚于终点 {e:%Y-%m-%d}")
        s = _clamp_start(s)
        e = _clamp_end(e, today)
        return s, e, "自由起止", None

    # ---- 评奖年模式 ----
    if yr != 999:
        max_year = today.year + MAX_AHEAD
        if yr > max_year:
            sys.exit(f"[错误] yr 不能大于 {max_year}（当前为 {yr}）")
        if yr <= FALLBACK_YEAR:
            print(f"[提示] yr={yr} 过小，已退化为 999 模式（提取至今日）")
            yr = 999

    if yr == 999:
        e = today
        s = datetime(e.year - 6, 1, 1)
        return s, e, "评奖年(999)", None

    s = _clamp_start(datetime(yr - 8, 1, 1))
    e = datetime(yr, 3, 31) if today.year >= yr else datetime(today.year, 12, 31)
    e = _clamp_end(e, today)
    return s, e, f"评奖年(yr={yr})", yr


# ---------------------------------------------------------------- 日历提取
def build_trade_days(start: datetime, end: datetime, exchange: str = "XSHG",
                     date_fmt: str | None = None) -> dict:
    """提取三类交易日序列。

    :return: {'trade_days', 'weekly_last_trading_days', 'monthly_last_trading_days'}
             date_fmt 为空/RAW 时值为 Timestamp，否则为格式化后的字符串
    """
    try:
        import exchange_calendars as xcals
    except ImportError:
        sys.exit("[错误] 缺少 exchange_calendars，请先执行：\n"
                 "       pip install exchange_calendars pandas openpyxl")

    try:
        cal = xcals.get_calendar(exchange)
    except Exception as exc:  # 交易所代码写错、日历数据包缺失等
        sys.exit(f"[错误] 无法加载日历 {exchange}：{exc}")

    sessions = cal.sessions_in_range(start, end)
    trade_days = pd.DatetimeIndex(sessions).tz_localize(None).normalize()
    if len(trade_days) == 0:
        sys.exit(f"[错误] {start:%Y-%m-%d} ~ {end:%Y-%m-%d} 内没有交易日，"
                 f"请检查范围或交易所代码 {exchange}")

    s = pd.Series(trade_days, index=trade_days)
    iso = trade_days.isocalendar()  # 跨自然年的周边界用 ISO 周处理

    weekly_last = s.groupby([iso.year, iso.week]).max().sort_values()
    monthly_last = s.groupby([trade_days.year, trade_days.month]).max().sort_values()

    days = {
        "trade_days": list(trade_days),
        "weekly_last_trading_days": weekly_last.tolist(),
        "monthly_last_trading_days": monthly_last.tolist(),
    }

    if date_fmt and date_fmt.strip().lower() not in RAW_DATE_TOKENS:
        try:
            days = {k: [d.strftime(date_fmt) for d in v] for k, v in days.items()}
        except (ValueError, TypeError) as exc:
            sys.exit(f"[错误] 日期格式 {date_fmt!r} 无法应用：{exc}")
    return days


# ---------------------------------------------------------------- 输出路径
def default_out_path(yr_effective: int | None) -> Path:
    """只算默认路径，不建目录（供交互式提示预览用）。

    yr_effective 为 None 表示 999 模式或自由起止模式，走 other/ 目录。
    """
    if yr_effective is not None:
        return SCRIPT_DIR / str(yr_effective) / "trade_days.xlsx"
    return SCRIPT_DIR / "other" / f"trade_days_{datetime.now().strftime('%Y%m%d')[2:]}.xlsx"


def resolve_out_path(yr_effective: int | None) -> Path:
    """沿用原脚本的保存规则：评奖年存 <yr>/，其余存 other/。"""
    out_path = default_out_path(yr_effective)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return out_path


def save_trade_days(data: dict, out_path: Path) -> None:
    with pd.ExcelWriter(out_path) as writer:
        for name, days in data.items():
            pd.DataFrame({name: days}).to_excel(writer, sheet_name=name, index=False)


# ---------------------------------------------------------------- 交互式提问
def _ask(prompt: str, default: str = "") -> str:
    """带默认值的提问，直接回车则用默认值。"""
    suffix = f" [{default}]" if default else ""
    try:
        raw = input(f"{prompt}{suffix}: ").strip()
    except EOFError:  # 非交互环境（管道/重定向）直接吃默认值
        print()
        return default
    return raw or default


def interactive_config() -> dict:
    """逐步询问，返回一份配置字典。"""
    print("=" * 46)
    print(" 交易日历生成器")
    print("=" * 46)
    print("范围模式： [1] 评奖年   [2] 自由起止")

    cfg: dict = {"out": OUT}
    if _ask("请选择", "1") == "2":
        today = datetime.now().strftime("%Y-%m-%d")
        cfg["yr"] = None
        cfg["start"] = _ask("起点 YYYY-MM-DD", START or f"{datetime.now().year - 6}-01-01")
        cfg["end"] = _ask("终点 YYYY-MM-DD", END or today)
    else:
        raw = _ask("评奖当年（999 表示提取至今日）", str(YR))
        try:
            cfg["yr"] = int(raw) if raw else YR
        except ValueError:
            print(f"[提示] “{raw}”不是有效年份，已按 999 处理")
            cfg["yr"] = 999
        cfg["start"] = cfg["end"] = ""

    cfg["exchange"] = _ask("交易所代码（XSHG 上交所 / XHKG 港交所）", EXCHANGE)
    cfg["date_fmt"] = _ask("日期格式（%Y%m%d / %Y-%m-%d / datetime）", DATE_FMT)
    if _ask("是否指定输出路径？[y/N]", "N").lower() in ("y", "yes"):
        yr_for_path = cfg["yr"] if cfg["yr"] not in (None, 999) else None
        cfg["out"] = _ask("输出文件路径", OUT or str(default_out_path(yr_for_path)))
    else:
        cfg["out"] = OUT
    print("-" * 46)
    return cfg


# ---------------------------------------------------------------- 入口
def main(argv: list[str] | None = None) -> None:
    # ---- 交互式：不带任何命令行参数运行时 ----
    if argv is None and len(sys.argv) == 1:
        cfg = interactive_config()
        yr, start, end = cfg["yr"], cfg["start"], cfg["end"]
        exchange, date_fmt, out = cfg["exchange"], cfg["date_fmt"], cfg["out"]
    # ---- 命令行 ----
    else:
        parser = argparse.ArgumentParser(
            description="交易日历生成器：可自定义范围与日期格式，输出 trade_days.xlsx",
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument("--yr", type=int, default=None,
                            help="评奖当年；999 表示提取至今日（默认读脚本内 YR 常量）")
        parser.add_argument("--start", default=None,
                            help="自由起止模式起点 YYYY-MM-DD（与 --end 成对）")
        parser.add_argument("--end", default=None,
                            help="自由起止模式终点 YYYY-MM-DD（与 --start 成对）")
        parser.add_argument("--exchange", default=None,
                            help="交易所日历代码，默认 XSHG（上交所）")
        parser.add_argument("--date-fmt", dest="date_fmt", default=None,
                            help='日期格式，如 %%Y%%m%%d / %%Y-%%m-%%d；填 datetime 则写日期类型单元格')
        parser.add_argument("--out", default=None,
                            help="自定义输出文件路径，留空则用默认路径规则")
        args = parser.parse_args(argv)

        if args.yr is not None and (args.start is not None or args.end is not None):
            sys.exit("[错误] --yr 与 --start/--end 二选一，不能同时指定")

        # 命令行 > 默认参数区
        yr = args.yr if args.yr is not None else YR
        start = args.start if args.start is not None else START
        end = args.end if args.end is not None else END
        exchange = args.exchange or EXCHANGE
        date_fmt = args.date_fmt if args.date_fmt is not None else DATE_FMT
        out = args.out or OUT

        # 显式给了 --yr 时，忽略默认参数区里可能残留的 START/END
        if args.yr is not None and (start or end):
            print("[提示] 已指定 --yr，忽略默认参数区中的 START/END")
            start = end = ""

    if out:
        out_path = Path(out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_path = None  # 等 yr_effective 确定后再算

    start_dt, end_dt, mode, yr_eff = resolve_range(yr, start, end)
    if out_path is None:
        out_path = resolve_out_path(yr_eff)

    print(f"[模式] {mode}")
    print(f"[范围] {start_dt:%Y-%m-%d} ~ {end_dt:%Y-%m-%d}    交易所 {exchange}")
    print(f"[格式] {'日期类型(datetime)' if date_fmt.strip().lower() in RAW_DATE_TOKENS else date_fmt}")

    data = build_trade_days(start_dt, end_dt, exchange, date_fmt)
    save_trade_days(data, out_path)

    print(f"已生成 {out_path}：交易日 {len(data['trade_days'])} 天，"
          f"周 {len(data['weekly_last_trading_days'])} 个，"
          f"月 {len(data['monthly_last_trading_days'])} 个")


if __name__ == "__main__":
    _interactive = len(sys.argv) == 1     # 不带参数 = 交互式
    try:
        main()
    except SystemExit as exc:
        if _interactive and exc.code:
            time.sleep(3)                 # 双击运行时留出看错误的时间
        raise
    if _interactive:
        try:
            input("\n按回车键退出...")
        except EOFError:
            pass
