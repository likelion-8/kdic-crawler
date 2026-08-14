"""평가(AD-006) — 실행 이력·게이트 판정·문항 편집·코퍼스·후보 등록.

프론트 계약 정본: web/src/routes/admin/evaluation/api.ts, docs/frontend-handoff.md "E. 평가"(E1~E10).
컬럼 정본: src/schema_admin.py(evaluation_runs·evaluation_results·testset_items) ·
src/schema.py(documents·rag_runs).

## 엔드포인트 7종
    GET  /runs                  실행 이력(Page)                     — 읽기
    GET  /runs/{run_id}/gate    게이트 판정 상세                     — 읽기
    GET  /items                 문항 목록(Page)                     — 읽기
    POST /items/validate        필드별 오류 [{field, message}]       — 검증(무상태)
    POST /apply                 {adds,edits,excludes}+reason        — EDITOR↑(위험 작업)
    GET  /corpus?q=             기대 출처 자동완성                   — 읽기
    POST /candidates            대화 로그 → 문항 후보(AD-005 연동)    — 쓰기

## 실행 로직은 새로 짜지 않는다 (감싸기만)
검색·생성 채점은 src/eval/eval_pipeline_retrieval.py · eval_pipeline_generation.py 에 이미
있다. 이 라우터는 그 결과를 evaluation_runs/results 에 적는 일만 한다(run_evaluation).

## 재측정은 apply 트랜잭션에서 실제로 실행된다 (E7)
apply 는 (1) 새 버전 스냅샷 + (2) 재측정 run 생성 + (3) 재측정 실행(_measure — src/eval 채점을
감싸 evaluation_results·metrics·gate 를 채움)을 **한 트랜잭션·한 커밋으로** 끝낸다. 실패하면
버전 반영째 롤백해 '측정 안 된 버전'이나 영구 RUNNING 이 남지 않는다.

⚠️ 측정은 문항 수만큼 OpenAI·HCX 를 부르는 수 분짜리 작업이라 apply 요청이 그만큼 오래 걸린다.
현재 팀에 워커(Redis·ARQ 예정)가 없어 동기로 돈다. 워커가 서면 apply 는 run 을 RUNNING 으로
남기고 마감을 워커에 넘기는 방식으로 바꾼다 — 그 마감 진입점이 run_evaluation(아래)이고, 지금도
CLI 로 부를 수 있다. _measure 는 커밋하지 않아 apply(한 트랜잭션)와 run_evaluation(워커) 양쪽이
공유한다.

## 게이트 목표값은 서버가 못 박는다 (E4·E10)
GATE_CRITERIA 가 정본이다(0.92↑/0.80↑/99.5%↑/10초↓/30of30). passed 와 기준별 판정을
compute_gate 가 함께 계산해 evaluation_runs.gate(JSONB)에 담고, 목록·상세가 그 한 값을 읽는다.
프론트 상수로 박으면 '관리자 화면에서 기준을 낮추는 우회'를 막는 설계가 무너진다.

## ⚠️ testset_items 에 없는 필드(intent·question_type)
편집용 testset_items 에는 두 컬럼이 없다(원본 evaluation_dataset 에만 있다). GET /items 는
null 로 내보내고, apply/candidates 는 그 값을 저장하지 못한다 — 처리 방침·제안은
docs/evaluation_api_notes.md 에 있다(로그 화면의 원천 없는 필드와 같은 원칙: 지어내지 않는다).
"""
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, insert, select

from api.deps import CurrentAdmin, DbSession, get_current_admin
from api.errors import BadRequestError, ForbiddenError, NotFoundError
from api.schemas.evaluations import (CandidateResult, CorpusSearchResult,
                                     EvalApplyRequest, EvalApplyResult, EvaluationRunList,
                                     EvalItemInput, EvalItemList, EvalItemValidation,
                                     GateDetail)
# src/ 는 flat import(api/__init__.py 가 sys.path 에 넣는다). 서비스 vs 관리자 스키마 분리.
from api.rag import observation
from schema import documents, evaluation_dataset, pipeline_jobs, rag_runs
from schema_admin import evaluation_results, evaluation_runs, testset_items

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/evaluations",
    tags=["admin-evaluations"],
    dependencies=[Depends(get_current_admin)],
)

KST = timezone(timedelta(hours=9))
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MIN_CORPUS_QUERY = 2                         # 2자 미만 자동완성은 부르지 않는다(H6)
# 역할 계층 정본: web/src/lib/codes.ts ROLE_RANK. apply(위험 작업+사유)는 EDITOR 이상.
ROLE_RANK = {"VIEWER": 0, "OPERATOR": 1, "EDITOR": 2, "ADMIN": 3}
# 후보 문항이 사는 가상 버전. 숫자 버전(운영 평가셋)과 섞이지 않게 sentinel 로 분리한다.
CANDIDATE_VERSION = "candidate"

