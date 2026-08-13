"""Generate an LLM-readable Korean domain wiki from the offline ontology artifacts.

The generated wiki is a navigation and grounding aid. It never replaces the current
official source documents and deliberately marks unapproved ontology items as review
material, not answer-ready knowledge.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

try:
    from .build_ontology_map import CORPUS_PATH, ROOT
except ImportError:  # direct script execution
    from build_ontology_map import CORPUS_PATH, ROOT


GRAPH_PATH = ROOT / "ontology" / "kdic-canonical-graph.json"
FACT_GAP_PATH = ROOT / "ontology" / "kdic-fact-gap-review-queue.json"
FACT_GAP_DECISIONS_PATH = ROOT / "ontology" / "review" / "fact-gap-review-decisions.json"
WIKI_PATH = ROOT / "ontology" / "llm-wiki"

STATUS_LABELS = {
    "base": "기본 업무 구조",
    "official_source": "공식 원문",
    "pending_domain_approval": "도메인 승인 대기",
    "source_verified_pending_domain_approval": "원문 검증 완료 · 도메인 승인 대기",
    "domain_approved": "도메인 승인 완료",
    "source_verified_domain_approved": "원문 검증·도메인 승인 완료",
    "domain_rejected": "도메인 검토 반려",
    "source_verified_domain_rejected": "원문 검증 완료 · 도메인 검토 반려",
    "domain_needs_changes": "도메인 수정 요청",
    "source_verified_domain_needs_changes": "원문 검증 완료 · 도메인 수정 요청",
    "source_verified_candidate_pending_domain_review": "원문 검증 완료 · 도메인 검토 대기",
}

ENTITY_TYPE_LABELS = {
    "Actor": "대상자·기관",
    "Concept": "개념",
    "ContactPoint": "문의·접수처",
    "EligibilityRule": "신청 조건",
    "MonetaryRule": "금액 기준",
    "Procedure": "절차",
    "RequiredDocument": "구비서류",
    "Service": "세부 서비스",
}

def _safe_name(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
    return re.sub(r"\s+", " ", value).strip(" .") or "이름 없음"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_inputs() -> tuple[dict, dict[str, dict], dict, dict]:
    graph = _read_json(GRAPH_PATH)
    fact_gap_queue = _read_json(FACT_GAP_PATH)
    fact_gap_decisions = _read_json(FACT_GAP_DECISIONS_PATH)
    with CORPUS_PATH.open(encoding="utf-8") as handle:
        corpus = {record["page_id"]: record for line in handle if (record := json.loads(line))}
    return graph, corpus, fact_gap_queue, fact_gap_decisions


def _domain_file_name(domain: dict) -> str:
    return f"업무영역/{_safe_name(domain['label'])}.md"


def _domain_service_ids(graph: dict) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for edge in graph["edges"]:
        if edge["relation"] == "BELONGS_TO_DOMAIN":
            result[edge["target"]].add(edge["source"])
    return result


def _services_for_node(graph: dict) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for edge in graph["edges"]:
        if edge["relation"] == "BELONGS_TO_SERVICE":
            result[edge["source"]].add(edge["target"])
    return result


def _domain_facts(graph: dict, domain_service_ids: dict[str, set[str]], node_service_ids: dict[str, set[str]]) -> dict[str, list[dict]]:
    nodes = {node["id"]: node for node in graph["nodes"]}
    facts_by_domain: dict[str, list[dict]] = defaultdict(list)
    for edge in graph["edges"]:
        if edge["relation"] != "ASSERTS_ABOUT":
            continue
        fact = nodes[edge["source"]]
        subject_services = node_service_ids.get(edge["target"], set())
        for domain_id, service_ids in domain_service_ids.items():
            if subject_services & service_ids:
                facts_by_domain[domain_id].append(fact)
    return {domain_id: sorted(facts, key=lambda fact: fact["id"]) for domain_id, facts in facts_by_domain.items()}


def _domain_document_nodes(graph: dict, domain_service_ids: dict[str, set[str]]) -> dict[str, list[dict]]:
    nodes = {node["id"]: node for node in graph["nodes"]}
    documents_by_domain: dict[str, list[dict]] = defaultdict(list)
    for edge in graph["edges"]:
        if edge["relation"] != "DOCUMENTS_SERVICE":
            continue
        for domain_id, service_ids in domain_service_ids.items():
            if edge["target"] in service_ids:
                documents_by_domain[domain_id].append(nodes[edge["source"]])
    return {domain_id: sorted(documents, key=lambda document: document["page_id"]) for domain_id, documents in documents_by_domain.items()}


def _domain_entities(graph: dict, domain_service_ids: dict[str, set[str]], node_service_ids: dict[str, set[str]]) -> dict[str, list[dict]]:
    nodes = {node["id"]: node for node in graph["nodes"]}
    entities_by_domain: dict[str, list[dict]] = defaultdict(list)
    for node_id, service_ids in node_service_ids.items():
        node = nodes[node_id]
        if node["node_type"] in {"Document", "Fact", "OfficialLabel"}:
            continue
        for domain_id, domain_services in domain_service_ids.items():
            if service_ids & domain_services:
                entities_by_domain[domain_id].append(node)
    return {
        domain_id: sorted(entities, key=lambda entity: (entity["node_type"], entity["label"], entity["id"]))
        for domain_id, entities in entities_by_domain.items()
    }


def _domain_fact_gaps(fact_gap_queue: dict, fact_gap_decisions: dict) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = defaultdict(list)
    decisions = {item["id"]: item for item in fact_gap_decisions["candidates"]}
    for candidate in fact_gap_queue["candidates"]:
        item = {**candidate, "review_decision": decisions[candidate["id"]]}
        for domain_label in candidate["business_domains"]:
            result[domain_label].append(item)
    return {
        domain_label: sorted(candidates, key=lambda candidate: candidate["id"])
        for domain_label, candidates in result.items()
    }


def _quote_lines(value: str) -> list[str]:
    return [f"> {line}" if line else ">" for line in value.splitlines()]


def _wiki_rules(graph: dict, fact_gap_queue: dict, fact_gap_decisions: dict) -> str:
    approval = graph.get("approval", {})
    entity_counts = approval.get("entity_counts", {})
    fact_counts = approval.get("fact_counts", {})
    entity_status = "도메인 승인 완료" if entity_counts and entity_counts.get("approved") == sum(entity_counts.values()) else "도메인 검토 진행 중"
    fact_status = "원문 검증·도메인 승인 완료" if fact_counts and fact_counts.get("approved") == sum(fact_counts.values()) else "원문 검증 완료 · 도메인 검토 진행 중"
    alias_counts = approval.get("official_label_counts", {})
    pending_aliases = alias_counts.get("source_verified_pending_domain_approval", 0)
    approved_aliases = alias_counts.get("source_verified_domain_approved", 0)
    gap_decision_counts = Counter(item["decision"] for item in fact_gap_decisions["candidates"])
    pending_gap_facts = gap_decision_counts["pending"]
    approved_gap_facts = gap_decision_counts["approved"]
    return f"""# LLM Wiki 사용 규칙

