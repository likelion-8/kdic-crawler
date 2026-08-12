"""AD-007 RAG 파라미터 + AD-008 프롬프트 계약 테스트(DB·네트워크 없음).

test_admin_dashboard_ops.py 와 같은 방식 — FakeDb 로 라우터 함수를 직접 부른다.
가장 중요한 축 세 가지:

    1) 파라미터 검증이 메타(min/max/타입)를 실제로 지키는가 — 읽는 쪽(runtime_config)은
       타입 검사를 안 하므로 여기가 뚫리면 잘못된 값이 파이프라인에 그대로 들어간다
    2) apply 의 409 가 현재 적용값 전문을 싣는가(R3) — 화면이 '이전 버전 유지'를 그린다
    3) 초안 지문(signature)이 '평가 후 수정'을 실제로 잡아내는가(R2·M2)
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.errors import BadRequestError, ForbiddenError
from api.routers import admin_prompt, admin_rag_params
from api.routers.admin_prompt import (PROTECTED_SAMPLES, compute_dirty,
                                      content_signature, validate_masking_rule)
from api.routers.admin_rag_params import (ParamsConflictError, compute_gate,
                                          draft_signature, validate_params)


def _admin(role="ADMIN"):
    return SimpleNamespace(email="test_admin@example.com", role=role,
                           last_auth_at=datetime.now(timezone.utc))


# ------------------------------------------------- 1) 파라미터 검증(메타가 정본)
def test_unknown_param_is_rejected():
    with pytest.raises(BadRequestError):
        validate_params({"hybrid_linear_alpha": 0.5})   # 의도적으로 목록에서 뺀 값(핫스왑 불가)


def test_out_of_range_and_wrong_type_are_rejected():
    with pytest.raises(BadRequestError):
        validate_params({"k_candidates": 500})          # max 50
    with pytest.raises(BadRequestError):
        validate_params({"min_top1_score": 1.5})        # max 1.0
    with pytest.raises(BadRequestError):
        validate_params({"use_reranker": "yes"})        # bool 이어야 함
    with pytest.raises(BadRequestError):
        validate_params({"k_final": True})              # bool 은 int 로 위장 못 함


def test_valid_params_pass_through():
    cleaned = validate_params({"k_candidates": 30, "min_top1_score": 0.4, "use_reranker": True})
    assert cleaned == {"k_candidates": 30, "min_top1_score": 0.4, "use_reranker": True}


def test_empty_params_are_rejected():
    with pytest.raises(BadRequestError):
        validate_params({})


# ------------------------------------------------- 2) 지문(signature)
def test_signature_is_order_independent_but_value_sensitive():
    a = draft_signature({"k_final": 5, "k_candidates": 20})
    b = draft_signature({"k_candidates": 20, "k_final": 5})
    c = draft_signature({"k_candidates": 21, "k_final": 5})
    assert a == b          # 키 순서가 달라도 같은 내용이면 같은 지문
    assert a != c          # 값이 하나라도 다르면 다른 지문(평가 무효화의 근거)


def test_content_signature_detects_edit_after_evaluation():
    content = {"system_instruction": "안내", "few_shot": [], "guardrails": {}}
    sig = content_signature(content)
    content["system_instruction"] = "안내문 수정"
    assert content_signature(content) != sig


# ------------------------------------------------- 3) 게이트 계산
def test_gate_passes_only_when_both_axes_clear():
    ok = compute_gate({"retrieval_accuracy@5": 0.93, "mrr": 0.81})
    assert ok["passed"] is True
    low_mrr = compute_gate({"retrieval_accuracy@5": 0.93, "mrr": 0.79})
    assert low_mrr["passed"] is False
    # 재지 않은 축은 '해당 없음'으로 명시된다 — 값 없이 축만 실으면 화면이 '미달'로 오독한다
    assert "generation_success_rate" in ok["not_measured"]


# ------------------------------------------------- 4) apply 409 + 현재값 전문 (R3)
class _Result:
    def __init__(self, value=None):
        self.value = value

    def first(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalar(self):
        return self.value


class _FakeDb:
    """조회 결과를 순서대로 돌려준다. apply 의 409 경로는 쓰기 전에 끝나므로 commit 이 없어야 한다."""

    def __init__(self, results):
        self.results = list(results)
        self.commits = 0

    def execute(self, statement, params=None):
        if not self.results:
            raise AssertionError(f"예상하지 않은 DB 호출: {statement}")
        return self.results.pop(0)

    def commit(self):
        self.commits += 1


def test_apply_without_draft_is_409_with_current_values():
    # 조회 순서: draft(없음) -> _effective_params 의 current(없음)
    db = _FakeDb([_Result(None), _Result(None)])
    with pytest.raises(ParamsConflictError) as exc:
        admin_rag_params.apply_draft(
            {"request_id": "r1", "reason": "테스트"}, None, _admin("EDITOR"), db)
    # 409 본문에 현재 적용값 전문이 실린다(R3) — DB 가 비었으니 코드 기본값 그대로여야 한다
    current = exc.value.extra["current"]
    assert current["k_candidates"] == 20 and current["k_final"] == 5
    assert current["min_top1_score"] == pytest.approx(0.35)
    assert db.commits == 0     # 거절 경로에서 아무것도 쓰지 않는다


def test_apply_requires_reason():
    with pytest.raises(BadRequestError):
        admin_rag_params.apply_draft({"request_id": "r1"}, None, _admin("EDITOR"), _FakeDb([]))


def test_apply_requires_editor():
    with pytest.raises(ForbiddenError):
        admin_rag_params.apply_draft(
            {"request_id": "r1", "reason": "x"}, None, _admin("VIEWER"), _FakeDb([]))


def test_stale_signature_is_409():
    draft = SimpleNamespace(id="d1", version=3, params={"k_final": 4},
                            draft_signature=draft_signature({"k_final": 4}),
                            evaluation_run_id="run-1")
    # 조회 순서: draft -> _effective_params 의 current (지문 불일치라 run 조회 전에 끝난다)
    db = _FakeDb([_Result(draft), _Result(None)])
    with pytest.raises(ParamsConflictError):
        admin_rag_params.apply_draft(
            {"request_id": "r1", "reason": "x", "draft_signature": "다른지문"},
            None, _admin("EDITOR"), db)
    assert db.commits == 0


# ------------------------------------------------- 5) 프롬프트 초안 dirty (M2)
def test_dirty_flags_track_each_section_independently():
    base = {"system_instruction": "si", "few_shot": [{"question": "q", "answer": "a"}],
            "no_evidence_notice": "n", "guardrails": {"blocklist": {"items": []}}}
    same = compute_dirty(dict(base), base)
    assert same == {"prompt": False, "fewshot": False, "guardrail": False}
    edited = dict(base, system_instruction="si2")
    assert compute_dirty(edited, base)["prompt"] is True
    assert compute_dirty(edited, base)["fewshot"] is False


def test_draft_put_rejects_empty_system_instruction():
    db = _FakeDb([_Result(None), _Result(None)])   # baseline(게시본 없음) -> draft(없음)
    with pytest.raises(BadRequestError):
        admin_prompt.save_draft(
            {"request_id": "r1", "system_instruction": "   "}, _admin("EDITOR"), db)


def test_draft_put_rejects_unvalidated_masking_rule():
    db = _FakeDb([_Result(None), _Result(None)])
    with pytest.raises(BadRequestError):
        admin_prompt.save_draft(
            {"request_id": "r1", "system_instruction": "si",
             "guardrails": {"masking": {"items": [{"pattern": r"\d+", "validated": False}]}}},
            _admin("EDITOR"), db)


# ------------------------------------------------- 6) 긴급 롤백 권한(M5)
def test_emergency_rollback_requires_admin_role():
    with pytest.raises(ForbiddenError):
        admin_prompt.emergency_rollback({"request_id": "r1"}, None, _admin("EDITOR"), _FakeDb([]))


# ------------------------------------------------- 7) 마스킹 검증(M6)
def test_masking_validate_flags_syntax_error():
    out = validate_masking_rule({"pattern": "[미닫힘"}, _admin("EDITOR"))
    assert out["passed"] is False and "문법 오류" in out["message"]


def test_masking_validate_flags_overmatching_digits():
    # \d+ 는 "5,000만원"·"1332"·날짜를 전부 잡아먹는다 — 계좌번호 정규식을 금지한 팀 결정과
    # 같은 원칙이 서버 판정으로 강제되는지 확인한다
    out = validate_masking_rule({"pattern": r"\d+"}, _admin("EDITOR"))
    assert out["passed"] is False and "과대 매칭" in out["message"]
    assert out["sample_count"] == len(PROTECTED_SAMPLES)


def test_masking_validate_passes_specific_phone_pattern():
    out = validate_masking_rule({"pattern": r"01[016789]-\d{3,4}-\d{4}"}, _admin("EDITOR"))
    assert out["passed"] is True


def test_masking_validate_requires_editor():
    with pytest.raises(ForbiddenError):
        validate_masking_rule({"pattern": r"\d+"}, _admin("VIEWER"))
