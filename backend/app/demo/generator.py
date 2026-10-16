"""Demo 数据生成器：生成与 WHOOP API v2 结构完全一致的模拟数据，走与真实同步相同的入库流程。

模拟的生理规律（让个人规律学习能“学到东西”）：
- 睡眠不足 → 次日 HRV 下降、RHR 上升
- 前一天高 Strain → HRV 下降；连续两天高 Strain → 额外下降
- 饮酒 → 次日 HRV 大幅下降、RHR 升高、深睡减少
- 生病 → HRV↓ RHR↑ 呼吸频率↑ 皮温↑，持续数天
- 长期：HRV 随训练适应缓慢上升
- 最近 4 天：考试复习 + 连续高负荷 → 短期恢复不足（便于演示 Dashboard）
"""

from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timedelta

import numpy as np
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import (
    BodyMeasurement,
    Conversation,
    DailyMetric,
    DailyReport,
    LearnedPattern,
    Memory,
    MetricAnomaly,
    MetricBaseline,
    NutritionPlan,
    TrainingPlan,
    User,
    WeeklyReport,
    WhoopCycle,
    WhoopRecovery,
    WhoopSleep,
    WhoopWorkout,
)
from app.whoop import ingest

TZ = "+08:00"
TZ_DELTA = timedelta(hours=8)

# 训练模板：(名称, sport_name, sport_id, 平均 Strain, 时长分钟)
SESSIONS = {
    "push": ("胸 + 三头", "weightlifting", 45, 13.0, 70),
    "pull": ("背 + 二头", "weightlifting", 45, 12.5, 65),
    "legs": ("腿", "weightlifting", 45, 14.5, 75),
    "z2": ("Zone 2 慢跑", "running", 0, 10.5, 45),
    "long": ("长距离骑行", "cycling", 1, 15.0, 110),
    "hiit": ("HIIT 间歇", "functional-fitness", 48, 14.0, 35),
}


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def wipe_user_data(db: Session, user_id: int) -> None:
    for model in (
        WhoopCycle, WhoopRecovery, WhoopSleep, WhoopWorkout, BodyMeasurement, DailyMetric, MetricBaseline,
        MetricAnomaly, LearnedPattern, DailyReport, WeeklyReport, Memory, TrainingPlan, NutritionPlan,
    ):
        db.execute(delete(model).where(model.user_id == user_id))
    for conv in db.query(Conversation).filter(Conversation.user_id == user_id):
        db.delete(conv)
    db.commit()


