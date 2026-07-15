"""통합 테스트셋(data/testset/testset_all.jsonl) 일관성 검증.

실행: python src/validate_testset.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYS = ["test_id", "question", "question_type", "business_function", "expected_sources",
        "must_include", "must_not_include", "expected_links", "reference_answer", "note"]
QUESTION_TYPES = {"fact", "faq", "table_lookup", "link_guide", "file_download", "out_of_scope"}


def main():
    corpus = {}
    with open(ROOT / "data/corpus.jsonl", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            corpus[d["page_id"]] = d["business_function"]

    errors = []
    seen_ids = set()
    with open(ROOT / "data/testset/testset_all.jsonl", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            d = json.loads(line)
            where = f"L{n} {d.get('test_id')}"
            if list(d.keys()) != KEYS:
                errors.append(f"{where}: 필드 구성/순서 불일치 {list(d.keys())}")
            if d["test_id"] in seen_ids:
                errors.append(f"{where}: test_id 중복")
            seen_ids.add(d["test_id"])
            if d["question_type"] not in QUESTION_TYPES:
                errors.append(f"{where}: 알 수 없는 question_type={d['question_type']}")
            for src in d["expected_sources"]:
                if src not in corpus:
                    errors.append(f"{where}: corpus에 없는 doc_id={src}")
                elif corpus[src] != d["business_function"]:
                    errors.append(f"{where}: business_function={d['business_function']} != corpus({src})={corpus[src]}")
            # out_of_scope는 코퍼스로 답할 수 없는 질문이므로 출처가 없어야 한다
            if (d["question_type"] == "out_of_scope") != (not d["expected_sources"]):
                errors.append(f"{where}: out_of_scope와 expected_sources가 어긋남")

    for e in errors:
        print(e)
    print(f"{len(seen_ids)}건 검증, 오류 {len(errors)}건")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