> 이 Wiki는 공식 원문 스냅샷을 찾고 검증된 답변 근거를 고르는 안내서입니다. 최신 정본은 각 공식 원문 URL이며, 로컬 답변은 수집일과 해시가 표시된 스냅샷 기준입니다.

## 답변 절차

1. 질문의 업무영역을 `00 시작하기.md`에서 찾는다.
2. **승인된 핵심 사실**에 질문과 정확히 일치하는 항목이 있으면 해당 항목의 구조화 값·원문 인용·`page_id`·해시를 함께 확인한다.
3. 승인된 핵심 사실에 없는 내용은 **공식 원문 색인**의 `page_id`로 `data/corpus.jsonl` 원문을 검색한다.
4. 현재 시점의 최신성이 중요하면 표시된 공식 원문 URL을 다시 확인한다.
5. 답변에는 실제 근거가 된 공식 원문 URL과 로컬 스냅샷 수집일을 함께 제시한다.
6. 근거가 부족하면 추측하지 말고, 확인 가능한 공식 페이지를 안내하거나 추가 정보를 요청한다.

## 사용 금지

- 승인된 사실 보강 후보 {approved_gap_facts}개도 core fact로 명시적으로 승격되기 전에는 답변 값으로 사용하지 않는다.
- 승인된 `문맥상 표기`는 공식 페이지의 문맥 표기일 뿐 동의어가 아니므로 검색어로 자동 확장하지 않는다.
- 승인 대기인 사실 후보 {pending_gap_facts}개와 공식 표기 {pending_aliases}개는 어떤 검색·답변에도 사용하지 않는다.
- Wiki 요약만으로 금액·날짜·기한을 확정하지 않는다.
- 표시된 해시와 로컬 `data/corpus.jsonl`의 해시가 다르면 해당 사실을 사용하지 않는다.

## 현재 상태

