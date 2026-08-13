"""Derive conservative official label variants for canonical ontology entities.

Only corpus page titles and breadcrumb segments are considered. A label must be an
exact normalized variant of, or contain/be contained by, the canonical label. The
latter is marked contextual and must not be treated as an interchangeable synonym.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
CANONICAL_PATH = ROOT / "ontology" / "kdic-canonical-ontology-draft.json"
CORPUS_PATH = ROOT / "data" / "corpus.jsonl"
OUTPUT_PATH = ROOT / "ontology" / "kdic-official-label-aliases.json"
GENERIC = frozenset({"FAQ", "개요", "고객센터", "안내", "유의사항", "절차", "제도란", "신청방법", "상황선택", "소개"})


def alias_id(entity_id: str, label: str) -> str:
    digest = hashlib.sha256(f"{entity_id}\0{label}".encode("utf-8")).hexdigest()[:16]
    return f"alias:{digest}"


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.lower())


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_corpus(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8") as f:
        return {row["page_id"]: row for line in f if (row := json.loads(line))}


def candidate_labels(source: dict) -> list[str]:
    labels = [source["page_title"]]
    labels.extend(part.strip() for part in source["sub_category"].split(">"))
    return labels


def alias_type(alias: str, canonical: str) -> str | None:
    a, c = normalize(alias), normalize(canonical)
    if not a or alias in GENERIC or a == c and alias == canonical:
        return None
    if a == c:
        return "official_label_variant"
    if len(a) >= 4 and len(c) >= 4 and (a in c or c in a):
        return "contextual_label"
    return None


def build_aliases(canonical: dict, corpus: dict[str, dict]) -> dict:
    aliases = []
    for entity in canonical["entities"]:
        found: dict[tuple[str, str], set[str]] = {}
        for evidence in entity["evidence"]:
            page_id = evidence["page_id"]
            for label in candidate_labels(corpus[page_id]):
                kind = alias_type(label, entity["label"])
                if kind:
                    found.setdefault((label, kind), set()).add(page_id)
        for (label, kind), page_ids in sorted(found.items()):
            aliases.append({
                "id": alias_id(entity["id"], label),
                "entity_id": entity["id"],
                "canonical_label": entity["label"],
                "label": label,
                "alias_type": kind,
                "review_status": "source_verified_pending_domain_approval",
                "evidence_page_ids": sorted(page_ids),
            })
    aliases.sort(key=lambda item: (item["entity_id"], item["alias_type"], item["label"]))
    return {
        "schema_version": "1.0.0",
        "status": "official_aliases_pending_domain_approval",
        "production_impact": "none",
        "source": canonical["source"],
        "policies": {
            "source_fields": ["page_title", "sub_category"],
            "heldout_testset_used": False,
            "generated_user_phrases_allowed": False,
            "contextual_labels_are_synonyms": False,
            "runtime_use": "prohibited_until_domain_approval_and_evaluation",
        },
        "alias_count": len(aliases),
        "aliases": aliases,
    }


def serialize(output: dict) -> str:
    return json.dumps(output, ensure_ascii=False, indent=2) + "\n"


def write_or_check(check: bool) -> int:
    output = serialize(build_aliases(load_json(CANONICAL_PATH), load_corpus(CORPUS_PATH)))
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
