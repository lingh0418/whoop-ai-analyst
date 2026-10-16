from datetime import date, datetime

from app.whoop import ingest


def test_cycle_date_attribution():
    # 本地 23:30 入睡（UTC 15:30）→ 归属第二天
    assert ingest.cycle_date(datetime(2026, 10, 15, 15, 30), "+08:00") == date(2026, 10, 16)
    # 本地 01:30 入睡 → 归属当天
    assert ingest.cycle_date(datetime(2026, 10, 15, 17, 30), "+08:00") == date(2026, 10, 16)
    # 美东时区
    assert ingest.cycle_date(datetime(2026, 10, 16, 3, 0), "-04:00") == date(2026, 10, 16)


def test_parse_ts():
    assert ingest.parse_ts("2022-04-24T11:25:44.774Z") == datetime(2022, 4, 24, 11, 25, 44, 774000)
    assert ingest.parse_ts(None) is None
