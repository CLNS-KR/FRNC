"""단정 표현 금지 스캔 — "위법입니다 / 문제없습니다 / 안전합니다 / 무조건" 같은 확정 어구 0건.

이 서비스는 확정 판정을 하지 않습니다. 그래서 (1) 우리가 쓴 문장에서 확정 어구를 찾고,
(2) 반대로 '확정이 아니다'라는 고정 문장이 실제로 남아 있는지도 함께 확인합니다.
법 조문 원문(법제처 실조회본)은 그대로 인용해야 하므로 스캔 대상에서 제외합니다.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import api, engine, guides, live_api, models, usage, web_ui  # noqa: E402

# 결론을 확정하는 어구 — 조문 인용이 아닌 우리 문장에는 나오면 안 된다.
FORBIDDEN = [
    "문제없습니다", "문제없음", "문제 없습니다", "문제가 없습니다", "아무 문제",
    "안전합니다", "안전해요", "안전하다고", "100% 안전",
    "위법입니다", "불법입니다", "합법입니다",
    "무조건", "보장합니다", "확정입니다", "이상 없습니다",
]


NEGATIONS = ("아닙니다", "아니라", "않습니다", "아님", "뜻이 아")


def claim_hits(text: str) -> list:
    """확정 어구를 찾되, 바로 뒤에서 부정하는 인용("…는 뜻이 아닙니다")은 뺀다.

    예: "0건은 '문제없음·안전'이 아닙니다" — 0건이 안전하다는 뜻이 아니라는 안내이므로
    통과시키고, "위약금은 문제없습니다" 같은 단정은 잡는다.
    """
    hits = []
    for phrase in FORBIDDEN:
        start = 0
        while True:
            index = text.find(phrase, start)
            if index < 0:
                break
            tail = text[index + len(phrase):index + len(phrase) + 30]
            if not any(word in tail for word in NEGATIONS):
                hits.append((phrase, text[max(0, index - 20):index + len(phrase) + 20]))
            start = index + len(phrase)
    return hits


def guide_prose(guide) -> str:
    parts = [guide.get("topic", ""), guide.get("question", ""), guide.get("one_line", ""),
             guide.get("law_note_ko", "")]
    for field in ("points", "checklist", "pitfalls", "keywords"):
        parts += [str(row) for row in guide.get(field) or []]
    for question, answer in guide.get("faq") or []:
        parts += [question, answer]
    return "\n".join(parts)


def service_prose() -> str:
    parts = [models.DISCLAIMER_KO, " ".join(models.SCOPE_LIMITS_KO),
             " ".join(models.VERDICT_ONELINE_KO.values()), guides.DISCLAIMER_KO,
             guides.LAW_NOTE_KO, live_api.ZERO_RESULT_NOTICE_KO,
             " ".join(live_api.STATUS_MESSAGES_KO.values()),
             " ".join(live_api.HOW_TO_CONFIRM_KO),
             web_ui.render_page({"data_state": "sample"}),
             web_ui.render_page({"data_state": "live"})]
    for definition in api.TOOL_DEFS:
        parts.append(definition["description_ko"])
    for payload in (api._meta_block(), api.call_tool("get_service_meta", {})["result"]):
        parts.append(str(payload))
    parts.append(str(usage.statistics(None, days=1)))
    return "\n".join(parts)


class NoDefinitiveClaimTest(unittest.TestCase):
    def test_guides_have_no_definitive_claim(self):
        for guide in guides.GUIDES:
            hits = claim_hits(guide_prose(guide))
            self.assertEqual(hits, [], guide["slug"])

    def test_rendered_guides_have_no_definitive_claim_outside_law_cards(self):
        for slug in guides.slugs():
            page = guides.render_item(slug) or ""
            # 조문 원문 카드는 법이 정한 문장이므로 제외하고 우리 문장만 본다.
            body = re.sub(r'<div class="lawcard">.*?</div>\s*</div>', "", page, flags=re.S)
            body = re.sub(r'<script type="application/ld\+json">.*?</script>', "", body, flags=re.S)
            self.assertEqual(claim_hits(body), [], slug)

    def test_home_and_api_have_no_definitive_claim(self):
        self.assertEqual(claim_hits(service_prose()), [])

    def test_negative_disclaimers_remain(self):
        # 단정 금지의 반대편 — '확정이 아니다'가 실제로 화면과 응답에 남아 있어야 한다.
        home = web_ui.render_page({"data_state": "sample"})
        self.assertIn("확정 판정 아님", home)
        self.assertIn("확정하지 않", home)
        for slug in guides.slugs():
            page = guides.render_item(slug) or ""
            self.assertIn("확정하지 않습니다", page, slug)
        self.assertIn("확정 판정이 아닙니다", models.DISCLAIMER_KO)
        result = api.call_tool("check_franchise_risk", {"brand_name": "샘플치킨"})
        self.assertIn("확정 판정이 아닙니다", result["result"]["disclaimer_ko"])

    def test_zero_result_says_it_is_not_safe(self):
        notice = live_api.ZERO_RESULT_NOTICE_KO
        self.assertIn("0건", notice)
        self.assertIn("'문제없다·안전하다'는 뜻도 아닙니다", notice)
        self.assertTrue(notice.endswith("확인하세요."))

    def test_verdict_labels_do_not_claim_safety(self):
        for label in models.VERDICT_LABELS_KO.values():
            self.assertEqual(claim_hits(label), [], label)
        self.assertNotIn("안전", " ".join(models.VERDICT_LABELS_KO.values()))

    def test_engine_summary_has_no_definitive_claim(self):
        cases = [
            {"brand_name": "A", "disclosure_days_before": 0, "payment_route": "hq_account"},
            {"brand_name": "B"},
            dict(web_ui.PRESETS[3]["values"], brand_name="C"),
        ]
        for args in cases:
            result = engine.check_franchise_risk(args)
            text = " ".join([result["summary_ko"], result["verdict"]["one_line_ko"],
                             " ".join(result["questions_ko"]),
                             " ".join(result["checklist_ko"])])
            self.assertEqual(claim_hits(text), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
