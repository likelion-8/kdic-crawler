"""Initialize the human-owned machine-readable review decision file.

This script creates the file once with every canonical entity and core fact in a
``pending`` state. It deliberately refuses to overwrite the file: reviewers own all
subsequent decisions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from .build_ontology_map import ROOT
except ImportError:  # direct script execution
    from build_ontology_map import ROOT


CANONICAL_PATH = ROOT / "ontology" / "kdic-canonical-ontology-draft.json"
FACTS_PATH = ROOT / "ontology" / "kdic-core-fact-proposals.json"
OUTPUT_PATH = ROOT / "ontology" / "review" / "canonical-ontology-decisions.json"

FACT_REVIEW_LABELS = {
    "fact:concealed_assets_reward_maximum": "은닉재산 신고 포상금 최대 30억원",
    "fact:concealed_assets_reward_rate": "은닉재산 신고 포상금 회수금액의 5~20%",
    "fact:deposit_protection_limit": "예금자 보호한도 1인·금융회사별 1억원",
    "fact:deposit_protection_limit_effective_date": "예금자 보호한도 1억원 적용일 2025년 9월 1일",
    "fact:individual_rehabilitation_income_requirement": "개인회생 신청 조건 · 계속적·반복적 수입 가능성",
    "fact:individual_rehabilitation_repayment_period": "개인회생 변제기간 최대 5년",
    "fact:individual_rehabilitation_secured_debt_limit": "개인회생 담보부 채무 한도 15억원 이하",
    "fact:individual_rehabilitation_unsecured_debt_limit": "개인회생 무담보 채무 한도 10억원 이하",
    "fact:mistaken_remittance_amount_range": "착오송금 반환지원 신청금액 5만원 이상 1억원 이하",
    "fact:mistaken_remittance_application_deadline": "착오송금 반환지원 신청기한 · 송금일로부터 1년 이내",
    "fact:mistaken_remittance_prior_return_request": "착오송금 반환지원 사전 조건 · 금융회사 등에 반환 요청",
    "fact:mistaken_remittance_supported_date_threshold": "착오송금 반환지원 대상 송금일 · 2021년 7월 6일 이후",
    "fact:recipient_voluntary_return_deadline": "착오송금 수취인 자진반환 기한 · 통지일로부터 2주",
    "fact:visit_reception_hours": "착오송금 방문접수 시간 · 평일 오전 9시~오후 5시",
    "fact:visit_reception_lunch_break": "착오송금 방문접수 점심시간 · 낮 12시~오후 1시",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_descriptor(path: Path) -> dict[str, str]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": _sha256(path)}


def fact_label(fact: dict) -> str:
    return FACT_REVIEW_LABELS.get(fact["id"], fact["id"])


def build_initial_decisions(canonical: dict, facts: dict) -> dict:
    return {
        "schema_version": "1.0.0",
        "status": "pending_domain_review",
        "production_impact": "none",
        "policy": {
            "automatic_approval": False,
            "approved_items_only_for_future_runtime_promotion": True,
            "reviewer_identity_required_for_non_pending_decisions": True,
        },
        "source": {
            "canonical_draft": _source_descriptor(CANONICAL_PATH),
            "core_facts": _source_descriptor(FACTS_PATH),
        },
        "entities": [
            {"id": entity["id"], "label": entity["label"], "decision": "pending", "reviewed_by": None, "reviewed_at": None, "note": None}
            for entity in canonical["entities"]
        ],
        "facts": [
            {"id": fact["id"], "label": fact_label(fact), "decision": "pending", "reviewed_by": None, "reviewed_at": None, "note": None}
            for fact in facts["facts"]
        ],
    }


def write_initial(output_path: Path = OUTPUT_PATH) -> None:
    if output_path.exists():
        raise FileExistsError(f"review decision file already exists and is human-owned: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(build_initial_decisions(load_json(CANONICAL_PATH), load_json(FACTS_PATH)), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify that the human-owned decision file exists")
    args = parser.parse_args()
    if args.check:
        if OUTPUT_PATH.exists():
            print(f"review decision file exists: {OUTPUT_PATH.relative_to(ROOT)}")
            return 0
        print(f"missing review decision file: {OUTPUT_PATH.relative_to(ROOT)}")
        return 1
    write_initial()
    print(f"initialized pending review decisions: {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
