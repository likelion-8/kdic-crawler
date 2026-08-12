"""RAG 파라미터(AD-007) — 검색·생성 파라미터의 초안·평가·반영·이력·롤백.

프론트 계약 정본: docs/frontend-handoff.md "R. RAG 파라미터"(R1~R4).
컬럼 정본: src/schema_admin.py rag_param_versions (current 1 · draft 1 · history N —
부분 유니크 인덱스 uq_rag_param_versions_current/draft 가 DB 에서 강제한다).

## 엔드포인트 6종
    GET  /                      params 메타 + current + draft + gate      — 읽기
    POST /evaluate              초안 저장 + 검색 평가 실행(draft_signature) — EDITOR↑
    POST /ab-search             질문 1개를 두 설정으로 검색해 나란히 비교    — 읽기
    POST /apply                 초안 반영. 게이트 미통과 409 + 현재값 전문   — EDITOR↑(사유 필수)
    GET  /history               버전 이력                                — 읽기
    POST /history/{id}/rollback 지난 버전으로 되돌리기                    — EDITOR↑(사유 필수)

## 파라미터 메타는 서버가 정본이다 (R1)

PARAM_META 가 이름·라벨·타입·범위·기본값을 전부 내려준다. 프론트는 이 배열을 그대로
그리므로 항목·범위가 바뀌어도 프론트 재배포가 필요 없다. **기본값은 코드 상수를 그 자리에서
읽는다** — 각 상수 주석의 실측 근거(README 2.4절 리랭커 조건표 · MIN_TOP1_SCORE 0.35 실측 ·
플래너 100문항 벤치마크)가 살아 있는 원본이고, 여기 복사해 두면 두 곳이 어긋난다.

⚠️ HYBRID_LINEAR_ALPHA(retrieval.py)는 목록에서 뺐다. 검색 엔진 싱글턴(_build_engines)을
조립할 때 한 번 박히는 값이라 프로세스 재시작 없이는 반영되지 않는다 — 노브로 노출하면
"바꿨는데 그대로"가 된다. 엔진 재조립 경로가 생기면 그때 추가한다.

## 평가(evaluate)는 검색 축만 잰다

여기 파라미터는 전부 검색·게이트 단계 값이라(k_candidates·k_final·min_top1_score·스위치)
생성(HCX)까지 부를 필요가 없다. held-out(test_set, 89문항)의 expected_sources 로
hit@5 비율·MRR 을 계산한다 — src/eval/eval_pipeline_retrieval.py 의 채점(page_of ·
recall_mrr)과 같은 규약이다. 게이트도 검색 두 축(0.92↑/0.80↑)만 판정하고, 생성·latency
축은 '해당 없음'으로 명시한다(지어내지 않는다 — E10 의 원칙).

⚠️ 문항 수만큼 임베딩+pgvector 질의가 나가는 동기 작업이다(워밍업된 서버에서 수십 초).
admin_evaluations.apply 가 같은 이유로 동기인 것과 같은 사정 — 워커(Redis·ARQ 예정)가
서면 그쪽 방식대로 옮긴다.

## 반영(apply)·롤백은 runtime_config 캐시를 즉시 무효화한다

파이프라인은 src/runtime_config.get_param() 으로 current 행을 읽는다(TTL 60초). 같은
프로세스는 invalidate() 로 즉시, CLI·Streamlit 은 TTL 만료 때 따라온다.
"""
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
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
from schema import test_set
from schema_admin import evaluation_runs, rag_param_versions

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/rag-params",
    tags=["admin-rag-params"],
    dependencies=[Depends(get_current_admin)],
)

# 역할 계층 정본: web/src/lib/codes.ts ROLE_RANK. 쓰기는 전부 EDITOR 이상(R4 — AD-007 에는
# 승인 분리가 없다는 기획서 0.4절 근거).
ROLE_RANK = {"VIEWER": 0, "OPERATOR": 1, "EDITOR": 2, "ADMIN": 3}