# 🔴 게이트 목표값 정본(E4). (label, target 표기, 판정 op, 임계값, 포맷터). 서버만 이 값을 안다.
_SCORE = lambda v: f"{v:.3f}" if v is not None else "—"
_PCT = lambda v: f"{v * 100:.1f}%" if v is not None else "—"
_SEC = lambda v: f"{v:.1f}초" if v is not None else "—"
GATE_CRITERIA = [
    ("retrieval_accuracy@5", "검색 정확도@5", "0.92 이상", ">=", 0.92, _SCORE),
    ("mrr", "MRR", "0.80 이상", ">=", 0.80, _SCORE),
    ("generation_success_rate", "생성 성공률", "99.5% 이상", ">=", 0.995, _PCT),
    ("avg_latency_s", "평균 응답시간", "10초 이하", "<=", 10.0, _SEC),
]
# Smoke 는 정확히 30문항 전부 통과여야 한다 — 5/5·29/29 처럼 total 이 30 미만이면 통과가 아니다.
SMOKE_REQUIRED = 30
SMOKE_TARGET = f"{SMOKE_REQUIRED}/{SMOKE_REQUIRED}"


# ──────────────────────────────── 공용 헬퍼 ─────────────────────────────────

def _to_kst_iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(KST).isoformat()


def _require_editor(me: CurrentAdmin) -> None:
    """EDITOR 이상만 쓰기(apply). admin_change_requests 와 같은 인라인 role 체크."""
    if ROLE_RANK.get(me.role, -1) < ROLE_RANK["EDITOR"]:
        raise ForbiddenError(
            f"이 작업에는 EDITOR 이상 권한이 필요합니다. 현재 권한은 {me.role}입니다.")


def _ver_int(value: Optional[str]) -> int:
    """testset_version(String) -> int. 숫자가 아니면(=candidate 등) 0."""
    return int(value) if value and value.isdigit() else 0


def _current_version(db) -> int:
    """지금 적용 중인 평가셋 버전 = 존재하는 숫자 버전 중 최대. 없으면 0(첫 apply 가 1)."""
    rows = db.execute(select(testset_items.c.testset_version).distinct()).all()
    return max((_ver_int(v) for (v,) in rows), default=0)


def _bootstrap_if_empty(db) -> None:
    """testset_items 가 비어 있으면 골든셋(schema.py evaluation_dataset)을 **버전 1** 로 씨딩한다.

    편집용 사본(testset_items)은 신설이라 비어 있는데, 그대로 두면 문항 목록이 빈 채로 뜨고
    첫 apply 가 '기존 평가셋 없는 버전 2'를 만든다. 기존 골든셋을 편집 대상으로 끌어오는
    다리다 — is_active 문항만, expected_sources(→expected_links)·업무·기준답변·라벨 2종
    (question_type·intent, 2026-08-13 컬럼 추가)을 옮긴다.
    비었을 때 한 번만 도는 지연 씨딩이라 조회/반영 진입에서 함께 부른다.
    """
    if db.execute(select(func.count()).select_from(testset_items)).scalar_one():
        return
    golden = db.execute(
        select(evaluation_dataset.c.question, evaluation_dataset.c.expected_sources,
               evaluation_dataset.c.expected_links, evaluation_dataset.c.business_function,
               evaluation_dataset.c.question_type, evaluation_dataset.c.intent,
               evaluation_dataset.c.reference_answer)
        .where(evaluation_dataset.c.is_active.is_(True))
    ).all()
    if not golden:
        return
    for g in golden:
        links = list(g.expected_links or g.expected_sources or []) or None
        db.execute(insert(testset_items).values(
            testset_version="1", question=g.question, expected_links=links,
            business_function=g.business_function, reference_answer=g.reference_answer,
            question_type=g.question_type, intent=g.intent,
            excluded=False, created_by="system(bootstrap)"))
    db.commit()
    logger.info("testset_items 부트스트랩: evaluation_dataset %s문항 -> 버전 1", len(golden))