- 공식 원문: 58개
- 업무영역: 6개
- 정규 개념·절차 등: 45개, {entity_status}
- 핵심 사실: 15개, {fact_status}
- 공식 표기: {approved_aliases}개, 도메인 승인 완료 (문맥상 표기는 동의어 아님)
- 사실 보강 후보: {approved_gap_facts}개, 도메인 승인 완료·core fact 승격 대기
- 런타임 RAG 반영: 금지됨
"""


def _domain_page(
    domain: dict,
    base_services: list[dict],
    entities: list[dict],
    documents: list[dict],
    facts: list[dict],
    gap_facts: list[dict],
    corpus: dict[str, dict],
) -> str:
    lines = [
        "---",
        f"업무영역: {domain['label']}",
        "문서_성격: LLM 답변을 위한 공식 원문 탐색 안내",
        "런타임_사용: 검색 품질 게이트 통과 전 금지",
        "---",
        "",
        f"# {domain['label']}",
        "",
        "> 이 문서는 답변의 출발점입니다. 정확한 답변은 아래의 공식 원문을 확인한 뒤 작성합니다.",
        "",
        "## 연결된 기본 서비스",
        "",
    ]
    for service in base_services:
        lines.append(f"- {service['label']}")

    all_entities_approved = bool(entities) and all(entity["status"] == "domain_approved" for entity in entities)
    entity_heading = "## 승인된 업무 구성" if all_entities_approved else "## 검토 중인 업무 구성"
    lines += ["", entity_heading, ""]
    entities_by_type: dict[str, list[dict]] = defaultdict(list)
    for entity in entities:
        entities_by_type[entity["node_type"]].append(entity)
    if not entities_by_type:
        lines.append("- 연결된 검토 대상 없음")
    for node_type in sorted(entities_by_type):
        label = ENTITY_TYPE_LABELS.get(node_type, node_type)
        values = ", ".join(entity["label"] for entity in entities_by_type[node_type])
        lines.append(f"- {label}: {values}")

    lines += ["", "## 승인된 핵심 사실", "", "> 아래 사실은 원문 인용과 해시 검증 및 도메인 승인을 마쳤습니다. 최신성이 중요하면 공식 원문 URL을 다시 확인합니다.", ""]
    if not facts:
        lines.append("- 승인된 핵심 사실 없음")
    for fact in facts:
        evidence = fact["evidence"]
        source = corpus[evidence["page_id"]]
        lines += [
            f"### {fact['label']}",
            "",
            f"- 승인 상태: {STATUS_LABELS.get(fact['status'], fact['status'])}",
            f"- 구조화 값: `{json.dumps(fact['object'], ensure_ascii=False, sort_keys=True)}`",
            f"- 근거 `page_id`: `{evidence['page_id']}`",
            f"- 사실 근거 URL: [{evidence['source_url']}]({evidence['source_url']})",
            f"- 원문 수집일: {source['collected_at']}",
            f"- 원문 해시: `{evidence['content_sha256']}`",
            "- 원문 인용:",
            "",
            *_quote_lines(evidence["quote"]),
            "",
        ]

    all_gap_facts_approved = bool(gap_facts) and all(
        candidate["review_decision"]["decision"] == "approved" for candidate in gap_facts
    )
    gap_heading = "## 승인된 사실 보강 후보 · core fact 승격 대기" if all_gap_facts_approved else "## 검토 중인 사실 보강 후보"
    lines += [
        "", gap_heading, "",
        "> 이 후보는 원문 검증과 사람 승인을 마쳤더라도 core fact로 명시적으로 승격되기 전에는 답변 값이나 검색 확장에 사용하지 않습니다.",
        "",
    ]
    if not gap_facts:
        lines.append("- 별도 검토 대기 후보 없음")
    for candidate in gap_facts:
        evidence = candidate["evidence"]
        source = corpus[evidence["page_id"]]
        decision = candidate["review_decision"]
        status = "도메인 승인 완료 · core fact 미승격" if decision["decision"] == "approved" else decision["decision"]
        lines += [
            f"### {candidate['label']}",
            "",
            f"- 상태: {status}",
            f"- 검토자·승인일: {decision.get('reviewed_by') or '-'} · {decision.get('reviewed_at') or '-'}",
            f"- 근거 `page_id`: `{evidence['page_id']}`",
            f"- 후보 근거 URL: [{evidence['source_url']}]({evidence['source_url']})",
            f"- 원문 수집일: {source['collected_at']}",
            f"- 원문 해시: `{evidence['content_sha256']}`",
            f"- 검토 초점: {candidate['review_focus']}",
            "- 원문 인용:",
            "",
            *_quote_lines(evidence["quote"]),
            "",
        ]

    lines += ["", "## 공식 원문 색인", ""]
    for document in documents:
        source = corpus[document["page_id"]]
        lines += [
            f"### {source['page_title']}",
            "",
            source.get("summary", "공식 원문 요약이 없습니다."),
            "",
            f"- 공식 원문: [{source['source_url']}]({source['source_url']})",
            f"- `page_id`: `{document['page_id']}`",
            f"- 원문 수집일: {source['collected_at']}",
            f"- 원문 해시: `{document['content_sha256']}`",
            f"- 분류: {source['sub_category']}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def build_wiki(
    graph: dict,
    corpus: dict[str, dict],
    fact_gap_queue: dict,
    fact_gap_decisions: dict,
) -> dict[str, str]:
    """Return all generated files keyed by paths relative to ``WIKI_PATH``."""
    nodes = {node["id"]: node for node in graph["nodes"]}
    domains = sorted((node for node in graph["nodes"] if node["node_type"] == "BusinessDomain"), key=lambda node: node["label"])
    domain_service_ids = _domain_service_ids(graph)
    node_service_ids = _services_for_node(graph)
    documents = _domain_document_nodes(graph, domain_service_ids)
    entities = _domain_entities(graph, domain_service_ids, node_service_ids)
    facts = _domain_facts(graph, domain_service_ids, node_service_ids)
    fact_gaps = _domain_fact_gaps(fact_gap_queue, fact_gap_decisions)

    output = {"01 LLM 응답 규칙.md": _wiki_rules(graph, fact_gap_queue, fact_gap_decisions)}
    index = [
        "# KDIC 업무 LLM Wiki", "",
        "> 공식 KDIC 원문 58개와 오프라인 ontology를 바탕으로 만든 한글 지식 탐색 Wiki입니다.",
        "> 이 Wiki는 답변 생성의 정본이 아니며, 실제 답변에는 항상 연결된 공식 원문을 사용합니다.", "",
        "## 사용 순서", "",
        "1. [LLM 응답 규칙](01 LLM 응답 규칙.md)을 먼저 확인합니다.",
        "2. 질문에 맞는 업무영역을 선택합니다.",
        "3. 업무영역 문서의 공식 원문 URL을 검색·확인한 뒤 답변합니다.", "",
        "## 6대 업무영역", "",
    ]
    for domain in domains:
        index.append(f"- [{domain['label']}]({_domain_file_name(domain)})")
    index += [
        "", "## 범위와 상태", "",
        f"- 공식 원문: {graph['source']['document_count']}개",
        f"- 그래프: {graph['summary']['node_count']}개 노드, {graph['summary']['edge_count']}개 연결",
        f"- 승인 완료: 정규 업무 구성 45개, 핵심 사실 15개, 공식 표기 47개",
        f"- 승인 완료·core fact 승격 대기: 사실 보강 후보 {len(fact_gap_queue['candidates'])}개",
        "- 현재 상태: 오프라인 지식 탐색용 · 런타임 RAG 적용 차단",
        "- 상세 검토 상태: [Ontology Release Readiness](../RELEASE_READINESS.md)",
    ]
    output["00 시작하기.md"] = "\n".join(index) + "\n"

    for domain in domains:
        service_ids = domain_service_ids[domain["id"]]
        base_services = [nodes[service_id] for service_id in sorted(service_ids)]
        output[_domain_file_name(domain)] = _domain_page(
            domain,
            base_services,
            entities.get(domain["id"], []),
            documents.get(domain["id"], []),
            facts.get(domain["id"], []),
            fact_gaps.get(domain["label"], []),
            corpus,
        )
    return dict(sorted(output.items()))


def write_or_check(check: bool) -> int:
    graph, corpus, fact_gap_queue, fact_gap_decisions = load_inputs()
    output = build_wiki(graph, corpus, fact_gap_queue, fact_gap_decisions)
    if check:
        existing = {
            path.relative_to(WIKI_PATH).as_posix(): path.read_text(encoding="utf-8")
            for path in WIKI_PATH.rglob("*.md")
        } if WIKI_PATH.exists() else {}
        if existing != output:
            print("out of date: ontology/llm-wiki")
            return 1
        print("up to date: ontology/llm-wiki")
        return 0

    for path in WIKI_PATH.rglob("*.md") if WIKI_PATH.exists() else []:
        path.unlink()
    for relative_path, content in output.items():
        target = WIKI_PATH / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote LLM Wiki: {len(output)} files, {graph['source']['document_count']} official documents")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail when the generated Wiki is stale")
    return write_or_check(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
