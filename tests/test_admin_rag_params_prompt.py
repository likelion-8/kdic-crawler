"""AD-007 RAG 파라미터 + AD-008 프롬프트 계약 테스트(DB·네트워크 없음).

계약 정본은 프론트 파일 두 개다 — rag/api.ts · promptops/api.ts. 여기서는 그 계약의
축이 되는 서버 로직을 검사한다:

    1) 파라미터 검증(메타 범위·타입) — 읽는 쪽(runtime_config)은 타입 검사를 안 하므로
       여기가 뚫리면 잘못된 값이 파이프라인에 그대로 들어간다
    2) 초안 지문 — '평가 후 수정'을 실제로 잡아내는가(무효화의 근거)
    3) apply 409 — 현재 적용값 전문(extra.current)을 싣는가(화면이 '이전 버전 유지'를 그림)
    4) 프롬프트 분해/조립 — **마커 규칙(잠금 원칙)이 어떤 편집에도 살아남는가** ← 최중요.
       출처 부착·사후 판정(source_check) 전체가 이 마커에 걸려 있다
    5) 마스킹 정규식 서버 판정 — 과대 매칭(답변 핵심 숫자를 잡아먹는 패턴) 거부
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.errors import BadRequestError, ForbiddenError
from api.routers import admin_prompt, admin_rag_params
from api.routers.admin_prompt import (PROTECTED_SAMPLES, assemble_instruction,
                                      split_instruction, validate_masking_rule)
from api.routers.admin_rag_params import (ParamsConflictError, build_gate,
                                          draft_signature, validate_params)

sys.path.insert(0, str(ROOT / "src"))
import prompt_builder  # noqa: E402


def _admin(role="ADMIN"):
    return SimpleNamespace(email="test_admin@example.com", role=role,
                           last_auth_at=datetime.now(timezone.utc))


# ------------------------------------------------- 1) 파라미터 검증
def test_unknown_param_is_rejected():
    with pytest.raises(BadRequestError):
        validate_params({"fusion_alpha": 0.5})   # 의도적으로 미노출(핫스왑 불가 — 재시작 필요)


def test_out_of_range_and_wrong_type_are_rejected():
    with pytest.raises(BadRequestError):
        validate_params({"k_candidates": 500})          # max 50
    with pytest.raises(BadRequestError):
        validate_params({"min_top1_score": 1.5})        # max 1.0
    with pytest.raises(BadRequestError):
        validate_params({"use_reranker": "yes"})        # toggle 은 bool
    with pytest.raises(BadRequestError):
        validate_params({"k_final": True})              # bool 은 숫자로 위장 못 함


def test_valid_params_pass_through():
    cleaned = validate_params({"k_candidates": 30, "min_top1_score": 0.4, "use_reranker": True})
    assert cleaned == {"k_candidates": 30, "min_top1_score": 0.4, "use_reranker": True}


# ------------------------------------------------- 2) 지문
def test_signature_is_order_independent_but_value_sensitive():
    a = draft_signature({"k_final": 5, "k_candidates": 20})
    b = draft_signature({"k_candidates": 20, "k_final": 5})
    c = draft_signature({"k_candidates": 21, "k_final": 5})
    assert a == b and a != c


# ------------------------------------------------- 3) 게이트(RagGate 모양)
def test_gate_before_evaluation_is_blocked():
    gate = build_gate()
    assert gate["passed"] is False and gate["warning_reason"]
    assert gate["smoke_total"] == 0     # 생성 Smoke 는 재지 않는다 — 30/30 을 지어내지 않는다


def test_gate_passes_only_when_both_axes_clear():
    ok = build_gate(current_metrics={"retrieval_accuracy@5": 0.90, "mrr": 0.75},
                    draft_metrics={"retrieval_accuracy@5": 0.93, "mrr": 0.81,
                                   "holdout_passed": 83},
                    signature="sig", evaluated_at="t", holdout_total=89)
    assert ok["passed"] is True
    assert ok["quantitative"]["improved"] == 2      # 두 축 모두 현행보다 나아짐(실측 a/b)
    low = build_gate(current_metrics={"retrieval_accuracy@5": 0.93, "mrr": 0.81},
                     draft_metrics={"retrieval_accuracy@5": 0.93, "mrr": 0.79,
                                    "holdout_passed": 83},
                     signature="sig", evaluated_at="t", holdout_total=89)
    assert low["passed"] is False and "MRR" in low["warning_reason"]


# ------------------------------------------------- 4) apply 409 + 현재값 전문
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
    db = _FakeDb([_Result(None), _Result(None)])   # draft 없음 -> current 없음(_effective)
    with pytest.raises(ParamsConflictError) as exc:
        admin_rag_params.apply_draft(
            {"request_id": "r1", "reason": "테스트"}, None, _admin("EDITOR"), db)
    current = exc.value.extra["current"]
    assert current["k_candidates"] == 20 and current["k_final"] == 5
    assert current["min_top1_score"] == pytest.approx(0.35)
    assert db.commits == 0                          # 거절 경로에서 아무것도 쓰지 않는다


def test_apply_with_stale_signature_warns_instead_of_blocking():
    """2026-08-19 정책 변경 — 지문 불일치·게이트 미달은 반영을 막지 않고 경고로만 남는다."""
    draft = SimpleNamespace(id="d1", version=3, params={"k_final": 4},
                            draft_signature=draft_signature({"k_final": 4}),
                            evaluation_run_id="run-1")
    db = _FakeDb([_Result(None)])                   # evaluation_runs.gate 조회(판정 없음)
    warnings = admin_rag_params.compute_gate_warnings(
        db, draft, {"draft": {"k_final": 5}})       # 평가본과 다른 초안
    assert "평가 이후 초안 수정됨(재평가 없이 반영)" in warnings
    assert "게이트 미달 상태로 반영" in warnings


def test_apply_without_evaluation_warns_instead_of_blocking():
    draft = SimpleNamespace(id="d1", version=3, params={"k_final": 4},
                            draft_signature=None, evaluation_run_id=None)
    assert admin_rag_params.compute_gate_warnings(_FakeDb([]), draft, {}) == ["초안 평가 없이 반영"]


def test_apply_requires_editor_and_reason():
    with pytest.raises(ForbiddenError):
        admin_rag_params.apply_draft(
            {"request_id": "r1", "reason": "x"}, None, _admin("VIEWER"), _FakeDb([]))
    with pytest.raises(BadRequestError):
        admin_rag_params.apply_draft({"request_id": "r1"}, None, _admin("EDITOR"), _FakeDb([]))


# ------------------------------------------------- 5) 프롬프트 분해/조립 — 마커 규칙 생존
def test_split_extracts_locked_marker_rule():
    header, principles, locked = split_instruction(prompt_builder.SYSTEM_INSTRUCTION)
    assert "[SOURCE_USED]" in locked                 # 마커 규칙이 잠금으로 분리된다
    assert all("[SOURCE_USED]" not in p for p in principles)
    assert len(principles) == 6                      # 편집 가능 원칙 6개(코드 상수 기준)
    assert header.startswith("당신은 예금보험공사")


def test_roundtrip_preserves_full_instruction():
    header, principles, locked = split_instruction(prompt_builder.SYSTEM_INSTRUCTION)
    rebuilt = assemble_instruction(header, principles, locked)
    # 재조립본이 원본과 의미상 동일해야 한다(번호·본문 모두)
    assert rebuilt == prompt_builder.SYSTEM_INSTRUCTION


def test_assemble_reappends_locked_rule_even_if_client_drops_it():
    header, principles, locked = split_instruction(prompt_builder.SYSTEM_INSTRUCTION)
    # 클라이언트가 원칙 두 개만 남기고 마커 규칙 없이 보내도 —
    rebuilt = assemble_instruction(header, principles[:2], locked)
    assert "[SOURCE_USED]" in rebuilt                # 서버가 무조건 다시 붙인다
    assert rebuilt.rstrip().split("\n")[-1].startswith("3. ")   # 마지막 번호로


# ------------------------------------------------- 6) 긴급 롤백 권한
def test_emergency_rollback_requires_admin_role():
    with pytest.raises(ForbiddenError):
        admin_prompt.emergency_rollback("v1.1", {"request_id": "r1", "reason": "x"},
                                        None, _admin("EDITOR"), _FakeDb([]))


# ------------------------------------------------- 7) 마스킹 검증
def test_masking_validate_flags_syntax_error():
    out = validate_masking_rule({"pattern": "[미닫힘"}, _admin("EDITOR"))
    assert out["passed"] is False and "문법 오류" in out["message"]


def test_masking_validate_flags_overmatching_digits():
    out = validate_masking_rule({"pattern": r"\d+"}, _admin("EDITOR"))
    assert out["passed"] is False and "과대 매칭" in out["message"]
    assert out["sample_count"] == len(PROTECTED_SAMPLES)


def test_masking_validate_passes_specific_phone_pattern():
    out = validate_masking_rule({"pattern": r"01[016789]-\d{3,4}-\d{4}"}, _admin("EDITOR"))
    assert out["passed"] is True


def test_masking_validate_requires_editor():
    with pytest.raises(ForbiddenError):
        validate_masking_rule({"pattern": r"\d+"}, _admin("VIEWER"))
