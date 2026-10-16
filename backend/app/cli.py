"""命令行工具。

    whoop-analyst demo [--days 200]   生成 Demo 数据并完成分析
    whoop-analyst sync [--full]       同步 WHOOP 数据
    whoop-analyst recompute           从原始数据重算全部分析
    whoop-analyst report [--date D]   在终端打印日报
    whoop-analyst ask "问题"          在终端向 Agent 提问
"""

import argparse
import json
from datetime import date

from app.db import SessionLocal, init_db
from app.deps import ensure_default_user


def main() -> None:
    parser = argparse.ArgumentParser(prog="whoop-analyst", description="WHOOP AI Analyst 命令行")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("demo", help="生成 Demo 数据")
    p.add_argument("--days", type=int, default=200)
    p = sub.add_parser("sync", help="同步 WHOOP")
    p.add_argument("--full", action="store_true")
    sub.add_parser("recompute", help="重算分析层")
    p = sub.add_parser("report", help="打印日报")
    p.add_argument("--date", type=date.fromisoformat)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("ask", help="向 Agent 提问")
    p.add_argument("question")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as db:
        user = ensure_default_user(db)
        if args.cmd == "demo":
            from app.analytics.pipeline import recompute_user
            from app.demo.generator import generate

            print(generate(db, user, days=args.days))
            print(recompute_user(db, user))
        elif args.cmd == "sync":
            from app.whoop.sync import sync_user

            print(json.dumps(sync_user(db, user, full=args.full), ensure_ascii=False, indent=2))
        elif args.cmd == "recompute":
            from app.analytics.pipeline import recompute_user

            print(recompute_user(db, user))
        elif args.cmd == "report":
            from app.reports.daily import get_daily_report

            r = get_daily_report(db, user, args.date, refresh=True)
            print(json.dumps(r, ensure_ascii=False, indent=2, default=str) if args.json else r.get("narrative", r))
        elif args.cmd == "ask":
            from app.agent.agent import chat

            r = chat(db, user, args.question)
            for t in r["message"]["tool_calls"]:
                print(f"  ↳ 调用工具 {t['name']}({json.dumps(t['args'], ensure_ascii=False)})")
            print()
            print(r["message"]["content"])


if __name__ == "__main__":
    main()
