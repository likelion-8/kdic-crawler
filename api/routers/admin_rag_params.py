"""RAG 파라미터(AD-007) — 초안 평가·A/B 검색·운영 반영·이력·롤백.

🔴 계약 정본은 web/src/routes/admin/settings/rag/api.ts 다. 핸드오프 문서(R1~R4)가 아니라
화면이 실제로 부르는 이 파일의 타입(RagParamsResponse·RagGate·AbSearchResponse·
RagHistoryEntry)에 응답 모양을 1:1로 맞춘다 — 처음 구현을 핸드오프 기준으로 했다가
필드명이 달라 화면이 통째로 비는 사고가 있었다(2026-08-12).

## 엔드포인트 6종 (전부 EDITOR 이상 쓰기 / 읽기는 로그인만)
    GET  /                      params 메타 + current + draft + gate
    POST /evaluate  {draft}     초안 저장 + held-out 검색 실측 -> RagGate
    POST /ab-search {query,draft}  현행(A) vs 초안(B) 검색 비교 -> AbSearchResponse
    POST /apply     {draft}+reason 운영 반영 -> RagParamsResponse(반영 후 전체 상태)
    GET  /history               버전 이력 -> Page<RagHistoryEntry>
    POST /history/{id}/rollback 그 시점 값으로 **초안만** 복원 -> {draft}

## 파라미터 메타는 서버가 정본이다

PARAM 목록의 key·label·control·범위를 서버가 내려주고 화면은 그대로 그린다 — 항목이
바뀌어도 프론트 재배포가 없다. default 는 호출 시점에 코드 상수를 읽는다(상수 주석의
실측 근거가 원본이라 숫자를 복사하면 두 곳이 어긋난다).

⚠️ HYBRID_LINEAR_ALPHA(융합 비중)는 노출하지 않는다 — 검색 엔진 싱글턴 조립 때 박히는
값이라 재시작 없이는 반영이 안 된다. 노출하면 "바꿨는데 그대로"가 된다.

## 평가는 검색 축 실측이다

held-out(test_set)의 expected_sources 로 **현행(A)과 초안(B)을 둘 다** 재서
hit@5 비율·MRR 을 비교한다(quantitative 의 a/b 가 실측값). 생성 Smoke 는 이 화면의
파라미터가 생성 품질을 직접 바꾸지 않아 재지 않는다 — smoke 0/0 + warning 으로 명시하고,
게이트 판정은 검색 두 축(정확도 0.92↑ · MRR 0.80↑)으로만 한다. 지어내지 않는다.

⚠️ 문항 수 × 2(A/B) 만큼 임베딩+pgvector 질의가 나가는 동기 작업(워밍업된 서버에서 1~2분).

## 반영·롤백과 runtime_config

apply 는 게이트 판정을 **막지 않고 경고로만** 남긴다(2026-08-19 정책 변경 — 종전에는
게이트 통과 + 지문 일치일 때만 승격했다). 반영 즉시 runtime_config.invalidate("params") — 같은 프로세스는 즉시,
CLI 는 TTL(60초) 내 반영. history 의 rollback 은 **초안 복원만** 한다(화면 계약 §1.7 —
실제 적용은 [운영 반영]이 다시 게이트를 거친다).
"""
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, insert, select, update

from api.deps import CurrentAdmin, DbSession, get_current_admin, write_activity_log
from api.errors import ApiError, BadRequestError, ForbiddenError, NotFoundError
# src/ 는 flat import(api/__init__.py 가 sys.path 에 넣는다).
import candidate_ranking
import pipeline
import query_planner
import runtime_config
from schema import documents, test_set
from schema_admin import evaluation_runs, rag_param_versions

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/rag-params",
    tags=["admin-rag-params"],
    dependencies=[Depends(get_current_admin)],
)

KST = timezone(timedelta(hours=9))
ROLE_RANK = {"VIEWER": 0, "OPERATOR": 1, "EDITOR": 2, "ADMIN": 3}

ACTION_EVALUATE = "RAG 파라미터 평가"
ACTION_APPLY = "RAG 파라미터 반영"
ACTION_ROLLBACK = "RAG 파라미터 초안 복원"

