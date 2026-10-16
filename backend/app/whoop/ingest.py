"""把 WHOOP API v2 返回的原始 JSON 清洗并写入原始数据表。

真实同步与 Demo 数据生成共用这一套映射逻辑。

日期归属规则（WHOOP 的“生理日” cycle 以入睡为界）：
- cycle：本地开始时间 + 8h 所在日期（晚上 23:00 入睡 → 归属第二天）
- recovery：与所属 cycle 同一天
- sleep：醒来（end）的本地日期
- workout：本地开始时间 - 4h 所在日期（凌晨 0~4 点的训练算前一天）
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import WhoopCycle, WhoopRecovery, WhoopSleep, WhoopWorkout


def parse_ts(value: str | None) -> datetime | None:
    """ISO8601 → naive UTC datetime。"""
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_offset(offset: str | None) -> timedelta:
    if not offset:
        return timedelta(hours=8)
    sign = -1 if offset.startswith("-") else 1
    hh, mm = offset.lstrip("+-").split(":")
    return sign * timedelta(hours=int(hh), minutes=int(mm))


def local(dt: datetime, offset: str | None) -> datetime:
    return dt + parse_offset(offset)


def cycle_date(start_utc: datetime, offset: str | None) -> date:
    return (local(start_utc, offset) + timedelta(hours=8)).date()


def _score(rec: dict) -> dict:
    return rec.get("score") or {}


def ingest_cycle(db: Session, user_id: int, rec: dict) -> WhoopCycle:
    start = parse_ts(rec["start"])
    sc = _score(rec)
    row = WhoopCycle(
        id=int(rec["id"]),
        user_id=user_id,
        date=cycle_date(start, rec.get("timezone_offset")),
        start=start,
        end=parse_ts(rec.get("end")),
        timezone_offset=rec.get("timezone_offset"),
        score_state=rec.get("score_state"),
        strain=sc.get("strain"),
        kilojoule=sc.get("kilojoule"),
        average_heart_rate=sc.get("average_heart_rate"),
        max_heart_rate=sc.get("max_heart_rate"),
        raw=rec,
    )
    return db.merge(row)


def ingest_recovery(db: Session, user_id: int, rec: dict) -> WhoopRecovery:
    cycle_id = int(rec["cycle_id"])
    cycle = db.get(WhoopCycle, cycle_id)
    if cycle is not None:
        d = cycle.date
    else:  # 理论上不会发生（先同步 cycle），兜底用创建时间
        d = (parse_ts(rec.get("created_at")) + timedelta(hours=8)).date()
    sc = _score(rec)
    row = WhoopRecovery(
        cycle_id=cycle_id,
        user_id=user_id,
        date=d,
        sleep_id=str(rec.get("sleep_id")) if rec.get("sleep_id") else None,
        score_state=rec.get("score_state"),
        user_calibrating=sc.get("user_calibrating"),
        recovery_score=sc.get("recovery_score"),
        resting_heart_rate=sc.get("resting_heart_rate"),
        hrv_rmssd_milli=sc.get("hrv_rmssd_milli"),
        spo2_percentage=sc.get("spo2_percentage"),
        skin_temp_celsius=sc.get("skin_temp_celsius"),
        raw=rec,
    )
    return db.merge(row)


def ingest_sleep(db: Session, user_id: int, rec: dict) -> WhoopSleep:
    start, end = parse_ts(rec["start"]), parse_ts(rec["end"])
    sc = _score(rec)
    stage = sc.get("stage_summary") or {}
    need = sc.get("sleep_needed") or {}
    row = WhoopSleep(
        id=str(rec["id"]),
        user_id=user_id,
        cycle_id=rec.get("cycle_id"),
        date=local(end, rec.get("timezone_offset")).date(),
        start=start,
        end=end,
        timezone_offset=rec.get("timezone_offset"),
        nap=bool(rec.get("nap")),
        score_state=rec.get("score_state"),
        total_in_bed_milli=stage.get("total_in_bed_time_milli"),
        total_awake_milli=stage.get("total_awake_time_milli"),
        total_no_data_milli=stage.get("total_no_data_time_milli"),
        total_light_sleep_milli=stage.get("total_light_sleep_time_milli"),
        total_slow_wave_sleep_milli=stage.get("total_slow_wave_sleep_time_milli"),
        total_rem_sleep_milli=stage.get("total_rem_sleep_time_milli"),
        sleep_cycle_count=stage.get("sleep_cycle_count"),
        disturbance_count=stage.get("disturbance_count"),
        need_baseline_milli=need.get("baseline_milli"),
        need_from_sleep_debt_milli=need.get("need_from_sleep_debt_milli"),
        need_from_recent_strain_milli=need.get("need_from_recent_strain_milli"),
        need_from_recent_nap_milli=need.get("need_from_recent_nap_milli"),
        respiratory_rate=sc.get("respiratory_rate"),
        sleep_performance_percentage=sc.get("sleep_performance_percentage"),
        sleep_consistency_percentage=sc.get("sleep_consistency_percentage"),
        sleep_efficiency_percentage=sc.get("sleep_efficiency_percentage"),
        raw=rec,
    )
    return db.merge(row)


def ingest_workout(db: Session, user_id: int, rec: dict) -> WhoopWorkout:
    start, end = parse_ts(rec["start"]), parse_ts(rec["end"])
    sc = _score(rec)
    zones = sc.get("zone_durations") or {}
    row = WhoopWorkout(
        id=str(rec["id"]),
        user_id=user_id,
        date=(local(start, rec.get("timezone_offset")) - timedelta(hours=4)).date(),
        start=start,
        end=end,
        timezone_offset=rec.get("timezone_offset"),
        sport_id=rec.get("sport_id"),
        sport_name=rec.get("sport_name"),
        score_state=rec.get("score_state"),
        strain=sc.get("strain"),
        average_heart_rate=sc.get("average_heart_rate"),
        max_heart_rate=sc.get("max_heart_rate"),
        kilojoule=sc.get("kilojoule"),
        percent_recorded=sc.get("percent_recorded"),
        distance_meter=sc.get("distance_meter"),
        altitude_gain_meter=sc.get("altitude_gain_meter"),
        zone_zero_milli=zones.get("zone_zero_milli"),
        zone_one_milli=zones.get("zone_one_milli"),
        zone_two_milli=zones.get("zone_two_milli"),
        zone_three_milli=zones.get("zone_three_milli"),
        zone_four_milli=zones.get("zone_four_milli"),
        zone_five_milli=zones.get("zone_five_milli"),
        raw=rec,
    )
    return db.merge(row)
