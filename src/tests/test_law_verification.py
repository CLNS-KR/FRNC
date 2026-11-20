"""법령 실조회 결과(law-verification.json) 검사.

이 파일의 조문은 `tools/verify_law_articles.py` 가 법제처 OPEN API 로 받은 응답입니다.
테스트는 **브리프가 지정한 조문이 실제로 들어 있고, 그 안에 핵심 문구가 있는지**를 봅니다.
문구가 바뀌면(법 개정) 테스트가 먼저 깨져서 사람이 확인하게 됩니다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
LAW_PATH = os.path.join(PROJECT, "law-verification.json")
sys.path.insert(0, os.path.dirname(HERE))

from franchise_kr import engine  # noqa: E402


class LawVerificationFileTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(LAW_PATH, "r", encoding="utf-8") as handle:
            cls.data = json.load(handle)
        cls.articles = cls.data["articles"]
        cls.annexes = cls.data["annexes"]

    def text_of(self, key):
        record = self.articles.get(key) or self.annexes.get(key)
        self.assertIsNotNone(record, key)
        return engine.law_full_text(record)

    @staticmethod
    def flat(text):
        return re.sub(r"\s+", "", text)

    def test_two_laws_are_verified(self):
        laws = {law["short"]: law for law in self.data["laws"]}
        self.assertIn("가맹사업법", laws)
        self.assertIn("가맹사업법 시행령", laws)
        act = laws["가맹사업법"]
        self.assertEqual(act["ministery"] if "ministery" in act else act["ministry"], "공정거래위원회")
        self.assertTrue(act["mst"].isdigit())
        self.assertRegex(act["effective_on"], r"^\d{8}$")

    def test_no_oc_key_in_file(self):
        raw = json.dumps(self.data, ensure_ascii=False)
        self.assertNotIn("OC=", raw)
        self.assertNotIn("pil" + "otage", raw)

    def test_article_7_provides_14_day_cooling_off(self):
        text = self.text_of("가맹사업법:제7조")
        self.assertIn("14일", text)
        self.assertIn("정보공개서", text)
        self.assertIn("가맹금을 수령", text)
        self.assertIn("가맹계약을 체결", text)
        self.assertIn("7일", text)  # 자문 시 단축

    def test_article_6_5_requires_escrow(self):
        text = self.text_of("가맹사업법:제6조의5")
        self.assertIn("예치", text)
        self.assertIn("예치기관", text)
        self.assertIn("가맹점사업자피해보상보험계약", text)

    def test_article_9_requires_written_revenue_and_estimate(self):
        text = self.text_of("가맹사업법:제9조")
        self.assertIn("서면", text)
        self.assertIn("예상매출액", text)
        self.assertIn("산정서", text)
        self.assertIn("허위", text)

    def test_article_11_contract_document_and_14_days(self):
        text = self.text_of("가맹사업법:제11조")
        self.assertIn("가맹계약서", text)
        self.assertIn("14일", text)
        self.assertIn("영업지역의 설정", text)

    def test_article_12_and_annex_forced_purchase(self):
        text = self.text_of("가맹사업법:제12조")
        self.assertIn("불공정거래행위", text)
        annex = self.text_of("가맹사업법 시행령:불공정거래행위의 유형 또는 기준(제13조제1항관련)")
        self.assertIn("구입강제", annex)
        self.assertIn("경영에필요한양을넘는", self.flat(annex))
        self.assertIn("판매목표 강제", annex)
        self.assertIn("과중한 위약금", annex)

    def test_article_11_item_12_requires_supply_price_method(self):
        text = self.text_of("가맹사업법:제11조")
        self.assertIn("공급 가격 산정방식", text)
        self.assertIn("거래할 것을 강제할 경우", text)

    def test_disclosure_annex_defines_margin_payment_and_essential_items(self):
        annex = self.flat(self.text_of("가맹사업법 시행령:정보공개서의 기재사항(제4조제1항 관련)"))
        for word in ("차액가맹금", "필수품목구입대금추정액", "주요품목별직전사업연도공급가격",
                     "가격을정하여이에따르도록권장", "거래할것을강제또는권장"):
            self.assertIn(word, annex, word)

    def test_unfair_practice_annex_has_price_fixing_and_counterparty_restraint(self):
        annex = self.flat(self.text_of("가맹사업법 시행령:불공정거래행위의 유형 또는 기준(제13조제1항관련)"))
        for word in ("가.가격의구속", "나.거래상대방의구속", "사전협의를통해판매가격을강요하는행위",
                     "가.구입강제", "경영에필요한양을넘는"):
            self.assertIn(word, annex, word)

    def test_article_12_2_to_12_6(self):
        self.assertIn("점포환경개선", self.text_of("가맹사업법:제12조의2"))
        self.assertIn("영업시간", self.text_of("가맹사업법:제12조의3"))
        territory = self.text_of("가맹사업법:제12조의4")
        self.assertIn("영업지역", territory)
        self.assertIn("직영점이나 가맹점", territory)
        self.assertIn("보복조치", self.text_of("가맹사업법:제12조의5"))
        self.assertIn("광고", self.text_of("가맹사업법:제12조의6"))

    def test_article_13_renewal_and_14_termination(self):
        renewal = self.text_of("가맹사업법:제13조")
        self.assertIn("180일", renewal)
        self.assertIn("10년", renewal)
        termination = self.text_of("가맹사업법:제14조")
        self.assertIn("2개월 이상의 유예기간", termination)
        self.assertIn("2회 이상 통지", termination)
        self.assertIn("효력이 없다", termination)

    def test_decree_defines_escrow_institutions(self):
        text = self.text_of("가맹사업법 시행령:제5조의8")
        for word in ("은행", "체신관서", "보험회사", "신탁업자"):
            self.assertIn(word, text)
    def test_paragraph_structure_is_preserved(self):
        record = self.articles["가맹사업법:제7조"]
        paragraphs = record.get("paragraphs") or []
        self.assertGreaterEqual(len(paragraphs), 4)
        third = [row for row in paragraphs if row.get("no") == "③"]
        self.assertTrue(third)
        self.assertTrue(third[0].get("items"))
        numbers = [item.get("no") for item in third[0]["items"]]
        self.assertIn("1.", numbers)
        self.assertIn("2.", numbers)

    def test_source_urls_are_law_go_kr(self):
        for key in ("가맹사업법:제7조", "가맹사업법:제9조"):
            record = self.articles[key]
            self.assertTrue(record["source_url"].startswith("https://www.law.go.kr/"))

    def test_all_cited_articles_have_effective_dates(self):
        for key, record in self.articles.items():
            if key in ("가맹사업법:제8조",):
                continue  # 삭제 조문
            self.assertRegex(str(record.get("effective_on"),), r"^\d{8}$", key)


if __name__ == "__main__":
    unittest.main(verbosity=2)
