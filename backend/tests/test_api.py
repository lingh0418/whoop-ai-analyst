def test_status(client):
    r = client.get("/api/status").json()
    assert r["data"]["days"] >= 190
    assert r["llm"]["provider"] == "none"


def test_dashboard(client):
    d = client.get("/api/dashboard").json()
    assert d["available"]
    assert d["state"]["score"] is not None
    assert len(d["conclusions"]) == 3
    assert {t["metric"] for t in d["tiles"]} >= {"recovery", "hrv", "rhr", "sleep_duration", "strain"}
    # Demo 场景：最近 3 天连续高负荷 + 睡眠减少
    assert d["joint"]["state"] in {"short_term_under_recovery", "systemic_decline"}
    assert d["training"]["level"] == "reduce"
    assert d["training"]["adjusted"]["exercises"][0]["sets"] < d["training"]["original"]["exercises"][0]["sets"]


def test_trends(client):
    for metric in ("hrv", "rhr", "recovery", "sleep_duration", "strain", "weight"):
        r = client.get(f"/api/trends?metric={metric}&days=90")
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["points"]) == 90


def test_patterns_and_drivers(client):
    pats = client.get("/api/patterns").json()
    assert len(pats) >= 3
    assert all(p["sample_size"] >= 3 for p in pats)
    drv = client.get("/api/drivers").json()
    assert drv["available"]


def test_weekly(client):
    weeks = client.get("/api/reports/weekly").json()["weeks"]
    assert weeks
    w = client.get(f"/api/reports/weekly/{weeks[1]['week_start']}").json()
    assert w["available"]
    assert "narrative" in w


def test_chat_rule_engine(client):
    r = client.post("/api/chat", json={"message": "为什么我的 HRV 最近一直下降？"}).json()
    assert r["message"]["tool_calls"]
    assert "HRV" in r["message"]["content"]
    r2 = client.post("/api/chat", json={"message": "昨晚喝了酒", "conversation_id": r["conversation_id"]}).json()
    assert any(t["name"] == "save_memory" for t in r2["message"]["tool_calls"])
    mems = client.get("/api/memories").json()
    assert any("喝了酒" in m["content"] for m in mems)


def test_settings_threshold_override(client):
    s = client.get("/api/settings").json()
    assert s["anomaly_rules"]["rules"]["hrv_drop"]["pct"] == 0.15
    sug = client.get("/api/settings/threshold-suggestions").json()
    assert "hrv_drop" in sug
    r = client.put("/api/settings", json={"anomaly_rules": {"rules": {"hrv_drop": {"pct": 0.12}}}}).json()
    assert r["recomputed"]["days"] > 0
    s2 = client.get("/api/settings").json()
    assert s2["anomaly_rules"]["rules"]["hrv_drop"]["pct"] == 0.12


def test_all_tools_execute(client):
    import json

    from app.agent.tools import TOOLS, ToolContext, execute_tool
    from app.db import SessionLocal
    from app.models import User

    args = {"get_personal_baseline": {"metric": "hrv"}, "get_metric_trend": {"metric": "hrv", "days": 90},
            "search_relevant_memory": {"query": "喝酒"}, "save_memory": {"content": "今天开始 Deload 周"}}
    with SessionLocal() as db:
        ctx = ToolContext(db=db, user=db.get(User, 1))
        for t in TOOLS:
            out = json.loads(execute_tool(ctx, t.name, args.get(t.name, {})))
            assert "error" not in out, (t.name, out)
