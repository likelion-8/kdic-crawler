"""Gate3(검색 관련도 게이트) — 원본 dense top-1 후보가 저관련도/후보없음이면 HCX 생성·
OpenAI 사후검증을 아예 안 타고 즉시 고정응답으로 끝나는지 검증한다.

실제 OpenAI·HCX·Supabase·CrossEncoder는 하나도 부르지 않는다 — 전부 monkeypatch 대역이다.

네 계층으로 나눠 검사한다:
  1) candidate_ranking.gate3_exit()      — 순수 판정 함수(경계값 포함)
  2) api.rag.answer.prepare_sub()        — 웹 경로, SubPlan 필드·실행 순서
  3) api.rag.sse.chat_event_stream()     — 웹 경로 통합, 호출 카운트·단일/복합 질문
  4) pipeline._answer_one()              — CLI 경로, rerank 순서(원본 점수만 봐야 함)
"""
import queue as queue_mod
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "api", ROOT / "src"):
    sys.path.insert(0, str(p))

import candidate_ranking  # noqa: E402
import pipeline  # noqa: E402
from api.rag import answer as answer_mod  # noqa: E402
from api.rag import sse  # noqa: E402
from prompt_builder import NO_RELEVANT_EVIDENCE_MESSAGE, OUT_OF_SCOPE_MESSAGE  # noqa: E402

CAND_LOW = [("page_a#1", 0.34, "관련 없어 보이는 본문")]
CAND_BOUNDARY = [("page_a#1", 0.35, "경계값 본문")]
CAND_HIGH = [("page_a#1", 0.80, "실제로 관련된 본문"), ("page_a#2", 0.60, "본문2")]


# ════════════════════════ 1) candidate_ranking.gate3_exit — 순수 판정 ════════════════════════

def test_gate3_exit_below_threshold_is_exit():
    assert candidate_ranking.gate3_exit(CAND_LOW, threshold=0.35) is True


def test_gate3_exit_boundary_equal_is_exit():
    """요구사항이 '0.35 이하'라 경계값(정확히 threshold)도 EXIT — gate_low_relevance(<)와
    비교연산자가 다르다."""
    assert candidate_ranking.gate3_exit(CAND_BOUNDARY, threshold=0.35) is True


def test_gate3_exit_above_threshold_passes():
    assert candidate_ranking.gate3_exit(CAND_HIGH, threshold=0.35) is False


def test_gate3_exit_empty_candidates_is_exit():
    assert candidate_ranking.gate3_exit([], threshold=0.35) is True


def test_gate3_exit_reads_admin_threshold_when_none_given(monkeypatch):
    """threshold 를 안 넘기면 runtime_config.get_param("min_top1_score", ...)를 읽는다 —
    관리자 화면(AD-007) 변경값이 재시작 없이 반영되는 지점."""
    import runtime_config
    monkeypatch.setattr(runtime_config, "get_param", lambda k, d: 0.9 if k == "min_top1_score" else d)
    # candidates top-1=0.80 < 관리자값 0.9 → EXIT (코드 기본값 0.35였다면 통과했을 점수)
    assert candidate_ranking.gate3_exit(CAND_HIGH) is True


# ════════════════════════ 2) api.rag.answer.prepare_sub — 웹 경로 SubPlan ════════════════════════

@pytest.fixture
def dense_only(monkeypatch):
    """use_type_routing Off(기본) — Gate3가 실제로 적용되는 경로. 다른 키는 코드 기본값 그대로."""
    monkeypatch.setattr(answer_mod, "get_param",
                        lambda k, d: False if k == "use_type_routing" else d)


def test_prepare_sub_gate3_exit_low_score_fields(dense_only, monkeypatch):
    monkeypatch.setattr(answer_mod, "route_search_chunks", lambda q, k: CAND_LOW)

    sp = answer_mod.prepare_sub("아무 관련 없는 질문", intent="informational")

    assert sp.fixed_response == NO_RELEVANT_EVIDENCE_MESSAGE
    assert sp.exit_at == "gate3"
    assert sp.gate3_reason == "low_retrieval_relevance"
    assert sp.top == []
    assert sp.prompt is None, "Gate3 EXIT면 프롬프트를 준비할 필요가 없다(LLM 미호출)"
    assert sp.civil is None
    assert sp.evidence == ""
    assert sp.obs_used_source is False
    assert sp.retrieval_top1_score == pytest.approx(0.34)
    assert sp.retrieval_threshold == pytest.approx(0.35)


