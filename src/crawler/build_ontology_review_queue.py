"""Build a human review queue for turning metadata labels into ontology concepts.

The v1 document/concept map is intentionally generated from corpus metadata. It is
useful as an inventory, but its labels are not automatically safe query-expansion
terms. This script creates an auditable, source-linked queue for a domain reviewer.
It never reads the held-out test set and does not change runtime retrieval.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
MAP_PATH = ROOT / "ontology" / "kdic-document-concept-map.json"
CORPUS_PATH = ROOT / "data" / "corpus.jsonl"
OUTPUT_PATH = ROOT / "ontology" / "review" / "CONCEPT_REVIEW_QUEUE.md"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_corpus(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8") as f:
        return {row["page_id"]: row for line in f if (row := json.loads(line))}


def priority(document_count: int) -> str:
    if document_count >= 3:
        return "P1"
    if document_count == 2:
        return "P2"
    return "P3"


def markdown_safe(value: str) -> str:
    return value.replace("`", "\\`").replace("\n", " ").strip()


def build_queue(mapping: dict, corpus: dict[str, dict]) -> str:
    services = {service["id"]: service["label"] for service in mapping["services"]}
    documents = {document["page_id"]: document for document in mapping["document_mappings"]}
    concept_services: dict[str, set[str]] = defaultdict(set)
    for document in mapping["document_mappings"]:
        for concept_id in document["concept_ids"]:
            concept_services[concept_id].update(document["service_ids"])

    concepts = sorted(
        mapping["concepts"],
        key=lambda concept: (-concept["document_count"], concept["label"], concept["id"]),
    )
    lines = [
        "# KDIC Ontology Concept Review Queue",
        "",
        "Generated from the v1 metadata map. Every item is `proposed`; it is not a runtime query term, a fact, or a production retrieval filter.",
        "",
        "## Scope and review rules",
        "",
        "1. Review from the linked official pages only. Do not use `data/testset` or its results to choose labels or synonyms.",
        "2. Accept a label only when it represents a stable KDIC domain concept, task, rule, or status. Reject navigation-only and overly broad labels.",
        "3. Record a canonical label, a concept kind, and any synonyms separately. Synonyms require an official-page citation.",
        "4. Keep `page_id` and `content_sha256` as the evidence pointer. If the corpus hash changes, review the item again.",
        "5. Only entries explicitly marked `approved` in a future curated source may be evaluated as retrieval hints; no automatic promotion is allowed.",
        "",
        "Suggested concept kinds: `Service`, `Eligibility`, `Procedure`, `RequiredDocument`, `Deadline`, `MonetaryRule`, `Organization`, `Policy`, `Status`, `ContactChannel`.",
        "",
        "## Queue",
        "",
        f"- Concepts: {len(concepts)}",
        f"- Source documents: {len(documents)}",
        "- Priority: P1 = used by 3+ documents; P2 = used by 2 documents; P3 = one document.",
        "",
    ]
    for number, concept in enumerate(concepts, start=1):
        concept_id = concept["id"]
        page_ids = concept["page_ids"]
        service_labels = sorted(services[service_id] for service_id in concept_services[concept_id])
        lines.extend([
            f"## {priority(concept['document_count'])}-{number:03d} · `{concept_id}`",
            "",
            f"- Metadata label: `{markdown_safe(concept['label'])}`",
            f"- Evidence usage: {concept['document_count']} document(s); service(s): {', '.join(f'`{markdown_safe(label)}`' for label in service_labels)}",
            "- Review status: `proposed`",
            "- Decision: `pending` (`approved` | `rejected` | `needs_split`)",
            "- Canonical label: ",
            "- Concept kind: ",
            "- Synonyms (with page evidence): ",
            "- Review note: ",
            "- Evidence:",
        ])
        for page_id in page_ids:
            source = corpus[page_id]
            document = documents[page_id]
            lines.extend([
                f"  - `{page_id}` — {markdown_safe(source['page_title'])}",
                f"    - URL: {source['source_url']}",
                f"    - content_sha256: `{document['content_sha256']}`",
            ])
        lines.append("")
    return "\n".join(lines) + "\n"


def write_or_check(check: bool) -> int:
    output = build_queue(load_json(MAP_PATH), load_corpus(CORPUS_PATH))
    if check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != output:
            print(f"out of date: {OUTPUT_PATH.relative_to(ROOT)}")
            return 1
        print(f"up to date: {OUTPUT_PATH.relative_to(ROOT)}")
        return 0
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(output, encoding="utf-8", newline="\n")
    print(f"wrote: {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the generated queue is out of date")
    return write_or_check(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