ACTION_EVALUATE = "RAG 파라미터 평가"
ACTION_APPLY = "RAG 파라미터 반영"
ACTION_ROLLBACK = "RAG 파라미터 롤백"


class ParamsConflictError(ApiError):
    """반영 불가(409, R3). admin_pipeline 의 Job*ConflictError 와 같은 방식으로 라우터가
    자기 409 를 정의한다. `extra` 로 현재 적용값 전문을 본문에 실어(errors.py extra 규약)
    화면이 '실패 시 이전 버전 유지'를 그대로 다시 그린다."""
    status_code = 409
    retryable = False

# 검색 게이트 정본(R3·E4) — admin_evaluations.GATE_CRITERIA 의 검색 두 축과 같은 임계값.
# 생성 성공률·latency 는 이 평가가 재지 않으므로 목록에 넣지 않는다(값 없이 축만 보여주면
# '미달'로 오독된다).
GATE_CRITERIA = [
    ("retrieval_accuracy@5", "검색 정확도@5", "0.92 이상", 0.92),
    ("mrr", "MRR", "0.80 이상", 0.80),
]


def _param_meta() -> list:
    """파라미터 메타 정본(R1). default 는 호출 시점에 코드 상수를 읽는다 — 상수 주석의
    실측 근거가 원본이고, 여기 숫자를 복사하면 두 곳이 어긋난다."""
    return [
        {"name": "k_candidates", "label": "1차 검색 후보 수", "type": "int",
         "min": 5, "max": 50, "step": 5, "default": pipeline.K_CANDIDATES,
         "description": "route_search_chunks 가 뽑는 1차 후보 청크 수. Recall@20 실측 99%+ 근거."},
        {"name": "k_final", "label": "최종 근거 청크 수", "type": "int",
         "min": 1, "max": 10, "step": 1, "default": pipeline.K_FINAL,
         "description": "LLM 에 넘기는 최종 근거 수. 프로젝트 평가 기준(AnswerRecall@5)과 동일 k."},
        {"name": "min_top1_score", "label": "무관 질문 게이트 임계값", "type": "float",
         "min": 0.0, "max": 1.0, "step": 0.05, "default": candidate_ranking.MIN_TOP1_SCORE,
         "description": "top-1 점수가 이 값 미만이면 근거를 비워 환각을 차단. 0.35 는 인스코프 137건 오차단 0 실측."},
        {"name": "use_reranker", "label": "리랭커(cross-encoder)", "type": "bool",
         "default": pipeline.USE_RERANKER,
         "description": "CPU 에서 문항당 96초라 기본 Off. GPU 확보 시 held-out 재검증 후 판단(README 2.4절)."},
        {"name": "use_query_planner", "label": "쿼리 플래너(분해+intent 한 콜)", "type": "bool",
         "default": query_planner.USE_QUERY_PLANNER,
         "description": "gpt-5.6-luna structured output. 100문항 joint 벤치마크 89% 근거."},
        {"name": "use_query_decomposition", "label": "복합 질문 분해(플래너 Off 폴백)", "type": "bool",
         "default": pipeline.USE_QUERY_DECOMPOSITION,
         "description": "플래너를 껐을 때만 쓰는 HCX 분해 경로."},
        {"name": "use_source_recheck", "label": "출처 재확인(NO_SOURCE 사후 판정)", "type": "bool",
         "default": pipeline.USE_SOURCE_RECHECK,
         "description": "마커 오표기(61건 중 33건 출처 소실 실측)를 별도 LLM 판정으로 복구."},
    ]


def _require_editor(me: CurrentAdmin, what: str) -> None:
    if ROLE_RANK.get(me.role, -1) < ROLE_RANK["EDITOR"]:
        raise ForbiddenError(
            f"{what}에는 EDITOR 이상 권한이 필요합니다. 현재 권한은 {me.role}입니다.")