# 검색 게이트 임계값 — admin_evaluations.GATE_CRITERIA 의 검색 두 축과 같은 값.
GATE_ACCURACY = 0.92
GATE_MRR = 0.80


class ParamsConflictError(ApiError):
    """반영 불가(409). `extra` 로 현재 적용값 전문을 본문에 실어(errors.py extra 규약)
    화면이 '실패 시 이전 버전 유지'를 그대로 다시 그린다."""
    status_code = 409
    retryable = False


def _param_meta() -> list:
    """화면 계약(rag/api.ts RagParam) 모양의 메타 정본. default 는 여기서만 쓰는 내부 값이라
    응답의 params 배열에는 내보내지 않는다(현행값은 current 가 따로 든다)."""
    return [
        {"key": "k_candidates", "label": "1차 후보 수", "group": "retrieval",
         "control": "stepper", "apply_timing": "무중단",
         "min": 5, "max": 50, "step": 5, "default": pipeline.K_CANDIDATES,
         "note": "route_search_chunks 1차 후보 청크 수 (Recall@20 99%+ 실측)"},
        {"key": "k_final", "label": "최종 근거 수", "group": "retrieval",
         "control": "stepper", "apply_timing": "무중단",
         "min": 1, "max": 10, "step": 1, "default": pipeline.K_FINAL,
         "note": "LLM 에 넘기는 근거 청크 수 (AnswerRecall@5 기준과 동일 k)"},
        {"key": "min_top1_score", "label": "무관 질문 게이트 임계값", "group": "retrieval",
         "control": "slider", "apply_timing": "무중단",
         "min": 0.0, "max": 1.0, "step": 0.05, "default": candidate_ranking.MIN_TOP1_SCORE,
         "scale_start": "관대(통과 많음)", "scale_end": "엄격(차단 많음)",
         "note": "top-1 점수가 미만이면 근거를 비워 환각 차단 (0.35 = 인스코프 오차단 0 실측)"},
        {"key": "use_reranker", "label": "리랭커(cross-encoder)", "group": "retrieval",
         "control": "toggle", "apply_timing": "무중단",
         "default": pipeline.USE_RERANKER,
         "note": "CPU 문항당 96초 실측으로 기본 Off — GPU 확보 시 재검증(README 2.4)"},
        {"key": "use_query_planner", "label": "쿼리 플래너(분해+intent 한 콜)", "group": "retrieval",
         "control": "toggle", "apply_timing": "무중단",
         "default": query_planner.USE_QUERY_PLANNER,
         "note": "gpt-5.6-luna structured output (100문항 joint 89% 실측)"},
        {"key": "use_query_decomposition", "label": "복합 질문 분해(플래너 Off 폴백)",
         "group": "retrieval", "control": "toggle", "apply_timing": "무중단",
         "default": pipeline.USE_QUERY_DECOMPOSITION,
         "note": "플래너를 껐을 때만 쓰는 HCX 분해 경로"},
        {"key": "use_source_recheck", "label": "답변 사후 검증(전 답변 1콜)",
         "group": "generation", "control": "toggle", "apply_timing": "무중단",
         "default": pipeline.USE_SOURCE_RECHECK,
         "note": "근거 실사용·질문-답변 적절성을 별도 LLM 1콜로 검증(2026-08-14 확대) — Off 면 마커만 신뢰"},
    ]


def _require_editor(me: CurrentAdmin, what: str) -> None:
    if ROLE_RANK.get(me.role, -1) < ROLE_RANK["EDITOR"]:
        raise ForbiddenError(
            f"{what}에는 EDITOR 이상 권한이 필요합니다. 현재 권한은 {me.role}입니다.")


