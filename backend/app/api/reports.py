from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.agent import summarize_daily, summarize_weekly
from app.agent.llm import LLMError
from app.db import get_db
from app.deps import get_current_user
from app.models import DailyMetric, User
from app.reports import daily, weekly

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/dashboard")
def dashboard(day: date | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return daily.get_daily_report(db, user, day)


@router.get("/reports/daily/{day}")
def daily_report(day: date, refresh: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return daily.get_daily_report(db, user, day, refresh=refresh)


@router.post("/reports/daily/{day}/ai")
def daily_ai(day: date, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    report = daily.get_daily_report(db, user, day)
    if not report.get("available"):
        raise HTTPException(404, report.get("reason", "没有数据"))
    try:
        result = summarize_daily(report)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    if result is None:
        raise HTTPException(400, "未配置大模型（LLM_PROVIDER），无法生成 AI 解读")
    text, model = result
    daily.save_ai_summary(db, user, day, text, model)
    return {"ai_summary": text, "ai_model": model}


@router.get("/reports/weekly")
def weekly_list(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    first = db.scalar(select(func.min(DailyMetric.date)).where(DailyMetric.user_id == user.id))
    last = db.scalar(select(func.max(DailyMetric.date)).where(DailyMetric.user_id == user.id))
    if not first:
        return {"weeks": []}
    weeks = []
    ws = weekly.week_start_of(last)
    while ws >= weekly.week_start_of(first) and len(weeks) < 26:
        weeks.append({"week_start": ws.isoformat(), "week_end": (ws + timedelta(days=6)).isoformat(),
                      "in_progress": ws + timedelta(days=6) > last})
        ws -= timedelta(days=7)
    return {"weeks": weeks}


@router.get("/reports/weekly/{week_start}")
def weekly_report(week_start: date, refresh: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return weekly.get_weekly_report(db, user, weekly.week_start_of(week_start), refresh=refresh)


@router.post("/reports/weekly/{week_start}/ai")
def weekly_ai(week_start: date, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    ws = weekly.week_start_of(week_start)
    report = weekly.get_weekly_report(db, user, ws)
    if not report.get("available"):
        raise HTTPException(404, report.get("reason", "没有数据"))
    try:
        text = summarize_weekly(report)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    if text is None:
        raise HTTPException(400, "未配置大模型（LLM_PROVIDER），无法生成 AI 总结")
    weekly.save_ai_summary(db, user, ws, text)
    return {"ai_summary": text}
