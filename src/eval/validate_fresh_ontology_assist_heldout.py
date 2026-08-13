"""Validate a newly authored, independent held-out set for ontology assist.

The validator enforces structural independence from the frozen pipeline held-out set.
It does not evaluate or change retrieval.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
LEGACY_TESTSET_PATH = ROOT / "data" / "testset" / "testset_pipeline.jsonl"
MAP_PATH = ROOT / "ontology" / "kdic-document-concept-map.json"
CORPUS_PATH = ROOT / "data" / "corpus.jsonl"
MINIMUM_ANSWERABLE = 72
MINIMUM_PER_DOMAIN = 12
ALLOWED_QUERY_FORMS = frozenset({"official_label_explicit", "user_paraphrase", "typo_variant", "multi_part"})
REQUIRED_FIELDS = frozenset({
    "test_id", "question", "business_function", "expected_sources", "question_type",
    "intent", "query_form", "authored_by", "authored_at",
})


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.lower())


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def known_domains() -> set[str]:
    mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    return {item["business_domain"] for item in mapping["services"]}


def known_page_ids() -> set[str]:
    return {row["page_id"] for row in load_jsonl(CORPUS_PATH)}


def validate_rows(rows: list[dict], legacy_rows: list[dict], domains: set[str], page_ids: set[str]) -> dict:
    errors: list[str] = []
    test_ids = [row.get("test_id") for row in rows]
    if len(test_ids) != len(set(test_ids)):
        errors.append("test_id must be unique")
    legacy_ids = {row["test_id"] for row in legacy_rows}
    overlap_ids = sorted(set(test_ids) & legacy_ids)
    if overlap_ids:
        errors.append(f"test_id overlaps frozen held-out set: {', '.join(overlap_ids)}")
    legacy_questions = {normalize(row["question"]) for row in legacy_rows}
    question_keys = []
    domain_counts = Counter()
    form_counts = Counter()

    for index, row in enumerate(rows, 1):
        missing = sorted(REQUIRED_FIELDS - set(row))
        if missing:
            errors.append(f"row {index}: missing required fields: {', '.join(missing)}")
            continue
        question = row["question"]
        question_key = normalize(question)
        question_keys.append(question_key)
        if not question_key:
            errors.append(f"row {index}: question must contain searchable text")
        if question_key in legacy_questions:
            errors.append(f"row {index}: question duplicates frozen held-out wording")
        if row["business_function"] not in domains:
            errors.append(f"row {index}: unknown business_function: {row['business_function']}")
        else:
            domain_counts[row["business_function"]] += 1
        if row["query_form"] not in ALLOWED_QUERY_FORMS:
            errors.append(f"row {index}: unknown query_form: {row['query_form']}")
        else:
            form_counts[row["query_form"]] += 1
        if not isinstance(row["expected_sources"], list) or not row["expected_sources"]:
            errors.append(f"row {index}: expected_sources must contain at least one official page_id")
        else:
            unknown_sources = sorted(set(row["expected_sources"]) - page_ids)
            if unknown_sources:
                errors.append(f"row {index}: unknown expected_sources: {', '.join(unknown_sources)}")
        if not isinstance(row["authored_by"], str) or not row["authored_by"].strip():
            errors.append(f"row {index}: authored_by is required")
        if not isinstance(row["authored_at"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["authored_at"]):
            errors.append(f"row {index}: authored_at must be YYYY-MM-DD")
    if len(question_keys) != len(set(question_keys)):
        errors.append("question wording must be unique after normalization")
    if len(rows) < MINIMUM_ANSWERABLE:
        errors.append(f"at least {MINIMUM_ANSWERABLE} answerable rows are required")
    for domain in sorted(domains):
        if domain_counts[domain] < MINIMUM_PER_DOMAIN:
            errors.append(f"{domain}: at least {MINIMUM_PER_DOMAIN} rows are required; found {domain_counts[domain]}")
    non_official_count = sum(count for form, count in form_counts.items() if form != "official_label_explicit")
    if rows and non_official_count / len(rows) < 0.5:
        errors.append("at least 50% of questions must be user_paraphrase, typo_variant, or multi_part")
    return {
        "valid": not errors,
        "production_impact": "none",
        "llm_calls": 0,
        "database_calls": 0,
        "minimums": {
            "answerable_rows": MINIMUM_ANSWERABLE,
            "rows_per_business_domain": MINIMUM_PER_DOMAIN,
            "non_official_query_ratio": 0.5,
        },
        "counts": {
            "rows": len(rows),
            "business_domains": dict(sorted(domain_counts.items())),
            "query_forms": dict(sorted(form_counts.items())),
        },
        "errors": errors,
    }


def validate_file(path: Path) -> dict:
    return validate_rows(load_jsonl(path), load_jsonl(LEGACY_TESTSET_PATH), known_domains(), known_page_ids())


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a fresh ontology-assist held-out JSONL file.")
    parser.add_argument("input", type=Path, help="new independently-authored JSONL file")
    args = parser.parse_args()
    report = validate_file(args.input)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
