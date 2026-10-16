"""FastAPI 依赖。v0.1 为自托管单用户模式：默认使用 id=1 的用户。"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User

DEFAULT_USER_ID = 1


def ensure_default_user(db: Session) -> User:
    user = db.get(User, DEFAULT_USER_ID)
    if user is None:
        user = User(id=DEFAULT_USER_ID, name="我", timezone=get_settings().timezone)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def get_current_user(db: Session = Depends(get_db)) -> User:
    return ensure_default_user(db)
