"""Build domain-scoped human review packets without changing approval decisions."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

try:
    from .build_ontology_map import ROOT
except ImportError:  # direct script execution
    from build_ontology_map import ROOT


MAP_PATH = ROOT / "ontology" / "kdic-document-concept-map.json"
CANONICAL_PATH = ROOT / "ontology" / "kdic-canonical-ontology-draft.json"
FACTS_PATH = ROOT / "ontology" / "kdic-core-fact-proposals.json"
DECISIONS_PATH = ROOT / "ontology" / "review" / "canonical-ontology-decisions.json"
FACT_GAP_PATH = ROOT / "ontology" / "kdic-fact-gap-review-queue.json"
FACT_GAP_DECISIONS_PATH = ROOT / "ontology" / "review" / "fact-gap-review-decisions.json"
OUTPUT_DIR = ROOT / "ontology" / "review" / "by-domain"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _fact_service_ids(fact: dict, entity_service_ids: dict[str, list[str]], page_service_ids: dict[str, list[str]]) -> list[str]:
    service_ids = entity_service_ids.get(fact["subject_id"])
    if service_ids:
        return service_ids
    return page_service_ids[fact["evidence"]["page_id"]]


def _item_evidence_lines(evidence: dict) -> list[str]:
    return [
        f"- 원문: [{evidence['page_id']}]({evidence['source_url']})",
        f"- 원문 해시: `{evidence['content_sha256']}`",
        f"- 인용: {evidence['quote']}",
    ]


def build_packets(
    mapping: dict,
    canonical: dict,
    facts: dict,
    decisions: dict,
    fact_gap_queue: dict,
    fact_gap_decisions: dict,
) -> dict[str, str]:
    services = sorted(mapping["services"], key=lambda item: item["id"])
    service_labels = {item["id"]: item["label"] for item in services}
    page_service_ids = {item["page_id"]: item["service_ids"] for item in mapping["document_mappings"]}
    entity_service_ids = {item["id"]: item["parent_service_ids"] for item in canonical["entities"]}
    entity_decisions = {item["id"]: item for item in decisions["entities"]}
    fact_decisions = {item["id"]: item for item in decisions["facts"]}
    gap_decisions = {item["id"]: item for item in fact_gap_decisions["candidates"]}
    entities_by_service: dict[str, list[dict]] = defaultdict(list)
    facts_by_service: dict[str, list[dict]] = defaultdict(list)
    gaps_by_service: dict[str, list[dict]] = defaultdict(list)

    for entity in canonical["entities"]:
        for service_id in entity["parent_service_ids"]:
            entities_by_service[service_id].append(entity)
    for fact in facts["facts"]:
        for service_id in _fact_service_ids(fact, entity_service_ids, page_service_ids):
            facts_by_service[service_id].append(fact)
    service_id_by_domain = {item["business_domain"]: item["id"] for item in services}
    for candidate in fact_gap_queue["candidates"]:
        for domain in candidate["business_domains"]:
            gaps_by_service[service_id_by_domain[domain]].append(candidate)

    index_lines = [
        "# 6대 업무영역 Ontology 검토 인덱스", "",
        "> 이 문서는 사람 검토를 분담하기 위한 생성물입니다. 승인 결정의 원본은 `../canonical-ontology-decisions.json`이며,",
        "> 패킷의 체크 표시는 자동 승인·런타임 반영을 일으키지 않습니다.", "",
        "## 검토 순서", "",
        "1. 자신의 업무영역 패킷에서 엔터티와 핵심 사실의 원문·해시·범위를 검토합니다.",
        "2. 결정은 `canonical-ontology-decisions.json`에 `approved`·`rejected`·`needs_changes`로 기록합니다.",
        "3. 보강 후보는 이 패킷에서만 검토하며, 승인 후에도 별도 core fact 변경과 재검증이 필요합니다.",
        "4. 생성물을 다시 만들고 release validator가 통과하는지 확인합니다.", "",
        "| 업무영역 | 공식 문서 | 엔터티 결정 | 핵심 사실 결정 | 보강 후보 | 패킷 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    outputs: dict[str, str] = {}

    for service in services:
        service_id = service["id"]
        slug = service_id.split(":", 1)[1]
        entities = sorted(entities_by_service[service_id], key=lambda item: item["id"])
        core_facts = sorted(facts_by_service[service_id], key=lambda item: item["id"])
        gap_facts = sorted(gaps_by_service[service_id], key=lambda item: item["id"])
        index_lines.append(
            f"| {service['label']} | {service['document_count']} | {len(entities)} | {len(core_facts)} | {len(gap_facts)} | [{service['label']}]({slug}.md) |"
        )
        lines = [
            f"# {service['label']} Ontology 검토 패킷", "",
            "> 이 패킷은 검토를 돕는 생성물입니다. 실제 승인 상태는 `../canonical-ontology-decisions.json`만 사용합니다.",
            "> 어떤 항목도 승인 전에는 검색·답변·Supabase/RAG에 자동 반영되지 않습니다.", "",
            "## 범위", "",
            f"- 공식 문서: {service['document_count']}개",
            f"- canonical 엔터티 결정: {len(entities)}개",
            f"- source-verified 핵심 사실 결정: {len(core_facts)}개",
            f"- source-verified 보강 후보: {len(gap_facts)}개 (core fact 자동 승격 없음)", "",
            "## 검토 기준", "",
            "- 용어가 공식적이고 안정적인 업무 개념인지 확인합니다.",
            "- 클래스·상위 Service·관계·값·조건이 원문과 일치하는지 확인합니다.",
            "- 인용과 content hash가 현재 원문을 정확히 가리키는지 확인합니다.",
            "- `통상`, 기한, 금액, 예외 조건을 과장하거나 누락하지 않습니다.", "",
            "## Canonical 엔터티", "",
        ]
        if not entities:
            lines += ["- 이 업무영역에 연결된 canonical 엔터티가 없습니다.", ""]
        for entity in entities:
            decision = entity_decisions[entity["id"]]
            evidence_pages = ", ".join("`" + item["page_id"] + "`" for item in entity["evidence"])
            lines += [
                f"### `{entity['id']}` — {entity['label']}", "",
                f"- 클래스: `{entity['ontology_class']}`",
                f"- 현재 결정: `{decision['decision']}` ({decision.get('reviewed_by') or '-'} · {decision.get('reviewed_at') or '-'})",
                f"- 근거 페이지: {evidence_pages}",
                "- [ ] 승인  [ ] 반려  [ ] 수정 요청",
                "- 결정은 `../canonical-ontology-decisions.json`에 기록: ",
                "",
            ]
        lines += ["## Source-verified 핵심 사실", ""]
        if not core_facts:
            lines += ["- 승인된 핵심 사실이 없습니다. 아래 보강 후보를 별도로 검토합니다.", ""]
        for fact in core_facts:
            decision = fact_decisions[fact["id"]]
            lines += [
                f"### `{fact['id']}`", "",
                f"- 대상: `{fact['subject_id']}`",
                f"- 관계: `{fact['predicate']}`",
                f"- 값: `{_json(fact['object'])}`",
                f"- 현재 결정: `{decision['decision']}` ({decision.get('reviewed_by') or '-'} · {decision.get('reviewed_at') or '-'})",
                *_item_evidence_lines(fact["evidence"]),
                "- [ ] 승인  [ ] 반려  [ ] 수정 요청",
                "- 결정은 `../canonical-ontology-decisions.json`에 기록: ",
                "",
            ]
        lines += ["## Source-verified 사실 보강 후보", ""]
        if not gap_facts:
            lines += ["- 이 업무영역에는 별도 보강 후보가 없습니다.", ""]
        for candidate in gap_facts:
            decision = gap_decisions[candidate["id"]]
            lines += [
                f"### `{candidate['id']}` — {candidate['label']}", "",
                f"- 대상: `{candidate['subject_id']}`",
                f"- 관계: `{candidate['predicate']}`",
                f"- 값: `{_json(candidate['object'])}`",
                f"- 현재 결정: `{decision['decision']}` ({decision.get('reviewed_by') or '-'} · {decision.get('reviewed_at') or '-'})",
                *_item_evidence_lines(candidate["evidence"]),
                f"- 검토 초점: {candidate['review_focus']}",
                "- [ ] core fact 승격 제안  [ ] 반려  [ ] 수정 요청",
                "- 메모: ",
                "",
            ]
        outputs[f"{slug}.md"] = "\n".join(lines) + "\n"
    outputs["INDEX.md"] = "\n".join(index_lines) + "\n"
    return outputs


def generate() -> dict[str, str]:
    return build_packets(
        load_json(MAP_PATH), load_json(CANONICAL_PATH), load_json(FACTS_PATH),
        load_json(DECISIONS_PATH), load_json(FACT_GAP_PATH), load_json(FACT_GAP_DECISIONS_PATH),
    )


def write_or_check(check: bool) -> int:
    packets = generate()
    if check:
        stale = [name for name, content in packets.items() if not (OUTPUT_DIR / name).exists() or (OUTPUT_DIR / name).read_text(encoding="utf-8") != content]
        if stale:
            for name in stale:
                print(f"out of date: {OUTPUT_DIR.relative_to(ROOT) / name}")
            return 1
        print("up to date: ontology domain review packets")
        return 0
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in packets.items():
        path = OUTPUT_DIR / name
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote: {path.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    return write_or_check(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
