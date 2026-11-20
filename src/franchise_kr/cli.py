"""명령줄 — 서버 없이 판정·조회 한 번.

    PYTHONPATH=src python -m franchise_kr.cli check --brand 샘플치킨 --days 0 --payment hq_account
    PYTHONPATH=src python -m franchise_kr.cli lookup --brand 샘플치킨
    PYTHONPATH=src python -m franchise_kr.cli law "제7조"
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from . import engine, live_api


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=1))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="franchise_kr.cli", description="FRNC 명령줄")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="조건으로 리스크 체크")
    check.add_argument("--brand", default="")
    check.add_argument("--industry", default="")
    check.add_argument("--fee", default="")
    check.add_argument("--interior", default="")
    check.add_argument("--deposit", default="")
    check.add_argument("--days", type=int, default=None, help="정보공개서 수령 후 경과일")
    check.add_argument("--payment", default="", choices=["", "escrow", "insurance", "hq_account", "none"])
    check.add_argument("--territory", default="", choices=["", "exclusive", "defined", "none"])
    check.add_argument("--interior-designation", dest="interior_designated", default="",
                       choices=["", "free", "partial", "forced"])
    check.add_argument("--closure-rate", type=float, default=None)

    lookup = sub.add_parser("lookup", help="브랜드 정보공개서 요약")
    lookup.add_argument("--brand", default="")
    lookup.add_argument("--code", default="")

    law = sub.add_parser("law", help="가맹사업법 조문 조회")
    law.add_argument("article")

    cases = sub.add_parser("cases", help="리스크 케이스 목록")

    args = parser.parse_args(argv)
    if args.command == "check":
        payload: Dict[str, Any] = {
            "brand_name": args.brand, "industry": args.industry,
            "franchise_fee_krw": args.fee, "interior_krw": args.interior,
            "deposit_krw": args.deposit, "payment_route": args.payment,
            "territory": args.territory, "interior_designated": args.interior_designated,
        }
        if args.days is not None:
            payload["disclosure_days_before"] = args.days
        if args.closure_rate is not None:
            payload["closure_rate_3y_pct"] = args.closure_rate
        result = engine.check_franchise_risk(payload)
        _print({
            "verdict": result["verdict"],
            "risk_score": result["risk_score"],
            "summary_ko": result["summary_ko"],
            "risk_points": [row["title_ko"] for row in result["risk_points"]],
            "questions_ko": result["questions_ko"],
        })
        return 0
    if args.command == "lookup":
        _print(live_api.lookup(args.brand, args.code))
        return 0
    if args.command == "law":
        _print(engine.search_law_article(args.article))
        return 0
    if args.command == "cases":
        data = engine.list_risk_cases()
        _print({"count": data["count"],
                "cases": [{"id": row["trap_id"], "title_ko": row["title_ko"],
                           "severity": row["severity"], "law_verified": row["law_verified"]}
                          for row in data["cases"]]})
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
