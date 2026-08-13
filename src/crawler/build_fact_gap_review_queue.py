"""Build a small, source-verified fact review queue for under-covered domains.

Candidates in this queue are intentionally separate from ``kdic-core-fact-proposals``.
They are literal-source verified, but a domain reviewer must decide whether each is
stable and useful enough to be promoted into the canonical fact set.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

try:
    from .build_ontology_map import ROOT
except ImportError:  # direct script execution
    from build_ontology_map import ROOT


MAP_PATH = ROOT / "ontology" / "kdic-document-concept-map.json"
CANONICAL_PATH = ROOT / "ontology" / "kdic-canonical-ontology-draft.json"
CORPUS_PATH = ROOT / "data" / "corpus.jsonl"
OUTPUT_PATH = ROOT / "ontology" / "kdic-fact-gap-review-queue.json"
REVIEW_PATH = ROOT / "ontology" / "review" / "FACT_GAP_REVIEW_QUEUE.md"


FACT_CANDIDATES = (
    (
        "candidate_fact:deposit_insurance_claim_right_expiry",
        "예금보험금 청구권 행사기한 · 지급개시일로부터 5년",
        "concept:deposit_insurance_payment",
        "claim_right_expires_after",
        {"type": "Duration", "value": 5, "unit": "year", "anchor": "deposit_insurance_payment_start_date", "condition": "if_not_exercised"},
        "ms_expln",
        "예금자등의 예금보험금청구권은 「예금자보호법」제31조제7항의 규정에 의하여 예금보험금지급 개시일로부터 5년간 행사하지 아니하면 시효로 인하여 소멸하기 때문에 예금보험금이 지급되지 않습니다.",
        "법정 시효의 예외·중단 사유가 있는지 도메인 담당자가 확인한다.",
    ),
    (
        "candidate_fact:deposit_insurance_online_application_exclusion",
        "예금보험금 인터넷 신청 제외 대상 · 미성년자 및 법인",
        "concept:deposit_insurance_payment",
        "online_application_excludes",
        {"type": "ActorCategorySet", "values": ["minor", "corporation"]},
        "ms_expln",
        "공사 홈페이지 접속을 통한 인터넷 신청은 미성년자 및 법인의 경우에는 불가하오니 이점 참고하시기 바랍니다.",
        "인터넷 신청만의 제한인지, 대리·방문 신청의 제한으로 오해되지 않는지 검토한다.",
    ),
    (
        "candidate_fact:deposit_insurance_typical_payment_timing",
        "예금보험금 신청 후 통상 입금 시점 · 다음 영업일 이내",
        "procedure:deposit_insurance_payment_application",
        "has_typical_processing_time",
        {"type": "Duration", "value": 1, "unit": "business_day", "qualifier": "typically", "anchor": "application"},
        "ms_aply_proc",
        "통상 익영업일내에 예금보험금이 입금 완료됨",
        "‘통상’이라는 비보장 표현을 반드시 보존하고, 지급보류·추가 확인 사례에는 적용하지 않는다.",
    ),
    (
        "candidate_fact:unclaimed_funds_definition",
        "고객 미수령금의 정의 · 부실화 금융회사 예금자 등이 찾아가지 않은 금액",
        "service:unclaimed_funds",
        "has_definition",
        {"type": "Definition", "meaning": "amount_not_collected_by_depositors_of_failed_financial_institutions"},
        "uc_gudn",
        "부실화된 금융회사의 예금자 등이 찾아가지 아니한 금액을 말합니다.",
        "서비스 범위의 정의로 적절한지, 다른 미수령금 범주가 포함되는지 검토한다.",
    ),
    (
        "candidate_fact:unclaimed_funds_unified_application_start",
        "미수령금 전국 지급대행점 통합 신청 시작 · 2016년 10월",
        "service:unclaimed_funds",
        "unified_application_available_from",
        {"type": "YearMonth", "value": "2016-10", "scope": "nationwide_any_payment_agency"},
        "uc_gudn",
        "미수령금 종류별·부실금융회사별 구분없이 ‘16.10월부터 전국 지급대행점 어디에서든 미수령금을 통합 신청할 수 있도록 하였습니다.",
        "원문 표기 ‘16.10월을 2016-10으로 해석한 것이 맞는지와 현재 적용 여부를 검토한다.",
    ),
    (
        "candidate_fact:unclaimed_funds_categories",
        "고객 미수령금 주요 종류 · 예금보험금·파산배당금·개산지급금 정산금",
        "service:unclaimed_funds",
        "has_fund_categories",
        {"type": "CategorySet", "values": ["deposit_insurance_payment", "bankruptcy_dividend", "provisional_payment_settlement"]},
        "uc_gudn",
        "고객 미수령금의 종류\n예금보험금\n예금보험에 가입한 금융회사가 예금의 지급정지, 영업 인·허가의 취소 등 보험사고로 인하여 고객의 예금을 지급할 수 없을 때 공사가 해당 금융회사를 대신하여 지급하는 보험금을 말합니다.\n파산배당금\n금융회사가 파산하는 경우 남은 자산을 현금화하여 채권자들에게 그 채권액 비율대로 배당하는 금액을 말합니다.\n개산지급금 정산금\n파산배당금 등으로 회수한 금액에서 소요비용을 공제한 금액이 수령한 개산지급금을 초과하는 때에 그 초과금액을 예금자에게 추가로 지급하는데, 이를 개산지급금 정산금이라고 합니다.",
        "‘주요 종류’가 완전한 목록인지와 카테고리 명칭을 사용자 답변에 그대로 쓸지 검토한다.",
    ),
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_corpus(path: Path = CORPUS_PATH) -> dict[str, dict]:
    with path.open(encoding="utf-8") as handle:
        return {record["page_id"]: record for line in handle if (record := json.loads(line))}


def build_queue(mapping: dict, canonical: dict, corpus: dict[str, dict]) -> dict:
    if mapping["source"] != canonical["source"]:
        raise ValueError("canonical draft must use the current document map")
    document_map = {item["page_id"]: item for item in mapping["document_mappings"]}
    subjects = {item["id"] for item in canonical["entities"]} | {item["id"] for item in canonical["base_services"]}
    service_by_id = {item["id"]: item["business_domain"] for item in mapping["services"]}
    entity_service_ids = {item["id"]: item["parent_service_ids"] for item in canonical["entities"]}
    candidates = []
    seen_ids = set()
    for candidate_id, label, subject_id, predicate, value, page_id, quote, review_focus in FACT_CANDIDATES:
        if candidate_id in seen_ids:
            raise ValueError(f"duplicate candidate ID: {candidate_id}")
        seen_ids.add(candidate_id)
        if subject_id not in subjects:
            raise ValueError(f"unknown candidate subject: {subject_id}")
        if page_id not in document_map or quote not in corpus[page_id]["text"]:
            raise ValueError(f"literal source quote not found: {candidate_id}")
        service_ids = entity_service_ids.get(subject_id, [subject_id])
        business_domains = sorted({service_by_id[service_id] for service_id in service_ids})
        candidates.append({
            "id": candidate_id,
            "label": label,
            "subject_id": subject_id,
            "business_domains": business_domains,
            "predicate": predicate,
            "object": value,
            "review_status": "source_verified_candidate_pending_domain_review",
            "review_focus": review_focus,
            "evidence": {
                "page_id": page_id,
                "source_url": corpus[page_id]["source_url"],
                "content_sha256": document_map[page_id]["content_sha256"],
                "quote": quote,
            },
        })
    domain_counts = Counter(domain for candidate in candidates for domain in candidate["business_domains"])
    return {
        "schema_version": "1.0.0",
        "status": "fact_gap_candidates_source_verified_pending_domain_review",
        "production_impact": "none",
        "source": mapping["source"],
        "policy": {
            "literal_source_quote_required": True,
            "automatic_core_fact_promotion": False,
            "automatic_runtime_promotion": False,
            "heldout_testset_used": False,
            "purpose": "close fact-coverage gaps without changing approved facts",
        },
        "summary": {
            "candidate_count": len(candidates),
            "business_domain_candidate_counts": dict(sorted(domain_counts.items())),
            "targeted_zero_core_fact_domains": ["고객 미수령금 신청", "예금보험금 안내"],
        },
        "candidates": candidates,
    }


def build_review_markdown(queue: dict) -> str:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for candidate in queue["candidates"]:
        for domain in candidate["business_domains"]:
            grouped[domain].append(candidate)
    lines = [
        "# Fact Coverage Gap Review Queue", "",
        "> 이 문서는 예금보험금 안내·고객 미수령금 신청에서 발견한 source-verified fact 후보다.",
        "> 모든 항목은 도메인 승인 전이며 `kdic-core-fact-proposals.json`이나 런타임 RAG에 자동 반영되지 않는다.", "",
        "## 검토 기준", "",
        "- 원문 인용이 후보의 의미·조건·범위를 충분히 뒷받침하는가?",
        "- 값이 최신성·예외 조건을 포함한 사용자 답변용 사실로 안전한가?",
        "- 승인한다면 기존 핵심 사실과 중복되지 않는가?",
        "- `통상`, 특정 시점, 메뉴 전용 조건은 표현을 보존해야 하는가?", "",
    ]
    for domain in sorted(grouped):
        lines += [f"## {domain}", ""]
        for candidate in sorted(grouped[domain], key=lambda item: item["id"]):
            evidence = candidate["evidence"]
            lines += [
                f"### `{candidate['id']}` — {candidate['label']}", "",
                f"- 대상: `{candidate['subject_id']}`",
                f"- 관계: `{candidate['predicate']}`",
                f"- 값: `{json.dumps(candidate['object'], ensure_ascii=False)}`",
                f"- 원문: [{evidence['page_id']}]({evidence['source_url']})",
                f"- 원문 해시: `{evidence['content_sha256']}`",
                f"- 인용: {evidence['quote']}",
                f"- 검토 초점: {candidate['review_focus']}",
                "- [ ] core fact로 승인",
                "- [ ] 반려",
                "- [ ] 수정 요청",
                "- 검토자 / 날짜: ",
                "- 메모: ",
                "",
            ]
    return "\n".join(lines) + "\n"


def serialize(queue: dict) -> str:
    return json.dumps(queue, ensure_ascii=False, indent=2) + "\n"


def generate() -> tuple[str, str]:
    queue = build_queue(load_json(MAP_PATH), load_json(CANONICAL_PATH), load_corpus())
    return serialize(queue), build_review_markdown(queue)


def write_or_check(check: bool) -> int:
    queue, review = generate()
    outputs = ((OUTPUT_PATH, queue), (REVIEW_PATH, review))
    if check:
        stale = [path for path, content in outputs if not path.exists() or path.read_text(encoding="utf-8") != content]
        if stale:
            for path in stale:
                print(f"out of date: {path.relative_to(ROOT)}")
            return 1
        print("up to date: fact gap review queue")
        return 0
    for path, content in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote: {path.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    return write_or_check(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
