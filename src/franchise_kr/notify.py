"""문의 접수 알림·이중 기록 — 무료 플랜에서 문의가 조용히 사라지지 않게.

왜 필요한가
-----------
Render 무료 플랜은 영구 디스크가 없어 재시작·슬립 해제·재배포 때 `data/app.sqlite` 가
통째로 사라집니다. 그러면 이용자가 문의 카드로 보낸 연락처도 함께 사라지는데, 지금까지는
관리자 알림도 조회 수단도 없어 아무도 그 사실을 몰랐습니다.

그래서 접수에 **성공한 직후** 두 가지를 남깁니다.
1) **미러 파일**(JSONL, `FRNC_INQUIRY_MIRROR`) — 영구 볼륨을 붙였을 때 SQLite 와 별개로
   남고, 서버가 다시 뜰 때 `restore()` 가 SQLite 로 되돌려 놓습니다(중복은 접수 내용으로
   걸러 냅니다).
2) **웹훅**(`FRNC_INQUIRY_WEBHOOK_URL`) — Slack·Discord·자체 엔드포인트로 즉시 알립니다.
   기본적으로 **연락처는 넣지 않고** 접수번호·유형·미리보기만 보냅니다(채널에 연락처가
   남지 않게). `FRNC_INQUIRY_WEBHOOK_CONTACT=1` 이면 회신 목적으로 연락처도 함께 보냅니다.

두 경로의 실패는 접수 응답을 막지 않고 `alert` 상태로 돌려줍니다(접수는 이미 저장됨).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

KST = timezone(timedelta(hours=9))
DEFAULT_TIMEOUT = 4.0
PREVIEW_CHARS = 120
MAX_RESTORE_LINES = 5000
MAX_RESTORE_BYTES = 4 * 1024 * 1024
MIRROR_KEEP_NOTE_KO = "미러 파일은 접수 원문 그대로이므로, 회신·보관 기간(180일)이 지나면 지웁니다."


def _env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    return os.environ if env is None else env


def config(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """환경변수 → 알림 설정(비밀값은 밖으로 돌려주지 않는다)."""
    source = _env(env)
    url = str(source.get("FRNC_INQUIRY_WEBHOOK_URL") or "").strip()
    mirror = str(source.get("FRNC_INQUIRY_MIRROR") or "").strip()
    include_contact = str(source.get("FRNC_INQUIRY_WEBHOOK_CONTACT") or "").strip().lower() in (
        "1", "true", "yes", "on")
    return {
        "webhook_url": url,
        "webhook_configured": bool(url),
        "webhook_contact": include_contact,
        "mirror_path": mirror,
        "mirror_configured": bool(mirror),
        "base_url": str(source.get("PUBLIC_BASE_URL") or "https://frnc.onrender.com").rstrip("/"),
    }


def status(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """healthz·meta 에 넣는 알림 상태 — 주소·토큰 값은 절대 넣지 않는다."""
    cfg = config(env)
    host = ""
    if cfg["webhook_url"]:
        try:
            host = urllib.parse.urlparse(cfg["webhook_url"]).hostname or ""
        except ValueError:
            host = ""
    return {
        "webhook": {"configured": cfg["webhook_configured"],
                    "host": host,
                    "includes_contact": cfg["webhook_contact"]},
        "mirror": {"configured": cfg["mirror_configured"]},
        "note_ko": ("알림이 설정되지 않아도 접수는 저장됩니다. 무료 플랜은 재시작 때 DB 가 "
                    "초기화될 수 있으니, 웹훅이나 영구 볼륨(FRNC_INQUIRY_MIRROR)을 권장합니다."),
    }


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def _entry(clean: Dict[str, Any], receipt: Optional[str], day: str) -> Dict[str, Any]:
    message = str(clean.get("message") or "")
    return {
        "receipt": receipt,
        "day": day,
        "topic": clean.get("topic"),
        "contact": clean.get("contact"),
        "message": message,
        "created_at": _now(),
        "cohort": str(clean.get("cohort") or ""),
    }


def mirror_append(path: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """접수 1건을 JSONL 로 덧붙인다(실패해도 접수는 유효)."""
    if not path:
        return {"configured": False, "written": False}
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        return {"configured": True, "written": False, "error": type(exc).__name__}
    return {"configured": True, "written": True, "file": path}


def mirror_read(path: str) -> List[Dict[str, Any]]:
    """미러 파일에서 접수 행을 읽는다(깨진 줄은 건너뛴다)."""
    if not path:
        return []
    target = Path(path)
    try:
        if target.stat().st_size > MAX_RESTORE_BYTES:
            return []
        with open(target, "r", encoding="utf-8") as handle:
            lines = handle.readlines()[-MAX_RESTORE_LINES:]
    except OSError:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("topic") and row.get("contact"):
            rows.append(row)
    return rows


def webhook_payload(clean: Dict[str, Any], receipt: Optional[str], day: str,
                    cfg: Dict[str, Any]) -> Dict[str, Any]:
    message = str(clean.get("message") or "")
    preview = message[:PREVIEW_CHARS]
    topic = str(clean.get("topic") or "")
    cohort = str(clean.get("cohort") or "")
    payload: Dict[str, Any] = {
        "event": "frnc.inquiry",
        "service": "frnc",
        "receipt": receipt,
        "day": day,
        "topic": topic,
        "message_preview_ko": preview,
        "message_chars": len(message),
        "admin_path": "/v1/inquiries",
        "admin_url": f"{cfg.get('base_url', '')}/v1/inquiries",
        "contact_included": bool(cfg.get("webhook_contact")),
        "checked_at": _now(),
        "text": (f"[FRNC] 새 문의 {receipt or '(번호 없음)'} · {topic}"
                 + (f" · {cohort}" if cohort else "")
                 + (f" · {preview}" if preview else "")
                 + " — 연락처는 관리자 조회(/v1/inquiries)에서 확인하세요."),
    }
    if cohort:
        payload["cohort"] = cohort
    if cfg.get("webhook_contact") and clean.get("contact"):
        payload["contact"] = clean.get("contact")
        payload["text"] = (f"[FRNC] 새 문의 {receipt or '(번호 없음)'} · {topic}"
                           + (f" · {cohort}" if cohort else "")
                           + f" · {clean.get('contact')}" + (f" · {preview}" if preview else ""))
    return payload


def webhook_send(url: str, payload: Dict[str, Any], timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """웹훅 1회 POST(실패는 상태로 돌려준다)."""
    if not url:
        return {"configured": False, "delivered": False}
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return {"configured": True, "delivered": False, "error": "invalid_url"}
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {"configured": True, "delivered": False, "error": "invalid_url"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "frnc-inquiry-alert/1.0",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"configured": True, "delivered": 200 <= int(response.status) < 300,
                    "status": int(response.status)}
    except urllib.error.HTTPError as exc:
        return {"configured": True, "delivered": False, "status": int(exc.code)}
    except Exception as exc:  # noqa: BLE001 - 알림 실패가 접수를 막지 않는다
        return {"configured": True, "delivered": False, "error": type(exc).__name__}


def deliver(clean: Dict[str, Any], receipt: Optional[str], day: str,
            env: Optional[Dict[str, str]] = None,
            store: Any = None) -> Dict[str, Any]:
    """접수 성공 직후 미러·웹훅을 남기고 결과를 돌려준다."""
    cfg = config(env)
    entry = _entry(clean, receipt, day)
    mirror = mirror_append(cfg["mirror_path"], entry)
    webhook = webhook_send(cfg["webhook_url"],
                           webhook_payload(clean, receipt, day, cfg)) if cfg["webhook_configured"] \
        else {"configured": False, "delivered": False}
    alert = {
        "mirror": mirror,
        "webhook": webhook,
        "durable_copy": bool(mirror.get("written") or webhook.get("delivered")),
        "note_ko": ("접수 내용은 서버 DB 에 저장됩니다. 무료 플랜은 재시작 때 DB 가 초기화될 수 "
                    "있어, 알림·미러가 설정돼 있으면 그 사본으로 복구할 수 있습니다."),
    }
    if store is not None:
        try:
            store.set_state("inquiry_alert_last", {
                "receipt": receipt, "day": day,
                "mirror_written": bool(mirror.get("written")),
                "webhook_configured": bool(webhook.get("configured")),
                "webhook_delivered": bool(webhook.get("delivered")),
                "checked_at": _now(),
            })
        except Exception:  # noqa: BLE001 - 상태 기록 실패도 접수를 막지 않는다
            pass
    return alert


def restore(store: Any, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """미러 파일 → SQLite 복구(서버가 다시 뜰 때). 중복은 접수 내용으로 건너뛴다."""
    cfg = config(env)
    rows = mirror_read(cfg["mirror_path"])
    if not rows or store is None:
        return {"configured": cfg["mirror_configured"], "scanned": len(rows), "imported": 0}
    imported = 0
    for row in rows:
        day = str(row.get("day") or "")[:10] or datetime.now(KST).strftime("%Y-%m-%d")
        try:
            if store.inquiry_exists(day, str(row.get("topic")), str(row.get("contact")),
                                    str(row.get("message") or "")):
                continue
            store.add_inquiry(day, str(row.get("topic")), str(row.get("contact")),
                              str(row.get("message") or ""),
                              cohort=str(row.get("cohort") or "")[:40])
            imported += 1
        except Exception:  # noqa: BLE001 - 한 건 실패가 나머지를 막지 않는다
            continue
    return {"configured": True, "scanned": len(rows), "imported": imported}