def validate_params(body_params: dict) -> dict:
    """초안 파라미터를 메타(min/max/step·타입)로 검증해 정규화한 dict 를 돌려준다.

    쓰기 쪽 검증이 정본이다 — 읽는 쪽(runtime_config.get_param)은 타입 검사를 하지 않으므로
    여기서 걸러지지 않은 값은 파이프라인에 그대로 들어간다.
    """
    meta = {m["name"]: m for m in _param_meta()}
    unknown = set(body_params) - set(meta)
    if unknown:
        raise BadRequestError(f"지원하지 않는 파라미터입니다: {', '.join(sorted(unknown))}")
    cleaned = {}
    for name, value in body_params.items():
        m = meta[name]
        if m["type"] == "bool":
            if not isinstance(value, bool):
                raise BadRequestError(f"{name} 값은 true 또는 false여야 합니다.")
        elif m["type"] == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise BadRequestError(f"{name} 값은 정수여야 합니다.")
            if not (m["min"] <= value <= m["max"]):
                raise BadRequestError(f"{name} 값은 {m['min']}~{m['max']} 범위여야 합니다.")
        else:  # float
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise BadRequestError(f"{name} 값은 숫자여야 합니다.")
            if not (m["min"] <= value <= m["max"]):
                raise BadRequestError(f"{name} 값은 {m['min']}~{m['max']} 범위여야 합니다.")
        cleaned[name] = value
    if not cleaned:
        raise BadRequestError("변경할 파라미터를 하나 이상 보내 주세요.")
    return cleaned


def draft_signature(params: dict) -> str:
    """초안의 지문(R2). '평가 이후 초안을 수정하면 평가 무효화'를 판정하는 유일한 근거라
    키 정렬로 정규화해 같은 내용이면 항상 같은 값이 나오게 한다."""
    canon = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def _row(db, status: str):
    return db.execute(
        select(rag_param_versions).where(rag_param_versions.c.status == status)
    ).first()


def _next_version(db) -> int:
    return (db.execute(select(func.max(rag_param_versions.c.version))).scalar_one() or 0) + 1


def _effective_params(db) -> dict:
    """현재 적용값 전문 = 코드 기본값 위에 current 행을 얹은 것. 파이프라인이 실제로 읽는
    값과 같은 계산이다(runtime_config: DB 에 없으면 코드 상수)."""
    current = _row(db, "current")
    values = {m["name"]: m["default"] for m in _param_meta()}
    if current and current.params:
        values.update({k: v for k, v in dict(current.params).items() if k in values})
    return values


def compute_gate(metrics: dict) -> dict:
    """검색 두 축의 게이트 판정(passed + 기준별) — 목록·상세가 같은 값을 읽도록 한 덩어리로.
    admin_evaluations.compute_gate 와 같은 모양({passed, criteria:[...]})을 따른다."""
    criteria = []
    for key, label, target, threshold in GATE_CRITERIA:
        value = metrics.get(key)
        ok = value is not None and value >= threshold
        criteria.append({
            "key": key, "label": label, "target": target,
            "value": f"{value:.3f}" if value is not None else "—",
            "passed": ok,
        })
    return {
        "passed": all(c["passed"] for c in criteria),
        "criteria": criteria,
        # 이 평가가 재지 않은 축을 명시한다 — 값 없이 축만 실으면 화면에서 '미달'로 오독된다.
        "not_measured": ["generation_success_rate", "avg_latency_s"],
    }


