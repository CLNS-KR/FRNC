"""법제처 국가법령정보 OPEN API 로 가맹사업법·시행령 조문을 실조회해 `law-verification.json` 을 만든다.

추측 금지 원칙
--------------
이 프로젝트의 모든 조문 인용은 **이 스크립트가 받은 응답**에서만 나옵니다. 조문 텍스트를
손으로 옮겨 적지 않고, 응답의 `조문내용`·`항`·`호`·`목` 을 그대로 보존합니다.

사용
----
    LAW_GO_KR_OC=<발급받은 OC> PYTHONPATH=src python -m tools.verify_law_articles

결과
----
    law-verification.json   (프로젝트 루트)

- `laws`: 법령 메타(법령명·법령ID·MST·공포일·시행일·소관부처)
- `articles`: `"가맹사업법:제7조"` 형태 키 → 제목·시행일·조문 전문·항/호 구조·출처
- `annexes`: 시행령 별표 2(불공정거래행위의 유형 또는 기준) 전문

OC 값은 응답·파일에 남기지 않습니다(요청 URL 에서 뺀 형태로 기록).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

KST = timezone(timedelta(hours=9))
SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"

TARGETS = (
    {"key": "franchise_act", "short": "가맹사업법", "query": "가맹사업거래의 공정화에 관한 법률",
     "target": "law"},
    {"key": "franchise_decree", "short": "가맹사업법 시행령",
     "query": "가맹사업거래의 공정화에 관한 법률 시행령", "target": "law"},
)

# 사람이 읽는 원문 주소(참고용). API 주소에는 OC 를 넣지 않는다.
HUMAN_URL = {
    "franchise_act": "https://www.law.go.kr/법령/가맹사업거래의공정화에관한법률",
    "franchise_decree": "https://www.law.go.kr/법령/가맹사업거래의공정화에관한법률시행령",
}


class LawApiError(RuntimeError):
    pass


def _get_json(url: str, timeout: float = 40.0) -> Dict[str, Any]:
    request = urllib.request.Request(url, headers={
        "User-Agent": "frnc/0.1 (+law.go.kr OPEN API)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", "replace")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - API 형식이 바뀌면 여기서 멈춘다
        raise LawApiError(f"법령 API 응답이 JSON 이 아닙니다: {raw[:200]}") from exc
    if not isinstance(payload, dict):
        raise LawApiError("법령 API 응답이 객체가 아닙니다.")
    return payload


def find_law(oc: str, query: str, target: str) -> Dict[str, Any]:
    """법령명으로 검색해 현행 법령 1건의 메타를 돌려준다."""
    url = SEARCH_URL + "?" + urllib.parse.urlencode({
        "OC": oc, "target": target, "query": query, "type": "JSON",
        "display": "5", "page": "1",
    })
    payload = _get_json(url)
    search = payload.get("LawSearch") or {}
    rows = search.get("law")
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list) or not rows:
        raise LawApiError(f"법령을 찾지 못했습니다: {query}")
    for row in rows:
        if row.get("법령명한글") == query and row.get("현행연혁코드") == "현행":
            return row
    for row in rows:
        if row.get("법령명한글") == query:
            return row
    return rows[0]


def fetch_law(oc: str, mst: str) -> Dict[str, Any]:
    url = SERVICE_URL + "?" + urllib.parse.urlencode({
        "OC": oc, "target": "law", "MST": mst, "type": "JSON",
    })
    return _get_json(url)


def _join(values: List[str]) -> str:
    return "\n".join(value for value in values if value)


def _text(value: Any) -> str:
    """항·호·목의 내용은 문자열일 수도, 목록일 수도 있다."""
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(_text(item) for item in value).strip()
    if isinstance(value, dict):
        return _text(value.get("content") or value.get("내용") or "")
    return str(value).strip()


def paragraph_rows(unit: Dict[str, Any]) -> List[Dict[str, Any]]:
    """조문단위의 `항` 구조를 `[{no, text, items:[{no,text}], subitems:[...]}]` 로 평탄화.

    `항` 은 리스트일 수도, `{"항내용": ..., "호": [...]}` 일 수도, 항번호 없이
    `{"호": [...]}` 만 올 수도 있다(예: 시행령 제5조의8 의 호 목록).
    """
    rows: List[Dict[str, Any]] = []
    hang = unit.get("항")
    if isinstance(hang, dict):
        hang = [hang]
    if not isinstance(hang, list):
        return rows
    for entry in hang:
        if not isinstance(entry, dict):
            continue
        row: Dict[str, Any] = {
            "no": entry.get("항번호") or "",
            "text": _text(entry.get("항내용")),
        }
        hos = entry.get("호")
        if isinstance(hos, dict):
            hos = [hos]
        items: List[Dict[str, Any]] = []
        if isinstance(hos, list):
            for ho in hos:
                if not isinstance(ho, dict):
                    continue
                item: Dict[str, Any] = {
                    "no": ho.get("호번호") or "",
                    "text": _text(ho.get("호내용")),
                }
                moks = ho.get("목")
                if isinstance(moks, dict):
                    moks = [moks]
                if isinstance(moks, list):
                    item["subitems"] = [
                        {"no": mok.get("목번호") or "", "text": _text(mok.get("목내용"))}
                        for mok in moks if isinstance(mok, dict)
                    ]
                items.append(item)
        if items:
            row["items"] = items
        rows.append(row)
    return rows


def article_key(short: str, number: str, branch: str = "") -> str:
    """`가맹사업법:제7조` · `가맹사업법:제6조의5` 형태 키."""
    base = f"제{number}조"
    if branch:
        base += f"의{branch}"
    return f"{short}:{base}"


def collect_articles(law: Dict[str, Any], short: str, source_url: str,
                     verified_at: str) -> Dict[str, Any]:
    root = law.get("법령") or {}
    units = ((root.get("조문") or {}).get("조문단위")) or []
    out: Dict[str, Any] = {}
    for unit in units:
        if not isinstance(unit, dict):
            continue
        number = str(unit.get("조문번호") or "").strip()
        if not number:
            continue
        title = (unit.get("조문제목") or "").strip()
        body = (unit.get("조문내용") or "").strip()
        if not title and "제" not in body:
            continue          # 장·절 제목 줄 등은 건너뛴다
        branch = str(unit.get("조문가지번호") or "").strip()
        key = article_key(short, number, branch)
        record: Dict[str, Any] = {
            "law": short,
            "article": key.split(":", 1)[1],
            "title": title,
            "effective_on": unit.get("조문시행일자") or root.get("기본정보", {}).get("시행일자"),
            "text": body,
            "source_url": source_url,
            "verified_at": verified_at,
        }
        paragraphs = paragraph_rows(unit)
        if paragraphs:
            record["paragraphs"] = paragraphs
        if record["text"] or paragraphs:
            out[key] = record
    return out


def collect_annexes(law: Dict[str, Any], short: str, source_url: str,
                    verified_at: str) -> Dict[str, Any]:
    root = law.get("법령") or {}
    units = ((root.get("별표") or {}).get("별표단위")) or []
    out: Dict[str, Any] = {}
    for unit in units:
        if not isinstance(unit, dict):
            continue
        title = (unit.get("별표제목") or "").strip()
        content = unit.get("별표내용")
        if not title or content is None:
            continue
        lines: List[str] = []
        # 별표내용은 [[line, line, ...]] 이거나 [line, ...] 이다.
        rows = content[0] if isinstance(content, list) and content and isinstance(content[0], list) else content
        if isinstance(rows, list):
            lines = [str(row).rstrip() for row in rows]
        elif isinstance(rows, str):
            lines = rows.splitlines()
        text = "\n".join(lines).strip("\n")
        if not text:
            continue
        out[f"{short}:{title}"] = {
            "law": short,
            "title": title,
            "text": text,
            "source_url": source_url,
            "verified_at": verified_at,
        }
    return out


def build(oc: str) -> Dict[str, Any]:
    verified_at = datetime.now(KST).isoformat(timespec="seconds")
    laws: List[Dict[str, Any]] = []
    articles: Dict[str, Any] = {}
    annexes: Dict[str, Any] = {}
    for target in TARGETS:
        meta = find_law(oc, target["query"], target["target"])
        mst = str(meta.get("법령일련번호") or "")
        if not mst:
            raise LawApiError(f"법령일련번호가 없습니다: {target['query']}")
        payload = fetch_law(oc, mst)
        root = payload.get("법령") or {}
        info = root.get("기본정보") or {}
        source_url = f"{SERVICE_URL}?target=law&MST={mst}&type=JSON"
        laws.append({
            "key": target["key"],
            "short": target["short"],
            "name": info.get("법령명_한글") or meta.get("법령명한글"),
            "abbreviation": info.get("법령명약칭") or "",
            "law_id": info.get("법령ID") or meta.get("법령ID"),
            "mst": mst,
            "kind": meta.get("법령구분명"),
            "ministry": (info.get("소관부처") or {}).get("content") or meta.get("소관부처명"),
            "department": ((info.get("연락부서") or {}).get("부서단위") or {}).get("부서명", ""),
            "promulgated_on": info.get("공포일자") or meta.get("공포일자"),
            "effective_on": info.get("시행일자") or meta.get("시행일자"),
            "promulgation_no": info.get("공포번호") or meta.get("공포번호"),
            "source_url": source_url,
            "human_url": HUMAN_URL.get(target["key"], ""),
            "articles": int(len(((root.get("조문") or {}).get("조문단위")) or [])),
        })
        articles.update(collect_articles(payload, target["short"], source_url, verified_at))
        annexes.update(collect_annexes(payload, target["short"], source_url, verified_at))
    return {
        "generated_at": verified_at,
        "source": "법제처 국가법령정보 공동활용 OPEN API (law.go.kr DRF)",
        "note_ko": (
            "조문 텍스트는 법제처 OPEN API 응답의 조문내용·항·호·목을 그대로 보존했습니다. "
            "OC 인증값은 파일에 남기지 않았습니다."
        ),
        "laws": laws,
        "articles": articles,
        "annexes": annexes,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="가맹사업법·시행령 조문 실조회 → law-verification.json")
    parser.add_argument("--oc", default=os.environ.get("LAW_GO_KR_OC", ""),
                        help="법제처 OPEN API OC 값(환경변수 LAW_GO_KR_OC)")
    parser.add_argument("--out", default="law-verification.json")
    args = parser.parse_args(argv)
    oc = (args.oc or "").strip()
    if not oc:
        print("LAW_GO_KR_OC 가 없습니다.", file=sys.stderr)
        return 2
    data = build(oc)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    print(f"{args.out}: 법령 {len(data['laws'])}건 · 조문 {len(data['articles'])}개 · "
          f"별표 {len(data['annexes'])}개")
    for law in data["laws"]:
        print(f"  - {law['short']} MST={law['mst']} 시행 {law['effective_on']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
