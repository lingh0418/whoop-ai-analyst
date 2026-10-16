"""定时任务：每天自动同步 WHOOP、生成日报；每周一生成周报（ENABLE_SCHEDULER=true 时启用）。"""

import logging
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.agent.agent import summarize_daily, summarize_weekly
from app.config import get_settings
from app.db import SessionLocal
from app.models import User, WhoopConnection
from app.reports import daily, weekly
from app.whoop.sync import sync_user

log = logging.getLogger(__name__)


def daily_job() -> None:
    with SessionLocal() as db:
        for conn in db.scalars(select(WhoopConnection)):
            user = db.get(User, conn.user_id)
            try:
                sync_user(db, user)
                report = daily.get_daily_report(db, user, refresh=True)
                if report.get("available"):
                    result = summarize_daily(report)
                    if result:
                        daily.save_ai_summary(db, user, date.fromisoformat(report["date"]), *result)
            except Exception:  # noqa: BLE001
                log.exception("用户 %s 每日任务失败", conn.user_id)


def weekly_job() -> None:
    with SessionLocal() as db:
        for conn in db.scalars(select(WhoopConnection)):
            user = db.get(User, conn.user_id)
            try:
                from app.analytics.pipeline import latest_date

                last = latest_date(db, user.id)
                if last is None:
                    continue
                ws = weekly.week_start_of(last) - timedelta(days=7)  # 上一个完整周
                report = weekly.get_weekly_report(db, user, ws, refresh=True)
                if report.get("available"):
                    text = summarize_weekly(report)
                    if text:
                        weekly.save_ai_summary(db, user, ws, text)
            except Exception:  # noqa: BLE001
                log.exception("用户 %s 周报任务失败", conn.user_id)


def start_scheduler() -> BackgroundScheduler:
    s = get_settings()
    sched = BackgroundScheduler(timezone=s.timezone)
    sched.add_job(daily_job, "cron", hour=s.daily_sync_hour, minute=0, id="daily")
    sched.add_job(daily_job, "cron", hour=s.daily_sync_hour + 3, minute=0, id="daily_retry")
    sched.add_job(weekly_job, "cron", day_of_week="mon", hour=s.daily_sync_hour + 1, minute=0, id="weekly")
    sched.start()
    log.info("定时任务已启动")
    return sched