def _measure_retrieval(db, params: dict) -> tuple[dict, int]:
    """초안 파라미터로 held-out 검색 평가 -> (metrics, 문항 수).

    src/eval/eval_pipeline_retrieval.py 와 같은 규약: chunk_id 의 '#' 앞이 page_id 이고,
    expected_sources(정답 페이지 집합)에 대한 hit@5 비율과 MRR 을 잰다. 초안이 실제로
    바꾸는 지점만 초안 값으로 돌린다 — k_candidates(1차 폭)·k_final(컷)·min_top1_score
    (게이트, 걸리면 근거가 비어 miss). 리랭커는 CPU 에서 문항당 96초라 여기서 켜지 않는다
    (use_reranker=True 초안이어도 검색 평가는 Off 로 잰다 — 응답에 명시).
    """
    from retrieval import route_search_chunks  # 지연 import — 첫 호출에 엔진 조립(수십 초)

    rows = db.execute(
        select(test_set.c.question, test_set.c.expected_sources)
        .where(test_set.c.is_active.is_(True), test_set.c.expected_sources.isnot(None))
        .order_by(test_set.c.question_id)
    ).all()
    if not rows:
        raise BadRequestError("평가할 held-out 문항이 없습니다(test_set 비어 있음).")

    k_candidates = params.get("k_candidates", pipeline.K_CANDIDATES)
    k_final = params.get("k_final", pipeline.K_FINAL)
    threshold = params.get("min_top1_score", candidate_ranking.MIN_TOP1_SCORE)

    hits = 0
    rr_sum = 0.0
    for r in rows:
        gold = set(r.expected_sources or [])
        chunks = route_search_chunks(r.question, k=k_candidates)
        top = candidate_ranking.gate_low_relevance(
            candidate_ranking.top_k_cut(chunks, k=k_final), threshold=threshold)
        pages = []
        for cid, _score, _text in top:
            page = cid.split("#")[0]
            if page not in pages:
                pages.append(page)
        ranked5 = pages[:5]
        if gold & set(ranked5):
            hits += 1
        for i, page in enumerate(ranked5, 1):
            if page in gold:
                rr_sum += 1.0 / i
                break
    n = len(rows)
    return {"retrieval_accuracy@5": hits / n, "mrr": rr_sum / n}, n


# ──────────────────────────────── 엔드포인트 ────────────────────────────────

@router.get("")
def get_rag_params(admin: CurrentAdmin, db: DbSession):
    """메타 + current + draft + (초안에 연결된) 게이트. 프론트가 이 한 응답으로 화면 전체를
    그린다 — 메타를 서버가 내려주므로(R1) 값·범위가 바뀌어도 재배포가 없다."""
    del admin
    current = _row(db, "current")
    draft = _row(db, "draft")
    gate = None
    if draft and draft.evaluation_run_id:
        run = db.execute(
            select(evaluation_runs.c.gate)
            .where(evaluation_runs.c.id == draft.evaluation_run_id)
        ).first()
        gate = run.gate if run else None

    effective = _effective_params(db)
    meta = _param_meta()
    for m in meta:
        m["value"] = effective[m["name"]]
    return {
        "params": meta,
        "current": {
            "version": current.version if current else None,
            "applied_at": current.applied_at.isoformat() if current and current.applied_at else None,
            "values": effective,
        },
        "draft": None if not draft else {
            "values": dict(draft.params),
            "draft_signature": draft.draft_signature,
            "evaluated": draft.evaluation_run_id is not None,
        },
        "gate": gate,
    }


