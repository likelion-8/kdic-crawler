"""Build the deterministic v1 Document -> Service/Concept ontology mapping.

The mapping uses only reviewed corpus metadata. It does not ask an LLM to invent or
summarize concepts. `business_function` selects one service, while breadcrumb segments
and `page_title` become concept labels. Every mapping keeps the source content hash so
it can be invalidated when the page changes.

Usage from the repository root:
    python src/crawler/build_ontology_map.py
    python src/crawler/build_ontology_map.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent.parent
CORPUS_PATH = ROOT / "data" / "corpus.jsonl"
OUTPUT_PATH = ROOT / "ontology" / "kdic-document-concept-map.json"
EXPECTED_DOCUMENT_COUNT = 58

SERVICES = {
    "예금자보호제도": ("service:deposit_protection", "예금자보호제도"),
    "예금보험금 안내": ("service:deposit_insurance_payment", "예금보험금 안내"),
    "고객 미수령금 신청": ("service:unclaimed_funds", "고객 미수령금 신청"),
    "착오송금 반환 신청": ("service:mistaken_remittance_return", "착오송금 반환 신청"),
    "채무조정 안내": ("service:debt_adjustment", "채무조정 안내"),
    "은닉재산 신고": ("service:concealed_assets_report", "은닉재산 신고"),
}


def load_corpus(path: Path = CORPUS_PATH) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON at {path}:{line_no}") from exc
    return records


def _normalize_label(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _concept_id(label: str) -> str:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()[:16]
    return f"concept:c_{digest}"


def _concept_labels(record: dict) -> list[str]:
    business = _normalize_label(record.get("business_function"))
    labels = []
    for part in _normalize_label(record.get("sub_category")).split(">"):
        label = _normalize_label(part)
        if label and label != business and label not in labels:
            labels.append(label)
    title = _normalize_label(record.get("page_title"))
    if title and title != business and title not in labels:
        labels.append(title)
    return labels or [title or business]


def _source_fingerprint(records: Iterable[dict]) -> str:
    rows = sorted(f"{r['page_id']}:{r['content_sha256']}" for r in records)
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()


def build_mapping(records: list[dict]) -> dict:
    concept_pages: dict[str, set[str]] = defaultdict(set)
    concept_labels: dict[str, str] = {}
    document_mappings = []

    for record in sorted(records, key=lambda r: r["page_id"]):
        business = _normalize_label(record.get("business_function"))
        if business not in SERVICES:
            raise ValueError(f"unknown business_function: {business!r}")
        service_id, _ = SERVICES[business]
        labels = _concept_labels(record)
        concept_ids = []
        for label in labels:
            concept_id = _concept_id(label)
            concept_ids.append(concept_id)
            concept_labels[concept_id] = label
            concept_pages[concept_id].add(record["page_id"])

        document_mappings.append({
            "page_id": record["page_id"],
            "document_id": f"document:{record['page_id']}",
            "business_domain": business,
            "service_ids": [service_id],
            "concept_ids": concept_ids,
            "content_sha256": record["content_sha256"],
            "mapping": {
                "method": "deterministic_metadata_v1",
                "source_fields": ["business_function", "sub_category", "page_title"],
                "review_status": "unreviewed",
            },
        })

    services = [
        {
            "id": service_id,
            "label": label,
            "business_domain": business,
            "document_count": sum(1 for r in records if r.get("business_function") == business),
        }
        for business, (service_id, label) in SERVICES.items()
    ]
    concepts = [
        {
            "id": concept_id,
            "label": concept_labels[concept_id],
            "document_count": len(concept_pages[concept_id]),
            "page_ids": sorted(concept_pages[concept_id]),
        }
        for concept_id in sorted(concept_labels)
    ]

    result = {
        "schema_version": "1.0.0",
        "ontology_version": "0.1.0",
        "status": "metadata_mapped_unreviewed",
        "source": {
            "path": "data/corpus.jsonl",
            "document_count": len(records),
            "content_set_sha256": _source_fingerprint(records),
        },
        "services": services,
        "concepts": concepts,
        "document_mappings": document_mappings,
    }
    validate_mapping(result)
    return result


def validate_mapping(mapping: dict) -> None:
    documents = mapping["document_mappings"]
    if mapping["source"]["document_count"] != len(documents):
        raise ValueError("source document_count does not match document_mappings")
    if len(documents) != EXPECTED_DOCUMENT_COUNT:
        raise ValueError(f"expected {EXPECTED_DOCUMENT_COUNT} documents, got {len(documents)}")

    page_ids = [d["page_id"] for d in documents]
    if len(page_ids) != len(set(page_ids)):
        raise ValueError("duplicate page_id in document mappings")
    if set(d["business_domain"] for d in documents) != set(SERVICES):
        raise ValueError("mapped business domains do not match the six controlled values")

    service_ids = {s["id"] for s in mapping["services"]}
    concept_ids = {c["id"] for c in mapping["concepts"]}
    for document in documents:
        if not set(document["service_ids"]) <= service_ids:
            raise ValueError(f"unknown service in {document['page_id']}")
        if not document["concept_ids"] or not set(document["concept_ids"]) <= concept_ids:
            raise ValueError(f"invalid concepts in {document['page_id']}")
        if not re.fullmatch(r"[0-9a-f]{64}", document["content_sha256"]):
            raise ValueError(f"invalid content hash in {document['page_id']}")

    mapped_counts = Counter(d["business_domain"] for d in documents)
    declared_counts = {s["business_domain"]: s["document_count"] for s in mapping["services"]}
    if dict(mapped_counts) != declared_counts:
        raise ValueError("service document counts do not match mappings")


def serialize(mapping: dict) -> str:
    return json.dumps(mapping, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the checked-in map is stale")
    args = parser.parse_args()
    generated = serialize(build_mapping(load_corpus()))

    if args.check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != generated:
            raise SystemExit("ontology mapping is stale; run build_ontology_map.py")
        print("ontology mapping is current: 58 documents")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(generated, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT_PATH}: 58 documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
