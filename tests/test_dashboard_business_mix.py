"""AD-001 업무별 분포 — rag_runs 에 업무 컬럼이 없어 종전엔 빈 배열만 나갔다.

원천은 **답변이 실제로 인용한 문서**다(observation.subs[].top[0].page_id →
documents.business_function). 질문 문구로 추측하지 않는다는 규칙은 그대로 지키면서,
이미 쌓여 있는 근거를 세기만 한다.

여기서 지키려는 것은 조인이다 — page_id 규약이나 observation 모양이 바뀌면 쿼리는
아무 오류 없이 **행이 0개**가 되고, 화면은 다시 '분류된 업무가 없습니다'로 조용히 돌아간다.
그래서 내가 넣은 한 건이 그 업무 칸에서 +1 로 잡히는지를 본다(다른 행이 같이 세어지므로
절대값이 아니라 증분을 본다 — 팀이 공유하는 실 DB다).
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "api", ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _counts(session, sql, window):
    return {label: count for label, count in session.execute(sql, window).all()}


def test_a_cited_page_lands_in_its_business_function(db_session, test_prefix, db_cleanup):
    from sqlalchemy import select

    from api.routers.admin_dashboard import BUSINESS_MIX_SQL, _today_window
    from schema import documents, rag_runs

    db_cleanup(rag_runs, rag_runs.c.session_id)
    page_id, business = db_session.execute(
        select(documents.c.page_id, documents.c.business_function)
        .where(documents.c.business_function.isnot(None)).limit(1)
    ).one()

    start, end = _today_window(datetime.now(timezone.utc))
    window = {"start": start, "end": end}
    before = _counts(db_session, BUSINESS_MIX_SQL, window)

    db_session.execute(rag_runs.insert(), {
        "question": "업무별 분포 조인 확인",
        "session_id": test_prefix + "sess",
        "request_id": test_prefix + uuid.uuid4().hex,
        "observation": {"subs": [{"top": [{"chunk_id": f"{page_id}#0", "page_id": page_id}]}]},
    })
    db_session.commit()

    after = _counts(db_session, BUSINESS_MIX_SQL, window)
    assert after.get(business, 0) == before.get(business, 0) + 1


def test_runs_without_a_request_id_are_out_of_the_population(db_session, test_prefix, db_cleanup):
    """대화 로그와 같은 모집단이어야 한다 — 상세로 열 수 없는 기록은 세지 않는다."""
    from sqlalchemy import select

    from api.routers.admin_dashboard import BUSINESS_MIX_SQL, _today_window
    from schema import documents, rag_runs

    db_cleanup(rag_runs, rag_runs.c.session_id)
    page_id = db_session.execute(
        select(documents.c.page_id).where(documents.c.business_function.isnot(None)).limit(1)
    ).scalar_one()

    window = dict(zip(("start", "end"), _today_window(datetime.now(timezone.utc))))
    before = _counts(db_session, BUSINESS_MIX_SQL, window)

    db_session.execute(rag_runs.insert(), {
        "question": "request_id 없는 기록",
        "session_id": test_prefix + "sess",
        "observation": {"subs": [{"top": [{"chunk_id": f"{page_id}#0", "page_id": page_id}]}]},
    })
    db_session.commit()

    assert _counts(db_session, BUSINESS_MIX_SQL, window) == before
