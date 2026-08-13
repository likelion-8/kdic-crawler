"""Create a page-level review queue for one-document (P3) metadata concepts.

P3 labels are often duplicate title/breadcrumb variants from the same official page.
This generator groups them by page, retains every source label, and suggests a review
priority and ontology class from transparent rules. It never approves a concept,
reads the held-out test set, or changes runtime retrieval.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
MAP_PATH = ROOT / "ontology" / "kdic-document-concept-map.json"
CORPUS_PATH = ROOT / "data" / "corpus.jsonl"
CURATED_PROPOSALS_PATH = ROOT / "ontology" / "kdic-curated-concept-proposals.json"
OUTPUT_PATH = ROOT / "ontology" / "kdic-p3-concept-triage.json"

GENERIC_LABELS = frozenset({
    "faq", "faqtop10", "개요", "고객센터", "안내", "유의사항", "절차", "제도란",
    "신청방법", "상황선택", "조사업무소개", "소개", "신고센터소개",
})
CLASS_HINTS = (
    ("RequiredDocument", ("구비서류",)),
    ("EligibilityRule", ("신청대상", "대상여부")),
    ("Procedure", ("신청절차", "반환지원절차", "신청방법")),
    ("ContactPoint", ("전화문의", "방문접수", "신고센터")),
)


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.lower())


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_corpus(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8") as f:
        return {row["page_id"]: row for line in f if (row := json.loads(line))}


def is_generic(label: str) -> bool:
    normalized = normalize(label)
    return (
        normalized in GENERIC_LABELS
        or "faq" in normalized
        or normalized.endswith("개요")
        or normalized.endswith("소개")
    )


def title_relation(label: str, title: str) -> str:
    normalized_label = normalize(label)
    normalized_title = normalize(title)
    if normalized_label == normalized_title:
        return "exact"
    if normalized_label in normalized_title or normalized_title in normalized_label:
        return "overlap"
    return "metadata_only"


def select_label(concepts: list[dict], page_title: str) -> dict:
    return sorted(
        concepts,
        key=lambda concept: (
            {"exact": 0, "overlap": 1, "metadata_only": 2}[title_relation(concept["label"], page_title)],
            is_generic(concept["label"]),
            -len(normalize(concept["label"])),
            concept["label"],
        ),
    )[0]


def suggested_class(label: str) -> str:
    normalized = normalize(label)
    for ontology_class, fragments in CLASS_HINTS:
        if any(normalize(fragment) in normalized for fragment in fragments):
            return ontology_class
    return "Concept"


def existing_candidate_matches(label: str, curated_candidates: list[dict]) -> list[str]:
    normalized_label = normalize(label)
    matches = []
    for candidate in curated_candidates:
        normalized_candidate = normalize(candidate["label"])
        if len(normalized_candidate) < 4:
            continue
        if normalized_candidate in normalized_label or normalized_label in normalized_candidate:
            matches.append(candidate["id"])
    return sorted(matches)


def review_priority(label: str, relation: str, summary: str, parent_matches: list[str]) -> str:
    if "faq" in normalize(label):
        return "P3-low"
    if parent_matches:
        return "P3-medium"
    if is_generic(label):
        return "P3-low"
    if relation == "exact" and summary.strip():
        return "P3-high"
    return "P3-medium"


def review_action(priority: str) -> str:
    if priority == "P3-high":
        return "verify_as_canonical_candidate"
    if priority == "P3-medium":
        return "verify_scope_and_parent_relation"
    return "verify_or_reject_navigation_label"


def build_triage(mapping: dict, corpus: dict[str, dict], curated_proposals: dict) -> dict:
    p3_concepts = [concept for concept in mapping["concepts"] if concept["document_count"] == 1]
    if curated_proposals["source"] != mapping["source"]:
        raise ValueError("curated P1/P2 proposals must be generated from the current corpus map")
    by_page: dict[str, list[dict]] = defaultdict(list)
    for concept in p3_concepts:
        page_id = concept["page_ids"][0]
        by_page[page_id].append({"id": concept["id"], "label": concept["label"]})

    documents = {document["page_id"]: document for document in mapping["document_mappings"]}
    candidates = []
    for page_id in sorted(by_page):
        source = corpus[page_id]
        concepts = sorted(by_page[page_id], key=lambda concept: (concept["label"], concept["id"]))
        selected = select_label(concepts, source["page_title"])
        relation = title_relation(selected["label"], source["page_title"])
        parent_matches = existing_candidate_matches(selected["label"], curated_proposals["candidates"])
        priority = review_priority(selected["label"], relation, source.get("summary", ""), parent_matches)
        candidates.append({
            "page_id": page_id,
            "candidate_label": selected["label"],
            "suggested_ontology_class": suggested_class(selected["label"]),
            "title_relation": relation,
            "review_priority": priority,
            "review_action": review_action(priority),
            "status": "triage_only_pending_domain_review",
            "potential_parent_candidate_ids": parent_matches,
            "source_metadata_concepts": concepts,
            "evidence": {
                "source_url": source["source_url"],
                "content_sha256": documents[page_id]["content_sha256"],
                "page_title": source["page_title"],
                "summary": source.get("summary", ""),
            },
        })
    candidates.sort(key=lambda candidate: (candidate["review_priority"], candidate["candidate_label"], candidate["page_id"]))
    priority_counts = Counter(candidate["review_priority"] for candidate in candidates)
    return {
        "schema_version": "1.0.0",
        "status": "triage_only_pending_domain_review",
        "production_impact": "none",
        "source": mapping["source"],
        "review_policy": {
            "heldout_testset_used": False,
            "automatic_candidate_approval": False,
            "runtime_use": "prohibited",
            "source_label_retention": "every P3 metadata concept remains visible in its page candidate",
            "parent_match_semantics": "string overlap only; it is a reviewer hint, not a merge decision",
        },
        "summary": {
            "source_metadata_concept_count": len(p3_concepts),
            "page_candidate_count": len(candidates),
            "review_priority_counts": dict(sorted(priority_counts.items())),
        },
        "page_candidates": candidates,
    }


def serialize(triage: dict) -> str:
    return json.dumps(triage, ensure_ascii=False, indent=2) + "\n"


def write_or_check(check: bool) -> int:
    output = serialize(build_triage(
        load_json(MAP_PATH), load_corpus(CORPUS_PATH), load_json(CURATED_PROPOSALS_PATH)
    ))
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
    parser.add_argument("--check", action="store_true", help="fail if the generated triage is out of date")
    return write_or_check(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
