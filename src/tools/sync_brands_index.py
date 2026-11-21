"""브랜드 색인 빌드/동기화 — 공정위 `getBrandinfo` 전체 페이지 → `data/brands_index.json.gz`.

`getBrandinfo` 에는 브랜드명 검색 파라미터가 없어서(2026-11-21 실측) 전체 페이지를 훑어
색인을 만듭니다. 서버·웹·MCP 의 브랜드 조회는 이 색인을 먼저 보고, 색인에 없을 때만
실시간 API 를 다시 훑습니다.

가맹점 수·직영점 수
------------------
승인된 가맹점 및 직영점 데이터셋(15125490)도 함께 훑어(기본값) 각 브랜드 행에 가맹점 수·
직영점 수를 저장합니다. 그러면 인증키가 없는 배포에서도 '몇 곳인지'가 나오고, 서버가
인증키를 가졌을 때도 조회마다 20만 행짜리 데이터셋을 다시 부르지 않습니다.
이 데이터셋은 시·도 행과 '전체' 합계 행을 함께 주므로 '전체' 행만 씁니다(두 배 방지).

사용
----
    # .env 의 DATA_GO_KR_SERVICE_KEY 사용(브랜드 목록 + 가맹점 수)
    PYTHONPATH=src python -m tools.sync_brands_index

    # 연도·출력 경로 지정(기본: 최근 4개 연도, data/brands_index.json.gz)
    PYTHONPATH=src python -m tools.sync_brands_index --years 2026 2025 --out data/brands_index.json.gz

    # 브랜드 목록만 빠르게(가맹점 수 생략, 약 2~3분)
    PYTHONPATH=src python -m tools.sync_brands_index --no-stores

    # 인증키 없이 네트워크도 쓰지 않고 현재 색인만 점검
    PYTHONPATH=src python -m tools.sync_brands_index --check

갱신 주기: `.github/workflows/sync-brands-index.yml` 이 **주 1회**(매주 월요일 05:00 KST) 돌립니다.
가맹정보 기준연도 데이터는 연 단위로 바뀌므로 일 1회까지 돌릴 필요는 없습니다.
가맹점 수까지 받으면 4개 연도 기준 약 750페이지(15~20분)입니다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
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
    parser.add_argument("--no-stores", dest="with_stores", action="store_false",
                        help="가맹점 및 직영점(15125490) 수집을 건너뛴다(브랜드 목록만)")
    parser.add_argument("--store-max-pages", type=int, default=brand_index.STORE_MAX_PAGES,
                        help=f"연도당 가맹점 페이지 상한(기본 {brand_index.STORE_MAX_PAGES})")
    parser.add_argument("--store-workers", type=int, default=6,
                        help="가맹점 페이지를 동시에 받을 개수(기본 6, 1이면 순서대로)")
    parser.set_defaults(with_stores=True)
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

    store_endpoint = ""
    if args.with_stores:
        store_endpoint = str((live_api.dataset_index().get("brand_direct_stores") or {})
                             .get("endpoint") or "").strip()
        if not store_endpoint:
            print("가맹점 및 직영점(15125490) 주소를 확인하지 못해 브랜드 목록만 받습니다.",
                  file=sys.stderr)

    years = args.years or _recent_years(brand_index.DEFAULT_YEAR_SPAN)
    client = live_api.FtcClient(key, timeout=40.0)
    started = time.time()
    payload = brand_index.build(client, endpoint, years, max_pages=args.max_pages,
                                with_stores=bool(store_endpoint),
                                store_endpoint=store_endpoint,
                                store_max_pages=args.store_max_pages,
                                store_workers=max(1, args.store_workers))
    if not payload.get("rows"):
        print("받은 행이 0건입니다 — 승인 상태·연도를 확인하세요.", file=sys.stderr)
        for report in payload.get("fetches") or []:
            print(f"  {report}", file=sys.stderr)
        return 4

    path = brand_index.save(payload, str(target))
    size_kb = path.stat().st_size / 1024
    elapsed = int(time.time() - started)
    print(f"{path}: 브랜드 {payload['count']:,}건 · 기준연도 {payload['primary_year']} · "
          f"{size_kb:.0f}KB (압축) · {elapsed}초")
    for report in payload.get("fetches") or []:
        print(f"  목록 {report['year']}: {report['rows']:,}건 · {report['pages']}페이지 · "
              f"완전수집 {report['complete']} · 코드 {report['code']}")
    stores = payload.get("stores") or {}
    for report in stores.get("fetches") or []:
        print(f"  가맹점·직영 {report.get('year')}: {report.get('brands', 0):,}브랜드 · "
              f"{report.get('pages', 0)}페이지 · 합계 적용 {report.get('filled_rows', 0):,}행 · "
              f"완전수집 {report.get('complete')} · 코드 {report.get('code')}")
    if stores:
        print(f"  가맹점 수가 붙은 행: {int(stores.get('rows_with_stores') or 0):,}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
