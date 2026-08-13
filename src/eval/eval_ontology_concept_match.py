"""Offline held-out evaluation for deterministic ontology concept matching.

This measures the metadata ontology as a standalone retrieval hint. It does not call an
LLM, connect to Supabase, or change production retrieval. A low result is useful: it
means the v1 metadata concepts are not yet a sufficient semantic retrieval signal.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
MAP_PATH = ROOT / "ontology" / "kdic-document-concept-map.json"
TESTSET_PATH = ROOT / "data" / "testset" / "testset_pipeline.jsonl"
OUTPUT_PATH = ROOT / "results" / "ontology" / "metadata_concept_match_heldout.json"
K_VALUES = (1, 3, 5)
GENERIC_CONCEPTS = frozenset({
    "개요", "안내", "FAQ", "신청", "신고", "조회", "제도", "지원", "절차", "대상",
    "업무 소개", "소개", "처리", "방법", "서류", "정보", "기타",
})


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.lower())


def load_index(path: Path = MAP_PATH) -> dict:
    mapping = json.loads(path.read_text(encoding="utf-8"))
    concept_docs = {concept["id"]: concept["page_ids"] for concept in mapping["concepts"]}
    concepts = [
        {"id": concept["id"], "label": concept["label"], "normalized": normalize(concept["label"]),
         "document_count": concept["document_count"]}
        for concept in mapping["concepts"]
        if concept["label"] not in GENERIC_CONCEPTS and len(normalize(concept["label"])) >= 3
    ]
    return {"concepts": concepts, "concept_docs": concept_docs, "document_count": len(mapping["document_mappings"])}


def rank_documents(question: str, index: dict) -> tuple[list[str], list[str]]:
    query = normalize(question)
    scores: dict[str, float] = defaultdict(float)
    matched_concepts = []
    for concept in index["concepts"]:
        if concept["normalized"] not in query:
            continue
        matched_concepts.append(concept["label"])
        # Exact longer labels and concepts shared by fewer documents get more weight.
        weight = len(concept["normalized"]) * math.log((index["document_count"] + 1) /
                                                         (concept["document_count"] + 1))
        for page_id in index["concept_docs"][concept["id"]]:
            scores[page_id] += weight
    ranked = [page_id for page_id, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]
    return ranked, matched_concepts


def _recall_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    return len(set(ranked[:k]) & gold) / len(gold)


def evaluate(rows: list[dict], index: dict) -> dict:
    answerable = [row for row in rows if row.get("expected_sources")]
    sums = {k: 0.0 for k in K_VALUES}
    matched_sums = {k: 0.0 for k in K_VALUES}
    matched = 0
    per_question = []
    concept_counter = Counter()
    for row in answerable:
        gold = set(row["expected_sources"])
        ranked, concepts = rank_documents(row["question"], index)
        recall = {k: _recall_at_k(ranked, gold, k) for k in K_VALUES}
        for k in K_VALUES:
            sums[k] += recall[k]
        if concepts:
            matched += 1
            for k in K_VALUES:
                matched_sums[k] += recall[k]
            concept_counter.update(concepts)
        per_question.append({
            "test_id": row["test_id"],
            "gold": sorted(gold),
            "matched_concepts": concepts,
            "ranked_pages": ranked[:5],
            "hit_at_5": bool(set(ranked[:5]) & gold),
        })

    n = len(answerable)
    return {
        "testset": "data/testset/testset_pipeline.jsonl",
        "mode": "standalone_exact_metadata_concept_match",
        "production_impact": "none",
        "n_answerable": n,
        "concept_match_coverage": round(matched / n, 4) if n else 0.0,
        "recall_all_questions": {f"Recall@{k}": round(sums[k] / n, 4) if n else 0.0 for k in K_VALUES},
        "recall_when_concept_matched": {
            f"Recall@{k}": round(matched_sums[k] / matched, 4) if matched else None for k in K_VALUES
        },
        "matched_question_count": matched,
        "top_matched_concepts": concept_counter.most_common(20),
        "per_question": per_question,
    }


def load_rows(path: Path = TESTSET_PATH) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> int:
    result = evaluate(load_rows(), load_index())
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("ontology metadata concept match")
    print("  answerable:", result["n_answerable"])
    print("  coverage:", result["concept_match_coverage"])
    print("  recall:", result["recall_all_questions"])
    print("  wrote:", OUTPUT_PATH.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