@router.post("/evaluate")
def evaluate_draft(body: dict, request: Request, me: CurrentAdmin, db: DbSession):
    """초안 저장 + held-out 검색 평가(동기, 워밍업된 서버에서 수십 초 — 모듈 주석).

    응답에 draft_signature 를 담는다(R2) — apply 는 이 지문이 초안과 일치할 때만 게이트를
    믿는다. 평가 후 초안을 고치면 지문이 달라져 자동으로 무효가 된다.
    """
    _require_editor(me, "RAG 파라미터 평가")
    if not str(body.get("request_id") or "").strip():
        raise BadRequestError("request_id가 필요합니다.")
    params = validate_params(dict(body.get("params") or {}))
    signature = draft_signature(params)

    metrics, n = _measure_retrieval(db, params)
    gate = compute_gate(metrics)

    run_id = uuid.uuid4()
    db.execute(insert(evaluation_runs).values(
        id=run_id, target="RAG", source="RAG 파라미터 평가",
        metrics=[
            {"label": "검색 정확도@5", "value": f"{metrics['retrieval_accuracy@5']:.3f}"},
            {"label": "MRR", "value": f"{metrics['mrr']:.3f}"},
            {"label": "문항 수", "value": str(n)},
        ],
        gate=gate, triggered_by=me.email,
        finished_at=datetime.now(timezone.utc), status="DONE",
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
        target=f"초안 {signature}",
        detail={"params": params, "metrics": {k: round(v, 4) for k, v in metrics.items()},
                "evaluated_n": n, "gate_passed": gate["passed"]},
    )
    return {
        "draft_signature": signature,
        "metrics": [{"label": "검색 정확도@5", "value": f"{metrics['retrieval_accuracy@5']:.3f}"},
                    {"label": "MRR", "value": f"{metrics['mrr']:.3f}"},
                    {"label": "문항 수", "value": str(n)}],
        "gate": gate,
        # 초안에 use_reranker=True 가 있어도 검색 평가는 Off 로 쟀다(문항당 96초 — 모듈 주석).
        "notes": ["리랭커는 평가에서 항상 Off 다(CPU 문항당 96초). 생성·latency 축은 재지 않았다."],
    }


@router.post("/ab-search")
def ab_search(body: dict, me: CurrentAdmin, db: DbSession):
    """질문 1개를 두 설정(a/b)으로 검색해 나란히 돌려준다. 평가 전에 노브 하나의 효과를
    눈으로 확인하는 용도라 채점 없이 상위 페이지·점수만 준다."""
    del db
    _require_editor(me, "A/B 검색")
    query = str(body.get("query") or "").strip()
    if not query:
        raise BadRequestError("query가 필요합니다.")

    from retrieval import route_search_chunks

    def _side(raw) -> dict:
        params = validate_params(dict(raw or {})) if raw else {}
        k_candidates = params.get("k_candidates", pipeline.K_CANDIDATES)
        k_final = params.get("k_final", pipeline.K_FINAL)
        threshold = params.get("min_top1_score", candidate_ranking.MIN_TOP1_SCORE)
        top = candidate_ranking.gate_low_relevance(
            candidate_ranking.top_k_cut(route_search_chunks(query, k=k_candidates), k=k_final),
            threshold=threshold)
        return {
            "params": params,
            "gated": not top,   # true 면 게이트가 근거를 통째로 비웠다(무관 질문 판정)
            "chunks": [{"chunk_id": cid, "page_id": cid.split("#")[0], "score": round(s, 4)}
                       for cid, s, _text in top],
        }

    return {"query": query, "a": _side(body.get("a")), "b": _side(body.get("b"))}


@router.post("/apply")
def apply_draft(body: dict, request: Request, me: CurrentAdmin, db: DbSession):
    """초안을 current 로 승격한다. 게이트 미통과·평가 없음·초안 변경(지문 불일치)은 전부
    409 로 막고 **현재 적용값 전문을 실어** 화면이 '이전 버전 유지'를 그대로 다시 그리게
    한다(R3)."""
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
        raise _conflict("반영할 초안이 없습니다. 먼저 평가를 실행해 주세요.")
    if draft.evaluation_run_id is None:
        raise _conflict("평가되지 않은 초안입니다. 먼저 평가를 실행해 주세요.")
    # 화면이 들고 있던 지문과 대조한다(R2) — 평가 후 다른 사람이 초안을 고쳤으면 여기서 걸린다.
    sent_signature = str(body.get("draft_signature") or "").strip()
    if sent_signature and sent_signature != draft.draft_signature:
        raise _conflict("평가 이후 초안이 수정되었습니다. 다시 평가해 주세요.")
    run = db.execute(
        select(evaluation_runs.c.gate).where(evaluation_runs.c.id == draft.evaluation_run_id)
    ).first()
    if not run or not run.gate or not run.gate.get("passed"):
        raise _conflict("게이트를 통과하지 못한 초안은 반영할 수 없습니다.")

    now = datetime.now(timezone.utc)
    before = _effective_params(db)
    current = _row(db, "current")
    # current -> history 를 먼저 눕혀야 부분 유니크(current 1개)가 안 걸린다. 같은 트랜잭션이다.
    if current:
        db.execute(update(rag_param_versions)
                   .where(rag_param_versions.c.id == current.id).values(status="history"))
    db.execute(update(rag_param_versions)
               .where(rag_param_versions.c.id == draft.id)
               .values(status="current", reason=reason, updated_by=me.email, applied_at=now))
    db.commit()
    runtime_config.invalidate("params")   # 같은 프로세스는 즉시, CLI 는 TTL(60초) 내 반영

    after = _effective_params(db)
    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=ACTION_APPLY,
        target=f"RAG 파라미터 v{draft.version}", reason=reason,
        before_value=json.dumps(before, ensure_ascii=False, sort_keys=True),
        after_value=json.dumps(after, ensure_ascii=False, sort_keys=True),
        detail={"version": draft.version, "draft_signature": draft.draft_signature},
    )
    return {"version": draft.version, "applied_at": now.isoformat(), "values": after}


