import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.demo.generator import wipe_user_data
from app.deps import get_current_user
from app.models import User, WhoopConnection
from app.whoop import client as wc
from app.whoop.sync import save_connection, sync_user

router = APIRouter(prefix="/api/whoop", tags=["whoop"])

# OAuth state（单进程自托管场景足够；多实例部署可换成 Redis）
_STATES: dict[str, float] = {}


@router.get("/auth/login")
def login():
    try:
        url, state = wc.build_authorize_url()
    except wc.WhoopAuthError as e:
        raise HTTPException(400, str(e)) from e
    _STATES[state] = time.time()
    return RedirectResponse(url)


@router.get("/auth/callback")
def callback(code: str | None = None, state: str | None = None, error: str | None = None,
             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    front = get_settings().frontend_url
    if error or not code:
        return RedirectResponse(f"{front}/settings?whoop=error&reason={error or 'no_code'}")
    if not state or time.time() - _STATES.pop(state, 0) > 600:
        return RedirectResponse(f"{front}/settings?whoop=error&reason=invalid_state")
    try:
        token = wc.exchange_code(code)
    except wc.WhoopAuthError:
        return RedirectResponse(f"{front}/settings?whoop=error&reason=token")
    if user.is_demo:
        wipe_user_data(db, user.id)  # 连接真实账号前清空 Demo 数据
        user.is_demo = False
        db.commit()
    save_connection(db, user, token)
    try:
        sync_user(db, user, full=True)
    except Exception:  # noqa: BLE001 首次同步失败不影响授权结果，用户可在设置页重试
        return RedirectResponse(f"{front}/settings?whoop=connected&sync=failed")
    return RedirectResponse(f"{front}/?whoop=connected")


@router.post("/sync")
def sync(full: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return sync_user(db, user, full=full)
    except wc.WhoopAuthError as e:
        raise HTTPException(401, str(e)) from e


@router.delete("/connection")
def disconnect(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.execute(delete(WhoopConnection).where(WhoopConnection.user_id == user.id))
    db.commit()
    return {"ok": True}
