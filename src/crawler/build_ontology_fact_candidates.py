"""Extract source-grounded numeric/temporal fact candidates for ontology review.

This is a review queue, not an automatic truth generator. It only keeps values that
appear literally in corpus text and preserves the page hash and a source snippet.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

try:  # direct script execution from src/crawler
    from .build_ontology_map import CORPUS_PATH, load_corpus
except ImportError:  # noqa: E402 - preserves the repository's flat-script convention
    from build_ontology_map import CORPUS_PATH, load_corpus


ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_PATH = ROOT / "ontology" / "kdic-fact-candidates.json"

PATTERNS = (
    ("monetary", re.compile(r"(?<!\d)(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:억원|만원|원|천원|백만원|조원)")),
    ("percentage", re.compile(r"(?<!\d)(?:\d+(?:\.\d+)?)\s*%")),
    ("date", re.compile(r"(?<!\d)\d{4}[./-]\d{1,2}[./-]\d{1,2}(?!\d)")),
    ("temporal", re.compile(r"(?<!\d)\d+\s*(?:년|개월|일|주|분기|시간)(?:\s*(?:이내|동안|까지|후|전))?")),
)


def _candidate_id(page_id: str, kind: str, value: str, context: str) -> str:
    raw = f"{page_id}|{kind}|{value}|{context}".encode("utf-8")
    return "candidate:" + hashlib.sha256(raw).hexdigest()[:20]


def build_candidates(records: list[dict]) -> dict:
    candidates = []
    seen = set()
    for record in sorted(records, key=lambda row: row["page_id"]):
        for line in str(record.get("text") or "").splitlines():
            context = re.sub(r"\s+", " ", line).strip()
            if not context:
                continue
            for kind, pattern in PATTERNS:
                for match in pattern.finditer(context):
                    value = match.group(0).strip()
                    key = (record["page_id"], kind, value, context)
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append({
                        "id": _candidate_id(record["page_id"], kind, value, context),
                        "subject": {"type": "Document", "id": f"document:{record['page_id']}"},
                        "predicate": "has_claim_candidate",
                        "object": {"type": "Literal", "value": value, "candidate_type": kind},
                        "evidence": {
                            "page_id": record["page_id"],
                            "content_sha256": record["content_sha256"],
                            "context": context[:400],
                        },
                        "status": "proposed",
                        "review_status": "unreviewed",
                        "extraction_method": "literal_regex_v1",
                    })

    return {
        "schema_version": "1.0.0",
        "ontology_version": "0.1.0",
        "status": "proposed_candidates",
        "source": {
            "path": "data/corpus.jsonl",
            "document_count": len(records),
        },
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def serialize(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    payload = build_candidates(load_corpus(CORPUS_PATH))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(serialize(payload), encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT_PATH}: {payload['candidate_count']} proposed candidates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
