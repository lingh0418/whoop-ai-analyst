"""指标注册表：名称、单位、方向（越高越好 / 越低越好 / 中性）。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    unit: str
    # +1: 越高越好；-1: 越低越好；0: 中性（负荷类，没有好坏）
    direction: int
    decimals: int = 1
    is_core: bool = False


METRICS: dict[str, MetricDef] = {
    m.key: m
    for m in [
        MetricDef("recovery", "Recovery", "%", +1, 0, True),
        MetricDef("hrv", "HRV", "ms", +1, 1, True),
        MetricDef("rhr", "静息心率", "bpm", -1, 0, True),
        MetricDef("sleep_duration", "睡眠时长", "min", +1, 0, True),
        MetricDef("sleep_performance", "睡眠表现", "%", +1, 0, True),
        MetricDef("strain", "Strain", "", 0, 1, True),
        MetricDef("sleep_need", "睡眠需求", "min", 0, 0),
        MetricDef("sleep_debt", "睡眠负债", "min", -1, 0),
        MetricDef("sleep_consistency", "睡眠一致性", "%", +1, 0),
        MetricDef("sleep_efficiency", "睡眠效率", "%", +1, 0),
        MetricDef("deep_sleep", "深睡", "min", +1, 0),
        MetricDef("rem_sleep", "REM 睡眠", "min", +1, 0),
        MetricDef("awake_time", "夜间清醒", "min", -1, 0),
        MetricDef("disturbances", "夜醒次数", "次", -1, 0),
        MetricDef("bedtime", "入睡时间", "h", 0, 2),
        MetricDef("resp_rate", "呼吸频率", "次/分", 0, 1),
        MetricDef("skin_temp", "皮肤温度", "°C", 0, 2),
        MetricDef("spo2", "血氧", "%", +1, 1),
        MetricDef("workout_count", "训练次数", "次", 0, 0),
        MetricDef("workout_minutes", "训练时长", "min", 0, 0),
        MetricDef("weight", "体重", "kg", 0, 1),
    ]
}

CORE_METRICS = [k for k, m in METRICS.items() if m.is_core]
# 计算并持久化个人基线的指标
BASELINE_METRICS = [
    "recovery",
    "hrv",
    "rhr",
    "sleep_duration",
    "sleep_performance",
    "strain",
    "sleep_debt",
    "sleep_consistency",
    "sleep_efficiency",
    "deep_sleep",
    "rem_sleep",
    "resp_rate",
    "skin_temp",
    "weight",
]
WINDOWS = (7, 28, 90)

METRIC_ALIASES = {
    "恢复": "recovery",
    "recovery": "recovery",
    "hrv": "hrv",
    "心率变异性": "hrv",
    "rhr": "rhr",
    "静息心率": "rhr",
    "resting_heart_rate": "rhr",
    "sleep": "sleep_duration",
    "睡眠": "sleep_duration",
    "sleep_duration": "sleep_duration",
    "strain": "strain",
    "负荷": "strain",
    "weight": "weight",
    "体重": "weight",
}


def resolve_metric(name: str) -> str:
    key = name.strip().lower()
    if key in METRICS:
        return key
    if key in METRIC_ALIASES:
        return METRIC_ALIASES[key]
    raise KeyError(f"未知指标: {name}，可选: {', '.join(METRICS)}")


def fmt_value(metric: str, value: float | None) -> str:
    """把指标值格式化为中文可读字符串。"""
    if value is None:
        return "无数据"
    m = METRICS.get(metric)
    if metric in {"sleep_duration", "sleep_need", "sleep_debt", "deep_sleep", "rem_sleep",
                  "awake_time", "workout_minutes"}:
        return fmt_minutes(value)
    if metric == "bedtime":
        return fmt_bedtime(value)
    if m is None:
        return f"{value:.1f}"
    num = f"{value:.{m.decimals}f}"
    return f"{num}{m.unit}" if m.unit in {"%", "°C"} else f"{num} {m.unit}".strip()


def fmt_minutes(minutes: float | None) -> str:
    if minutes is None:
        return "无数据"
    sign = "-" if minutes < 0 else ""
    total = int(round(abs(minutes)))
    h, m = divmod(total, 60)
    if h == 0:
        return f"{sign}{m}分钟"
    return f"{sign}{h}小时{m:02d}分"


def fmt_bedtime(hours_since_noon: float | None) -> str:
    if hours_since_noon is None:
        return "无数据"
    h = (12 + hours_since_noon) % 24
    hh, mm = int(h), int(round((h - int(h)) * 60)) % 60
    return f"{hh:02d}:{mm:02d}"


def fmt_pct(x: float | None, signed: bool = True) -> str:
    if x is None:
        return "—"
    v = x * 100
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


PERCENT_POINT_METRICS = {"recovery", "sleep_performance", "sleep_consistency", "sleep_efficiency", "spo2"}


def fmt_delta(metric: str, value: float | None, base: float | None) -> str:
    """value 相对 base 的差异文字：百分比类指标用“个百分点”，时长类用分钟，其余用百分比。"""
    if value is None or base is None:
        return "—"
    diff = value - base
    word = "高" if diff >= 0 else "低"
    if metric in PERCENT_POINT_METRICS:
        return f"{word} {abs(diff):.0f} 个百分点"
    if metric in {"sleep_duration", "deep_sleep", "rem_sleep", "sleep_debt", "sleep_need", "awake_time"}:
        return f"{'多' if diff >= 0 else '少'} {fmt_minutes(abs(diff))}"
    if base == 0:
        return "—"
    return f"{word}约 {abs(diff) / abs(base) * 100:.0f}%"