def _validate_item(db, inp: EvalItemInput, current_version: str, seen: Optional[set] = None) -> list:
    """문항 1건 검증 -> 필드별 오류 [{field,message}]. validate 엔드포인트와 apply 가 공유한다
    (E6). ① 질문 비었나·개인정보 ② 코퍼스에 기대 출처 존재 ③ 중복 질문(현재 버전 + 같은 배치)."""
    errors = []
    question = (inp.question or "").strip()
    if not question:
        errors.append({"field": "question", "message": "질문을 입력해 주세요."})
    else:
        if any(p.search(question) for p in _PII_PATTERNS):
            errors.append({"field": "question", "message": "질문에 개인정보로 보이는 값이 있습니다."})
        # 중복: 같은 요청 배치(seen) 먼저, 그다음 현재 버전.
        is_dup = bool(seen and question in seen)
        if not is_dup:
            dup = select(func.count()).select_from(testset_items).where(
                testset_items.c.testset_version == current_version,
                testset_items.c.question == question,
                testset_items.c.excluded.is_(False))
            if inp.ignore_id:                       # 기존 행 편집은 자기 자신을 중복에서 뺀다
                dup = dup.where(testset_items.c.id != inp.ignore_id)
            is_dup = db.execute(dup).scalar_one() > 0
        if is_dup:
            errors.append({"field": "question", "message": "이미 같은 질문이 있습니다."})

    doc_id = (inp.expected_source_id or "").strip()
    if not doc_id:
        errors.append({"field": "expected_source", "message": "기대 출처를 선택해 주세요."})
    elif not db.execute(select(func.count()).select_from(documents)
                        .where(documents.c.page_id == doc_id)).scalar_one():
        errors.append({"field": "expected_source", "message": "코퍼스에 없는 출처입니다."})
    return errors


def compute_gate(m: dict) -> dict:
    """측정값(dict) -> 게이트 판정 전문. passed 와 기준별 판정을 **함께** 계산한다(E10).

    목표값은 GATE_CRITERIA(서버 정본, E4)에서만 온다. 목록·상세가 이 한 값을 읽어 어긋나지
    않게 한다.
    """
    criteria = []
    all_passed = True
    for key, label, target, op, threshold, fmt in GATE_CRITERIA:
        val = m.get(key)
        if val is None:
            passed = False
        elif op == ">=":
            passed = val >= threshold
        else:  # "<="
            passed = val <= threshold
        all_passed = all_passed and passed
        criteria.append({"label": label, "target": target, "result": fmt(val), "passed": passed})

    sp, st = m.get("smoke_passed") or 0, m.get("smoke_total") or 0
    # 🔴 정확히 30/30 이어야 통과. sp==st 로만 보면 1/1·5/5·29/29 도 통과가 되어 목표(30of30)가 무너진다.
    smoke_ok = (sp == SMOKE_REQUIRED and st == SMOKE_REQUIRED)
    all_passed = all_passed and smoke_ok
    criteria.append({"label": "Smoke 30문항", "target": SMOKE_TARGET,
                     "result": f"{sp}/{st}", "passed": smoke_ok})

    blocked = None if all_passed else \
        ", ".join(c["label"] for c in criteria if not c["passed"]) + " 미달"
    return {"passed": all_passed, "criteria": criteria,
            "smoke_passed": sp or 0, "smoke_total": st or 0, "blocked_reason": blocked}


def format_metrics(m: dict) -> list:
    """측정값 -> RAG 이력 표 '핵심 결과'(E1). 반올림까지 끝낸 문자열로, 서버가 표기를 확정한다.
    생성 성공률을 반드시 넣는다 — 환각률로 대체하지 않는다(E2, 의미가 다르다)."""
    return [
        {"label": "검색 정확도@5", "value": _SCORE(m.get("retrieval_accuracy@5"))},
        {"label": "MRR", "value": _SCORE(m.get("mrr"))},
        {"label": "생성 성공률", "value": _PCT(m.get("generation_success_rate"))},
    ]


def _titles_for(db, doc_ids: set) -> dict:
    """page_id -> page_title 일괄 조회. 목록에서 N+1 을 피한다."""
    if not doc_ids:
        return {}
    rows = db.execute(
        select(documents.c.page_id, documents.c.page_title)
        .where(documents.c.page_id.in_(doc_ids))
    ).all()
    return {pid: title for pid, title in rows}


def _all_links(expected_links) -> list:
    """testset_items.expected_links(JSONB, [doc_id,...]) 의 **모든** 출처 id.

    채점은 반드시 이걸 쓴다. 종전에는 _first_link 로 첫 하나만 정답으로 넘겨서, 정답 출처가
    여러 개인 문항(골든셋 851 중 110문항)이 두 번째 출처를 맞혀도 오답으로 잡혔다.
    eval_pipeline_retrieval 은 정답이 여러 개면 비율로 Recall 을 매기므로(recall_mrr), 전량을
    넘겨야 정기 평가·게이트와 같은 눈금이 된다."""
    if not isinstance(expected_links, list):
        return []
    # [{doc_id,...}] 형태로 저장됐을 수도 있어 둘 다 받는다.
    return [(x.get("doc_id") if isinstance(x, dict) else str(x)) for x in expected_links if x]