def test_prepare_sub_gate3_exit_no_candidates(dense_only, monkeypatch):
    """검색 결과 없음(candidates=[])도 동일한 Gate3 고정응답."""
    monkeypatch.setattr(answer_mod, "route_search_chunks", lambda q, k: [])

    sp = answer_mod.prepare_sub("아무 관련 없는 질문", intent="informational")

    assert sp.fixed_response == NO_RELEVANT_EVIDENCE_MESSAGE
    assert sp.exit_at == "gate3"
    assert sp.gate3_reason == "no_candidates"
    assert sp.retrieval_top1_score is None


def test_prepare_sub_gate3_passes_through_unchanged(dense_only, monkeypatch):
    """Top-1 > threshold면 기존 흐름(top_k_cut → 프롬프트 조립)이 그대로 유지된다."""
    monkeypatch.setattr(answer_mod, "route_search_chunks", lambda q, k: CAND_HIGH)

    sp = answer_mod.prepare_sub("착오송금 반환지원 신청 방법", intent="informational")

    assert sp.fixed_response is None
    assert sp.exit_at is None
    assert sp.top == CAND_HIGH[: len(sp.top)] or sp.top  # 비지 않음(top_k_cut 결과)
    assert sp.prompt is not None


def test_prepare_sub_calls_route_search_chunks_with_k_candidates_20(dense_only, monkeypatch):
    """Gate3 판정을 위해 route_search_chunks가 기존 k_candidates=20으로 호출됨(후보 수 유지)."""
    seen_k = []

    def fake_search(q, k):
        seen_k.append(k)
        return CAND_LOW

    monkeypatch.setattr(answer_mod, "route_search_chunks", fake_search)
    answer_mod.prepare_sub("아무 질문", intent="informational")

    assert seen_k == [20]


def test_prepare_sub_skips_gate3_when_hybrid_routing_on(monkeypatch):
    """use_type_routing이 켜지면 candidates가 Hybrid/RRF 점수일 수 있어 Gate3(dense 전용
    임계값)를 건너뛴다 — 점수가 낮아도 EXIT하지 않고 기존 흐름을 그대로 탄다."""
    monkeypatch.setattr(answer_mod, "get_param",
                        lambda k, d: True if k == "use_type_routing" else d)
    monkeypatch.setattr(answer_mod, "route_search_chunks", lambda q, k: CAND_LOW)

    sp = answer_mod.prepare_sub("아무 질문", intent="informational")

    assert sp.fixed_response is None, "hybrid 라우팅에서는 Gate3를 타면 안 된다"
    assert sp.top


def test_prepare_sub_admin_threshold_change_applies_to_next_call(dense_only, monkeypatch):
    """min_top1_score 변경값이 다음 요청에 반영된다(재시작 불필요)."""
    monkeypatch.setattr(answer_mod, "route_search_chunks", lambda q, k: [("p#1", 0.5, "본문")])
    state = {"threshold": 0.4}

    def get_param(k, d):
        if k == "min_top1_score":
            return state["threshold"]
        if k == "use_type_routing":
            return False
        return d

    monkeypatch.setattr(answer_mod, "get_param", get_param)

    sp1 = answer_mod.prepare_sub("질문", intent="informational")
    assert sp1.fixed_response is None, "0.5 > 0.4 통과"

    state["threshold"] = 0.6
    sp2 = answer_mod.prepare_sub("질문", intent="informational")
    assert sp2.fixed_response is not None, "관리자가 0.6으로 올리면 같은 0.5점 질문이 이제 EXIT"


# ════════════════════════ 3) api.rag.sse.chat_event_stream — 웹 경로 통합 ════════════════════════

def _fake_stream_one(prompt):
    q = queue_mod.Queue()
    q.put(("tok", "정상 생성된 답변입니다."))
    q.put(("end", None))
    return q


def _passthrough_finalize_sub(sp, body, marker_used_source):
    from api.schemas.chat import SubAnswer
    return SubAnswer(title=sp.question, answer=body, sources=[], attachments=[]), True


