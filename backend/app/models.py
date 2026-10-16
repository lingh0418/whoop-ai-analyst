"""数据库模型。

分三层：
1. WHOOP 原始数据（whoop_cycles / whoop_recovery / whoop_sleep / whoop_workouts）—— 原样保存，可随时重算
2. 分析层（daily_metrics / metric_baselines / metric_anomalies / learned_patterns）—— 由 Python 分析层生成
3. 个性化上下文（memories / training_plans / nutrition_plans / conversations）—— 帮助解释 WHOOP 数据
"""

import datetime as dt
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


# --------------------------------------------------------------------------- 用户


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="我")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    # 目标 / 背景：如 {"goal": "cut", "training_age": "3y", "sex": "male"}
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    # 用户级配置覆盖，如异常检测阈值 {"anomaly_rules": {...}}
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class WhoopConnection(TimestampMixin, Base):
    __tablename__ = "whoop_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    whoop_user_id: Mapped[int | None] = mapped_column(BigInteger)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    scopes: Mapped[str | None] = mapped_column(String(255))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sync_status: Mapped[str | None] = mapped_column(String(255))


# --------------------------------------------------------------------------- WHOOP 原始数据


class WhoopCycle(Base):
    __tablename__ = "whoop_cycles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # WHOOP cycle id
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)  # 归属的本地日期
    start: Mapped[datetime] = mapped_column(DateTime)
    end: Mapped[datetime | None] = mapped_column(DateTime)
    timezone_offset: Mapped[str | None] = mapped_column(String(10))
    score_state: Mapped[str | None] = mapped_column(String(32))
    strain: Mapped[float | None] = mapped_column(Float)
    kilojoule: Mapped[float | None] = mapped_column(Float)
    average_heart_rate: Mapped[int | None] = mapped_column(Integer)
    max_heart_rate: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)


class WhoopRecovery(Base):
    __tablename__ = "whoop_recovery"

    cycle_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    sleep_id: Mapped[str | None] = mapped_column(String(64))
    score_state: Mapped[str | None] = mapped_column(String(32))
    user_calibrating: Mapped[bool | None] = mapped_column(Boolean)
    recovery_score: Mapped[float | None] = mapped_column(Float)
    resting_heart_rate: Mapped[float | None] = mapped_column(Float)
    hrv_rmssd_milli: Mapped[float | None] = mapped_column(Float)
    spo2_percentage: Mapped[float | None] = mapped_column(Float)
    skin_temp_celsius: Mapped[float | None] = mapped_column(Float)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)


class WhoopSleep(Base):
    __tablename__ = "whoop_sleep"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # v2 UUID
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    cycle_id: Mapped[int | None] = mapped_column(BigInteger)
    date: Mapped[dt.date] = mapped_column(Date, index=True)  # 醒来的本地日期
    start: Mapped[datetime] = mapped_column(DateTime)
    end: Mapped[datetime] = mapped_column(DateTime)
    timezone_offset: Mapped[str | None] = mapped_column(String(10))
    nap: Mapped[bool] = mapped_column(Boolean, default=False)
    score_state: Mapped[str | None] = mapped_column(String(32))
    total_in_bed_milli: Mapped[int | None] = mapped_column(BigInteger)
    total_awake_milli: Mapped[int | None] = mapped_column(BigInteger)
    total_no_data_milli: Mapped[int | None] = mapped_column(BigInteger)
    total_light_sleep_milli: Mapped[int | None] = mapped_column(BigInteger)
    total_slow_wave_sleep_milli: Mapped[int | None] = mapped_column(BigInteger)
    total_rem_sleep_milli: Mapped[int | None] = mapped_column(BigInteger)
    sleep_cycle_count: Mapped[int | None] = mapped_column(Integer)
    disturbance_count: Mapped[int | None] = mapped_column(Integer)
    need_baseline_milli: Mapped[int | None] = mapped_column(BigInteger)
    need_from_sleep_debt_milli: Mapped[int | None] = mapped_column(BigInteger)
    need_from_recent_strain_milli: Mapped[int | None] = mapped_column(BigInteger)
    need_from_recent_nap_milli: Mapped[int | None] = mapped_column(BigInteger)
    respiratory_rate: Mapped[float | None] = mapped_column(Float)
    sleep_performance_percentage: Mapped[float | None] = mapped_column(Float)
    sleep_consistency_percentage: Mapped[float | None] = mapped_column(Float)
    sleep_efficiency_percentage: Mapped[float | None] = mapped_column(Float)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)