def validate_params(body_params: dict) -> dict:
    """초안 파라미터를 메타(범위·타입)로 검증해 정규화한다. 읽는 쪽(runtime_config)은 타입
    검사를 안 하므로 여기서 걸러지지 않은 값은 파이프라인에 그대로 들어간다."""
    meta = {m["key"]: m for m in _param_meta()}
    unknown = set(body_params) - set(meta)
    if unknown:
        raise BadRequestError(f"지원하지 않는 파라미터입니다: {', '.join(sorted(unknown))}")
    cleaned = {}
    for name, value in body_params.items():
        m = meta[name]
        if m["control"] == "toggle":
            if not isinstance(value, bool):
                raise BadRequestError(f"{name} 값은 true 또는 false여야 합니다.")
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise BadRequestError(f"{name} 값은 숫자여야 합니다.")
            if not (m["min"] <= value <= m["max"]):
                raise BadRequestError(f"{name} 값은 {m['min']}~{m['max']} 범위여야 합니다.")
            if m["control"] == "stepper":
                value = int(value)
        cleaned[name] = value
    if not cleaned:
        raise BadRequestError("변경할 파라미터를 하나 이상 보내 주세요.")
    return cleaned


def draft_signature(params: dict) -> str:
    """초안의 지문. '평가 이후 초안을 수정하면 평가 무효'(화면 Desc 0)를 판정하는 유일한
    근거라 키 정렬로 정규화한다 — 같은 내용이면 항상 같은 값."""
    canon = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def _row(db, status: str):
    return db.execute(
        select(rag_param_versions).where(rag_param_versions.c.status == status)
    ).first()


def _next_version(db) -> int:
    return (db.execute(select(func.max(rag_param_versions.c.version))).scalar_one() or 0) + 1


def _effective_params(db) -> dict:
    """현행 운영값 전문 = 코드 기본값 위에 current 행을 얹은 것 — 파이프라인이 실제로 읽는
    값과 같은 계산이다(runtime_config: DB 에 없으면 코드 상수)."""
    values = {m["key"]: m["default"] for m in _param_meta()}
    current = _row(db, "current")
    if current and current.params:
        values.update({k: v for k, v in dict(current.params).items() if k in values})
    return values