def _open_gates_no_cache(monkeypatch):
    monkeypatch.setattr(sse.answer, "guardrail_hit", lambda *a, **kw: None)
    monkeypatch.setattr(sse.answer, "cache_get", lambda _q: None)
    monkeypatch.setattr(sse.conversation, "recent_messages", lambda _s: [])
    monkeypatch.setattr(sse.conversation, "save_user_message", lambda *a: None)
    monkeypatch.setattr(sse.conversation, "save_assistant_message", lambda *a: None)
    monkeypatch.setattr(sse.answer, "log_run", lambda *a, **kw: None)
    monkeypatch.setattr(sse.answer, "cache_put", lambda *a: None)
    monkeypatch.setattr("observability.record_trace", lambda *a, **kw: "trace-1")
    monkeypatch.setattr("gate1.run_gate1", lambda _q: SimpleNamespace(
        action="CONTINUE", label="CONTINUE", rule_id=None, reason="no_rule_matched"))
    monkeypatch.setattr("gate2.run_gate2", lambda _q: SimpleNamespace(
        action="CONTINUE", s_id=0.9, s_ood=0.1, threshold=0.5,
        nearest_out_cluster_id=None, nearest_out_category=None, reason="in_domain"))
    monkeypatch.setattr("query_rewriter.triage_query", lambda q, h: SimpleNamespace(
        rewritten=False, standalone_question=q, needs_clarification=False))


@pytest.fixture
def call_counts(monkeypatch):
    """_stream_one·finalize_sub·validate_answer·call_hyperclova·rerank 호출 횟수를 센다."""
    counts = {"stream_one": 0, "finalize_sub": 0, "validate_answer": 0,
             "call_hyperclova": 0, "rerank": 0}

    def counting_stream_one(prompt):
        counts["stream_one"] += 1
        return _fake_stream_one(prompt)

    def counting_finalize_sub(sp, body, marker_used_source):
        counts["finalize_sub"] += 1
        return _passthrough_finalize_sub(sp, body, marker_used_source)

    def counting_validate_answer(*a):
        counts["validate_answer"] += 1
        return None

    def counting_call_hyperclova(*a):
        counts["call_hyperclova"] += 1
        return "본문"

    def counting_rerank(q, c):
        counts["rerank"] += 1
        return c

    monkeypatch.setattr(sse, "_stream_one", counting_stream_one)
    monkeypatch.setattr(sse.answer, "finalize_sub", counting_finalize_sub)
    monkeypatch.setattr(answer_mod, "validate_answer", counting_validate_answer)
    monkeypatch.setattr("llm_client.call_hyperclova", counting_call_hyperclova)
    monkeypatch.setattr(candidate_ranking, "rerank", counting_rerank)
    return counts


def _sp_gate3_exit(question):
    return answer_mod.SubPlan(
        question=question, intent="informational", top=[], prompt=None, civil=None,
        evidence="", fixed_response=NO_RELEVANT_EVIDENCE_MESSAGE, exit_at="gate3",
        gate3_reason="low_retrieval_relevance", retrieval_top1_score=0.34,
        retrieval_threshold=0.35, obs_used_source=False)


def _sp_gate3_pass(question):
    return answer_mod.SubPlan(
        question=question, intent="informational", top=CAND_HIGH,
        prompt=[("system", "sys"), ("human", "질문: " + question + "\n답변:")],
        civil=None, evidence="근거 텍스트")


def test_single_question_gate3_exit_makes_zero_llm_calls(call_counts, monkeypatch):
    """단일 질문 전부가 Gate3 EXIT — HCX 0회·OpenAI 사후검증 0회·rerank 0회, sources/attachments
    빈 배열, out_of_scope=true."""
    _open_gates_no_cache(monkeypatch)
    monkeypatch.setattr(sse.answer, "plan", lambda _q: sse.answer.Plan([("아무 관련 없는 질문", "informational")]))
    monkeypatch.setattr(sse.answer, "prepare_sub", lambda q, intent: _sp_gate3_exit(q))

    events = list(sse.chat_event_stream("아무 관련 없는 질문", "sess", "req"))

    assert call_counts == {"stream_one": 0, "finalize_sub": 0, "validate_answer": 0,
                            "call_hyperclova": 0, "rerank": 0}
    done = [e for e in events if "event: done" in e][0]
    import json
    payload = json.loads(done.split("data: ", 1)[1])
    assert payload["answer"] == NO_RELEVANT_EVIDENCE_MESSAGE
    assert payload["sources"] == []
    assert payload["attachments"] == []
    assert payload["out_of_scope"] is True


