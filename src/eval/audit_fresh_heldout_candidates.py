"""Inventory existing testsets for fresh ontology-assist held-out eligibility.

Only aggregate metadata and overlap counts are written. Question text is never emitted.
No existing set becomes eligible without the provenance fields required by the fresh
held-out protocol.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

try:
    from .validate_fresh_ontology_assist_heldout import REQUIRED_FIELDS, normalize
except ImportError:  # direct script execution
    from validate_fresh_ontology_assist_heldout import REQUIRED_FIELDS, normalize


ROOT = Path(__file__).resolve().parent.parent.parent
TESTSET_DIR = ROOT / "data" / "testset"
FROZEN_PATH = TESTSET_DIR / "testset_pipeline.jsonl"
OUTPUT_PATH = ROOT / "results" / "ontology" / "fresh_heldout_candidate_inventory.json"
REVIEW_PATH = ROOT / "ontology" / "review" / "FRESH_HELDOUT_CANDIDATE_INVENTORY.md"


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def inspect_rows(path: Path, rows: list[dict], frozen_ids: set[str], frozen_questions: set[str]) -> dict:
    field_presence = {field: sum(field in row and row[field] not in (None, "", []) for row in rows) for field in REQUIRED_FIELDS}
    ids = [row.get("test_id") for row in rows if isinstance(row.get("test_id"), str)]
    questions = [normalize(row["question"]) for row in rows if isinstance(row.get("question"), str)]
    id_overlap = len(set(ids) & frozen_ids)
    question_overlap = len(set(questions) & frozen_questions)
    missing_provenance = sorted(field for field in ("query_form", "authored_by", "authored_at") if field_presence[field] != len(rows))
    reasons = []
    if path == FROZEN_PATH:
        reasons.append("currently_used_as_frozen_ontology_assist_heldout")
    if id_overlap:
        reasons.append("test_id_overlaps_frozen_heldout")
    if question_overlap:
        reasons.append("normalized_question_overlaps_frozen_heldout")
    if missing_provenance:
        reasons.append("missing_required_fresh_holdout_provenance")
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "row_count": len(rows),
        "answerable_count": sum(bool(row.get("expected_sources")) for row in rows),
        "question_type_counts": dict(sorted(Counter(row.get("question_type", "") for row in rows).items())),
        "required_field_presence": dict(sorted(field_presence.items())),
        "frozen_test_id_overlap_count": id_overlap,
        "frozen_normalized_question_overlap_count": question_overlap,
        "fresh_heldout_eligible": not reasons,
        "ineligible_reasons": reasons,
    }


def build_inventory(paths: list[Path]) -> dict:
    frozen_rows = load_jsonl(FROZEN_PATH)
    frozen_ids = {row["test_id"] for row in frozen_rows}
    frozen_questions = {normalize(row["question"]) for row in frozen_rows}
    entries = [inspect_rows(path, load_jsonl(path), frozen_ids, frozen_questions) for path in sorted(paths)]
    return {
        "schema_version": "1.0.0",
        "status": "metadata_inventory_only_no_fresh_heldout_selected",
        "production_impact": "none",
        "llm_calls": 0,
        "database_calls": 0,
        "policy": {
            "question_text_emitted": False,
            "automatic_fresh_heldout_selection": False,
            "fresh_heldout_requires_protocol_validation": True,
        },
        "summary": {
            "testset_files_inspected": len(entries),
            "fresh_heldout_eligible_files": sum(item["fresh_heldout_eligible"] for item in entries),
        },
        "testsets": entries,
    }


def serialize(inventory: dict) -> str:
    return json.dumps(inventory, ensure_ascii=False, indent=2) + "\n"


def build_review_markdown(inventory: dict) -> str:
    lines = [
        "# 기존 Testset의 새 Held-out 후보 점검", "",
        "> 이 문서는 질문 원문을 출력하지 않는 메타데이터 점검 결과입니다. 어떤 기존 세트도 자동 선택하지 않습니다.",
        "> 새 held-out은 `FRESH_HELDOUT_EVALUATION_PROTOCOL.md`의 작성자·날짜·질문 형태·중복 검증을 모두 통과해야 합니다.", "",
        "| 파일 | 문항 | 정답 보유 | ID 중복 | 질문 중복 | fresh held-out 사용 가능 | 사유 |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for item in inventory["testsets"]:
        reasons = ", ".join(item["ineligible_reasons"]) or "-"
        lines.append(
            f"| `{item['path']}` | {item['row_count']} | {item['answerable_count']} | "
            f"{item['frozen_test_id_overlap_count']} | {item['frozen_normalized_question_overlap_count']} | "
            f"`{item['fresh_heldout_eligible']}` | {reasons} |"
        )
    lines += [
        "", "## 다음 조치", "",
        "- 표에 `false`인 기존 세트는 이 평가에 재사용하지 않습니다.",
        "- 독립 작성자가 새 JSONL을 작성한 뒤 `validate_fresh_ontology_assist_heldout.py`로 반입 검증합니다.",
        "- 검증 통과 전에는 ontology 보조 규칙을 바꾸거나 운영 검색에 적용하지 않습니다.",
    ]
    return "\n".join(lines) + "\n"


def generate() -> tuple[str, str]:
    inventory = build_inventory(list(TESTSET_DIR.glob("testset_*.jsonl")))
    return serialize(inventory), build_review_markdown(inventory)


def write_or_check(check: bool) -> int:
    inventory, review = generate()
    outputs = ((OUTPUT_PATH, inventory), (REVIEW_PATH, review))
    if check:
        stale = [path for path, content in outputs if not path.exists() or path.read_text(encoding="utf-8") != content]
        if stale:
            for path in stale:
                print(f"out of date: {path.relative_to(ROOT)}")
            return 1
        print("up to date: fresh held-out candidate inventory")
        return 0
    for path, content in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote: {path.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    return write_or_check(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
