"""브랜드 색인 빌드/동기화 — 공정위 `getBrandinfo` 전체 페이지 → `data/brands_index.json.gz`.

`getBrandinfo` 에는 브랜드명 검색 파라미터가 없어서(2026-11-21 실측) 전체 페이지를 훑어
색인을 만듭니다. 서버·웹·MCP 의 브랜드 조회는 이 색인을 먼저 보고, 색인에 없을 때만
실시간 API 를 다시 훑습니다.

사용
----
    # .env 의 DATA_GO_KR_SERVICE_KEY 사용
    PYTHONPATH=src python -m tools.sync_brands_index

    # 연도·출력 경로 지정(기본: 최근 4개 연도, data/brands_index.json.gz)
    PYTHONPATH=src python -m tools.sync_brands_index --years 2026 2025 --out data/brands_index.json.gz

    # 인증키 없이 네트워크도 쓰지 않고 현재 색인만 점검
    PYTHONPATH=src python -m tools.sync_brands_index --check

갱신 주기: `.github/workflows/sync-brands-index.yml` 이 **주 1회**(매주 월요일 05:00 KST) 돌립니다.
가맹정보 기준연도 데이터는 연 단위로 바뀌므로 일 1회까지 돌릴 필요는 없습니다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

KST = timezone(timedelta(hours=9))


def _recent_years(count: int = 4) -> List[int]:
    """가맹사업 기준연도 후보 — 아직 공개되지 않은 연도는 빈 결과라 자동으로 빠진다."""
    year = datetime.now(KST).year
    return [year - offset for offset in range(count)]


def main(argv: Optional[List[str]] = None) -> int:
    try:
        from franchise_kr import brand_index, live_api
        from franchise_kr.config import load_dotenv
    except ImportError:  # `python src/tools/...` 로 직접 실행할 때
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from franchise_kr import brand_index, live_api
        from franchise_kr.config import load_dotenv

    parser = argparse.ArgumentParser(description="브랜드 색인 빌드(공정위 getBrandinfo 전체 페이지)")
    parser.add_argument("--years", nargs="*", type=int, default=None,
                        help=f"가맹사업 기준연도(기본: 최근 {brand_index.DEFAULT_YEAR_SPAN}개 연도)")
    parser.add_argument("--out", default="", help="색인 파일 경로(기본 data/brands_index.json.gz)")
    parser.add_argument("--max-pages", type=int, default=brand_index.MAX_PAGES,
                        help=f"연도당 최대 페이지(기본 {brand_index.MAX_PAGES})")
    parser.add_argument("--check", action="store_true", help="네트워크 없이 현재 색인만 점검")
    parser.add_argument("--key", default="", help="인증키(없으면 .env·환경변수)")
    args = parser.parse_args(argv)
    target = brand_index.index_path(args.out or None)

    if args.check:
        state = brand_index.meta(args.out or None)
        print(json.dumps(state, ensure_ascii=False, indent=1))
        return 0 if state["available"] else 1

    load_dotenv()
    key = (args.key or live_api.service_key()).strip()
    if not key:
        print("DATA_GO_KR_SERVICE_KEY 가 없습니다(.env 또는 환경변수).", file=sys.stderr)
        return 2

    endpoint = live_api.brand_endpoint()
    if not endpoint:
        print("getBrandinfo 오퍼레이션 주소를 확인하지 못했습니다(api-verification-*.json).",
              file=sys.stderr)
        return 3

    years = args.years or _recent_years(brand_index.DEFAULT_YEAR_SPAN)
    client = live_api.FtcClient(key, timeout=40.0)
    payload = brand_index.build(client, endpoint, years, max_pages=args.max_pages)
    if not payload.get("rows"):
        print("받은 행이 0건입니다 — 승인 상태·연도를 확인하세요.", file=sys.stderr)
        for report in payload.get("fetches") or []:
            print(f"  {report}", file=sys.stderr)
        return 4

    path = brand_index.save(payload, str(target))
    size_kb = path.stat().st_size / 1024
    print(f"{path}: 브랜드 {payload['count']:,}건 · 기준연도 {payload['primary_year']} · "
          f"{size_kb:.0f}KB (압축)")
    for report in payload.get("fetches") or []:
        print(f"  목록 {report['year']}: {report['rows']:,}건 · {report['pages']}페이지 · "
              f"완전수집 {report['complete']} · 코드 {report['code']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