def test_single_question_gate3_pass_keeps_existing_generation_path(call_counts, monkeypatch):
    """Gate3 통과면 기존 HCX 생성·검증 경로가 그대로 유지된다(회귀 없음)."""
    _open_gates_no_cache(monkeypatch)
    monkeypatch.setattr(sse.answer, "plan",
                        lambda _q: sse.answer.Plan([("착오송금 반환지원 신청 방법", "informational")]))
    monkeypatch.setattr(sse.answer, "prepare_sub", lambda q, intent: _sp_gate3_pass(q))

    list(sse.chat_event_stream("착오송금 반환지원 신청 방법", "sess", "req"))

    assert call_counts["stream_one"] == 1
    assert call_counts["finalize_sub"] == 1


def test_composite_partial_gate3_only_gated_sub_is_fixed(call_counts, monkeypatch):
    """복합 질문 중 하나만 Gate3 EXIT — 그 하위만 고정응답, 통과한 하위는 기존 생성/검증
    실행, 전체 out_of_scope=false(A가 근거를 썼으므로)."""
    _open_gates_no_cache(monkeypatch)
    monkeypatch.setattr(sse.answer, "plan", lambda _q: sse.answer.Plan([
        ("착오송금 반환지원 신청 방법", "informational"),
        ("아무 관련 없는 질문", "informational"),
    ]))

    def fake_prepare(q, intent):
        return _sp_gate3_pass(q) if q == "착오송금 반환지원 신청 방법" else _sp_gate3_exit(q)

    monkeypatch.setattr(sse.answer, "prepare_sub", fake_prepare)

    events = list(sse.chat_event_stream("복합 질문", "sess", "req"))

    assert call_counts["stream_one"] == 1, "통과한 하위 A만 스트리밍한다"
    assert call_counts["finalize_sub"] == 1, "통과한 하위 A만 사후검증을 탄다"
    done = [e for e in events if "event: done" in e][0]
    import json
    payload = json.loads(done.split("data: ", 1)[1])
    assert payload["out_of_scope"] is False, "A가 근거를 썼으면 전체는 범위외가 아니다"
    sub_b = [s for s in payload["sub_answers"] if s["title"] == "아무 관련 없는 질문"][0]
    assert sub_b["answer"] == NO_RELEVANT_EVIDENCE_MESSAGE
    assert sub_b["sources"] == [] and sub_b["attachments"] == []


def test_composite_all_gate3_makes_zero_llm_calls(call_counts, monkeypatch):
    """복합 질문 전체가 Gate3 EXIT — HCX·검증 호출 0회, 전체 out_of_scope=true."""
    _open_gates_no_cache(monkeypatch)
    monkeypatch.setattr(sse.answer, "plan", lambda _q: sse.answer.Plan([
        ("아무 관련 없는 질문 1", "informational"),
        ("아무 관련 없는 질문 2", "informational"),
    ]))
    monkeypatch.setattr(sse.answer, "prepare_sub", lambda q, intent: _sp_gate3_exit(q))

    events = list(sse.chat_event_stream("복합 질문", "sess", "req"))

    assert call_counts == {"stream_one": 0, "finalize_sub": 0, "validate_answer": 0,
                            "call_hyperclova": 0, "rerank": 0}
    done = [e for e in events if "event: done" in e][0]
    import json
    payload = json.loads(done.split("data: ", 1)[1])
    assert payload["out_of_scope"] is True