class WhoopWorkout(Base):
    __tablename__ = "whoop_workouts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # v2 UUID
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    start: Mapped[datetime] = mapped_column(DateTime)
    end: Mapped[datetime] = mapped_column(DateTime)
    timezone_offset: Mapped[str | None] = mapped_column(String(10))
    sport_id: Mapped[int | None] = mapped_column(Integer)
    sport_name: Mapped[str | None] = mapped_column(String(64))
    score_state: Mapped[str | None] = mapped_column(String(32))
    strain: Mapped[float | None] = mapped_column(Float)
    average_heart_rate: Mapped[int | None] = mapped_column(Integer)
    max_heart_rate: Mapped[int | None] = mapped_column(Integer)
    kilojoule: Mapped[float | None] = mapped_column(Float)
    percent_recorded: Mapped[float | None] = mapped_column(Float)
    distance_meter: Mapped[float | None] = mapped_column(Float)
    altitude_gain_meter: Mapped[float | None] = mapped_column(Float)
    zone_zero_milli: Mapped[int | None] = mapped_column(BigInteger)
    zone_one_milli: Mapped[int | None] = mapped_column(BigInteger)
    zone_two_milli: Mapped[int | None] = mapped_column(BigInteger)
    zone_three_milli: Mapped[int | None] = mapped_column(BigInteger)
    zone_four_milli: Mapped[int | None] = mapped_column(BigInteger)
    zone_five_milli: Mapped[int | None] = mapped_column(BigInteger)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)