def _kst(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return aware.astimezone(KST).isoformat()


# ──────────────────────────────── 게이트(RagGate) ───────────────────────────

def build_gate(*, current_metrics: dict = None, draft_metrics: dict = None,
               signature: str = None, evaluated_at: str = None,
               holdout_total: int = 0) -> dict:
    """화면의 RagGate 모양을 만든다. 평가 전이면 passed=false + blocked_reason.

    smoke 는 0/0 으로 명시한다 — 이 화면의 파라미터는 생성 품질을 직접 바꾸지 않아 생성
    Smoke 를 재지 않는다(모듈 주석). 지어낸 30/30 을 넣으면 게이트가 거짓말을 한다.
    """
    if draft_metrics is None:
        return {"passed": False, "draft_signature": signature, "evaluated_at": None,
                "blocked_reason": "초안 평가를 먼저 실행해 주세요.", "warning": None,
                "holdout_total": 0, "holdout_passed": 0,
                "smoke_total": 0, "smoke_passed": 0, "quantitative": None}

    acc, mrr = draft_metrics["retrieval_accuracy@5"], draft_metrics["mrr"]
    passed = acc >= GATE_ACCURACY and mrr >= GATE_MRR
    blocked = None
    if not passed:
        parts = []
        if acc < GATE_ACCURACY:
            parts.append(f"검색 정확도@5 {acc:.3f} < {GATE_ACCURACY}")
        if mrr < GATE_MRR:
            parts.append(f"MRR {mrr:.3f} < {GATE_MRR}")
        blocked = "게이트 미달 — " + " · ".join(parts)

    warning = None
    quantitative = None
    if current_metrics is not None:
        a_acc, a_mrr = current_metrics["retrieval_accuracy@5"], current_metrics["mrr"]
        improved = sum(1 for a, b in ((a_acc, acc), (a_mrr, mrr)) if b > a)
        regressed = sum(1 for a, b in ((a_acc, acc), (a_mrr, mrr)) if b < a)
        quantitative = {
            "basis": f"held-out {holdout_total}문항 · 검색 축 2종 (A=현행, B=초안 실측)",
            "metrics": [
                {"label": "검색 정확도@5", "a": round(a_acc, 4), "b": round(acc, 4)},
                {"label": "MRR", "a": round(a_mrr, 4), "b": round(mrr, 4)},
            ],
            "improved": improved, "regressed": regressed,
            "recommendation": ("→ B(초안) 반영 가능" if passed and regressed == 0
                               else "→ A(현행) 유지 권장"),
        }
        if passed and regressed:
            warning = "게이트는 통과했지만 현행보다 낮아진 지표가 있습니다."
    if warning is None and passed:
        warning = "생성 Smoke 는 이 평가에서 재지 않습니다(검색 축만 실측)."

    return {"passed": passed, "draft_signature": signature, "evaluated_at": evaluated_at,
            "blocked_reason": blocked, "warning": warning,
            "holdout_total": holdout_total,
            "holdout_passed": draft_metrics.get("holdout_passed", 0),
            "smoke_total": 0, "smoke_passed": 0, "quantitative": quantitative}


def _stored_gate(db) -> dict:
    """저장된 초안 + 연결된 평가로 RagGate 를 복원한다(GET 응답용)."""
    draft = _row(db, "draft")
    if draft is None or draft.evaluation_run_id is None:
        return build_gate(signature=draft.draft_signature if draft else None)
    run = db.execute(
        select(evaluation_runs.c.gate, evaluation_runs.c.finished_at)
        .where(evaluation_runs.c.id == draft.evaluation_run_id)
    ).first()
    if not run or not run.gate:
        return build_gate(signature=draft.draft_signature)
    stored = dict(run.gate)
    stored["draft_signature"] = draft.draft_signature
    stored["evaluated_at"] = _kst(run.finished_at)
    return stored


# ──────────────────────────────── 검색 실측 ─────────────────────────────────

def _holdout_rows(db):
    # ⚠️ expected_sources 는 범위외 문항에서 **빈 배열**이다(NULL 아님). isnot(None) 만 걸면
    # 정답이 없는 문항이 '무조건 miss'로 섞여 정확도가 부당하게 깎인다(2026-08-12 실측 —
    # 0.786 vs 기준선 0.922 의 원인 중 하나). 원소가 1개 이상인 답변형 문항만 잰다
    # (eval_pipeline_retrieval 의 "expected_sources 있는 행만"과 동일).
    rows = db.execute(
        select(test_set.c.question, test_set.c.expected_sources)
        .where(test_set.c.is_active.is_(True),
               func.array_length(test_set.c.expected_sources, 1) >= 1)
        .order_by(test_set.c.question_id)
    ).all()
    if not rows:
        raise BadRequestError("평가할 held-out 문항이 없습니다(test_set 비어 있음).")
    return rows


def _search_pages(query: str, params: dict, *, for_scoring: bool = False) -> list:
    """초안/현행 파라미터로 실검색 -> 페이지 순위. eval_pipeline_retrieval 과 같은 규약
    (chunk_id 의 '#' 앞이 page_id, 같은 페이지 첫 등장 = 최고 순위).

    for_scoring=True 면 k_final 컷 **없이** 후보 전체(k_candidates)에서 페이지를 접는다 —
    기준선(0.922/0.806, retrieve_pages)이 그렇게 재기 때문이다. 컷 이후로 재면 페이지가
    2~4개뿐이라 같은 검색이 기준선보다 불리하게 나와 게이트(0.92)가 영구 미달이 된다
    (2026-08-12 실측). 컷은 LLM 에 넘길 근거 선택이지 검색 품질의 정의가 아니다.
    for_scoring=False(A/B 화면)는 LLM 이 실제로 받는 것을 보여줘야 하므로 컷을 유지한다.
    """
    from retrieval import route_search_chunks
    k_candidates = params.get("k_candidates", pipeline.K_CANDIDATES)
    k_final = params.get("k_final", pipeline.K_FINAL)
    threshold = params.get("min_top1_score", candidate_ranking.MIN_TOP1_SCORE)
    candidates = route_search_chunks(query, k=k_candidates)
    ranked = candidates if for_scoring else candidate_ranking.top_k_cut(candidates, k=k_final)
    top = candidate_ranking.gate_low_relevance(ranked, threshold=threshold)
    pages = []
    for cid, _score, _text in top:
        page = cid.split("#")[0]
        if page not in pages:
            pages.append(page)
    return pages


def _measure(rows, params: dict) -> dict:
    """held-out 검색 실측 -> {retrieval_accuracy@5, mrr, holdout_passed}."""
    hits = 0
    rr_sum = 0.0
    for r in rows:
        gold = set(r.expected_sources or [])
        ranked5 = _search_pages(r.question, params, for_scoring=True)[:5]
        if gold & set(ranked5):
            hits += 1
        for i, page in enumerate(ranked5, 1):
            if page in gold:
                rr_sum += 1.0 / i
                break
    n = len(rows)
    return {"retrieval_accuracy@5": hits / n, "mrr": rr_sum / n, "holdout_passed": hits}


# ──────────────────────────────── 엔드포인트 ────────────────────────────────

def _full_response(db) -> dict:
    """GET 과 apply 성공이 공유하는 화면 전체 상태(RagParamsResponse)."""
    effective = _effective_params(db)
    draft = _row(db, "draft")
    meta = []
    for m in _param_meta():
        item = {k: v for k, v in m.items() if k != "default"}
        meta.append(item)
    return {
        "params": meta,
        "current": effective,
        "draft": dict(draft.params) if draft else None,
        "gate": _stored_gate(db),
    }


@router.get("")
def get_rag_params(admin: CurrentAdmin, db: DbSession):
    del admin
    return _full_response(db)


@router.post("/evaluate")
def evaluate_draft(body: dict, request: Request, me: CurrentAdmin, db: DbSession):
    """[초안 평가] — 초안을 서버에 저장하고 held-out 검색을 A(현행)/B(초안) 둘 다 실측한다.
    응답은 화면의 RagGate 그대로. ⚠️ 동기 1~2분(모듈 주석)."""
    _require_editor(me, "RAG 파라미터 평가")
    if not str(body.get("request_id") or "").strip():
        raise BadRequestError("request_id가 필요합니다.")
    params = validate_params(dict(body.get("draft") or {}))
    signature = draft_signature(params)

    rows = _holdout_rows(db)
    current_metrics = _measure(rows, _effective_params(db))
    draft_metrics = _measure(rows, params)
    now = datetime.now(timezone.utc)
    gate = build_gate(current_metrics=current_metrics, draft_metrics=draft_metrics,
                      signature=signature, evaluated_at=_kst(now),
                      holdout_total=len(rows))

    run_id = uuid.uuid4()
    db.execute(insert(evaluation_runs).values(
        id=run_id, target="RAG", source="RAG 파라미터 평가",
        metrics=[{"label": "검색 정확도@5", "value": f"{draft_metrics['retrieval_accuracy@5']:.3f}"},
                 {"label": "MRR", "value": f"{draft_metrics['mrr']:.3f}"},
                 {"label": "문항 수", "value": str(len(rows))}],
        gate=gate, triggered_by=me.email, finished_at=now, status="DONE",
    ))
    draft = _row(db, "draft")
    if draft:
        db.execute(update(rag_param_versions)
                   .where(rag_param_versions.c.id == draft.id)
                   .values(params=params, draft_signature=signature,
                           evaluation_run_id=run_id, updated_by=me.email))
    else:
        db.execute(insert(rag_param_versions).values(
            version=_next_version(db), status="draft", params=params,
            draft_signature=signature, evaluation_run_id=run_id, updated_by=me.email))
    db.commit()

    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=ACTION_EVALUATE,
        target=f"RAG 파라미터 초안 ({signature})",
        detail={"params": params, "gate_passed": gate["passed"],
                "holdout": f"{gate['holdout_passed']}/{gate['holdout_total']}"},
    )
    return gate