def generate(db: Session, user: User, days: int = 200, today: date | None = None, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    today = today or (datetime.utcnow() + TZ_DELTA).date()
    start = today - timedelta(days=days - 1)
    wipe_user_data(db, user.id)

    user.is_demo = True
    user.name = "Demo 用户"
    user.profile = {"goal": "cut", "sex": "male", "age": 28, "training_age": "4 年", "note": "力量训练 + 有氧，正在减脂"}
    db.commit()

    # ---- 一周训练模板（让“今天”正好是 胸 + 三头）
    week = ["push", "z2", "pull", None, "legs", "long", None]
    offset = today.weekday()
    template = {(offset + i) % 7: s for i, s in enumerate(week)}

    # ---- 生活事件
    alcohol_days, late_days, illness_days, travel_days = set(), set(), set(), set()
    d = start + timedelta(days=5)
    while d < today - timedelta(days=6):
        if d.weekday() in (4, 5) and rng.random() < 0.28:
            alcohol_days.add(d)
        if rng.random() < 0.05:
            late_days.add(d)
        d += timedelta(days=1)
    ill_start = today - timedelta(days=72)
    illness_days = {ill_start + timedelta(days=i) for i in range(5)}
    travel_start = today - timedelta(days=118)
    travel_days = {travel_start + timedelta(days=i) for i in range(4)}
    # 最近：考试周（其中两晚复习到很晚）
    exam_days = {today - timedelta(days=i) for i in (1, 2, 3, 4)}
    exam_late = {today - timedelta(days=i) for i in (1, 3)}

    memories = []
    for a in sorted(alcohol_days):
        memories.append((a, "聚餐喝了几杯酒", ["alcohol"], "event"))
    for l in sorted(late_days - exam_days):
        memories.append((l, "昨晚熬夜，很晚才睡", ["late_night"], "event"))
    memories.append((ill_start, "感冒了，嗓子疼，有点发烧", ["illness"], "event"))
    memories.append((travel_start, "出差去北京，坐早班飞机", ["travel"], "event"))
    memories.append((today - timedelta(days=45), "开始减脂，每天热量缺口约 400 kcal", ["cutting"], "state"))
    memories.append((today - timedelta(days=4), "这周期末考试，压力比较大", ["stress"], "event"))
    memories.append((today - timedelta(days=1), "昨晚复习到凌晨一点多才睡", ["late_night", "stress"], "event"))

    # ---- 逐日模拟
    cycle_id = 900_000_000
    prev_eff = 0.0
    strains: dict[date, float] = {}
    sleep_debt_min = 0.0
    bedtimes: list[float] = []
    hrv_hist: list[float] = []
    rhr_hist: list[float] = []
    records = {"cycles": [], "recoveries": [], "sleeps": [], "workouts": []}
    recent_window = {today - timedelta(days=i) for i in range(4)}

    for i in range(days):
        day = start + timedelta(days=i)
        prev = day - timedelta(days=1)
        quiet = day in recent_window  # 最近几天噪声更小，保证演示场景稳定
        noise = (lambda s: float(rng.normal(0, s) * (0.3 if quiet else 1.0)))

        progress = i / days
        hrv_base = 62 + 8 * progress
        rhr_base = 56 - 3 * progress

        # -- 前一晚睡眠（结束于 day 的早晨）
        bed = 11.25 + noise(0.45)  # 距前一日 12:00 的小时数 → 23:15
        if prev.weekday() in (4, 5):
            bed += 0.6
        if prev in late_days:
            bed += 1.9
        if prev in alcohol_days:
            bed += 0.8
        if prev in exam_days:
            bed += 0.7
        if prev in exam_late:
            bed += 1.2
        sleep_h = 7.35 + noise(0.42)
        if prev in late_days:
            sleep_h -= 1.4
        if prev in alcohol_days:
            sleep_h -= 0.5
        if prev in exam_days:
            sleep_h -= 0.7
        if prev in exam_late:
            sleep_h -= 0.45
        if prev in travel_days:
            sleep_h -= 0.8
        if prev.weekday() == 5:
            sleep_h += 0.4  # 周日早晨补觉
        sleep_h = float(np.clip(sleep_h, 4.2, 9.5))

        # -- 负荷
        s1 = strains.get(prev, 10.0)
        s2 = strains.get(prev - timedelta(days=1), 10.0)

        eff = -0.065 * max(0.0, 7.0 - sleep_h)
        eff -= 0.013 * max(0.0, s1 - 12.0)
        if s1 > 15 and s2 > 15:
            eff -= 0.04
        if prev in alcohol_days:
            eff -= 0.19
        if day in illness_days:
            eff -= 0.24
        if prev in travel_days:
            eff -= 0.06
        if prev in exam_days:
            eff -= 0.06  # 心理压力
        eff += 0.35 * prev_eff
        prev_eff = eff

        hrv = hrv_base * math.exp(eff + noise(0.075))
        rhr = rhr_base * (1 - 0.45 * eff + noise(0.022))
        if prev in alcohol_days:
            rhr += 3.5
        if day in illness_days:
            rhr += 3.0
        resp = 15.2 + noise(0.25) + (1.3 if day in illness_days else 0)
        skin = 33.6 + noise(0.18) + (0.75 if day in illness_days else 0) + (0.25 if prev in alcohol_days else 0)
        spo2 = float(np.clip(96.6 + noise(0.5), 92, 100))

        # -- 睡眠分期
        total_min = sleep_h * 60
        deep_frac = 0.20 + noise(0.02) - (0.04 if prev in alcohol_days else 0)
        rem_frac = 0.22 + noise(0.025) - (0.03 if prev in alcohol_days else 0)
        deep, rem = total_min * deep_frac, total_min * rem_frac
        light = total_min - deep - rem
        awake = max(12.0, 38 + noise(12) + (15 if prev in alcohol_days else 0))
        in_bed = total_min + awake
        disturbances = int(max(1, rng.poisson(9) + (5 if prev in alcohol_days else 0)))
        need_base = 7.6 * 60
        need_strain = max(0.0, (s1 - 10) * 4)
        need_debt = float(np.clip(sleep_debt_min * 0.35, 0, 120))
        need_total = need_base + need_strain + need_debt
        sleep_debt_min = max(0.0, sleep_debt_min * 0.6 + (need_base - total_min))
        perf = float(np.clip(total_min / need_total * 100, 30, 100))
        bedtimes.append(bed)
        avg_bed = float(np.mean(bedtimes[-7:]))
        consistency = float(np.clip(88 - abs(bed - avg_bed) * 28 + noise(4), 35, 99))
        efficiency = total_min / in_bed * 100

        # 与 WHOOP 类似：Recovery 相对“你自己最近的基线”计算
        ref_h = float(np.mean(hrv_hist[-30:])) if len(hrv_hist) >= 5 else hrv_base
        ref_r = float(np.mean(rhr_hist[-30:])) if len(rhr_hist) >= 5 else rhr_base
        hrv_hist.append(hrv)
        rhr_hist.append(rhr)
        z_h = math.log(hrv / ref_h) / 0.15
        z_r = -(rhr - ref_r) / 3.0
        recovery = 100 * _sigmoid(0.45 + 0.9 * z_h + 0.35 * z_r + 0.035 * (perf - 85))
        recovery = float(np.clip(recovery + noise(3), 2, 99))

        # -- 当天训练
        session = template.get(day.weekday())
        if day in illness_days or (day in travel_days and session != "z2"):
            session = None
        if session and rng.random() < 0.08 and not quiet:
            session = None  # 偶尔跳过
        if not session and day.weekday() in template and rng.random() < 0.05:
            session = "hiit"
        workout_strain = None
        if session:
            name, sport, sport_id, mean_strain, dur = SESSIONS[session]
            workout_strain = float(np.clip(mean_strain + noise(1.4), 6, 20))
        day_strain = (workout_strain + 1.6 + noise(0.6)) if workout_strain else 6.8 + noise(1.2)
        if day in travel_days:
            day_strain += 1.5
        day_strain = float(np.clip(day_strain, 3, 20.5))
        # 最近 3 天：连续高负荷（17.2 / 16.8 / 15.9）
        forced = {today - timedelta(days=3): 17.2, today - timedelta(days=2): 16.8, today - timedelta(days=1): 15.9}
        if day in forced:
            day_strain = forced[day]
            workout_strain = day_strain - 1.6
            if not session:
                session = "hiit"
        if day == today:
            day_strain = 4.6  # 今天才刚开始
            session = None
            workout_strain = None
        strains[day] = day_strain

        # -- 生成 WHOOP 结构
        cycle_id += 1
        bed_local = datetime.combine(prev, datetime.min.time()) + timedelta(hours=12 + bed)
        sleep_start_utc = bed_local - TZ_DELTA
        sleep_end_utc = sleep_start_utc + timedelta(minutes=in_bed)
        next_bed_local = datetime.combine(day, datetime.min.time()) + timedelta(hours=23.3)
        cycle_end_utc = None if day == today else next_bed_local - TZ_DELTA
        sleep_id = str(uuid.UUID(int=int(rng.integers(0, 2**63)) << 64 | i))
        ms = lambda minutes: int(minutes * 60_000)  # noqa: E731

        records["cycles"].append(
            {
                "id": cycle_id, "user_id": 10001,
                "created_at": _iso(sleep_start_utc), "updated_at": _iso(sleep_end_utc),
                "start": _iso(sleep_start_utc), "end": _iso(cycle_end_utc) if cycle_end_utc else None,
                "timezone_offset": TZ, "score_state": "SCORED",
                "score": {
                    "strain": round(day_strain, 4),
                    "kilojoule": round(8200 + day_strain * 260 + noise(400), 1),
                    "average_heart_rate": int(62 + day_strain * 1.1 + noise(2)),
                    "max_heart_rate": int(120 + day_strain * 3.5 + noise(5)),
                },
            }
        )
        records["sleeps"].append(
            {
                "id": sleep_id, "cycle_id": cycle_id, "v1_id": None, "user_id": 10001,
                "created_at": _iso(sleep_end_utc), "updated_at": _iso(sleep_end_utc),
                "start": _iso(sleep_start_utc), "end": _iso(sleep_end_utc),
                "timezone_offset": TZ, "nap": False, "score_state": "SCORED",
                "score": {
                    "stage_summary": {
                        "total_in_bed_time_milli": ms(in_bed),
                        "total_awake_time_milli": ms(awake),
                        "total_no_data_time_milli": 0,
                        "total_light_sleep_time_milli": ms(light),
                        "total_slow_wave_sleep_time_milli": ms(deep),
                        "total_rem_sleep_time_milli": ms(rem),
                        "sleep_cycle_count": int(max(2, round(total_min / 90))),
                        "disturbance_count": disturbances,
                    },
                    "sleep_needed": {
                        "baseline_milli": ms(need_base),
                        "need_from_sleep_debt_milli": ms(need_debt),
                        "need_from_recent_strain_milli": ms(need_strain),
                        "need_from_recent_nap_milli": 0,
                    },
                    "respiratory_rate": round(resp, 2),
                    "sleep_performance_percentage": round(perf),
                    "sleep_consistency_percentage": round(consistency),
                    "sleep_efficiency_percentage": round(efficiency, 1),
                },
            }
        )
        records["recoveries"].append(
            {
                "cycle_id": cycle_id, "sleep_id": sleep_id, "user_id": 10001,
                "created_at": _iso(sleep_end_utc), "updated_at": _iso(sleep_end_utc),
                "score_state": "SCORED",
                "score": {
                    "user_calibrating": i < 4,
                    "recovery_score": round(recovery),
                    "resting_heart_rate": round(rhr),
                    "hrv_rmssd_milli": round(hrv, 3),
                    "spo2_percentage": round(spo2, 1),
                    "skin_temp_celsius": round(skin, 2),
                },
            }
        )
        if session and workout_strain:
            name, sport, sport_id, _, dur = SESSIONS[session]
            dur = max(20.0, dur + noise(8))
            w_start_local = datetime.combine(day, datetime.min.time()) + timedelta(hours=18.5 + noise(0.6))
            w_start = w_start_local - TZ_DELTA
            avg_hr = int(118 + workout_strain * 2.6 + noise(4))
            zones_frac = (
                [0.05, 0.2, 0.35, 0.25, 0.12, 0.03] if sport == "weightlifting"
                else [0.02, 0.1, 0.55, 0.25, 0.07, 0.01] if sport in ("running", "cycling")
                else [0.03, 0.1, 0.2, 0.3, 0.27, 0.1]
            )
            records["workouts"].append(
                {
                    "id": str(uuid.UUID(int=int(rng.integers(0, 2**63)) << 64 | (i + 7))), "v1_id": None,
                    "user_id": 10001,
                    "created_at": _iso(w_start), "updated_at": _iso(w_start),
                    "start": _iso(w_start), "end": _iso(w_start + timedelta(minutes=dur)),
                    "timezone_offset": TZ, "sport_name": sport, "sport_id": sport_id, "score_state": "SCORED",
                    "score": {
                        "strain": round(workout_strain, 4),
                        "average_heart_rate": avg_hr,
                        "max_heart_rate": int(avg_hr + 30 + noise(5)),
                        "kilojoule": round(dur * 38 + noise(80), 1),
                        "percent_recorded": 100,
                        "distance_meter": round(dur * 160, 1) if sport in ("running", "cycling") else None,
                        "altitude_gain_meter": round(abs(noise(40)), 1) if sport == "cycling" else None,
                        "altitude_change_meter": None,
                        "zone_durations": {
                            f"zone_{n}_milli": ms(dur * f)
                            for n, f in zip(["zero", "one", "two", "three", "four", "five"], zones_frac)
                        },
                    },
                }
            )

    for rec in records["cycles"]:
        ingest.ingest_cycle(db, user.id, rec)
    db.flush()
    for rec in records["recoveries"]:
        ingest.ingest_recovery(db, user.id, rec)
    for rec in records["sleeps"]:
        ingest.ingest_sleep(db, user.id, rec)
    for rec in records["workouts"]:
        ingest.ingest_workout(db, user.id, rec)

    # ---- 体重（减脂期缓慢下降，每 3 天称一次）
    for k in range(0, days, 3):
        d = start + timedelta(days=k)
        cut_days = max(0, (d - (today - timedelta(days=45))).days)
        w = 78.6 - 0.05 * cut_days + float(rng.normal(0, 0.25))
        db.add(BodyMeasurement(user_id=user.id, date=d, weight_kg=round(w, 1), source="manual"))

    # ---- 记忆
    for d, content, tags, cat in memories:
        db.add(Memory(user_id=user.id, content=content, tags=tags, category=cat, event_date=d, source="demo",
                      importance=2))

    # ---- 训练计划（周模板）
    plans = {
        "push": ("胸 + 三头", "high", [
            {"name": "Bench Press 卧推", "sets": 4, "reps": "6", "rpe": 8, "weight": "80kg"},
            {"name": "Incline DB Press 上斜哑铃卧推", "sets": 3, "reps": "8-10", "rpe": 8},
            {"name": "Cable Fly 绳索夹胸", "sets": 3, "reps": "12", "rpe": 8},
            {"name": "Overhead Triceps Extension 过头臂屈伸", "sets": 3, "reps": "10-12", "rpe": 8},
            {"name": "Dips 双杠臂屈伸", "sets": 3, "reps": "AMRAP", "rpe": 9},
        ]),
        "pull": ("背 + 二头", "high", [
            {"name": "Deadlift 硬拉", "sets": 3, "reps": "5", "rpe": 8, "weight": "140kg"},
            {"name": "Pull-up 引体向上", "sets": 4, "reps": "8", "rpe": 8},
            {"name": "Barbell Row 杠铃划船", "sets": 3, "reps": "8", "rpe": 8},
            {"name": "DB Curl 哑铃弯举", "sets": 3, "reps": "12", "rpe": 8},
        ]),
        "legs": ("腿", "high", [
            {"name": "Back Squat 深蹲", "sets": 4, "reps": "5", "rpe": 8, "weight": "120kg"},
            {"name": "Romanian Deadlift 罗马尼亚硬拉", "sets": 3, "reps": "8", "rpe": 8},
            {"name": "Bulgarian Split Squat 保加利亚分腿蹲", "sets": 3, "reps": "10", "rpe": 8},
            {"name": "Leg Curl 腿弯举", "sets": 3, "reps": "12", "rpe": 8},
        ]),
        "z2": ("Zone 2 有氧", "low", [{"name": "Zone 2 慢跑", "sets": 1, "reps": "45min", "rpe": 5}]),
        "long": ("长距离骑行", "moderate", [{"name": "骑行", "sets": 1, "reps": "100-120min", "rpe": 6}]),
    }
    for wd, key in template.items():
        if key is None:
            db.add(TrainingPlan(user_id=user.id, weekday=wd, title="休息日", focus="休息 / 散步", intensity="low",
                                exercises=[{"name": "散步 / 拉伸", "sets": 1, "reps": "30min", "rpe": 3}]))
            continue
        title, intensity, ex = plans[key]
        db.add(TrainingPlan(user_id=user.id, weekday=wd, title=title, focus=title, intensity=intensity, exercises=ex))

    # ---- 饮食计划（减脂：训练日高碳，休息日低碳）
    for wd, key in template.items():
        high = key in ("push", "pull", "legs", "long")
        db.add(
            NutritionPlan(
                user_id=user.id, weekday=wd, goal="cut",
                day_type="high_carb" if high else "low_carb",
                calories=2300 if high else 1900, protein=170, carbs=260 if high else 140, fat=60 if high else 70,
            )
        )
    db.commit()
    return {
        "days": days,
        "start": start.isoformat(),
        "end": today.isoformat(),
        "workouts": len(records["workouts"]),
        "memories": len(memories),
    }
