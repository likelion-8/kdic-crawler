"""Record semantic coverage decisions for every official KDIC source document.

Every source page must either evidence an ontology node or be explicitly retained as
a document-only page. FAQ and routing pages stay searchable source documents; they
do not become artificial ontology entities merely to satisfy a coverage count.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .build_ontology_map import ROOT
except ImportError:  # direct script execution
    from build_ontology_map import ROOT


MAP_PATH = ROOT / "ontology" / "kdic-document-concept-map.json"
GRAPH_PATH = ROOT / "ontology" / "kdic-canonical-graph.json"
P3_REMAINING_PATH = ROOT / "ontology" / "kdic-p3-remaining-reviews.json"
OUTPUT_PATH = ROOT / "ontology" / "kdic-document-semantic-coverage.json"

DOCUMENT_ONLY_DISPOSITIONS = {
    "dr_faq_inq": {
        "document_role": "FAQ",
        "reason": "채무정보 조회 이용 중 발생하는 인증·브라우저 문제를 다루는 FAQ다. 독립적인 업무 개념은 만들지 않고 공식 문서로 유지한다.",
    },
    "faq_msdr_apply": {
        "document_role": "FAQ",
        "reason": "착오송금 반환지원의 반복 질문을 모은 FAQ다. 금액·기한·제외 사유는 별도 핵심 사실 검토에서만 구조화한다.",
    },
    "faq_nramt": {
        "document_role": "내용 범위 불일치 FAQ",
        "reason": "메뉴명은 미수령금 통합신청 FAQ지만 수집된 내용은 예금보호·가지급금 관련 문답이다. 도메인 담당자가 범위를 확인하기 전에는 독립 개념이나 동의어로 승격하지 않는다.",
    },
    "faq_top10": {
        "document_role": "FAQ",
        "reason": "착오송금 반환지원의 상위 질문을 모은 FAQ다. 독립 개념을 만들지 않고 실제 답변 시 공식 원문을 직접 확인한다.",
    },
    "ha_faq_dclr": {
        "document_role": "FAQ",
        "reason": "은닉재산 신고의 반복 질문을 모은 FAQ다. 포상금·절차 값은 별도 핵심 사실 검토에서만 구조화한다.",
    },
    "mtrs_stut_chc": {
        "document_role": "상황 분기 화면",
        "reason": "착오송금인과 수취인 메뉴를 기존 신청대상·절차·구비서류 페이지로 연결하는 탐색용 화면이다. 별도 업무 개체를 만들지 않는다.",
    },
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_coverage(mapping: dict, graph: dict, remaining_reviews: dict) -> dict:
    source = mapping["source"]
    if graph["source"] != source or remaining_reviews["source"] != source:
        raise ValueError("coverage inputs must use the current corpus map")

    graph_nodes = {node["id"]: node for node in graph["nodes"]}
    evidence_targets: dict[str, set[str]] = {}
    for edge in graph["edges"]:
        if edge["relation"] == "EVIDENCE_FOR" and edge["source"].startswith("document:"):
            evidence_targets.setdefault(edge["source"], set()).add(edge["target"])

    rejected_pages = {
        decision["page_id"]
        for decision in remaining_reviews["decisions"]
        if decision["decision"] == "rejected"
    }
    coverage = []
    unresolved = []
    for document in sorted(mapping["document_mappings"], key=lambda item: item["page_id"]):
        document_id = document["document_id"]
        target_ids = sorted(evidence_targets.get(document_id, set()))
        if target_ids:
            coverage.append({
                "page_id": document["page_id"],
                "document_id": document_id,
                "business_domain": document["business_domain"],
                "coverage_status": "semantic_evidence",
                "targets": [
                    {"id": target_id, "node_type": graph_nodes[target_id]["node_type"], "label": graph_nodes[target_id]["label"]}
                    for target_id in target_ids
                ],
            })
            continue

        page_id = document["page_id"]
        disposition = DOCUMENT_ONLY_DISPOSITIONS.get(page_id)
        if disposition is None or page_id not in rejected_pages:
            unresolved.append(page_id)
            continue
        coverage.append({
            "page_id": page_id,
            "document_id": document_id,
            "business_domain": document["business_domain"],
            "coverage_status": "document_only",
            "review_decision": "rejected_as_independent_entity",
            "document_role": disposition["document_role"],
            "reason": disposition["reason"],
            "targets": [],
        })

    if unresolved:
        raise ValueError(f"documents need a semantic coverage decision: {', '.join(unresolved)}")
    semantic_evidence_count = sum(item["coverage_status"] == "semantic_evidence" for item in coverage)
    document_only_count = sum(item["coverage_status"] == "document_only" for item in coverage)
    return {
        "schema_version": "1.0.0",
        "status": "document_semantic_coverage_pending_domain_approval",
        "production_impact": "none",
        "source": source,
        "policy": {
            "every_official_document_requires_a_coverage_decision": True,
            "faq_and_navigation_pages_remain_source_documents": True,
            "document_only_pages_are_not_ontology_entities": True,
            "automatic_runtime_promotion": False,
        },
        "summary": {
            "official_document_count": len(coverage),
            "semantic_evidence_count": semantic_evidence_count,
            "document_only_count": document_only_count,
            "unresolved_count": 0,
        },
        "documents": coverage,
    }


def serialize(coverage: dict) -> str:
    return json.dumps(coverage, ensure_ascii=False, indent=2) + "\n"


def current_coverage() -> dict:
    return build_coverage(load_json(MAP_PATH), load_json(GRAPH_PATH), load_json(P3_REMAINING_PATH))


def write_or_check(check: bool) -> int:
    output = serialize(current_coverage())
    if check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != output:
            print(f"out of date: {OUTPUT_PATH.relative_to(ROOT)}")
            return 1
        print(f"up to date: {OUTPUT_PATH.relative_to(ROOT)}")
        return 0
    OUTPUT_PATH.write_text(output, encoding="utf-8", newline="\n")
    print(f"wrote: {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    return write_or_check(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