@router.post("/ab-search")
def ab_search(body: dict, me: CurrentAdmin, db: DbSession):
    """[비교 실행] — 같은 질문을 A(현행)/B(초안)로 동시 검색. 결과를 저장하지 않는다(§1.5)."""
    _require_editor(me, "A/B 검색")
    query = str(body.get("query") or "").strip()
    if not query:
        raise BadRequestError("query가 필요합니다.")
    draft = validate_params(dict(body.get("draft") or {})) if body.get("draft") else {}
    current = _effective_params(db)
    merged = {**current, **draft}

    # 정답 표시(✓): 이 질문이 평가셋에 있으면 그 expected_sources 를 쓴다. 임의 질문이면
    # 정답을 알 수 없으므로 표시하지 않는다 — 지어내지 않는다.
    gold_row = db.execute(
        select(test_set.c.expected_sources).where(test_set.c.question == query)
    ).first()
    gold = set(gold_row.expected_sources or []) if gold_row else set()

    titles = dict(db.execute(select(documents.c.page_id, documents.c.page_title)).all())

    def _chips(p: dict) -> list:
        return [f"후보 {p['k_candidates']}", f"최종 {p['k_final']}",
                f"게이트 {p['min_top1_score']}",
                f"리랭커 {'On' if p['use_reranker'] else 'Off'}",
                f"플래너 {'On' if p['use_query_planner'] else 'Off'}"]

    def _column(label: str, p: dict, changed: list) -> dict:
        pages = _search_pages(query, p)
        return {
            "label": label, "chips": _chips(p), "changed_chips": changed,
            "hits": [{"rank": i + 1, "title": titles.get(pid, pid), "doc_id": pid,
                      "score": 0.0, "is_answer": pid in gold}
                     for i, pid in enumerate(pages[:5])],
        }

    changed = [c for a, c in zip(_chips(current), _chips(merged)) if a != c]
    return {"query": query,
            "a": _column("A. 현행 운영값", current, []),
            "b": _column("B. 초안 (편집 중)", merged, changed)}