def _first_link(expected_links) -> Optional[str]:
    """대표 출처 하나 — **화면 표시 전용**이다(AD-006 목록의 '기대 출처' 칼럼).
    채점에는 쓰지 말 것. 채점용은 _all_links."""
    links = _all_links(expected_links)
    return links[0] if links else None


def _item_to_dict(row, titles: dict) -> dict:
    """testset_items 한 행 -> EvalItem."""
    doc_id = _first_link(row.expected_links)
    return {
        "item_id": str(row.id),
        "question": row.question,
        "business_function": row.business_function,
        "question_type": row.question_type,
        "intent": row.intent,
        "expected_source": None if not doc_id else {
            "doc_id": doc_id, "title": titles.get(doc_id, "")},
    }


# ──────────────────────────────── 실행 이력 ─────────────────────────────────

@router.get("/runs", response_model=EvaluationRunList)
def list_runs(
    db: DbSession,
    target: str = "",
    source: str = "",
    sort: str = "started_at:desc",
    page: int = Query(default=1, ge=1),
    size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """평가 실행 이력 -> Page<EvaluationRun>. 거르기·자르기는 전부 서버가 한다(D104)."""
    filters = []
    if target.strip():
        filters.append(evaluation_runs.c.target == target.strip())
    if source.strip():
        filters.append(evaluation_runs.c.source == source.strip())

    # 문항 수는 evaluation_results 상관 스칼라로 센다(N+1 회피).
    item_count = (
        select(func.count()).select_from(evaluation_results)
        .where(evaluation_results.c.run_id == evaluation_runs.c.id)
        .scalar_subquery()
    )
    order = evaluation_runs.c.started_at.desc() if sort != "started_at:asc" \
        else evaluation_runs.c.started_at.asc()

    total = db.execute(
        select(func.count()).select_from(evaluation_runs).where(*filters)).scalar_one()
    rows = db.execute(
        select(evaluation_runs, item_count.label("item_count"))
        .where(*filters).order_by(order)
        .offset((page - 1) * size).limit(size)
    ).all()
    return {"items": [_run_to_dict(r) for r in rows],
            "total": total, "page": page, "size": size}


def _run_to_dict(row) -> dict:
    """evaluation_runs 한 행(+item_count) -> EvaluationRun."""
    gate = row.gate or {}
    return {
        "run_id": str(row.id),
        "target": row.target,
        "source": row.source or "",
        "started_at": _to_kst_iso(row.started_at) or "",
        "finished_at": _to_kst_iso(row.finished_at),
        "status": row.status or "RUNNING",
        "item_count": row.item_count or 0,
        "metrics": row.metrics or [],
        "gate": {
            "passed": bool(gate.get("passed", False)),
            "smoke_passed": gate.get("smoke_passed", 0) or 0,
            "smoke_total": gate.get("smoke_total", 0) or 0,
            "blocked_reason": gate.get("blocked_reason"),
        },
        "follow_up": row.follow_up,
        "testset_version": _ver_int(row.testset_version),
        "improved_by_composition": row.improved_by_composition,
    }


@router.get("/runs/{run_id}/gate", response_model=GateDetail)
def get_gate(run_id: str, db: DbSession):
    """게이트 판정 상세. 기준별 판정은 evaluation_runs.gate(서버 계산본)에서, 미달 문항은
    evaluation_results(passed=false)에서 온다(H8)."""
    run = _get_run_or_404(db, run_id)
    gate = run.gate or {}

    failed = db.execute(
        select(evaluation_results)
        .where(evaluation_results.c.run_id == run.id,
               evaluation_results.c.passed.is_(False))
    ).all()
    failed_items = []
    for r in failed:
        detail = r.detail or {}
        failed_items.append({
            "item_id": r.item_id or "",
            "question": r.question or "",
            "expected_source": detail.get("expected_source", ""),
            "actual_top1": detail.get("actual_top1", ""),
            "score": float(detail.get("score", 0.0) or 0.0),
        })

    return {
        "run_id": str(run.id),
        "target": run.target,
        "source": run.source or "",
        "started_at": _to_kst_iso(run.started_at) or "",
        "criteria": gate.get("criteria", []),
        "latest_smoke": f"{gate.get('smoke_passed', 0) or 0}/{gate.get('smoke_total', 0) or 0}",
        "failed_items": failed_items,
    }


def _get_run_or_404(db, run_id: str):
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise NotFoundError("평가 실행을 찾을 수 없습니다.")
    row = db.execute(select(evaluation_runs).where(evaluation_runs.c.id == run_id)).first()
    if row is None:
        raise NotFoundError("평가 실행을 찾을 수 없습니다.")
    return row


# ──────────────────────────────── 문항 목록 ─────────────────────────────────

@router.get("/items", response_model=EvalItemList)
def list_items(
    db: DbSession,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """현재 버전의 편집 가능한 문항 -> Page<EvalItem>. 제외된 문항·후보는 뺀다.
    비어 있으면 골든셋(evaluation_dataset)을 버전 1 로 씨딩해 빈 화면을 막는다."""
    _bootstrap_if_empty(db)
    current = str(_current_version(db))
    where = (testset_items.c.testset_version == current,
             testset_items.c.excluded.is_(False))

    total = db.execute(
        select(func.count()).select_from(testset_items).where(*where)).scalar_one()
    rows = db.execute(
        select(testset_items).where(*where)
        .order_by(testset_items.c.created_at.asc())
        .offset((page - 1) * size).limit(size)
    ).all()

    titles = _titles_for(db, {d for d in (_first_link(r.expected_links) for r in rows) if d})
    return {"items": [_item_to_dict(r, titles) for r in rows],
            "total": total, "page": page, "size": size}


# ──────────────────────────────── 검증 ──────────────────────────────────────

# 개인정보 최소 탐지(E: 저장 전 자동 검증 ③). 마스킹(api/masking.py)은 아직 스텁이라 여기서는
# 저장을 막는 용도로만 가볍게 본다 — 주민번호·전화번호 패턴.
_PII_PATTERNS = [
    re.compile(r"\d{6}\s*[-–]\s*\d{7}"),            # 주민등록번호
    re.compile(r"01[016-9]\s*[-–]?\s*\d{3,4}\s*[-–]?\s*\d{4}"),  # 휴대전화
]


@router.post("/items/validate", response_model=EvalItemValidation)
def validate_item(body: EvalItemInput, db: DbSession):
    """저장 전 자동 검증 -> {ok, errors[{field,message}], item?}. 걸린 필드만 붉게 칠하려면
    field 가 필수다(E6). 검증 규칙 정본은 _validate_item — apply 가 같은 함수로 재검증한다."""
    _bootstrap_if_empty(db)
    errors = _validate_item(db, body, str(_current_version(db)))
    if errors:
        return {"ok": False, "errors": errors, "item": None}

    # 통과 — 확정된 문항 형태를 돌려준다. item_id 는 저장 시점(apply)에 최종 확정되므로
    # 여기서는 미리보기 id 를 준다(무상태 검증 — 아직 저장하지 않는다).
    doc_id = body.expected_source_id.strip()
    title = db.execute(
        select(documents.c.page_title).where(documents.c.page_id == doc_id)).scalar_one_or_none()
    return {
        "ok": True, "errors": [],
        "item": {
            "item_id": body.item_id or f"preview_{uuid.uuid4().hex[:8]}",
            "question": body.question.strip(),
            "business_function": body.business_function,
            "question_type": body.question_type,     # 입력값 에코(저장은 컬럼 없어 못 함 — 문서)
            "intent": body.intent,
            "expected_source": {"doc_id": doc_id, "title": title or ""},
        },
    }


@router.get("/schedule")
def get_schedule(admin: CurrentAdmin, db: DbSession):
    """정기 재측정 일정 -> {next_check_at, testset_version}. 프론트(evaluation/api.ts
    fetchSchedule)가 AD-006 진입 즉시 부르는데 라우트가 없어 항상 404 였다(2026-08-13 실측).
    일정 정본은 PRD-03 '운영 재측정 4시점'의 정기 축 — 매주 월 04:00 KST.
    ⚠️ 스케줄러 프로세스는 아직 없다 — '계획된 다음 시각'이지 실행 보장이 아니다."""
    del admin
    _bootstrap_if_empty(db)
    kst = timezone(timedelta(hours=9))
    nxt = datetime.now(kst).replace(hour=4, minute=0, second=0, microsecond=0)
    while nxt <= datetime.now(kst) or nxt.weekday() != 0:   # 다음 월요일 04:00
        nxt += timedelta(days=1)
    return {"next_check_at": nxt.isoformat(), "testset_version": _current_version(db)}


# ──────────────────────────────── 반영(apply) ───────────────────────────────

@router.post("/apply", response_model=EvalApplyResult)
def apply_changes(body: EvalApplyRequest, db: DbSession, me: CurrentAdmin):
    """편집 묶음 반영 -> {testset_version, rerun_id}. EDITOR 이상 + 사유 필수(위험 작업).

    버전 스냅샷 + 재측정 run(RUNNING) + 재측정 잡(QUEUED)을 **한 커밋**으로 확정하고 즉시
    반환한다 — 측정 자체는 워커(src/worker.py SMOKE_EVAL → run_evaluation)가 마감한다.

    2026-08-13 전환: 종전에는 _measure 를 같은 HTTP 트랜잭션에서 동기 실행했다. 851문항 ×
    (OpenAI+HCX) = 1,702콜·1.5~3시간 동안 취소 불가였고(브라우저 중단 무효 — 동기 def 는
    클라이언트 종료를 모른다), 공유 Supabase 에 트랜잭션이 열린 채였으며, 프록시 타임아웃이면
    전량 롤백이었다(실측 사고). run_evaluation docstring 의 "HTTP 요청에서 부르지 말 것"
    경고를 이제 지킨다. 클라이언트가 /items/validate 를 건너뛰어도 아래에서 서버가 다시 검증한다.
    """
    _require_editor(me)
    if not (body.reason or "").strip():
        raise BadRequestError("변경 사유가 필요합니다.")
    _bootstrap_if_empty(db)

    current = _current_version(db)
    current_str = str(current)

    # 🔴 서버 재검증(E6) — validate 를 건너뛴 요청도 잘못된 문항(빈 출처·없는 문서·중복·개인정보)을
    # 저장하지 못하게 막는다. 제외 사유 공백도 여기서 거른다.
    seen = set()
    for inp in body.adds:
        _reject_if_invalid(db, inp, current_str, seen)
        seen.add((inp.question or "").strip())
    for inp in body.edits:
        if not inp.ignore_id:
            inp.ignore_id = inp.item_id          # 편집은 자기 자신을 중복에서 뺀다
        _reject_if_invalid(db, inp, current_str, seen)
        seen.add((inp.question or "").strip())
    for ex in body.excludes:
        if not (ex.reason or "").strip():
            raise BadRequestError(f"제외 사유가 필요합니다(item_id={ex.item_id}).")

    new_version = current + 1
    excludes = {e.item_id: e.reason for e in body.excludes}
    edits = {e.item_id: e for e in body.edits if e.item_id}

    new_rows = []
    # 현재 버전 문항을 새 버전으로 스냅샷(편집 낱건이 아니라 버전 단위로 쌓는다, schema 주석).
    if current > 0:
        for it in db.execute(
                select(testset_items)
                .where(testset_items.c.testset_version == current_str)).all():
            iid = str(it.id)
            if iid in edits:
                new_rows.append(_input_to_row(
                    edits[iid], new_version, me.email,
                    excluded=iid in excludes, exclude_reason=excludes.get(iid)))
            elif iid in excludes:
                new_rows.append(_carry_row(it, new_version, excluded=True,
                                           exclude_reason=excludes[iid]))
            else:
                new_rows.append(_carry_row(it, new_version))
    for add in body.adds:
        new_rows.append(_input_to_row(add, new_version, me.email))

    # 버전 스냅샷은 851행짜리라 낱건 execute 를 하면 왕복만 851번이다(2026-08-14 실측:
    # 화면이 수십 초 잠김). executemany 한 번으로 보낸다 — 컬럼 구성이 모든 행 동일해 안전하다.
    if new_rows:
        db.execute(insert(testset_items), new_rows)

    # 재측정 run 생성 — 마감(DONE)은 워커의 run_evaluation 이 한다.
    run = db.execute(
        insert(evaluation_runs).values(
            target="운영 설정", source="파이프라인 후속",
            testset_version=str(new_version), status="RUNNING",
            started_at=datetime.now(timezone.utc), triggered_by=me.email)
        .returning(evaluation_runs.c.id, evaluation_runs.c.testset_version)
    ).first()

    # 측정을 워커에 넘긴다 — targets[0] = run_id 가 apply→워커 인계 계약이다(_run_smoke_eval).
    db.execute(insert(pipeline_jobs).values(
        id=uuid.uuid4(), type="SMOKE_EVAL", status="QUEUED",
        targets=[str(run.id)],
        reason=f"평가셋 v{new_version} 변경 반영 자동 재측정 — {body.reason.strip()}",
        created_by=me.email,
        target_summary=f"평가셋 v{new_version} 재측정", target_count=len(new_rows),
        steps=[{"name": n, "status": "QUEUED"}
               for n in ("수집", "변환", "청킹", "검증", "색인", "반영")]))
    db.commit()

    logger.info("평가셋 반영 v%s (추가 %s·편집 %s·제외 %s), 재측정 run=%s, 요청자 %s",
                new_version, len(body.adds), len(edits), len(excludes), run.id, me.email)
    return {"testset_version": new_version, "rerun_id": str(run.id)}


def _reject_if_invalid(db, inp: EvalItemInput, current_version: str, seen: set) -> None:
    """apply 재검증 — 문항 하나라도 오류면 400. 첫 오류를 사람이 읽을 문구로 올린다(E6)."""
    errs = _validate_item(db, inp, current_version, seen)
    if errs:
        raise BadRequestError(
            f"문항 검증 실패: '{(inp.question or '').strip()[:30]}' — {errs[0]['message']}")


def _input_to_row(inp: EvalItemInput, version: int, created_by: str,
                  excluded: bool = False, exclude_reason: Optional[str] = None) -> dict:
    """EvalItemInput -> testset_items insert 값."""
    return {
        "testset_version": str(version),
        "question": inp.question,
        "expected_links": [inp.expected_source_id] if inp.expected_source_id else None,
        "business_function": inp.business_function,
        "question_type": inp.question_type,
        "intent": inp.intent,
        "reference_answer": None,
        "excluded": excluded,
        "exclude_reason": exclude_reason,
        "created_by": created_by,
    }


def _carry_row(it, version: int, excluded: bool = False,
               exclude_reason: Optional[str] = None) -> dict:
    """현재 버전 문항을 새 버전으로 그대로 옮긴 insert 값(제외 표시만 덧입힐 수 있다)."""
    return {
        "testset_version": str(version),
        "question": it.question,
        "expected_links": it.expected_links,
        "business_function": it.business_function,
        "question_type": it.question_type,
        "intent": it.intent,
        "reference_answer": it.reference_answer,
        "excluded": excluded or bool(it.excluded),
        "exclude_reason": exclude_reason or it.exclude_reason,
        "created_by": it.created_by,
    }


# ──────────────────────────────── 코퍼스 ────────────────────────────────────

@router.get("/corpus", response_model=CorpusSearchResult)
def search_corpus(db: DbSession, q: str = ""):
    """기대 출처 자동완성 -> {items:[{doc_id,title}]}. page_id·제목을 부분 일치로 찾는다."""
    query = q.strip()
    if len(query) < MIN_CORPUS_QUERY:      # 2자 미만은 후보가 너무 넓다(H6)
        return {"items": []}
    like = f"%{query.replace('%', '').replace('_', '')}%"
    rows = db.execute(
        select(documents.c.page_id, documents.c.page_title)
        .where(documents.c.page_title.ilike(like) | documents.c.page_id.ilike(like))
        .order_by(documents.c.page_title.asc()).limit(20)
    ).all()
    return {"items": [{"doc_id": pid, "title": title or ""} for pid, title in rows]}


# ──────────────────────────────── 후보 등록 ─────────────────────────────────

@router.post("/candidates", response_model=CandidateResult, status_code=201)
def add_candidate(body: dict, db: DbSession, me: CurrentAdmin):
    """대화 로그 1건 -> 문항 후보(AD-005 연동). 마스킹된 질문만 옮긴다.

    후보는 숫자 버전과 섞이지 않게 sentinel 버전('candidate')으로 저장한다 — apply 로 정식
    버전에 편입되기 전까지 GET /items 에 노출되지 않는다.

    **정답 출처를 미리 채운다(2026-08-14).** 종전에는 질문만 옮기고 expected_links·업무·
    기준답변이 전부 None 이라, 관리자가 "이 질문의 정답 출처가 뭐였더라"를 맨손으로 찾아야 했다.
    실제로 그 답변이 어떤 페이지를 근거로 삼았는지는 rag_runs.observation 에 있으므로 그걸
    초안으로 넣는다 — 관리자는 **확인·수정만** 하면 된다. 이게 AD-005 → AD-006 인계의 알맹이다.
    관측 이전에 쌓인 행은 observation 이 NULL 이라 종전처럼 빈 후보가 된다.
    intent·question_type 도 함께 옮긴다(2026-08-13 컬럼 추가로 가능해졌다).
    """
    request_id = str(body.get("source_request_id") or "").strip()
    if not request_id:
        raise BadRequestError("source_request_id가 필요합니다.")

    run = db.execute(
        select(rag_runs.c.question, rag_runs.c.intent, rag_runs.c.question_type,
               rag_runs.c.observation)
        .where(rag_runs.c.request_id == request_id)).first()
    if run is None:
        raise NotFoundError("대화 기록을 찾을 수 없습니다.")

    pages = observation.expected_pages(run.observation)
    row = db.execute(
        insert(testset_items).values(
            testset_version=CANDIDATE_VERSION, question=run.question,
            expected_links=pages or None, business_function=None, reference_answer=None,
            question_type=run.question_type, intent=run.intent,
            excluded=False, created_by=me.email)
        .returning(testset_items.c.id)
    ).first()
    db.commit()
    # prefilled_sources 로 화면이 "출처 N건을 미리 채웠습니다"를 안내한다(빈손 등록과 구분).
    return {"candidate_id": str(row.id), "status": "REGISTERED",
            "prefilled_sources": len(pages)}


# ──────────────────────── 측정 실행(워커/CLI 전용) ──────────────────────────

def _measure(db, run, *, rerank: bool = False) -> dict:
    """run 의 문항으로 측정해 evaluation_results 를 적고 run 을 DONE 으로 채운다.
    **커밋하지 않는다** — 호출자가 커밋한다(apply=한 트랜잭션 / run_evaluation=워커).

    src/eval 채점을 **감싸기만** 한다(새로 짜지 않는다): 검색은 eval_retrieval, 생성은
    evaluate_generation(출처 정확률·OOS 거절·must_include·실패 기록을 그대로 계산). 문항별
    결과를 evaluation_results 에 적어 item_count(GET /runs)·failed_items(GET /gate)의 원천을
    남긴다. ⚠️ 문항 수만큼 OpenAI·HCX 를 부르는 수 분짜리 작업이다.
    """
    import sys
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent.parent / "src"
    for p in (str(src), str(src / "eval")):           # 'eval' 은 파이썬 내장명이라 패키지 import 를 피하고 flat 로
        if p not in sys.path:
            sys.path.insert(0, p)
    import pipeline                                    # noqa: E402  (K_CANDIDATES)
    from eval_pipeline_retrieval import eval_retrieval  # noqa: E402
    from eval_pipeline_generation import evaluate_generation, load_page_urls  # noqa: E402

    items = db.execute(
        select(testset_items).where(
            testset_items.c.testset_version == run.testset_version,
            testset_items.c.excluded.is_(False))).all()
    rows = [{"test_id": str(it.id), "question": it.question,
             # 정답 출처 전량. 첫 하나만 넘기면 두 번째 출처를 맞힌 문항이 오답이 된다(_all_links).
             "expected_sources": _all_links(it.expected_links)}
            for it in items]

    retr, per = eval_retrieval(rows, pipeline.K_CANDIDATES, rerank)
    # 생성 축은 Smoke 표본(앞 30문항)만 실측한다 — 검색 축은 전 문항. 전량 생성은 851문항 기준
    # (OpenAI+HCX) 1,702콜·1.5~3시간이라 재측정 취지(게이트 판정 기록)에 맞지 않는다(2026-08-13).
    # compute_gate 의 smoke_passed/total 도 이 표본 기준이라 판정 의미는 동일하다.
    gen_summary, gen_records, _failed = evaluate_generation(
        rows[:SMOKE_REQUIRED], load_page_urls(), rerank=rerank)

    # 문항별 결과 저장 — item_count·failed_items 의 원천(리뷰 지적). 검색 per-row 를 test_id 로 합친다.
    per_by_id = {p["test_id"]: p for p in per}
    for it in items:
        tid = str(it.id)
        p = per_by_id.get(tid, {})
        top5 = p.get("top5_pages") or []
        db.execute(insert(evaluation_results).values(
            run_id=run.id, item_id=tid, question=it.question,
            passed=bool(p.get("hit@5")),
            detail={"expected_source": ", ".join(p.get("gold") or []),
                    "actual_top1": top5[0] if top5 else "",
                    "score": p.get("rr", 0.0)}))

    # smoke: 앞 30문항의 생성 성공 여부. compute_gate 가 정확히 30/30 을 요구한다(30 미만이면 미달).
    smoke_total = min(SMOKE_REQUIRED, len(rows))
    ok_ids = {r["test_id"] for r in gen_records}
    smoke_passed = sum(1 for r in rows[:smoke_total] if r["test_id"] in ok_ids)

    measured = {
        "retrieval_accuracy@5": retr.get("Recall@5"),
        "mrr": retr.get("MRR"),
        "generation_success_rate": gen_summary.get("생성_성공률"),
        "avg_latency_s": gen_summary.get("평균_응답시간_s"),
        "smoke_passed": smoke_passed, "smoke_total": smoke_total,
    }
    gate = compute_gate(measured)
    db.execute(evaluation_runs.update().where(evaluation_runs.c.id == run.id).values(
        metrics=format_metrics(measured), gate=gate, status="DONE",
        finished_at=datetime.now(timezone.utc)))
    return {"run_id": str(run.id), "gate_passed": gate["passed"]}


def run_evaluation(db, run_id: str, *, rerank: bool = False) -> dict:
    """측정 실행(워커/CLI 전용) — run_id 로 부른다. _measure 후 커밋한다.

    ⚠️ HTTP 요청에서 부르지 말 것(문항 수만큼 OpenAI·HCX). apply(AD-006)는 run 을 RUNNING
    으로 남기고 SMOKE_EVAL 잡을 인큐한다 — 워커(_run_smoke_eval)가 targets[0]=run_id 로 이
    함수를 불러 마감한다(2026-08-13 전환).
    """
    run = _get_run_or_404(db, run_id)
    result = _measure(db, run, rerank=rerank)
    db.commit()
    return result