def test_single_gate3_exit_is_recorded_as_served_from_gate3(monkeypatch):
    """단일 질문이 통째로 Gate3 EXIT면 served_from='gate3'로 기록한다."""
    _open_gates_no_cache(monkeypatch)
    captured = []
    monkeypatch.setattr(sse.answer, "log_run",
                        lambda *a, **kw: captured.append(kw.get("served_from")))
    monkeypatch.setattr(sse.answer, "plan",
                        lambda _q: sse.answer.Plan([("아무 관련 없는 질문", "informational")]))
    monkeypatch.setattr(sse.answer, "prepare_sub", lambda q, intent: _sp_gate3_exit(q))
    monkeypatch.setattr(sse, "_stream_one", _fake_stream_one)

    list(sse.chat_event_stream("아무 관련 없는 질문", "sess", "req"))

    assert captured == ["gate3"]


def test_composite_partial_gate3_does_not_overwrite_top_level_served_from(monkeypatch):
    """복합 질문 중 일부만 Gate3면 최상위 served_from을 gate3로 덮지 않는다(None으로 남는다) —
    그 정보는 observation의 하위 단위(exit_at)에 남긴다."""
    _open_gates_no_cache(monkeypatch)
    captured = []
    monkeypatch.setattr(sse.answer, "log_run",
                        lambda *a, **kw: captured.append(kw.get("served_from")))
    monkeypatch.setattr(sse.answer, "plan", lambda _q: sse.answer.Plan([
        ("착오송금 반환지원 신청 방법", "informational"),
        ("아무 관련 없는 질문", "informational"),
    ]))

    def fake_prepare(q, intent):
        return _sp_gate3_pass(q) if q == "착오송금 반환지원 신청 방법" else _sp_gate3_exit(q)

    monkeypatch.setattr(sse.answer, "prepare_sub", fake_prepare)
    monkeypatch.setattr(sse, "_stream_one", _fake_stream_one)
    monkeypatch.setattr(sse.answer, "finalize_sub", _passthrough_finalize_sub)

    list(sse.chat_event_stream("복합 질문", "sess", "req"))

    assert captured == [None]


def test_observation_records_gate3_fields_per_sub():
    """observation.build()가 exit_at/reason/점수/임계값을 하위 단위로 남긴다."""
    from api.rag import observation
    sp_exit = _sp_gate3_exit("범위밖 하위질문")
    sp_pass = _sp_gate3_pass("정상 하위질문")
    sp_pass.obs_used_source = True

    obs = observation.build([sp_pass, sp_exit])

    by_q = {s["question"]: s for s in obs["subs"]}
    assert by_q["범위밖 하위질문"]["exit_at"] == "gate3"
    assert by_q["범위밖 하위질문"]["gate3_reason"] == "low_retrieval_relevance"
    assert by_q["범위밖 하위질문"]["retrieval_top1_score"] == pytest.approx(0.34)
    assert by_q["범위밖 하위질문"]["retrieval_threshold"] == pytest.approx(0.35)
    assert by_q["정상 하위질문"]["exit_at"] is None


# ════════════════════════ 4) pipeline._answer_one — CLI 경로, rerank 순서 ════════════════════════

@pytest.fixture
def cli_dense_only_no_rerank_param(monkeypatch):
    """CLI 경로 공통 배선: use_type_routing Off, 그 외 get_param 은 코드 기본값(둘째 인자) 사용."""
    monkeypatch.setattr(pipeline, "get_param",
                        lambda k, d: False if k == "use_type_routing" else d)


def test_answer_one_gate3_exit_returns_fixed_message_no_llm(cli_dense_only_no_rerank_param, monkeypatch):
    monkeypatch.setattr(pipeline, "route_search_chunks", lambda q, k: CAND_LOW)
    calls = {"llm": 0, "validate": 0, "rerank": 0}
    monkeypatch.setattr(pipeline, "call_hyperclova", lambda p: calls.__setitem__("llm", calls["llm"] + 1))
    monkeypatch.setattr(pipeline, "validate_answer", lambda *a: calls.__setitem__("validate", calls["validate"] + 1))
    monkeypatch.setattr(pipeline, "rerank", lambda q, c: calls.__setitem__("rerank", calls["rerank"] + 1))

    result = pipeline._answer_one("아무 관련 없는 질문", {}, intent="informational")

    assert result == NO_RELEVANT_EVIDENCE_MESSAGE
    assert calls == {"llm": 0, "validate": 0, "rerank": 0}