def compute_gate_warnings(db, draft, body: dict) -> list:
    """게이트·평가 상태를 경고 목록으로 계산한다(2026-08-19 정책 변경 — 차단하지 않는다).
    apply 가 활동 로그 detail.gate_warnings 에 그대로 싣는다."""
    warnings = []
    if draft.evaluation_run_id is None:
        return ["초안 평가 없이 반영"]
    sent = validate_params(dict(body.get("draft") or {})) if body.get("draft") else None
    if sent is not None and draft_signature(sent) != draft.draft_signature:
        warnings.append("평가 이후 초안 수정됨(재평가 없이 반영)")
    run = db.execute(
        select(evaluation_runs.c.gate).where(evaluation_runs.c.id == draft.evaluation_run_id)
    ).first()
    if not run or not run.gate or not run.gate.get("passed"):
        warnings.append("게이트 미달 상태로 반영")
    return warnings


@router.post("/apply")
def apply_draft(body: dict, request: Request, me: CurrentAdmin, db: DbSession):
    """[운영 반영] — 저장된 초안을 승격한다. 게이트·평가 상태는 **막지 않고 경고로만**
    남긴다(2026-08-19 정책 변경) — 미평가·지문 불일치·게이트 미달은 활동 로그
    detail.gate_warnings 에 기록된다. 초안 자체가 없을 때만 409(extra.current).
    성공 응답은 반영 후 전체 상태(RagParamsResponse)."""
    _require_editor(me, "RAG 파라미터 반영")
    if not str(body.get("request_id") or "").strip():
        raise BadRequestError("request_id가 필요합니다.")
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise BadRequestError("변경 사유를 입력해 주세요.")

    def _conflict(msg: str):
        return ParamsConflictError(msg, extra={"current": _effective_params(db)})

    draft = _row(db, "draft")
    if draft is None:
        # 반영할 초안 자체가 없다 — 검토 판정이 아니라 대상 부재라 그대로 막는다.
        raise _conflict("저장된 초안이 없습니다. 초안을 먼저 저장해 주세요.")
    # 2026-08-19 정책 변경: 평가·게이트는 반영을 막지 않는다 — 경고로만 남긴다.
    # 화면이 같은 상태(gate)를 이미 보고 있으므로 사용자 인지는 화면 경고가, 사후 추적은
    # 활동 로그(detail.gate_warnings)가 맡는다.
    gate_warnings = compute_gate_warnings(db, draft, body)

    now = datetime.now(timezone.utc)
    before = _effective_params(db)
    current = _row(db, "current")
    # current -> history 를 같은 트랜잭션에서 먼저 눕혀야 부분 유니크(current 1개)가 안 걸린다.
    if current:
        db.execute(update(rag_param_versions)
                   .where(rag_param_versions.c.id == current.id).values(status="history"))
    db.execute(update(rag_param_versions)
               .where(rag_param_versions.c.id == draft.id)
               .values(status="current", reason=reason, updated_by=me.email, applied_at=now))
    db.commit()
    runtime_config.invalidate("params")   # 같은 프로세스 즉시 반영(CLI 는 TTL 60초)

    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=ACTION_APPLY,
        target=f"RAG 파라미터 v{draft.version}", reason=reason,
        before_value=json.dumps(before, ensure_ascii=False, sort_keys=True),
        after_value=json.dumps(_effective_params(db), ensure_ascii=False, sort_keys=True),
        detail={"version": draft.version, "draft_signature": draft.draft_signature,
                **({"gate_warnings": gate_warnings} if gate_warnings else {})},
    )
    return _full_response(db)