@router.get("/history")
def param_history(admin: CurrentAdmin, db: DbSession):
    del admin
    rows = db.execute(
        select(rag_param_versions).order_by(rag_param_versions.c.version.desc())
    ).all()
    return {"items": [{
        "id": str(r.id), "version": r.version, "status": r.status,
        "values": dict(r.params or {}), "reason": r.reason, "updated_by": r.updated_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "applied_at": r.applied_at.isoformat() if r.applied_at else None,
    } for r in rows], "total": len(rows)}


@router.post("/history/{version_id}/rollback")
def rollback_params(version_id: str, body: dict, request: Request,
                    me: CurrentAdmin, db: DbSession):
    """지난 버전의 값으로 **새 버전을 만들어** 되돌린다. 옛 행을 다시 current 로 세우지 않는
    이유: 이력이 '언제 무엇이 적용됐나'의 시간순 기록이어야 하는데, 행을 재사용하면 같은
    버전이 두 시기에 걸쳐 적용된 것이 되어 활동 로그와 대조할 수 없다."""
    _require_editor(me, "RAG 파라미터 롤백")
    if not str(body.get("request_id") or "").strip():
        raise BadRequestError("request_id가 필요합니다.")
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise BadRequestError("변경 사유를 입력해 주세요.")
    try:
        target_id = uuid.UUID(version_id)
    except ValueError:
        raise NotFoundError("해당 버전을 찾을 수 없습니다.")
    target = db.execute(
        select(rag_param_versions).where(rag_param_versions.c.id == target_id)
    ).first()
    if target is None:
        raise NotFoundError("해당 버전을 찾을 수 없습니다.")
    if target.status != "history":
        raise BadRequestError("이력(history) 상태의 버전만 롤백 대상입니다.")

    now = datetime.now(timezone.utc)
    before = _effective_params(db)
    current = _row(db, "current")
    if current:
        db.execute(update(rag_param_versions)
                   .where(rag_param_versions.c.id == current.id).values(status="history"))
    new_version = _next_version(db)
    db.execute(insert(rag_param_versions).values(
        version=new_version, status="current", params=dict(target.params or {}),
        reason=f"[v{target.version} 롤백] {reason}", updated_by=me.email, applied_at=now))
    db.commit()
    runtime_config.invalidate("params")

    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=ACTION_ROLLBACK,
        target=f"RAG 파라미터 v{target.version} -> v{new_version}", reason=reason,
        before_value=json.dumps(before, ensure_ascii=False, sort_keys=True),
        after_value=json.dumps(_effective_params(db), ensure_ascii=False, sort_keys=True),
        detail={"from_version": target.version, "new_version": new_version},
    )
    return {"version": new_version, "restored_from": target.version,
            "values": _effective_params(db)}
