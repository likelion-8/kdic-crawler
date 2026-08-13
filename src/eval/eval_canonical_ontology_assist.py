"""Offline shadow evaluation of canonical ontology assistance.

The frozen retrieval baseline is read from the existing held-out result. Canonical
labels and exact official label variants may prepend their evidence pages; contextual
labels, facts, and generated user phrases are excluded. The fixed rule is not tuned
on held-out outcomes and never changes production retrieval.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
TESTSET_PATH = ROOT / "data" / "testset" / "testset_pipeline.jsonl"
BASELINE_PATH = ROOT / "results" / "pipeline_holdout" / "retrieval_rerank_off.json"
CANONICAL_PATH = ROOT / "ontology" / "kdic-canonical-ontology-draft.json"
ALIASES_PATH = ROOT / "ontology" / "kdic-official-label-aliases.json"
ALIAS_DECISIONS_PATH = ROOT / "ontology" / "review" / "official-label-decisions.json"
OUTPUT_PATH = ROOT / "results" / "ontology" / "canonical_assist_shadow_heldout.json"
KS = (1, 3, 5)


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.lower())


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_rows(path: Path = TESTSET_PATH) -> dict[str, dict]:
    with path.open(encoding="utf-8") as f:
        return {row["test_id"]: row for line in f if (row := json.loads(line))}


def build_label_index(canonical: dict, aliases: dict, alias_decisions: dict) -> list[dict]:
    entity_pages = {
        entity["id"]: sorted({evidence["page_id"] for evidence in entity["evidence"]})
        for entity in canonical["entities"]
    }
    labels: dict[tuple[str, str], set[str]] = defaultdict(set)
    for entity in canonical["entities"]:
        normalized = normalize(entity["label"])
        if len(normalized) >= 4:
            labels[(entity["label"], normalized)].update(entity_pages[entity["id"]])
    approved_alias_ids = {
        item["id"] for item in alias_decisions["labels"] if item["decision"] == "approved"
    }
    for alias in aliases["aliases"]:
        if alias["id"] not in approved_alias_ids:
            continue
        if alias["alias_type"] != "official_label_variant":
            continue
        normalized = normalize(alias["label"])
        if len(normalized) >= 4:
            labels[(alias["label"], normalized)].update(alias["evidence_page_ids"])
    return [
        {"label": label, "normalized": normalized, "page_ids": sorted(page_ids)}
        for (label, normalized), page_ids in sorted(labels.items(), key=lambda item: (-len(item[0][1]), item[0][0]))
    ]


def ontology_pages(question: str, index: list[dict]) -> tuple[list[str], list[str]]:
    query = normalize(question)
    pages = []
    labels = []
    for item in index:
        if item["normalized"] not in query:
            continue
        labels.append(item["label"])
        for page_id in item["page_ids"]:
            if page_id not in pages:
                pages.append(page_id)
    return pages, labels


def assist_ranking(baseline_pages: list[str], matched_pages: list[str], limit: int = 5) -> list[str]:
    # Fixed conservative rule: exact official matches precede baseline pages while
    # preserving order in both groups. It is intentionally simple and auditable.
    return list(dict.fromkeys(matched_pages + baseline_pages))[:limit]


def metrics(per_rows: list[dict], ranking_key: str) -> dict:
    sums = {k: 0.0 for k in KS}
    reciprocal_rank = 0.0
    for item in per_rows:
        gold = set(item["gold"])
        ranked = item[ranking_key]
        for k in KS:
            sums[k] += len(gold & set(ranked[:k])) / len(gold)
        reciprocal_rank += next((1 / rank for rank, page in enumerate(ranked, 1) if page in gold), 0.0)
    n = len(per_rows)
    return {
        **{f"Recall@{k}": round(sums[k] / n, 4) for k in KS},
        "MRR@5": round(reciprocal_rank / n, 4),
        "n": n,
    }


def evaluate(rows: dict[str, dict], baseline: dict, index: list[dict]) -> dict:
    per_rows = []
    matched = 0
    changed = 0
    for base in baseline["per_row_retrieval"]:
        row = rows[base["test_id"]]
        baseline_pages = base["top5_pages"]
        matched_pages, labels = ontology_pages(row["question"], index)
        assisted = assist_ranking(baseline_pages, matched_pages)
        matched += bool(labels)
        changed += assisted != baseline_pages[:5]
        per_rows.append({
            "test_id": row["test_id"], "gold": sorted(row["expected_sources"]),
            "baseline_pages": baseline_pages[:5], "assisted_pages": assisted,
            "matched_labels": labels, "ontology_pages": matched_pages,
        })
    baseline_metrics = metrics(per_rows, "baseline_pages")
    assisted_metrics = metrics(per_rows, "assisted_pages")
    delta = {
        key: round(assisted_metrics[key] - baseline_metrics[key], 4)
        for key in ("Recall@1", "Recall@3", "Recall@5", "MRR@5")
    }
    # Gate is intentionally strict: no Recall@5 regression, and MRR plus Recall@1
    # must not regress. Passing only permits further review, never auto-deployment.
    gate_passed = delta["Recall@5"] >= 0 and delta["Recall@1"] >= 0 and delta["MRR@5"] >= 0
    return {
        "mode": "offline_shadow_exact_official_label_prepend",
        "production_impact": "none",
        "llm_calls": 0,
        "database_calls": 0,
        "heldout_tuning": False,
        "baseline_source": "results/pipeline_holdout/retrieval_rerank_off.json",
        "n_answerable": len(per_rows),
        "ontology_match_coverage": round(matched / len(per_rows), 4),
        "ranking_changed_count": changed,
        "baseline": baseline_metrics,
        "assisted": assisted_metrics,
        "delta": delta,
        "quality_gate": {
            "passed": gate_passed,
            "meaning": "eligible for further review only; never automatic production deployment",
        },
        "per_question": per_rows,
    }


def main() -> int:
    output = evaluate(
        load_rows(), load_json(BASELINE_PATH),
        build_label_index(
            load_json(CANONICAL_PATH), load_json(ALIASES_PATH), load_json(ALIAS_DECISIONS_PATH),
        ),
    )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("canonical ontology shadow assist")
    print("  coverage:", output["ontology_match_coverage"])
    print("  baseline:", output["baseline"])
    print("  assisted:", output["assisted"])
    print("  delta:", output["delta"])
    print("  gate passed:", output["quality_gate"]["passed"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
