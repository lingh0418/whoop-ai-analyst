"""WHOOP Developer API v2 客户端（OAuth2 + 分页拉取）。

文档：https://developer.whoop.com/api/
"""

from __future__ import annotations

import logging
import secrets
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

SCOPES = [
    "offline",  # 获取 refresh_token
    "read:recovery",
    "read:cycles",
    "read:workout",
    "read:sleep",
    "read:profile",
    "read:body_measurement",
]


class WhoopAuthError(RuntimeError):
    pass


def build_authorize_url(state: str | None = None) -> tuple[str, str]:
    s = get_settings()
    if not s.whoop_client_id:
        raise WhoopAuthError("未配置 WHOOP_CLIENT_ID，请先在 .env 中填写 WHOOP 开发者应用信息")
    state = state or secrets.token_urlsafe(16)  # WHOOP 要求 state ≥ 8 字符
    params = {
        "response_type": "code",
        "client_id": s.whoop_client_id,
        "redirect_uri": s.whoop_redirect_uri,
        "scope": " ".join(SCOPES),
        "state": state,
    }
    return f"{s.whoop_auth_url}?{urlencode(params)}", state


def _token_request(data: dict) -> dict:
    s = get_settings()
    payload = {"client_id": s.whoop_client_id, "client_secret": s.whoop_client_secret, **data}
    resp = httpx.post(s.whoop_token_url, data=payload, timeout=30)
    if resp.status_code >= 400:
        raise WhoopAuthError(f"WHOOP token 请求失败: {resp.status_code} {resp.text[:300]}")
    return resp.json()


def exchange_code(code: str) -> dict:
    return _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": get_settings().whoop_redirect_uri,
        }
    )


def refresh_token(refresh: str) -> dict:
    return _token_request({"grant_type": "refresh_token", "refresh_token": refresh, "scope": "offline"})


def token_expiry(token: dict) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        seconds=int(token.get("expires_in", 3600)) - 60
    )


class WhoopClient:
    def __init__(self, access_token: str):
        s = get_settings()
        self._http = httpx.Client(
            base_url=s.whoop_api_base,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> WhoopClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _get(self, path: str, params: dict | None = None) -> dict:
        for attempt in range(5):
            resp = self._http.get(path, params=params)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("retry-after", 2**attempt))
                log.warning("WHOOP %s %s, %ss 后重试", path, resp.status_code, wait)
                time.sleep(min(wait, 30))
                continue
            if resp.status_code == 401:
                raise WhoopAuthError("WHOOP access token 无效或已过期")
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return {}

    def _paginate(self, path: str, start: datetime | None, end: datetime | None) -> Iterator[dict]:
        params: dict = {"limit": 25}
        if start:
            params["start"] = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if end:
            params["end"] = end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        while True:
            data = self._get(path, params)
            yield from data.get("records", [])
            token = data.get("next_token")
            if not token:
                break
            params["nextToken"] = token

    def profile(self) -> dict:
        return self._get("/v2/user/profile/basic")

    def body_measurement(self) -> dict:
        return self._get("/v2/user/measurement/body")

    def cycles(self, start=None, end=None) -> Iterator[dict]:
        return self._paginate("/v2/cycle", start, end)

    def recoveries(self, start=None, end=None) -> Iterator[dict]:
        return self._paginate("/v2/recovery", start, end)

    def sleeps(self, start=None, end=None) -> Iterator[dict]:
        return self._paginate("/v2/activity/sleep", start, end)

    def workouts(self, start=None, end=None) -> Iterator[dict]:
        return self._paginate("/v2/activity/workout", start, end)
