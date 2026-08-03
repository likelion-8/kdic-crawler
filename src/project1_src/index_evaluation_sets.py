"""testset_all.jsonl(골든셋) → golden_set, testset_pipeline.jsonl(held-out 평가셋)
→ test_set 적재.

question_id(=test_id) 기준 upsert(ON CONFLICT DO UPDATE)를 쓴다 — document_chunks처럼
통째로 지우고 다시 넣으면 안 된다. 나중에 evaluation_results가 이 행의 id를 FK로
물게 되는데, delete+insert는 매번 새 UUID를 만들어 그 FK를 끊어버린다.

실행: python3 src/project1_src/index_evaluation_sets.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from db import get_engine  # noqa: E402
from schema import golden_set, test_set  # noqa: E402

from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402

_FIELDS = ("question_type", "intent", "business_function", "reference_answer",
           "expected_sources", "must_include", "must_not_include", "expected_links")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _rows(records):
    return [{"question_id": r["test_id"], "question": r["question"],
              **{k: r.get(k) for k in _FIELDS}} for r in records]


def _upsert(conn, table, rows):
    if not rows:
        return
    stmt = pg_insert(table).values(rows)
    update_cols = {k: stmt.excluded[k] for k in rows[0] if k != "question_id"}
    conn.execute(stmt.on_conflict_do_update(index_elements=["question_id"], set_=update_cols))


def main():
    golden_rows = _rows(_load(ROOT / "data" / "testset" / "testset_all.jsonl"))
    test_rows = _rows(_load(ROOT / "data" / "testset" / "testset_pipeline.jsonl"))

    engine = get_engine()
    with engine.begin() as conn:
        _upsert(conn, golden_set, golden_rows)
        _upsert(conn, test_set, test_rows)

    print(f"적재 완료: golden_set {len(golden_rows)}행, test_set {len(test_rows)}행")


if __name__ == "__main__":
    sys.exit(main())