def _summarize_change(prev: dict, cur: dict) -> str:
    """이력 한 줄 요약 — '복합 질문 분해 Off → On' 같은 문구를 diff 로 만든다."""
    labels = {m["key"]: m["label"] for m in _param_meta()}

    def _fmt(v):
        return ("On" if v else "Off") if isinstance(v, bool) else str(v)

    parts = [f"{labels.get(k, k)} {_fmt(prev.get(k))} → {_fmt(v)}"
             for k, v in cur.items() if prev.get(k) != v]
    return " · ".join(parts[:3]) + (" 외" if len(parts) > 3 else "") if parts else "변경 없음"


@router.get("/history")
def param_history(admin: CurrentAdmin, db: DbSession):
    """설정 이력 -> Page<RagHistoryEntry>. summary 는 직전 버전과의 diff 문구다."""
    del admin
    rows = db.execute(
        select(rag_param_versions)
        .where(rag_param_versions.c.status.in_(["current", "history"]))
        .order_by(rag_param_versions.c.version.asc())
    ).all()
    defaults = {m["key"]: m["default"] for m in _param_meta()}
    items = []
    prev = defaults
    for r in rows:
        cur = {**defaults, **dict(r.params or {})}
        items.append({
            "id": str(r.id),
            "changed_at": _kst(r.applied_at or r.created_at) or "",
            "summary": _summarize_change(prev, dict(r.params or {})),
            "actor": r.updated_by or "",
            "reason": r.reason or "",
        })
        prev = cur
    items.reverse()   # 화면은 최신순
    return {"items": items, "total": len(items), "page": 1, "size": len(items) or 1}


@router.post("/history/{version_id}/rollback")
def rollback_params(version_id: str, body: dict, request: Request,
                    me: CurrentAdmin, db: DbSession):
    """[롤백] — 그 시점 값으로 **초안만** 복원한다(화면 §1.7). 실제 적용은 [운영 반영]이
    다시 게이트를 거쳐야 한다 — 그래서 여기서는 평가 연결을 비운다(재평가 강제)."""
    _require_editor(me, "RAG 파라미터 초안 복원")
    if not str(body.get("request_id") or "").strip():
        raise BadRequestError("request_id가 필요합니다.")
    try:
        target_id = uuid.UUID(version_id)
    except ValueError:
        raise NotFoundError("해당 버전을 찾을 수 없습니다.")
    target = db.execute(
        select(rag_param_versions).where(rag_param_versions.c.id == target_id)
    ).first()
    if target is None:
        raise NotFoundError("해당 버전을 찾을 수 없습니다.")

    params = dict(target.params or {})
    signature = draft_signature(params)
    draft = _row(db, "draft")
    if draft:
        db.execute(update(rag_param_versions)
                   .where(rag_param_versions.c.id == draft.id)
                   .values(params=params, draft_signature=signature,
                           evaluation_run_id=None, updated_by=me.email))
    else:
        db.execute(insert(rag_param_versions).values(
            version=_next_version(db), status="draft", params=params,
            draft_signature=signature, updated_by=me.email))
    db.commit()

    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=ACTION_ROLLBACK,
        target=f"v{target.version} 값으로 초안 복원",
        detail={"from_version": target.version, "params": params},
    )
    return {"draft": params}
