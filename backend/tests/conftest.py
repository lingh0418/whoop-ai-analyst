import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}"
os.environ["LLM_PROVIDER"] = "none"


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/demo/seed", json={"days": 200})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture(scope="session")
def frame(client):
    from app.analytics.timeseries import load_daily_frame
    from app.db import SessionLocal

    with SessionLocal() as db:
        return load_daily_frame(db, 1)