def test_answer_one_gate3_exit_skips_rerank_even_when_reranker_enabled(monkeypatch):
    """Gate3 미달이면 리랭커 ON 설정이어도 rerank 호출 0회 — Gate3 통과 후에만 리랭킹."""
    monkeypatch.setattr(pipeline, "get_param", lambda k, d:
                        True if k == "use_reranker" else (False if k == "use_type_routing" else d))
    monkeypatch.setattr(pipeline, "route_search_chunks", lambda q, k: CAND_LOW)
    calls = {"rerank": 0}
    monkeypatch.setattr(pipeline, "rerank", lambda q, c: calls.__setitem__("rerank", calls["rerank"] + 1) or c)

    result = pipeline._answer_one("아무 관련 없는 질문", {}, intent="informational")

    assert result == NO_RELEVANT_EVIDENCE_MESSAGE
    assert calls["rerank"] == 0


def test_answer_one_gate3_uses_original_dense_score_not_reranked_score(monkeypatch):
    """rerank()가 훨씬 높은 점수로 덮어써도 Gate3 판정에 영향을 주면 안 된다 — 판정이 이미
    rerank 호출 전에 원본 점수로 끝나 있어야 한다(그래서 rerank 자체가 호출되지 않는다)."""
    monkeypatch.setattr(pipeline, "get_param", lambda k, d:
                        True if k == "use_reranker" else (False if k == "use_type_routing" else d))
    low_original = [("p#1", 0.30, "본문")]
    monkeypatch.setattr(pipeline, "route_search_chunks", lambda q, k: low_original)
    calls = {"rerank": 0}

    def fake_rerank_gives_high_score(q, c):
        calls["rerank"] += 1
        return [(cid, 0.95, text) for cid, _, text in c]   # cross-encoder가 후하게 줬다고 가정

    monkeypatch.setattr(pipeline, "rerank", fake_rerank_gives_high_score)

    result = pipeline._answer_one("질문", {}, intent="informational")

    assert result == NO_RELEVANT_EVIDENCE_MESSAGE
    assert calls["rerank"] == 0, "rerank가 불렸다면 Gate3가 원본 점수보다 먼저 결정하지 못한 것"


def test_answer_one_gate3_pass_runs_rerank_when_enabled(monkeypatch):
    """Gate3 통과 후에는 기존 리랭킹 경로가 그대로 실행된다."""
    monkeypatch.setattr(pipeline, "get_param", lambda k, d:
                        True if k == "use_reranker" else (False if k == "use_type_routing" else d))
    monkeypatch.setattr(pipeline, "route_search_chunks", lambda q, k: CAND_HIGH)
    calls = {"rerank": 0}

    def counting_rerank(q, c):
        calls["rerank"] += 1
        return c

    monkeypatch.setattr(pipeline, "rerank", counting_rerank)
    monkeypatch.setattr(pipeline, "format_all_citations", lambda ids: [])
    monkeypatch.setattr(pipeline, "call_hyperclova", lambda p: "[SOURCE_USED]\n생성된 답변")
    monkeypatch.setattr(pipeline, "validate_answer", lambda *a: None)

    result = pipeline._answer_one("착오송금 반환지원 신청 방법", {}, intent="informational")

    assert calls["rerank"] == 1
    assert result != NO_RELEVANT_EVIDENCE_MESSAGE


def test_answer_one_gate3_no_candidates_returns_fixed_message(cli_dense_only_no_rerank_param, monkeypatch):
    monkeypatch.setattr(pipeline, "route_search_chunks", lambda q, k: [])
    calls = {"llm": 0}
    monkeypatch.setattr(pipeline, "call_hyperclova", lambda p: calls.__setitem__("llm", calls["llm"] + 1))

    result = pipeline._answer_one("아무 관련 없는 질문", {}, intent="informational")

    assert result == NO_RELEVANT_EVIDENCE_MESSAGE
    assert calls["llm"] == 0


def test_answer_one_calls_route_search_chunks_with_k_candidates_20(cli_dense_only_no_rerank_param, monkeypatch):
    seen_k = []

    def fake_search(q, k):
        seen_k.append(k)
        return CAND_LOW

    monkeypatch.setattr(pipeline, "route_search_chunks", fake_search)
    pipeline._answer_one("아무 질문", {}, intent="informational")

    assert seen_k == [20]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
