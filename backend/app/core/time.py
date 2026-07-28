"""应用统一的本地日期定义。

产品面向中国用户，所有"今天"必须基于同一时区计算，
禁止在各模块里混用 UTC 与本地时间。
"""
from datetime import datetime, timedelta, timezone

APP_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_local() -> datetime:
    """当前本地时间（Asia/Shanghai）。"""
    return datetime.now(APP_TIMEZONE)


def today_str() -> str:
    """本地日期字符串 YYYY-MM-DD，作为全应用统一的"今天"。"""
    return now_local().strftime("%Y-%m-%d")