class BodyMeasurement(Base):
    __tablename__ = "body_measurements"
    __table_args__ = (UniqueConstraint("user_id", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    height_meter: Mapped[float | None] = mapped_column(Float)
    max_heart_rate: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # whoop | manual


# --------------------------------------------------------------------------- 分析层


class DailyMetric(Base):
    """每天一行的汇总表，Agent 与页面优先读这里，而不是反复扫描原始数据。"""

    __tablename__ = "daily_metrics"
    __table_args__ = (UniqueConstraint("user_id", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)

    recovery: Mapped[float | None] = mapped_column(Float)
    hrv: Mapped[float | None] = mapped_column(Float)
    rhr: Mapped[float | None] = mapped_column(Float)
    spo2: Mapped[float | None] = mapped_column(Float)
    skin_temp: Mapped[float | None] = mapped_column(Float)
    resp_rate: Mapped[float | None] = mapped_column(Float)

    sleep_duration: Mapped[float | None] = mapped_column(Float)  # 分钟（实际睡眠）
    time_in_bed: Mapped[float | None] = mapped_column(Float)
    sleep_performance: Mapped[float | None] = mapped_column(Float)
    sleep_need: Mapped[float | None] = mapped_column(Float)  # 分钟
    sleep_debt: Mapped[float | None] = mapped_column(Float)  # 分钟
    sleep_consistency: Mapped[float | None] = mapped_column(Float)
    sleep_efficiency: Mapped[float | None] = mapped_column(Float)
    deep_sleep: Mapped[float | None] = mapped_column(Float)
    rem_sleep: Mapped[float | None] = mapped_column(Float)
    light_sleep: Mapped[float | None] = mapped_column(Float)
    awake_time: Mapped[float | None] = mapped_column(Float)
    disturbances: Mapped[float | None] = mapped_column(Float)
    bedtime: Mapped[float | None] = mapped_column(Float)  # 入睡时刻，距前一日 12:00 的小时数
    nap_minutes: Mapped[float | None] = mapped_column(Float)

    strain: Mapped[float | None] = mapped_column(Float)
    kilojoule: Mapped[float | None] = mapped_column(Float)
    day_avg_hr: Mapped[float | None] = mapped_column(Float)
    workout_count: Mapped[int | None] = mapped_column(Integer)
    workout_minutes: Mapped[float | None] = mapped_column(Float)
    workout_strain: Mapped[float | None] = mapped_column(Float)  # 当日最高单次训练 Strain
    weight: Mapped[float | None] = mapped_column(Float)

    hrv_deviation_28d: Mapped[float | None] = mapped_column(Float)
    rhr_deviation_28d: Mapped[float | None] = mapped_column(Float)
    sleep_deviation_28d: Mapped[float | None] = mapped_column(Float)
    recovery_deviation_28d: Mapped[float | None] = mapped_column(Float)
    strain_deviation_28d: Mapped[float | None] = mapped_column(Float)
    readiness_score: Mapped[float | None] = mapped_column(Float)
    readiness_level: Mapped[str | None] = mapped_column(String(16))
    joint_state: Mapped[str | None] = mapped_column(String(48))


class MetricBaseline(Base):
    """个人基线：as_of_date 当天之前 window 天的统计量（不含当天）。"""

    __tablename__ = "metric_baselines"
    __table_args__ = (UniqueConstraint("user_id", "metric", "window", "as_of_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    metric: Mapped[str] = mapped_column(String(32))
    window: Mapped[int] = mapped_column(Integer)
    as_of_date: Mapped[dt.date] = mapped_column(Date, index=True)
    mean: Mapped[float | None] = mapped_column(Float)
    median: Mapped[float | None] = mapped_column(Float)
    std: Mapped[float | None] = mapped_column(Float)
    p10: Mapped[float | None] = mapped_column(Float)
    p90: Mapped[float | None] = mapped_column(Float)
    n: Mapped[int] = mapped_column(Integer, default=0)


class MetricAnomaly(Base):
    __tablename__ = "metric_anomalies"
    __table_args__ = (UniqueConstraint("user_id", "date", "rule"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    rule: Mapped[str] = mapped_column(String(48))
    metric: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(8))  # low | medium | high
    value: Mapped[float | None] = mapped_column(Float)
    baseline: Mapped[float | None] = mapped_column(Float)
    deviation_pct: Mapped[float | None] = mapped_column(Float)
    z_score: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class LearnedPattern(Base):
    __tablename__ = "learned_patterns"
    __table_args__ = (UniqueConstraint("user_id", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))  # sleep | strain | lifestyle | weekday ...
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    condition: Mapped[str] = mapped_column(String(200))
    outcome_metric: Mapped[str] = mapped_column(String(32))
    effect: Mapped[float] = mapped_column(Float)  # 条件组 - 对照组（单位见 effect_unit）
    effect_unit: Mapped[str] = mapped_column(String(16))
    condition_mean: Mapped[float | None] = mapped_column(Float)
    baseline_mean: Mapped[float | None] = mapped_column(Float)
    sample_size: Mapped[int] = mapped_column(Integer)
    comparison_size: Mapped[int] = mapped_column(Integer)
    p_value: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(8))  # low | medium | high
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    first_detected: Mapped[dt.date] = mapped_column(Date)
    last_updated: Mapped[dt.date] = mapped_column(Date)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class DailyReport(Base):
    __tablename__ = "daily_reports"
    __table_args__ = (UniqueConstraint("user_id", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[dt.date] = mapped_column(Date)
    payload: Mapped[dict] = mapped_column(JSON)
    narrative: Mapped[str] = mapped_column(Text)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_model: Mapped[str | None] = mapped_column(String(64))
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WeeklyReport(Base):
    __tablename__ = "weekly_reports"
    __table_args__ = (UniqueConstraint("user_id", "week_start"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    week_start: Mapped[dt.date] = mapped_column(Date)
    payload: Mapped[dict] = mapped_column(JSON)
    narrative: Mapped[str] = mapped_column(Text)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# --------------------------------------------------------------------------- 个性化上下文


class Memory(TimestampMixin, Base):
    """长期记忆：主要用于解释 WHOOP 数据（喝酒、熬夜、考试、减脂、Deload ...）。"""

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    # event: 某天发生的事（影响次日恢复） | state: 持续一段时间的状态（减脂期 / Deload 周）
    # preference: 偏好 | profile: 背景信息
    category: Mapped[str] = mapped_column(String(16), default="event")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    event_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    end_date: Mapped[dt.date | None] = mapped_column(Date)
    importance: Mapped[int] = mapped_column(Integer, default=2)  # 1-3
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | chat | demo
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TrainingPlan(TimestampMixin, Base):
    """训练计划：可以指定具体日期，或作为每周模板（weekday 0=周一）。"""

    __tablename__ = "training_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    weekday: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(100))
    focus: Mapped[str | None] = mapped_column(String(100))  # 如 胸+三头 / 腿 / 有氧
    intensity: Mapped[str] = mapped_column(String(16), default="moderate")  # low|moderate|high
    # [{"name": "Bench Press", "sets": 4, "reps": "6", "rpe": 8, "weight": "80kg"}]
    exercises: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)


class NutritionPlan(TimestampMixin, Base):
    __tablename__ = "nutrition_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    weekday: Mapped[int | None] = mapped_column(Integer)
    day_type: Mapped[str] = mapped_column(String(16), default="normal")  # high_carb|low_carb|normal
    goal: Mapped[str] = mapped_column(String(16), default="maintain")  # cut|maintain|bulk
    calories: Mapped[float | None] = mapped_column(Float)
    protein: Mapped[float | None] = mapped_column(Float)
    carbs: Mapped[float | None] = mapped_column(Float)
    fat: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation",
        order_by="ConversationMessage.id",
        cascade="all, delete-orphan",
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    conversation: Mapped[Conversation] = relationship(back_populates="messages")
