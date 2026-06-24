import exchange_calendars as ecals
import pandas as pd

cn_calendar = ecals.get_calendar("XSHG")  # 上海证券交易所 (XSHG)
# 获取 2019-01-01 到 2023-12-31 的交易日
trade_days = cn_calendar.sessions_in_range(pd.Timestamp(f'2017-01-01'), pd.Timestamp(f'2025-12-31'))
trade_days = pd.DataFrame({'交易日期':trade_days})
trade_days.info()
trade_days['交易日期'] = trade_days['交易日期'].dt.strftime('%Y-%m-%d')
trade_days.to_excel('trade_days.xlsx', sheet_name='trade_days', index=False)