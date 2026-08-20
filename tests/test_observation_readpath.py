"""관측을 읽는 두 화면이 실제로 값을 받는지 — AD-005 상세 · AD-006 후보 자동 채움.

쓰는 쪽(observation.build)은 tests/test_observation.py 가 지킨다. 여기서는 **읽는 쪽이 그 값을
화면 계약까지 실어 보내는지**만 본다. 이 둘이 끊기면 컬럼에는 값이 쌓이는데 관리자 화면은
여전히 null 을 봐서, 고쳤다고 착각한 채 진단 루프가 계속 끊겨 있게 된다.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "api", ROOT / "src"):
    sys.path.insert(0, str(p))

from api.deps import get_current_admin, get_db  # noqa: E402
from api.main import create_app  # noqa: E402

OBSERVATION = {"subs": [{
    "question": "예금자보호 한도가 얼마인가요?",
    "intent": "informational",
    "top": [
        {"chunk_id": "dp_protlmts#0", "page_id": "dp_protlmts", "score": 0.87},
        {"chunk_id": "dp_protlmts#1", "page_id": "dp_protlmts", "score": 0.81},
        {"chunk_id": "dp_faq_page#0", "page_id": "dp_faq_page", "score": 0.64},
    ],
    "marker": True, "used_source": True, "kind": "grounded",
    "appropriate": True, "normalized": False,
}]}


class _Result:
    def __init__(self, row=None, rows=None, scalar=None):
        self._row, self._rows, self._scalar = row, rows or [], scalar

    def first(self):
        return self._row

    def all(self):
        return self._rows

    def scalar_one(self):
        return self._scalar

    def scalar(self):
        return self._scalar


class _FakeDb:
    def __init__(self, *results):
        self.results = list(results)

    def execute(self, _statement):
        return self.results.pop(0) if self.results else _Result()

    def commit(self):
        pass

    def rollback(self):
        pass


# get_log 는 조회 사실을 먼저 활동 로그에 적는다(CM-DF-002 07절) — 그 execute 가 결과 하나를
# 먹으므로 앞에 자리끼를 하나 둔다. 이 규약이 바뀌면 여기가 먼저 깨져서 알려준다.
ACTIVITY_WRITE = _Result()


def _client(db, role="ADMIN"):
    app = create_app()
    app.dependency_overrides[get_current_admin] = lambda: SimpleNamespace(
        # 감사 기록(admin_activity_logs)은 추가 전용이라 지울 수 없다 — test_ 접두어로
        # 실재 계정과 구분되게 한다(conftest 모듈 주석)
        role=role, email="test_admin@demo", name="admin")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _log_row(observation):
    return SimpleNamespace(
        request_id="req_obs", created_at=datetime.now(timezone.utc),
        question="예금자보호 한도가 얼마인가요?", answer="1억원까지 보호됩니다.",
        intent="informational", question_type="fact", status="NORMAL",
        failure_stage=None, root_cause=None, total_latency_ms=5200,
        trace_id=None, observation=observation,
        triage="NONE", triage_reason=None, triaged_by=None, triaged_at=None,
        vote=None, reason_codes=None, comment=None, feedback_at=None)


# ─────────────────────────── AD-005 상세 ───────────────────────────

def test_detail_fills_the_four_fields_from_observation():
    """종전에 항상 null 이던 값들이 관측에서 채워진다 — 진단의 재료."""
    with _client(_FakeDb(ACTIVITY_WRITE, _Result(row=_log_row(OBSERVATION)))) as client:
        body = client.get("/api/admin/logs/req_obs").json()

    assert body["source_count"] == 2, "같은 페이지의 청크 2개는 출처 1개"
    c = body["classification"]
    assert c["source_used"] is True
    assert c["marker"] == "[SOURCE_USED]"
    assert c["normalized"] is False
    assert [t["page_id"] for t in body["observation"]["subs"][0]["top"]] == [
        "dp_protlmts", "dp_protlmts", "dp_faq_page"]


def test_detail_of_pre_observation_run_stays_null():
    """관측 신설 이전에 쌓인 대화는 종전과 똑같이 '모름'이어야 한다 — 0/false 로 지어내지 않는다."""
    with _client(_FakeDb(ACTIVITY_WRITE, _Result(row=_log_row(None)))) as client:
        body = client.get("/api/admin/logs/req_obs").json()

    assert body["source_count"] is None
    assert body["observation"] is None
    c = body["classification"]
    assert c["source_used"] is None and c["marker"] is None and c["normalized"] is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
