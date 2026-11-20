"""계약서·특약 문구 스캔 테스트 — 규칙·인용·0건 단정 금지·법 조문 대조.

핵심 원칙 세 가지를 테스트로 고정합니다.
1. 같은 문구는 항상 같은 규칙에 걸린다(결정적 규칙 엔진).
2. 인용문은 사용자가 넣은 글자 그대로다(우리가 문장을 만들지 않는다).
3. 잡히는 문구가 0건이어도 '안전·문제없음'을 쓰지 않고, 고정 문장을 항상 붙인다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
PROJECT = os.path.dirname(SRC)
sys.path.insert(0, SRC)

from franchise_kr import api, engine, mcp, models, web_ui  # noqa: E402

ANNEX = engine.ANNEX_UNFAIR

# 규칙 1건 ↔ 실제로 그 규칙에 걸려야 하는 특약 문구
SAMPLES = {
    "purchase_forced": (
        "제3조(인테리어) 가맹점사업자는 인테리어와 간판 시공을 당사가 지정한 업체를 통해서만 "
        "하여야 하며, 다른 업체를 이용할 수 없다."
    ),
    "excessive_penalty": (
        "제12조(중도해지) 가맹점사업자가 계약을 중도해지하는 경우 잔여 계약기간의 로열티 "
        "전액을 위약금으로 지급한다."
    ),
    "unilateral_termination": (
        "제15조(계약해지) 가맹점사업자가 이 계약을 위반한 경우 당사는 최고 없이 즉시 해지할 수 "
        "있으며, 별도의 유예기간은 두지 않는다."
    ),
    "territory_infringement": (
        "제9조(영업지역) 본사는 영업지역을 보장하지 않으며, 본사의 판단에 따라 인근 출점이 가능하다."
    ),
    "cooling_off_waiver": (
        "제5조(숙고기간) 가맹희망자는 정보공개서를 받은 당일 계약을 체결하며, 숙고기간은 "
        "적용하지 않는다."
    ),
    "payment_to_hq": (
        "제6조(가맹금) 가맹금과 보증금은 당사 계좌로 직접 입금한다."
    ),
    "ad_cost_unilateral": (
        "제11조(광고) 본사가 실시한 광고 비용을 가맹점에게 청구하며, 사전 동의 없이 판촉비를 "
        "부과할 수 있다."
    ),
    "revenue_guarantee": (
        "제7조(매출) 월 순수익 3,000만원 이상을 보장하며, 적자 발생 시 본사가 보전한다."
    ),
    "hours_bound": (
        "제10조(영업시간) 영업시간은 본사가 정한 대로 준수하여야 하며, 영업시간을 임의로 변경할 "
        "수 없다."
    ),
    "renewal_restraint": (
        "제14조(계약갱신) 본사는 갱신을 거절할 수 있다. 계약 종료 후 2년간 반경 1km 이내 동일 "
        "업종 창업을 금지한다."
    ),
}

# 규칙에 걸리면 안 되는 정상 문구 — 오탐 0건을 지킨다.
NORMAL_CLAUSES = [
    ("숙고기간 준수", "가맹희망자는 정보공개서를 받은 날부터 14일이 지난 후 계약을 체결한다."),
    ("예치", "가맹금은 예치기관에 예치한 뒤 지급하고, 예치 사실을 확인한다."),
    ("영업지역 기재", "본사는 가맹점사업자의 영업지역을 설정하여 가맹계약서에 이를 기재한다."),
    ("인테리어 자유", "인테리어 업체는 가맹점사업자가 비교견적 후 자유롭게 선정한다."),
    ("해지 절차", "본부는 2개월 이상의 유예기간을 두고 위반 사실을 서면으로 2회 이상 통지한 뒤 해지한다."),
    ("손해 범위 위약금", "위약금은 실제 발생한 손해의 범위에서 정한다."),
    ("광고 분담", "광고비는 본사와 가맹점이 절반씩 분담한다."),
    ("매출 서면", "매출 정보는 서면으로 제공하고 산출근거를 열람할 수 있게 한다."),
    ("즉시 해지 아님", "본사는 계약을 즉시 해지하지 않고 2개월 이상의 유예기간을 둔다."),
    ("갱신 10년 한도", "계약갱신은 전체 가맹계약기간이 10년을 초과하지 않는 범위에서 요구할 수 있다."),
    ("경업 한정", "경업금지는 계약기간 중 동일 상권에 한한다."),
    ("지정 없음", "본사는 특정 업체를 지정하지 않으며, 가맹점사업자가 자유롭게 선정한다."),
    ("판매목표 강요 없음", "가맹본부는 가맹점사업자에게 판매목표를 강요하지 않는다."),
    ("필수품목 없음", "필수품목은 없으며, 원부자재는 자유롭게 구매할 수 있다."),
    ("언제든지 상담", "본사는 언제든지 상담에 응한다."),
    ("가맹비 예치", "가맹금은 예치기관에 예치하고 영업개시 후 지급을 요청한다."),
]

CLEAN_CONTRACT = "\n".join(
    "제%d조 %s" % (index + 1, text) for index, (_name, text) in enumerate(NORMAL_CLAUSES)
)


def flat(text) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def scan(text) -> dict:
    return engine.scan_contract_text({"text": text})


class RuleTableTest(unittest.TestCase):
    def test_ten_rules_cover_brief_categories(self):
        self.assertEqual(len(engine.CONTRACT_RULES), 10)
        categories = {rule["category"] for rule in engine.CONTRACT_RULES}
        for category in ("purchase", "penalty", "termination", "territory", "cooling_off",
                         "payment", "advertising", "revenue", "hours", "renewal"):
            self.assertIn(category, categories, category)

    def test_rule_ids_unique_and_shaped(self):
        ids = [rule["id"] for rule in engine.CONTRACT_RULES]
        self.assertEqual(len(ids), len(set(ids)))
        for rule in engine.CONTRACT_RULES:
            for field in ("title_ko", "why_ko", "fix_ko", "ask_ko", "severity"):
                self.assertTrue(str(rule[field]).strip(), f"{rule['id']}:{field}")
            self.assertIn(rule["severity"], models.SEVERITY_ORDER, rule["id"])
            self.assertIn(rule["category"], models.CATEGORY_LABELS_KO, rule["id"])
            self.assertTrue(rule["patterns"], rule["id"])

    def test_fix_text_is_a_request_not_a_verdict(self):
        for rule in engine.CONTRACT_RULES:
            self.assertIn("요청", rule["fix_ko"], rule["id"])
            self.assertNotIn("위법", rule["fix_ko"], rule["id"])

    def test_every_law_ref_is_in_verified_file(self):
        for rule in engine.CONTRACT_RULES:
            self.assertTrue(rule["law_refs"], rule["id"])
            for key in rule["law_refs"]:
                self.assertIsNotNone(engine.law_record(key), f"{rule['id']}: {key}")

    def test_every_anchor_exists_in_verified_article(self):
        for rule in engine.CONTRACT_RULES:
            for key, anchor in (rule.get("anchors") or {}).items():
                record = engine.law_record(key)
                self.assertIsNotNone(record, f"{rule['id']}: {key}")
                text = re.sub(r"\s+", " ", engine.law_full_text(record))
                self.assertIn(anchor, text, f"{rule['id']}: {key} / {anchor}")

    def test_annex_two_is_cited_for_purchase_and_penalty(self):
        purchase = engine.CONTRACT_RULE_INDEX["purchase_forced"]
        penalty = engine.CONTRACT_RULE_INDEX["excessive_penalty"]
        self.assertIn(ANNEX, purchase["law_refs"])
        self.assertIn(ANNEX, penalty["law_refs"])
        self.assertIn("가맹사업법:제14조",
                      engine.CONTRACT_RULE_INDEX["unilateral_termination"]["law_refs"])
        self.assertIn("가맹사업법:제12조의4",
                      engine.CONTRACT_RULE_INDEX["territory_infringement"]["law_refs"])
        self.assertIn("가맹사업법:제7조",
                      engine.CONTRACT_RULE_INDEX["cooling_off_waiver"]["law_refs"])
        self.assertIn("가맹사업법:제6조의5", engine.CONTRACT_RULE_INDEX["payment_to_hq"]["law_refs"])
        self.assertIn("가맹사업법:제12조의6",
                      engine.CONTRACT_RULE_INDEX["ad_cost_unilateral"]["law_refs"])
        self.assertIn("가맹사업법:제9조", engine.CONTRACT_RULE_INDEX["revenue_guarantee"]["law_refs"])
        self.assertIn("가맹사업법:제12조의3", engine.CONTRACT_RULE_INDEX["hours_bound"]["law_refs"])
        self.assertIn("가맹사업법:제13조", engine.CONTRACT_RULE_INDEX["renewal_restraint"]["law_refs"])


class DetectionTest(unittest.TestCase):
    def test_each_sample_hits_its_rule(self):
        for rule_id, text in SAMPLES.items():
            with self.subTest(rule=rule_id):
                result = scan(text)
                self.assertEqual(result["verdict"]["code"], models.SCAN_VERDICT_FLAGGED)
                hit_ids = {row["rule_id"] for row in result["findings"]}
                self.assertIn(rule_id, hit_ids)
                self.assertGreaterEqual(result["counts"]["flagged"], 1)

    def test_samples_do_not_hit_unrelated_rules(self):
        for rule_id, text in SAMPLES.items():
            with self.subTest(rule=rule_id):
                hit_ids = {row["rule_id"] for row in scan(text)["findings"]}
                self.assertEqual(hit_ids, {rule_id})

    def test_normal_clauses_are_not_flagged(self):
        for name, text in NORMAL_CLAUSES:
            with self.subTest(clause=name):
                self.assertEqual(scan(text)["findings"], [], name)

    def test_clean_contract_has_zero_findings(self):
        result = scan(CLEAN_CONTRACT)
        self.assertEqual(result["counts"]["flagged"], 0)
        self.assertEqual(result["verdict"]["code"], models.SCAN_VERDICT_NO_MATCH)

    def test_purchase_rule_catches_two_separate_clauses(self):
        text = (
            "제3조 가맹점사업자는 인테리어를 당사가 지정한 업체를 통해서만 시공한다.\n"
            "제4조 원부자재와 포장재는 당사가 공급하는 물품만 사용하여야 한다."
        )
        result = scan(text)
        self.assertGreaterEqual(result["counts"]["flagged"], 2)
        for row in result["findings"]:
            self.assertEqual(row["rule_id"], "purchase_forced")
            self.assertEqual(row["severity"], models.SEVERITY_HIGH)

    def test_penalty_ratio_guard(self):
        high = scan("위약금은 총투자금의 40%로 한다.")
        low = scan("위약금은 총투자금의 10%로 한다.")
        self.assertTrue(any(row["rule_id"] == "excessive_penalty" for row in high["findings"]))
        self.assertFalse(any(row["rule_id"] == "excessive_penalty" for row in low["findings"]))

    def test_deposit_confiscation_detected(self):
        result = scan("가맹보증금은 계약 종료 시 전액 몰수하며 반환하지 않는다.")
        self.assertEqual([row["rule_id"] for row in result["findings"]], ["excessive_penalty"])

    def test_sales_target_and_mandatory_items(self):
        for text in ("필수품목은 매월 본사가 정한 수량 이상 구매하여야 한다.",
                     "판매목표를 달성하지 못하면 계약을 갱신하지 않는다."):
            result = scan(text)
            self.assertIn("purchase_forced", {row["rule_id"] for row in result["findings"]}, text)

    def test_anytime_termination(self):
        result = scan("본사는 언제든지 계약을 해지할 수 있다.")
        self.assertIn("unilateral_termination",
                      {row["rule_id"] for row in result["findings"]})

    def test_negation_is_not_counted(self):
        for text in (
            "위약금은 실제 손해를 넘지 않는다. 위약금을 부과하지 않는다.",
            "본사는 계약을 즉시 해지하지 않는다.",
            "본사는 업체를 지정하지 않으며 자유롭게 선정한다.",
        ):
            self.assertEqual(scan(text)["findings"], [], text)

    def test_spacing_and_line_breaks_are_absorbed(self):
        text = "가맹금과\n보증금은   당사   계좌로 직접 입금한다."
        result = scan(text)
        self.assertEqual([row["rule_id"] for row in result["findings"]], ["payment_to_hq"])


class QuoteTest(unittest.TestCase):
    def test_quote_comes_from_the_input(self):
        for rule_id, text in SAMPLES.items():
            with self.subTest(rule=rule_id):
                row = [item for item in scan(text)["findings"] if item["rule_id"] == rule_id][0]
                quote = flat(row["matched_text_ko"]).strip("…")
                self.assertIn(quote, flat(text))
                self.assertIn(flat(row["matched_exact_ko"]), flat(row["matched_text_ko"]))

    def test_quote_never_invents_words(self):
        text = SAMPLES["unilateral_termination"]
        row = scan(text)["findings"][0]
        for word in ("유예기간", "최고", "즉시"):
            self.assertIn(word, row["matched_exact_ko"] + row["matched_text_ko"])

    def test_same_sentence_is_shown_once_per_rule(self):
        text = (
            "가맹점사업자가 위반한 경우 당사는 최고 없이 즉시 해지할 수 있으며 "
            "별도의 유예기간은 두지 않는다."
        )
        rows = [row for row in scan(text)["findings"] if row["rule_id"] == "unilateral_termination"]
        self.assertEqual(len(rows), 1, [row["matched_exact_ko"] for row in rows])


class NotAClearanceTest(unittest.TestCase):
    def test_fixed_notice_is_exact(self):
        expected = (
            "제시된 패턴에서 잡히지 않았을 뿐, 다른 특약이나 정보공개서 불일치가 있을 수 있어 "
            "원문 전체와 가맹거래사 확인이 필요합니다."
        )
        self.assertEqual(engine.SCAN_NOT_A_CLEARANCE_KO, expected)

    def test_notice_present_when_zero_and_when_flagged(self):
        for text in (CLEAN_CONTRACT, SAMPLES["purchase_forced"], "짧음"):
            self.assertEqual(scan(text)["not_a_clearance_ko"], engine.SCAN_NOT_A_CLEARANCE_KO)

    def test_zero_result_does_not_claim_safety(self):
        result = scan(CLEAN_CONTRACT)
        prose = " ".join([
            result["summary_ko"], result["verdict"]["label_ko"],
            result["verdict"]["one_line_ko"],
            " ".join(row["result_ko"] for row in result["checks_ko"]),
            " ".join(result["questions_ko"]),
            " ".join(str(row.get("detail_ko", "")) for row in result["next_steps"]),
        ])
        for phrase in ("안전합니다", "안전해요", "문제없습니다", "문제없음", "위법입니다",
                       "합법입니다", "무조건"):
            self.assertNotIn(phrase, prose, phrase)
        self.assertIn("원문 전체", result["summary_ko"] + result["not_a_clearance_ko"])

    def test_verdict_labels_do_not_claim_safety(self):
        for code, label in models.SCAN_VERDICT_LABELS_KO.items():
            self.assertNotIn("안전", label, code)
            self.assertNotIn("문제없", label, code)

    def test_checks_list_covers_every_rule(self):
        result = scan(SAMPLES["hours_bound"])
        self.assertEqual(len(result["checks_ko"]), len(engine.CONTRACT_RULES))
        ids = [row["rule_id"] for row in result["checks_ko"]]
        self.assertEqual(ids, [rule["id"] for rule in engine.CONTRACT_RULES])
        matched = [row for row in result["checks_ko"] if row["matched_count"]]
        self.assertTrue(matched)
        for row in result["checks_ko"]:
            self.assertTrue(row["result_ko"])


class PayloadTest(unittest.TestCase):
    def test_payload_shape(self):
        result = scan(SAMPLES["revenue_guarantee"])
        for key in ("scanned", "verdict", "counts", "summary_ko", "findings", "checks_ko",
                    "not_a_clearance_ko", "questions_ko", "request_edits_ko", "law_basis",
                    "law_basis_scope_ko", "next_steps", "disclaimer_ko", "scope_limits_ko"):
            self.assertIn(key, result, key)
        self.assertTrue(result["law_basis"])
        for row in result["law_basis"]:
            self.assertTrue(row["excerpt_ko"])
            self.assertTrue(str(row["source_url"]).startswith("https://www.law.go.kr/"))
        for row in result["findings"]:
            self.assertEqual(len(row["law_refs_ko"]), len(row["law_refs"]))
            self.assertTrue(all(row["law_refs_ko"]))

    def test_counts_add_up(self):
        result = scan(SAMPLES["payment_to_hq"] + "\n" + SAMPLES["purchase_forced"])
        findings = result["findings"]
        counts = result["counts"]
        self.assertEqual(counts["flagged"], len(findings))
        self.assertEqual(counts["high"] + counts["medium"] + counts["low"], len(findings))
        self.assertEqual(counts["rules_matched"],
                         len({row["rule_id"] for row in findings}))

    def test_findings_sorted_by_severity(self):
        result = scan(SAMPLES["purchase_forced"] + "\n" + SAMPLES["ad_cost_unilateral"])
        order = {severity: index for index, severity in enumerate(models.SEVERITY_ORDER)}
        values = [order[row["severity"]] for row in result["findings"]]
        self.assertEqual(values, sorted(values))

    def test_request_edits_one_per_rule(self):
        text = SAMPLES["purchase_forced"] + "\n" + (
            "제4조 원부자재와 포장재는 당사가 공급하는 물품만 사용하여야 한다.")
        result = scan(text)
        ids = [row["rule_id"] for row in result["request_edits_ko"]]
        self.assertEqual(len(ids), len(set(ids)))
        for row in result["request_edits_ko"]:
            self.assertIn("요청", row["request_ko"])

    def test_empty_text_raises(self):
        for args in ({}, {"text": "   "}, {"text": None}, []):
            with self.assertRaises(ValueError):
                engine.scan_contract_text(args)

    def test_short_text_asks_for_more(self):
        result = scan("해지")
        self.assertEqual(result["verdict"]["code"], models.SCAN_VERDICT_TEXT_NEEDED)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["not_a_clearance_ko"], engine.SCAN_NOT_A_CLEARANCE_KO)

    def test_aliases_are_accepted(self):
        text = SAMPLES["territory_infringement"]
        for key in ("contract_text", "clause_text", "document_text", "content", "특약"):
            result = engine.scan_contract_text({key: text})
            self.assertEqual(result["scanned"]["source_field"], key)
            self.assertTrue(result["findings"], key)
        lines = engine.scan_contract_text({"text": text.split(". ")})
        self.assertTrue(lines["findings"])
        plain = engine.scan_contract_text(text)
        self.assertEqual(plain["scanned"]["source_field"], "text")
        self.assertTrue(plain["findings"])

    def test_long_text_is_truncated(self):
        text = "가맹금은 당사 계좌로 직접 입금한다. " * 2000
        result = scan(text)
        self.assertTrue(result["scanned"]["truncated"])
        self.assertEqual(result["scanned"]["chars"], engine.SCAN_MAX_CHARS)
        self.assertTrue(result["findings"])

    def test_repeated_clause_is_capped(self):
        # 같은 문구를 반복하면 인용이 한 번만 남고, 표현이 다르면 규칙별 상한(3건)이 걸린다.
        same = scan("\n".join([SAMPLES["payment_to_hq"]] * 12))
        self.assertEqual(len([row for row in same["findings"]
                             if row["rule_id"] == "payment_to_hq"]), 1)
        varied = "\n".join([
            "가맹금은 당사 계좌로 직접 입금한다.",
            "가맹비는 본사 계좌로 송금한다.",
            "보증금은 회사 명의에 납부한다.",
            "교육비는 당사 계좌로 지급한다.",
            "추가 가맹금은 본사 계좌에 입금한다.",
        ])
        result = scan(varied)
        rows = [row for row in result["findings"] if row["rule_id"] == "payment_to_hq"]
        self.assertEqual(len(rows), engine.SCAN_MAX_FINDINGS_PER_RULE)
        self.assertGreaterEqual(result["counts"]["more_matches"], 1)

    def test_disclaimer_remains(self):
        for text in (CLEAN_CONTRACT, SAMPLES["purchase_forced"]):
            result = scan(text)
            self.assertEqual(result["disclaimer_ko"], models.DISCLAIMER_KO)
            self.assertIn("확정 판정이 아닙니다", result["disclaimer_ko"])
            self.assertTrue(any("스캔" in limit for limit in result["scope_limits_ko"]))


class ApiTest(unittest.TestCase):
    def test_tool_registered_with_schema(self):
        definition = api.TOOL_INDEX.get("scan_contract_text")
        self.assertIsNotNone(definition)
        self.assertEqual(definition["input_schema"]["required"], ["text"])
        self.assertIn("보장", definition["description_ko"])
        self.assertIn("not_a_clearance_ko", definition["description_ko"])

    def test_call_tool_envelope(self):
        result = api.call_tool("scan_contract_text", {"text": SAMPLES["payment_to_hq"]})
        self.assertTrue(result["ok"])
        self.assertEqual(result["tool"], "scan_contract_text")
        payload = result["result"]
        self.assertEqual(payload["verdict"]["code"], models.SCAN_VERDICT_FLAGGED)
        self.assertIn("meta", payload)
        self.assertEqual(payload["meta"]["service"], "FRNC")

    def test_call_tool_missing_text_is_invalid_argument(self):
        result = api.call_tool("scan_contract_text", {})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_argument")

    def test_text_summary(self):
        flagged = api.call_tool("scan_contract_text", {"text": SAMPLES["payment_to_hq"]})
        summary = api.text_summary(flagged)
        self.assertIn("확인이 필요한 문구 있음", summary)
        self.assertIn(engine.SCAN_NOT_A_CLEARANCE_KO, summary)
        clean = api.call_tool("scan_contract_text", {"text": CLEAN_CONTRACT})
        self.assertIn("잡힌 문구 없음", api.text_summary(clean))

    def test_mcp_tools_call(self):
        out = mcp.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                          "params": {"name": "scan_contract_text",
                                     "arguments": {"text": SAMPLES["hours_bound"]}}})
        self.assertFalse(out["result"]["isError"])
        structured = out["result"]["structuredContent"]["result"]
        self.assertEqual(structured["verdict"]["code"], models.SCAN_VERDICT_FLAGGED)
        self.assertIn(models.SCAN_VERDICT_LABELS_KO[models.SCAN_VERDICT_FLAGGED],
                      out["result"]["content"][0]["text"])
        self.assertIn(engine.SCAN_NOT_A_CLEARANCE_KO, out["result"]["content"][0]["text"])

    def test_service_meta_documents_rules(self):
        payload = api.call_tool("get_service_meta", {})["result"]
        block = payload["contract_scan"]
        self.assertEqual(block["tool"], "scan_contract_text")
        self.assertEqual(len(block["rules"]), len(engine.CONTRACT_RULES))
        self.assertEqual(block["not_a_clearance_ko"], engine.SCAN_NOT_A_CLEARANCE_KO)
        codes = [row["code"] for row in block["verdicts"]]
        self.assertEqual(tuple(codes), models.SCAN_VERDICT_ORDER)


class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = web_ui.render_page({"data_state": "sample"})

    def test_scan_card_and_three_samples(self):
        self.assertIn('id="scan-card"', self.html)
        self.assertIn("특약·계약서 문구 1초 스캔", self.html)
        self.assertEqual(len(web_ui.SCAN_SAMPLES), 3)
        for sample in web_ui.SCAN_SAMPLES:
            self.assertIn(f'data-sample="{sample["id"]}"', self.html)
            self.assertIn(sample["title"], self.html)
        self.assertEqual([row["id"] for row in web_ui.SCAN_SAMPLES],
                         ["purchase", "penalty", "termination"])

    def test_samples_are_actively_flagged(self):
        for sample in web_ui.SCAN_SAMPLES:
            result = scan(sample["text"])
            self.assertEqual(result["verdict"]["code"], models.SCAN_VERDICT_FLAGGED,
                             sample["id"])
            self.assertTrue(result["findings"], sample["id"])

    def test_scan_controls_exist(self):
        for marker in ('id="scan-text"', 'id="scan-run"', 'id="scan-clear"', 'id="scan-count"',
                       'id="scan-result"', 'id="scan-status"',
                       "/v1/tools/scan_contract_text"):
            self.assertIn(marker, self.html, marker)

    def test_scan_text_has_no_name_attribute(self):
        # 스캔 입력은 판정 폼(collect)과 섞이지 않아야 한다.
        match = re.search(r"<textarea[^>]*id=\"scan-text\"[^>]*>", self.html)
        self.assertIsNotNone(match)
        self.assertNotIn("name=", match.group(0))

    def test_home_states_scan_is_not_a_clearance(self):
        self.assertIn("'안전'을 뜻하지 않습니다", self.html)
        self.assertIn("원문 전체", self.html)

    def test_scan_samples_are_embedded_for_one_click(self):
        script = self.html.split("<script>", 1)[1].split("</script>", 1)[0]
        self.assertIn("SCAN_SAMPLES_TEXT", script)
        for sample in web_ui.SCAN_SAMPLES:
            self.assertIn(sample["text"].split("\n")[0][:20], script)

    def test_no_scan_color_override(self):
        for value in re.findall(r'style="([^"]*)"', self.html):
            self.assertNotIn("color:", value.replace(" ", ""))
            self.assertNotIn("background:", value.replace(" ", ""))


class UsagePrivacyTest(unittest.TestCase):
    def test_scan_text_is_not_stored(self):
        """붙여넣은 특약 문구는 통계에도 남기지 않는다 — 툴 이름 횟수만 센다."""
        from franchise_kr import usage
        from franchise_kr.store import Store

        store = Store(":memory:")
        try:
            secret = "가맹금은 당사 계좌로 직접 입금한다. 문의 010-0000-0000"
            api.call_tool("scan_contract_text", {"text": secret}, store=store)
            dumped = json.dumps(usage.statistics(store, days=1), ensure_ascii=False)
            self.assertNotIn("010-0000", dumped)
            self.assertNotIn("당사 계좌", dumped)
            self.assertIn("scan_contract_text", dumped)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
