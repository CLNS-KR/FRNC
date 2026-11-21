"""SQLite 저장소 — 익명 일별 카운터 + 문의 접수.

판정 입력(브랜드·금액·조건)과 IP·쿠키는 저장하는 열 자체를 만들지 않았습니다. 유일한
예외는 이용자가 **문의 카드에 직접 적어 보낸 연락처**로, 회신 목적으로만 `inquiries`
표에 들어가고 익명 카운터·`/v1/stats` 에는 쓰이지 않습니다.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

KST = timezone(timedelta(hours=9))

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_daily (
    day        TEXT NOT NULL,
    kind       TEXT NOT NULL,
    key        TEXT NOT NULL,
    count      INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (day, kind, key)
);

CREATE TABLE IF NOT EXISTS inquiries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT NOT NULL,
    topic      TEXT NOT NULL,
    contact    TEXT NOT NULL,
    message    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    cohort     TEXT NOT NULL DEFAULT ''   -- 무료 베타·소개 유입 구분 태그(0.1.7, 선택)
);
CREATE INDEX IF NOT EXISTS idx_inquiries_day ON inquiries(day);

CREATE TABLE IF NOT EXISTS sync_state (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def now_kst() -> datetime:
    return datetime.now(KST)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
        self.conn.row_factory = sqlite3.Row
        if path != ":memory:":
            try:
                self.conn.execute("PRAGMA journal_mode=WAL")
                self.conn.execute("PRAGMA busy_timeout=5000")
            except sqlite3.Error:
                pass
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """이미 있는 파일 DB 에 0.1.7 컬럼(`cohort`)을 더한다(없을 때만)."""
        with self._lock:
            columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(inquiries)")}
            if "cohort" not in columns:
                self.conn.execute("ALTER TABLE inquiries ADD COLUMN cohort TEXT NOT NULL DEFAULT ''")
                self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # --- 익명 카운터 ---------------------------------------------------------
    def bump_usage(self, day: str, kind: str, key: str, amount: int = 1) -> None:
        stamp = iso(now_kst())
        with self._lock:
            self.conn.execute(
                "INSERT INTO usage_daily(day, kind, key, count, updated_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(day, kind, key) DO UPDATE SET count = count + ?, updated_at = ?",
                (day, kind, key, int(amount), stamp, int(amount), stamp),
            )
            self.conn.commit()

    def usage_rows(self, start_day: str, end_day: str) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT day, kind, key, count FROM usage_daily WHERE day BETWEEN ? AND ? "
                "ORDER BY day, kind, key", (start_day, end_day))
            return [dict(row) for row in cur.fetchall()]

    def usage_total(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT COALESCE(SUM(count), 0) AS c FROM usage_daily").fetchone()
        return int(row["c"])

    # --- 문의(이용자가 직접 남긴 연락처) ------------------------------------
    def add_inquiry(self, day: str, topic: str, contact: str, message: str = "",
                    cohort: str = "") -> int:
        """문의 1건을 저장하고 행 번호를 돌려준다(접수번호로 쓴다).

        `cohort`(0.1.7)는 무료 베타·소개 유입 구분 태그이며 비어 있어도 된다.
        """
        stamp = iso(now_kst())
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO inquiries(day, topic, contact, message, created_at, cohort) "
                "VALUES (?,?,?,?,?,?)",
                (day, topic, contact, message, stamp, str(cohort or "")[:40]))
            self.conn.commit()
            return int(cur.lastrowid or 0)

    def inquiry_exists(self, day: str, topic: str, contact: str, message: str) -> bool:
        with self._lock:
            row = self.conn.execute(
                "SELECT 1 FROM inquiries WHERE day=? AND topic=? AND contact=? AND message=? LIMIT 1",
                (day, topic, contact, message)).fetchone()
        return row is not None

    def inquiry_count(self, day: Optional[str] = None) -> int:
        with self._lock:
            if day:
                row = self.conn.execute("SELECT COUNT(*) AS c FROM inquiries WHERE day=?",
                                        (day,)).fetchone()
            else:
                row = self.conn.execute("SELECT COUNT(*) AS c FROM inquiries").fetchone()
        return int(row["c"])

    def recent_inquiries(self, limit: int = 50) -> List[Dict[str, Any]]:
        """최근 접수(관리자 조회용) — 연락처는 회신 목적으로만 돌려준다."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, day, topic, contact, message, created_at, cohort FROM inquiries "
                "ORDER BY id DESC LIMIT ?", (max(1, min(200, int(limit))),)).fetchall()
        return [{
            "receipt": f"F{int(row['id']):05d}",
            "day": str(row["day"]),
            "topic": str(row["topic"]),
            "contact": str(row["contact"]),
            "message": str(row["message"] or ""),
            "created_at": str(row["created_at"]),
            "cohort": str(row["cohort"] or ""),
        } for row in rows]

    def inquiry_topic_counts(self) -> Dict[str, int]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT topic, COUNT(*) AS c FROM inquiries GROUP BY topic ORDER BY c DESC"
            ).fetchall()
        return {str(row["topic"]): int(row["c"]) for row in rows}

    def inquiry_cohort_counts(self) -> Dict[str, int]:
        """무료 베타·소개 유입 태그별 건수(0.1.7, 관리자 요약용) — 연락처·내용은 읽지 않는다."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT cohort, COUNT(*) AS c FROM inquiries GROUP BY cohort ORDER BY c DESC"
            ).fetchall()
        return {str(row["cohort"] or ""): int(row["c"]) for row in rows}

    def purge_inquiries(self, keep_days: int = 180, day: Optional[str] = None) -> int:
        today = day or now_kst().strftime("%Y-%m-%d")
        try:
            cutoff = (datetime.strptime(today, "%Y-%m-%d")
                      - timedelta(days=max(1, int(keep_days)))).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return 0
        with self._lock:
            cur = self.conn.execute("DELETE FROM inquiries WHERE day < ?", (cutoff,))
            self.conn.commit()
            return int(cur.rowcount or 0)

    # --- 상태 저장 -----------------------------------------------------------
    def set_state(self, key: str, value: Dict[str, Any]) -> None:
        import json
        stamp = iso(now_kst())
        payload = json.dumps(value, ensure_ascii=False)
        with self._lock:
            self.conn.execute(
                "INSERT INTO sync_state(key, value_json, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=?, updated_at=?",
                (key, payload, stamp, payload, stamp))
            self.conn.commit()

    def get_state(self, key: str) -> Optional[Dict[str, Any]]:
        import json
        with self._lock:
            row = self.conn.execute("SELECT value_json FROM sync_state WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(row["value_json"])
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None
