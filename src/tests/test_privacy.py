"""개인정보·시크릿 0건 검사.

소스·문서·데이터 파일을 훑어 다음이 없음을 확인합니다.
- 공공데이터포털·법제처 인증값의 평문
- 휴대전화·주민등록번호·이메일 같은 개인정보
- 브랜드명·금액 같은 판정 입력을 저장하는 스키마·로그

개인정보 문자열 목록은 코드에 평문으로 두지 않습니다(저장소가 공개입니다).
프로젝트 루트의 `.private-terms`(gitignore·dockerignore 대상, 로컬 전용)에 한 줄에
하나씩 적어 두면 그 값으로 검사하고, 파일이 없으면(CI·외부 클론) 형식 검사만 합니다.
"""
from __future__ import annotations

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
PROJECT = os.path.dirname(SRC)

TEXT_SUFFIXES = (".py", ".md", ".txt", ".json", ".yaml", ".yml", ".example", "")
PRIVATE_TERMS_FILE = os.path.join(PROJECT, ".private-terms")
SKIP_DIRS = {"__pycache__", ".git", "build", "data", ".venv", "tests"}
SKIP_FILES = {".private-terms"}

EMAIL_RE = re.compile(r"[0-9A-Za-z._%+\-]+@[0-9A-Za-z.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\b0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}\b")
RRN_RE = re.compile(r"\b\d{6}\s?-\s?\d{7}\b")
CARD_RE = re.compile(r"\b(?:\d{4}[- ]){3}\d{4}\b")


def private_terms():
    try:
        with open(PRIVATE_TERMS_FILE, "r", encoding="utf-8") as handle:
            return [line.strip() for line in handle
                    if line.strip() and not line.lstrip().startswith("#")]
    except OSError:
        return []


def project_files():
    """검사 대상 — 제품 코드·문서·데이터·배포 설정.

    `src/tests` 는 제외합니다. 테스트에는 가짜 이메일·가짜 키 같은 픽스처가 일부러 들어가고,
    이 파일의 정규식 문장 자체도 패턴에 걸리기 때문입니다.
    """
    for root, dirs, files in os.walk(PROJECT):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        for name in files:
            if name in SKIP_FILES:
                continue
            if name.endswith(TEXT_SUFFIXES) or name in (".env.example", ".gitignore",
                                                        ".dockerignore", "Dockerfile"):
                yield os.path.join(root, name)


def read(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return ""


class SecretScanTest(unittest.TestCase):
    def test_no_hardcoded_service_key(self):
        patterns = [
            re.compile(r"DATA_GO_KR_SERVICE_KEY\s*=\s*['\"][^'\"]{8,}['\"]"),
            re.compile(r"serviceKey\s*=\s*['\"][A-Za-z0-9%+/=_-]{16,}['\"]"),
            re.compile(r"LAW_GO_KR_OC\s*=\s*['\"][^'\"]{3,}['\"]"),
            re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9%+/=]{20,}['\"]"),
        ]
        for path in project_files():
            text = read(path)
            for pattern in patterns:
                self.assertIsNone(pattern.search(text), f"{os.path.relpath(path, PROJECT)}: 시크릿 의심")

    def test_no_phone_or_rrn_pattern(self):
        for path in project_files():
            text = read(path)
            rel = os.path.relpath(path, PROJECT)
            self.assertIsNone(PHONE_RE.search(text), rel)
            self.assertIsNone(RRN_RE.search(text), rel)

    def test_no_real_email(self):
        # 예시 도메인(example.com 등)만 허용한다.
        allowed = ("example.com", "example.org", "example.net", "test.invalid")
        for path in project_files():
            text = read(path)
            rel = os.path.relpath(path, PROJECT)
            for match in EMAIL_RE.findall(text):
                self.assertTrue(any(match.lower().endswith("@" + domain) or domain in match.lower()
                                    for domain in allowed), f"{rel}: {match}")

    def test_no_card_numbers(self):
        for path in project_files():
            self.assertIsNone(CARD_RE.search(read(path)), os.path.relpath(path, PROJECT))

    def test_private_terms_absent_everywhere(self):
        terms = private_terms()
        if not terms:
            self.skipTest(".private-terms 없음(CI·외부 클론) — 형식 검사만 수행")
        for path in project_files():
            text = read(path)
            rel = os.path.relpath(path, PROJECT)
            for term in terms:
                self.assertNotIn(term, text, f"{rel}: 개인정보 문자열 발견")

    def test_gitignore_and_dockerignore_protect_secrets(self):
        gitignore = read(os.path.join(PROJECT, ".gitignore"))
        dockerignore = read(os.path.join(PROJECT, ".dockerignore"))
        for name in (".env", ".private-terms"):
            self.assertIn(name, gitignore)
            self.assertIn(name, dockerignore)

    def test_no_input_storage_schema(self):
        store = read(os.path.join(SRC, "franchise_kr", "store.py"))
        usage = read(os.path.join(SRC, "franchise_kr", "usage.py"))
        for text, name in ((store, "store.py"), (usage, "usage.py")):
            lowered = text.lower()
            for forbidden in ("brand_name text", "franchise_fee", "interior_krw",
                              "disclosure_days", "revenue_claim"):
                self.assertNotIn(forbidden, lowered, f"{name}: 판정 입력 저장 의심")

    def test_verification_files_have_no_key(self):
        for path in project_files():
            if "verification" not in os.path.basename(path):
                continue
            text = read(path)
            self.assertNotIn("serviceKey=", text, os.path.basename(path))
            self.assertNotIn("OC=", text, os.path.basename(path))

    def test_env_example_has_empty_values(self):
        example = read(os.path.join(PROJECT, ".env.example"))
        self.assertIn("DATA_GO_KR_SERVICE_KEY=", example)
        for line in example.splitlines():
            if line.startswith("DATA_GO_KR_SERVICE_KEY=") or line.startswith("LAW_GO_KR_OC="):
                self.assertEqual(line.split("=", 1)[1].strip(), "", line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
