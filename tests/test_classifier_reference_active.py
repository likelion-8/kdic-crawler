"""1-NN 참조셋이 is_active 문항만 읽는지 — 관리자가 AD-006에서 끈 문항(잘못된 라벨)이
평가·화면에서는 빠지는데 운영 라우팅 참조로는 살아남던 구멍의 회귀 방지(2026-08-19).

DB 없이 조회문 컴파일로만 검사한다(test_admin_pipeline 의 SQL 컴파일 방식과 동일).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)


def test_reference_stmt_filters_is_active():
    from query_classifier import reference_stmt
    sql = str(reference_stmt("question_type").compile(compile_kwargs={"literal_binds": True}))
    assert "is_active" in sql                    # 관리자 제외 반영
    assert "cardinality" in sql                  # 기존 out_of_scope 제외도 유지


def test_invalidate_clears_cached_classifiers():
    import query_classifier
    query_classifier._classifiers["question_type"] = object()   # 재로드 대상 더미
    query_classifier.invalidate_classifiers()
    assert query_classifier._classifiers == {}


if __name__ == "__main__":
    test_reference_stmt_filters_is_active()
    test_invalidate_clears_cached_classifiers()
    print("classifier reference-active selfcheck: 통과")
