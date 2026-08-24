"""AD-001 대시보드 + AD-009 운영 정책 계약 테스트(DB·네트워크 없음)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import Request
from sqlalchemy.dialects import postgresql

from api.errors import BadRequestError, ForbiddenError
from api.routers import admin_dashboard, admin_ops


def _request():
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def _admin(role="ADMIN", *, fresh=True):
    return SimpleNamespace(
        email="test_admin@example.com",
        role=role,
        last_auth_at=datetime.now(timezone.utc) - (timedelta(minutes=1) if fresh else timedelta(hours=1)),
    )


class Result:
    def __init__(self, value=None, *, rowcount=0):
        self.value = value
        self.rowcount = rowcount

    def scalar_one(self):
        return self.value

    def first(self):
        return self.value

    def all(self):
        return self.value

    def scalars(self):
        return self


class FakeDb:
    def __init__(self, results):
        self.results = list(results)
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement, params=None):
        self.executed.append((statement, params))
        if not self.results:
            raise AssertionError(f"예상하지 않은 DB 호출: {statement}")
        return self.results.pop(0)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


# ---------------------------------------------------------------- Dashboard


def test_dashboard_routes_are_exactly_the_three_contract_routes():
    paths = {route.path for route in admin_dashboard.router.routes}
    assert paths == {
        "/api/admin/dashboard/summary",
        "/api/admin/dashboard/trend",
        "/api/admin/dashboard/resources",
    }


def test_dashboard_summary_maps_legacy_status_and_sets_service_cause():
    latest = SimpleNamespace(
        status="FAILED", created_at=datetime(2026, 8, 12, 1, tzinfo=timezone.utc))
    db = FakeDb([
        Result(58),
        Result(812),
        Result([("success", 3), ("FAILED", 1)]),
        Result(5400),
        Result([("informational", 3), ("civil_petition", 1)]),
        Result(latest),
        Result(1),
        Result(2),
        # 할 일 3종(2026-08-14) — 나쁨 평가 / 열린 작업 / 최근 게이트
        Result(7),
        Result(0),
        Result(SimpleNamespace(gate={"passed": False})),
    ])

    response = admin_dashboard.dashboard_summary(_admin(), db)

    assert response["kpi"]["questions_today"] == 4
    # 건수와 이동 대상이 짝을 이뤄야 카드를 눌렀을 때 서버가 센 것과 같은 목록이 열린다
    assert [(t["key"], t["count"], t["target"]["screen"]) for t in response["todos"]] == [
        ("FEEDBACK_DOWN", 7, "logs"),
        ("PIPELINE_OPEN", 0, "pipeline"),     # 0건이어도 항목이 사라지지 않는다
        ("GATE_FAILED", 1, "evaluations"),
    ]
    assert response["service"] == {
        "level": "ERROR",
        "error_count": 4,  # RAG 1 + pipeline 1 + 활동 로그 2
        "cause": "PIPELINE",
    }
    assert response["distribution"]["intent"] == {
        "informational": 75,
        "civil_petition": 25,
    }
    assert response["distribution"]["business"] == []
    assert "indicators" not in response
    assert [stage["name"] for stage in response["latency"]["stages"]] == list(
        admin_dashboard.LATENCY_STAGE_NAMES)
    assert len(response["latency"]["stages"]) == 8


def test_dashboard_trend_query_groups_by_kst_date():
    query = admin_dashboard.build_dashboard_trend_query(
        start=datetime(2026, 8, 1, tzinfo=timezone.utc),
        end=datetime(2026, 8, 8, tzinfo=timezone.utc),
    )
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "timezone" in sql
    assert "Asia/Seoul" in query.compile(dialect=postgresql.dialect()).params.values()
    assert "rag_runs.request_id IS NOT NULL" in sql


@pytest.mark.parametrize("value", [0, 1, 14, 91])
def test_dashboard_rejects_unsupported_ranges(value):
    with pytest.raises(BadRequestError):
        admin_dashboard._range_days(value)


def test_resources_do_not_invent_missing_token_or_cost_measurements():
    response = admin_dashboard.dashboard_resources(_admin(), object(), 30)
    assert response["range"] == 30
    assert response["tokens"] == []
    assert response["cost"] == []
    assert response["cost_breakdown"] == []
    assert response["today"]["tokens_text"] == "집계 원천 없음"


# ---------------------------------------------------------------- Ops policy


def test_ops_routes_are_exactly_the_requested_endpoints():
    methods_and_paths = {
        (next(iter(route.methods - {"HEAD"})), route.path)
        for route in admin_ops.router.routes
    }
    assert methods_and_paths == {
        ("GET", "/api/admin/ops-policy"),
        ("PUT", "/api/admin/ops-policy"),
        ("GET", "/api/admin/cache/stats"),
        # 2026-08-20 추가: 화면이 비울 항목을 목록에서 고른다(AD-009 §4). 종전에는 질의를
        # 손으로 받아쓰게 해서, 캐시에 실제로 있는 질의인지 확인할 방법이 없었다.
        ("GET", "/api/admin/cache/entries"),
        ("POST", "/api/admin/cache/purge"),
        ("GET", "/api/admin/blocks"),
        ("POST", "/api/admin/blocks/{block_id}/release"),
        # 2026-08-12 추가: 화면 fetchSuggestedQuestions() 의 편집 시작점. PUT 만 있어
        # 405 가 나던 구멍을 전수 스모크에서 발견해 메웠다(원래 8종 계약 + 1).
        ("GET", "/api/admin/suggested-questions"),
        ("PUT", "/api/admin/suggested-questions"),
        ("POST", "/api/admin/suggested-questions/validate"),
        # 답변 매핑(AD-009)은 2026-08-14 추가됐다가 2026-08-19 Gate 1 이식과 함께 서빙 경로
        # (curated_get)를 파이프라인에서 없애면서 이 CRUD 도 함께 걷어냈다(9종 유지).
    }


def test_policy_patch_creates_a_version_then_writes_audit(monkeypatch):
    current = SimpleNamespace(version=2, policy=dict(admin_ops.DEFAULT_POLICY))
    db = FakeDb([Result(current), Result()])
    captured = {}

    def capture(log_db, log_request, **values):
        assert log_db is db
        assert db.commits == 1
        captured.update(values)

    monkeypatch.setattr(admin_ops, "write_activity_log", capture)
    response = admin_ops.update_ops_policy(
        {"ip_per_min": 12, "reason": "테스트 정책 조정", "request_id": "test_req_policy"},
        _request(), _admin(), db,
    )

    assert response["version"] == "v3.0"
    assert response["ip_per_min"] == 12
    assert response["burst_per_10s"] == admin_ops.DEFAULT_POLICY["burst_per_10s"]
    assert captured["actor"].startswith("test_")
    assert captured["action"] == admin_ops.ACTION_POLICY_UPDATE
    assert captured["detail"] == {"version": 3, "changed_fields": ["ip_per_min"]}


def test_policy_rejects_read_only_burst_and_stale_reauth():
    with pytest.raises(BadRequestError):
        admin_ops.update_ops_policy(
            {"burst_per_10s": 4, "reason": "테스트", "request_id": "test_req"},
            _request(), _admin(), FakeDb([]),
        )
    with pytest.raises(ForbiddenError):
        admin_ops.update_ops_policy(
            {"ip_per_min": 12, "reason": "테스트", "request_id": "test_req"},
            _request(), _admin(fresh=False), FakeDb([]),
        )


# ---------------------------------------------------------------- Cache


def test_cache_question_normalization_collapses_spaces_and_ellipsis():
    variants = [
        "착오송금   반환은?",
        " 착오송금 반환은?… ",
        "착오송금\n반환은?...",
    ]
    assert len({admin_ops.cache_key_for_question(value) for value in variants}) == 1


def test_query_cache_purge_commits_before_audit_and_uses_normalized_hash(monkeypatch):
    aggregate = SimpleNamespace(entries=2, hits=3)
    db = FakeDb([Result(rowcount=1), Result(aggregate), Result(None)])
    captured = {}

    def capture(log_db, log_request, **values):
        assert db.commits == 1
        captured.update(values)

    monkeypatch.setattr(admin_ops, "write_activity_log", capture)
    response = admin_ops.purge_cache(
        {"query": "착오송금   반환은?…", "reason": "테스트 캐시 정리",
         "request_id": "test_req_cache"},
        _request(), _admin(role="OPERATOR"), db, "query",
    )

    compiled = db.executed[0][0].compile(dialect=postgresql.dialect())
    assert admin_ops.cache_key_for_question("착오송금 반환은?") in compiled.params.values()
    assert response["removed"] == 1
    assert response["hit_rate"] == 0.6
    assert captured["action"] == admin_ops.ACTION_CACHE_PURGE


def test_cache_entries_lists_active_rows_with_page_envelope():
    row = SimpleNamespace(
        cache_key="a" * 64,
        question="착오송금 반환은 얼마나 걸리나요?",
        hit_count=12,
        created_at=datetime(2026, 8, 19, 1, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 8, 20, 1, 0, tzinfo=timezone.utc),
    )
    db = FakeDb([Result(7), Result([row])])

    response = admin_ops.list_cache_entries(_admin(role="VIEWER"), db, 1, 20)

    assert response["total"] == 7
    assert response["page"] == 1
    assert response["items"] == [{
        "cache_key": "a" * 64,
        "question": "착오송금 반환은 얼마나 걸리나요?",
        "hit_count": 12,
        "created_at": "2026-08-19T10:00:00+09:00",
        "expires_at": "2026-08-20T10:00:00+09:00",
    }]
    # 만료된 행은 stats의 '캐시 항목'에서 빠지므로 목록에서도 빠져야 한다 — 두 수치가 갈리면 안 된다
    compiled = str(db.executed[1][0].compile(dialect=postgresql.dialect()))
    assert "expires_at IS NULL OR query_cache.expires_at >" in compiled


def test_query_cache_purge_accepts_selected_cache_keys(monkeypatch):
    keys = ["a" * 64, "b" * 64]
    selected = [SimpleNamespace(cache_key=keys[0], question="착오송금 반환은?"),
                SimpleNamespace(cache_key=keys[1], question="예금보험 한도는?")]
    aggregate = SimpleNamespace(entries=0, hits=0)
    db = FakeDb([Result(selected), Result(rowcount=2), Result(aggregate), Result(None)])
    captured = {}

    monkeypatch.setattr(admin_ops, "write_activity_log",
                        lambda log_db, log_request, **values: captured.update(values))
    response = admin_ops.purge_cache(
        {"cache_keys": keys, "reason": "선택 정리", "request_id": "test_req_multi"},
        _request(), _admin(role="OPERATOR"), db, "query",
    )

    assert response["removed"] == 2
    # 감사 로그가 키 해시만 남기면 나중에 무엇을 지웠는지 읽을 수 없다 — 질의 원문을 남긴다
    assert captured["target"] == "착오송금 반환은? 외 1건"
    assert captured["detail"]["cache_keys"] == keys


def test_query_cache_purge_rejects_unknown_cache_keys():
    db = FakeDb([Result([])])
    with pytest.raises(BadRequestError):
        admin_ops.purge_cache(
            {"cache_keys": ["c" * 64], "reason": "없는 키", "request_id": "test_req_gone"},
            _request(), _admin(role="OPERATOR"), db, "query",
        )


# ---------------------------------------------------------------- Blocks


def test_block_release_updates_in_place_then_audits(monkeypatch):
    block_id = "55555555-5555-5555-5555-555555555555"
    future = datetime.now(timezone.utc) + timedelta(minutes=10)
    existing = SimpleNamespace(
        id=block_id, target="211.34.x.x", target_kind="ip", reason="테스트",
        blocked_at=datetime.now(timezone.utc), expires_at=future,
        released_at=None, released_by=None,
    )
    released = SimpleNamespace(**{**vars(existing), "released_at": datetime.now(timezone.utc),
                                  "released_by": "test_admin@example.com"})
    db = FakeDb([Result(existing), Result(released)])
    captured = {}

    def capture(log_db, log_request, **values):
        assert db.commits == 1
        captured.update(values)

    monkeypatch.setattr(admin_ops, "write_activity_log", capture)
    response = admin_ops.release_block(
        block_id, {"reason": "테스트 수동 해제", "request_id": "test_req_release"},
        _request(), _admin(role="OPERATOR"), db,
    )
    assert response.status_code == 204
    assert captured["action"] == admin_ops.ACTION_BLOCK_RELEASE
    assert captured["target"].startswith("IP 211.34.x.x")


# ---------------------------------------------------------------- Suggested questions


def test_suggestions_replace_commits_before_audit_and_returns_null_clicks(monkeypatch):
    old = SimpleNamespace(
        id="sq_01", text="기존 질문", business_function="착오송금 반환 신청",
        active=True, display_order=1, click_count=412,
    )
    db = FakeDb([Result([old]), Result(), Result()])
    captured = {}

    def capture(log_db, log_request, **values):
        assert db.commits == 1
        captured.update(values)

    monkeypatch.setattr(admin_ops, "write_activity_log", capture)
    response = admin_ops.replace_suggested_questions(
        {
            "items": [{
                "id": "sq_01", "text": "새 질문", "business_function": "예금자보호제도",
                "active": True, "order": 1, "click_count": 999,
            }],
            "reason": "테스트 추천 질문 변경",
            "request_id": "test_req_suggestions",
        },
        _request(), _admin(role="EDITOR"), db,
    )
    assert response["items"][0]["click_count"] is None
    assert captured["action"] == admin_ops.ACTION_SUGGESTIONS_REPLACE


def test_suggestion_validation_reads_the_published_blocklist(monkeypatch):
    """판정 원천은 AD-008 게시본이다.

    2026-08-24 정정 — 종전에는 guardrail_rules 테이블을 읽었는데 그 표에 **쓰는 코드가 어디에도
    없어** 늘 0행이었다. 관리자가 AD-008 에서 무엇을 등록하든 이 검사는 통과했다. 지금은 챗
    경로와 같은 함수(api.rag.answer.guardrail_hit)를 쓴다 — 이 테스트가 깨지면 원천이 다시
    갈린 것이다.
    """
    import runtime_config
    monkeypatch.setattr(
        runtime_config, "get_prompt",
        lambda _k, _d: {"blocklist": {"active": True,
                                      "items": [{"pattern": "수익 보장", "type": "단어",
                                                 "scope": "질문 + 답변", "active": True}]}})
    blocked = admin_ops.validate_suggested_question(
        {"text": "수익 보장 상품이 있나요?", "business_function": "예금자보호제도"},
        _admin(role="EDITOR"), FakeDb([]),
    )
    assert blocked["passed"] is False
    assert "수익 보장" in blocked["message"]

    passing = admin_ops.validate_suggested_question(
        {"text": "예금자보호 한도는 얼마인가요?", "business_function": "예금자보호제도"},
        _admin(role="EDITOR"), FakeDb([]),
    )
    assert passing["passed"] is True


def test_suggestion_limits_are_enforced():
    too_many_active = [
        {"id": f"sq_{i}", "text": f"질문 {i}", "business_function": "예금자보호제도",
         "active": True, "order": i}
        for i in range(1, 12)
    ]
    with pytest.raises(BadRequestError):
        admin_ops._validate_suggestions(too_many_active)


def test_dashboard_todos_treat_never_measured_gate_as_zero():
    """게이트 기록이 없으면 '미통과'가 아니라 '아직 잰 적 없음'이다 — false 로 접으면 거짓 경보."""
    db = FakeDb([
        Result(58), Result(812), Result([]), Result(0), Result([]),
        Result(None), Result(0), Result(0),
        Result(0), Result(0), Result(None),     # 게이트 실행 기록 없음
    ])

    response = admin_dashboard.dashboard_summary(_admin(), db)

    gate = next(t for t in response["todos"] if t["key"] == "GATE_FAILED")
    assert gate["count"] == 0
