"""testset_all.jsonl(골든셋) → evaluation_dataset, testset_pipeline.jsonl(held-out 평가셋)
→ test_set 적재.

**JSONL이 단일 진실원천이다(2026-08-19).** 트랜잭션 안에서 테이블을 통째로 비우고 다시
넣는다. upsert만 있던 종전에는 JSONL에서 문항을 지워도 DB 행이 영구히 남았다 — 골든셋
검증으로 중복·오라벨 문항을 걷어내도 query_classifier의 1-NN 참조셋에는 그대로 살아 있어,
"고쳤다"고 생각한 것이 실제로는 반영되지 않았다.

delete를 피했던 종전 근거는 "나중에 evaluation_results가 이 행의 id를 FK로 물게 되는데
delete+insert는 새 UUID를 만들어 그 FK를 끊는다"였다. 그 예측은 실현되지 않았다 —
evaluation_results는 evaluation_runs.id를 물고(schema_admin.py), 문항 편집은 testset_items로
갔다. 실제 DB를 조회해도 evaluation_dataset/test_set을 참조하는 FK는 0건이고, 코드 어디에서도
이 행의 id를 읽지 않는다(question·label·embedding만 읽는다). 그래서 교체가 안전하다.

is_active로 끄는 방식(soft delete)도 가능하지만 상태가 둘이 되어 "DB와 JSONL 중 어느 쪽이
맞나"가 다시 애매해진다. 교체는 상태가 하나뿐이라 그 질문이 생기지 않는다. 관리자 화면
(AD-006)은 골든셋을 건드리지 않으므로(2026-08-19 격리, 커밋 3159d86) 이 로더가 유일한
기록자이고, 화면 조작과 경합하지 않는다.

evaluation_dataset에만 question 임베딩을 같이 넣는다 — query_classifier.py의
QuestionTypeClassifier가 로컬 JSONL+npy 캐시 대신 여기서 1-NN 참조 예시를 읽도록
바꿀 것이라(팀 결정), evaluation_dataset.embedding이 그 원천이 된다. test_set은 그 용도가
없어 임베딩을 안 넣는다.

⚠️ 참조셋 반영에는 **API 프로세스 재시작**이 필요하다 — QuestionTypeClassifier는 참조셋을
프로세스 시작 시 한 번만 메모리에 올리고 그 뒤로 DB를 다시 안 본다. 같은 프로세스 안이라면
query_classifier.invalidate_classifiers()로 캐시를 비울 수 있으나, 이 스크립트는 별도
프로세스라 그 훅이 API에 닿지 않는다.

실행: python3 src/crawler/index_evaluation_sets.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from db import get_engine  # noqa: E402
from retrieval import DenseRetriever  # noqa: E402
from schema import evaluation_dataset, test_set  # noqa: E402

from sqlalchemy import delete, func, insert, select  # noqa: E402

_FIELDS = ("question_type", "intent", "business_function", "reference_answer",
           "expected_sources", "must_include", "must_not_include", "expected_links")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _rows(records, with_embedding=False):
    # is_active를 True로 못박는 이유: 교체 방식이라 JSONL에 있는 문항은 예외 없이 활성이다.
    # 컬럼 기본값에 맡기지 않고 명시해, reference_stmt()의 is_active 필터가 무엇을 보는지
    # 이 파일만 읽어도 드러나게 한다.
    rows = [{"question_id": r["test_id"], "question": r["question"], "is_active": True,
              **{k: r.get(k) for k in _FIELDS}} for r in records]
    if with_embedding:
        qids = [r["question_id"] for r in rows]
        questions = [r["question"] for r in rows]
        dense = DenseRetriever(qids, questions)  # 캐시 있으면 재사용, 없으면 인코딩
        for row, vec in zip(rows, dense.doc_emb):
            row["embedding"] = vec.tolist()
    return rows


def _replace(conn, table, rows):
    """테이블을 JSONL 내용으로 통째로 교체. 반환: (이전 행수, 새 행수).

    같은 트랜잭션 안에서 삭제·삽입하므로 조회 중인 프로세스에 빈 테이블이 보이지 않는다.
    rows가 비면 중단한다 — 경로 오타나 읽기 실패로 테이블이 통째로 날아가는 사고를 막는다.
    정상적으로 전건 삭제할 일은 없다."""
    if not rows:
        raise SystemExit(f"{table.name}: 적재할 행이 없습니다 — JSONL 경로·내용을 확인하세요.")
    before = conn.execute(select(func.count()).select_from(table)).scalar_one()
    conn.execute(delete(table))
    conn.execute(insert(table).values(rows))
    return before, len(rows)


def main():
    golden_rows = _rows(_load(ROOT / "data" / "testset" / "testset_all.jsonl"), with_embedding=True)
    test_rows = _rows(_load(ROOT / "data" / "testset" / "testset_pipeline.jsonl"))

    engine = get_engine()
    with engine.begin() as conn:
        g_before, g_after = _replace(conn, evaluation_dataset, golden_rows)
        t_before, t_after = _replace(conn, test_set, test_rows)

    print(f"적재 완료: evaluation_dataset {g_before} -> {g_after}행, "
          f"test_set {t_before} -> {t_after}행")
    print("⚠️ 참조셋 반영에는 API 프로세스 재시작이 필요합니다 "
          "(QuestionTypeClassifier가 시작 시 한 번만 읽습니다).")


if __name__ == "__main__":
    sys.exit(main())
