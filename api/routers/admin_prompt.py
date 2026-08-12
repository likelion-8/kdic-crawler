"""프롬프트·가드레일(AD-008) — 초안·평가(Smoke)·게시·승인·롤백.

프론트 계약 정본: docs/frontend-handoff.md "M. 프롬프트·가드레일"(M1~M7) ·
web/src/routes/admin/settings/promptops/api.ts.
컬럼 정본: src/schema_admin.py (prompt_versions · prompt_drafts · prompt_publish_requests ·
guardrail_rules).

## 엔드포인트 11종
    GET/PUT /prompt/draft                 초안 조회/저장(서버가 change_count·dirty 관리, M2)
    POST    /prompt/draft/discard         초안 폐기
    POST    /prompt/evaluate              Smoke 30문항 실측(HCX 실호출 — 아래 참고)
    GET     /prompt/versions              게시 이력
    POST    /prompt/versions/{v}/rollback 지정 버전으로 되돌리기 — EDITOR↑(사유 필수)
    POST    /prompt/versions/emergency-rollback  직전 버전 즉시 복귀 — ADMIN + 재인증(M5)
    POST    /prompt/publish               초안 게시 — {version, smoke:{passed,total}}(M4)
    GET/POST /prompt/publish-requests     게시 요청 목록/생성
    POST    /prompt/publish-requests/{id}/approve|reject|cancel
    POST    /guardrails/masking/validate  마스킹 정규식 서버 판정(M6)

## 초안 상태는 서버가 갖는다 (M2)

프론트는 diff 를 계산하지 않는다. PUT 마다 서버가 change_count 를 올리고, 게시본(없으면
코드 기본값) 대비 어느 구획이 바뀌었는지(dirty)와 글자 수를 계산해 돌려준다. **내용이
실제로 바뀌면 evaluation 을 비운다** — 평가는 특정 내용의 지문(signature)에 대한 판정이라
내용이 달라지면 무효다. publish 는 그 지문이 일치할 때만 게시를 허용한다.

## Smoke 는 실측이다 — 수 분짜리 동기 호출

evaluate 는 골든셋(evaluation_dataset) 상위 SMOKE_TOTAL 문항을 **초안 프롬프트로 실제
생성**해 판정한다(검색 -> 초안 SI·few-shot 으로 프롬프트 조립 -> HCX 호출 -> 마커·금칙어
검사). 문항당 HCX 1콜이라 2~4분 걸린다. admin_evaluations.apply 가 같은 이유로 동기인
것과 같은 사정이고(워커 예정), 지어낸 숫자로 게이트를 통과시키지 않기 위한 선택이다.
게시(publish)는 저장된 평가를 재사용하므로 LLM 을 다시 부르지 않는다.

판정 축(promptops 계약의 회귀/인용/중대 위반):
    회귀     = 근거가 검색된 문항에서 정상 답변(비거절)이 나오는가
    인용     = 그 답변이 [SOURCE_USED] 마커를 다는가(출처 부착 규약 유지)
    중대 위반 = 초안 가드레일 금칙어가 답변에 나타나는가(0건이어야 함)

## 게시본이 없으면 파이프라인은 코드 상수를 쓴다

prompt_versions 가 비어 있는 것은 정상 상태다 — src/runtime_config.get_prompt() 가
prompt_builder 의 SYSTEM_INSTRUCTION 등으로 떨어진다. 게시·롤백 후에는
runtime_config.invalidate("prompt") 로 같은 프로세스에 즉시 반영한다.

## ⚠️ 미확정(M7): 게시·승인에 비밀번호 재확인을 걸지 않았다

CM-DF-001 2.3 고위험 3종(전체 캐시 비우기·권한 변경·롤백)에 게시가 없어 화면도 재인증
입력을 뺐다. 재인증은 긴급 롤백에만 건다. 다르게 가려면 프론트에 먼저 알릴 것.
"""
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, insert, select, update

from api.deps import (CurrentAdmin, DbSession, ReauthedAdmin, get_current_admin,
                      write_activity_log)
from api.errors import ApiError, BadRequestError, ForbiddenError, NotFoundError
# src/ 는 flat import(api/__init__.py 가 sys.path 에 넣는다).
import prompt_builder
import runtime_config
from schema_admin import prompt_drafts, prompt_publish_requests, prompt_versions

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-prompt"],
    dependencies=[Depends(get_current_admin)],
)

ROLE_RANK = {"VIEWER": 0, "OPERATOR": 1, "EDITOR": 2, "ADMIN": 3}

ACTION_PUBLISH = "프롬프트 게시"
ACTION_ROLLBACK = "프롬프트 롤백"
ACTION_EMERGENCY = "프롬프트 긴급 롤백"
ACTION_REQUEST = "프롬프트 게시 요청"
ACTION_APPROVE = "프롬프트 게시 승인"
ACTION_REJECT = "프롬프트 게시 반려"
ACTION_CANCEL = "프롬프트 게시 요청 취소"

# Smoke 문항 수. admin_evaluations.SMOKE_REQUIRED(30of30 게이트)와 같은 값 — 30 미만이면
# 전건 통과여도 게이트가 아니다.
SMOKE_TOTAL = 30

# 초안의 세 구획(M2 dirty 축). guardrails 는 초안 객체 안에 함께 실린다(M3).
SECTIONS = ("prompt", "fewshot", "guardrail")

# 마스킹 정규식 과대 매칭 판정용 보존 표본(M6). api/masking.py 의 보존 원칙과 같은 목록 —
# 이 서비스 답변의 핵심인 금액·기한·연락처·page_id·URL 이 가려지면 안 된다.
PROTECTED_SAMPLES = [
    "5,000만원", "50000000원", "1억원 한도",
    "2024-03-15", "2024년 3월 15일",
    "1332", "02-758-0114",   # 기관 대표번호류 — 상담 연락처는 답변의 핵심 정보다
    "deposit_protection_faq#3",
    "https://www.kdic.or.kr/sp/dpstrprot/ProtSystFaq/selectScrn.do",
]
# 단, 개인 연락처 형태(010-)는 가려지는 것이 목적이므로 보존 표본에서 뺀다.
MASKING_MUST_MATCH_HINT = "010-1234-5678"


class PromptConflictError(ApiError):
    """게시·승인 불가(409). admin_rag_params.ParamsConflictError 와 같은 방식."""
    status_code = 409
    retryable = False


# ──────────────────────────────── 초안 도우미 ────────────────────────────────

def _default_content() -> dict:
    """초안이 없을 때의 바탕 = 현재 게시본, 그것도 없으면 코드 상수(문서화된 기본값)."""
    current = None
    return {
        "system_instruction": prompt_builder.SYSTEM_INSTRUCTION,
        "few_shot": prompt_builder.FEW_SHOT_EXAMPLES,
        "no_evidence_notice": prompt_builder.NO_EVIDENCE_NOTICE,
        "guardrails": {"blocklist": {"active": False, "items": []},
                       "masking": {"active": False, "items": []}},
    } if current is None else current


def _baseline_content(db) -> dict:
    """dirty 판정의 기준선 — 현재 게시본이 있으면 그것, 없으면 코드 기본값."""
    row = db.execute(
        select(prompt_versions).where(prompt_versions.c.is_current)
    ).first()
    if row is None:
        return _default_content()
    return {
        "system_instruction": row.system_instruction,
        "few_shot": row.few_shot or prompt_builder.FEW_SHOT_EXAMPLES,
        "no_evidence_notice": row.no_evidence_notice or prompt_builder.NO_EVIDENCE_NOTICE,
        "guardrails": row.guardrails or _default_content()["guardrails"],
    }


def content_signature(content: dict) -> str:
    """초안 내용의 지문. 평가·게시가 '무엇에 대한 판정/게시인가'를 대조하는 근거다."""
    canon = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def compute_dirty(content: dict, baseline: dict) -> dict:
    """구획별 변경 여부(M2). 프론트는 이 값으로 탭 변경 표시만 그린다 — diff 는 계산하지 않는다."""
    return {
        "prompt": (content.get("system_instruction") != baseline.get("system_instruction")
                   or content.get("no_evidence_notice") != baseline.get("no_evidence_notice")),
        "fewshot": content.get("few_shot") != baseline.get("few_shot"),
        "guardrail": content.get("guardrails") != baseline.get("guardrails"),
    }


def _draft_row(db):
    return db.execute(select(prompt_drafts).order_by(prompt_drafts.c.updated_at.desc())).first()


def _draft_response(db, row) -> dict:
    content = dict(row.content)
    return {
        "content": content,
        "change_count": row.change_count,
        "dirty": row.dirty or compute_dirty(content, _baseline_content(db)),
        "char_count": row.char_count or len(content.get("system_instruction") or ""),
        "evaluation": row.evaluation,
        "base_version": row.base_version,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _require_editor(me: CurrentAdmin, what: str) -> None:
    if ROLE_RANK.get(me.role, -1) < ROLE_RANK["EDITOR"]:
        raise ForbiddenError(
            f"{what}에는 EDITOR 이상 권한이 필요합니다. 현재 권한은 {me.role}입니다.")


def _require_request_id(body: dict) -> None:
    if not str(body.get("request_id") or "").strip():
        raise BadRequestError("request_id가 필요합니다.")


def _blocklist_patterns(guardrails: dict) -> list:
    """초안 가드레일에서 금칙어 목록을 꺼낸다. promptops 계약의 item 이 {word} 또는
    {pattern} 형태라 둘 다 받는다(방어적 — 정본은 초안 쪽이다, M3)."""
    block = (guardrails or {}).get("blocklist") or {}
    if not block.get("active", True):
        return []
    words = []
    for item in block.get("items") or []:
        word = item if isinstance(item, str) else (item.get("word") or item.get("pattern") or "")
        if str(word).strip():
            words.append(str(word).strip())
    return words


# ──────────────────────────────── 초안 ────────────────────────────────

@router.get("/prompt/draft")
def get_draft(admin: CurrentAdmin, db: DbSession):
    """초안이 없으면 기준선(게시본 또는 코드 기본값)으로 새 초안 모양을 돌려준다 —
    화면이 빈 편집기 대신 현행 내용에서 시작하게."""
    del admin
    row = _draft_row(db)
    if row is None:
        content = _baseline_content(db)
        return {
            "content": content, "change_count": 0,
            "dirty": {s: False for s in SECTIONS},
            "char_count": len(content.get("system_instruction") or ""),
            "evaluation": None, "base_version": None,
            "updated_by": None, "updated_at": None,
        }
    return _draft_response(db, row)


@router.put("/prompt/draft")
def save_draft(body: dict, me: CurrentAdmin, db: DbSession):
    """초안 저장(M2). 내용이 실제로 바뀌었을 때만 change_count 를 올리고 evaluation 을
    비운다 — 같은 내용을 다시 저장했다고 평가를 무효화하면 화면이 평가를 반복해야 한다."""
    _require_editor(me, "프롬프트 초안 저장")
    _require_request_id(body)

    baseline = _baseline_content(db)
    row = _draft_row(db)
    old_content = dict(row.content) if row else baseline

    content = dict(old_content)
    for key in ("system_instruction", "few_shot", "no_evidence_notice", "guardrails"):
        if key in body:
            content[key] = body[key]
    if not str(content.get("system_instruction") or "").strip():
        raise BadRequestError("시스템 프롬프트는 비울 수 없습니다.")

    # 미통과 마스킹 규칙이 섞인 저장은 400 으로 막는다(M6).
    masking = (content.get("guardrails") or {}).get("masking") or {}
    for item in masking.get("items") or []:
        if isinstance(item, dict) and item.get("validated") is False:
            raise BadRequestError("검증을 통과하지 못한 마스킹 규칙이 있습니다. 먼저 검증해 주세요.")

    changed = content != old_content
    dirty = compute_dirty(content, baseline)
    char_count = len(content.get("system_instruction") or "")
    now = datetime.now(timezone.utc)
    current = db.execute(
        select(prompt_versions.c.version).where(prompt_versions.c.is_current)
    ).scalar()

    if row is None:
        change_count = 1 if changed else 0
        db.execute(insert(prompt_drafts).values(
            content=content, change_count=change_count, dirty=dirty,
            char_count=char_count, evaluation=None, base_version=current,
            updated_by=me.email, updated_at=now))
    else:
        change_count = row.change_count + (1 if changed else 0)
        db.execute(update(prompt_drafts).where(prompt_drafts.c.id == row.id).values(
            content=content, change_count=change_count, dirty=dirty, char_count=char_count,
            # 내용이 바뀌면 평가 무효(M2). 안 바뀌었으면 기존 평가를 유지한다.
            evaluation=None if changed else row.evaluation,
            updated_by=me.email, updated_at=now))
    db.commit()
    return {"change_count": change_count, "dirty": dirty, "char_count": char_count,
            "evaluation": None if (changed or row is None) else row.evaluation}


@router.post("/prompt/draft/discard")
def discard_draft(body: dict, me: CurrentAdmin, db: DbSession):
    _require_editor(me, "프롬프트 초안 폐기")
    _require_request_id(body)
    row = _draft_row(db)
    if row is not None:
        db.execute(prompt_drafts.delete().where(prompt_drafts.c.id == row.id))
        db.commit()
    return {"discarded": row is not None}


# ──────────────────────────────── 평가(Smoke) ────────────────────────────────

def _run_smoke(db, content: dict) -> dict:
    """초안 프롬프트로 Smoke SMOKE_TOTAL 문항 실측(모듈 주석 — 문항당 HCX 1콜, 동기 수 분).

    실서비스와 같은 검색 경로로 근거를 뽑고, 초안의 SI·few-shot·notice 로 프롬프트를
    조립해 HCX 를 부른다. 판정: 회귀(비거절) · 인용([SOURCE_USED]) · 중대 위반(금칙어 0건).
    """
    from llm_client import call_hyperclova
    from retrieval import route_search_chunks
    from candidate_ranking import gate_low_relevance, top_k_cut
    from schema import evaluation_dataset

    rows = db.execute(
        select(evaluation_dataset.c.question)
        .where(evaluation_dataset.c.is_active.is_(True),
               evaluation_dataset.c.expected_sources.isnot(None))
        .order_by(evaluation_dataset.c.question_id)
        .limit(SMOKE_TOTAL)
    ).all()
    if len(rows) < SMOKE_TOTAL:
        raise BadRequestError(
            f"Smoke 에 필요한 문항이 부족합니다({len(rows)}/{SMOKE_TOTAL}).")

    si = content["system_instruction"]
    few_shot = content.get("few_shot") or []
    examples = "\n\n".join(f"질문: {ex['question']}\n답변: {ex['answer']}" for ex in few_shot)
    blockwords = _blocklist_patterns(content.get("guardrails") or {})

    passed = cited = 0
    violations = []
    for r in rows:
        top = gate_low_relevance(top_k_cut(route_search_chunks(r.question, k=20), k=5))
        context = "\n\n".join(text for _, _, text in top) if top else "(근거 없음)"
        human = (f"{examples}\n\n--- 아래는 실제 질문입니다 ---\n\n"
                 f"근거 자료:\n{context}\n\n질문: {r.question}\n답변:")
        try:
            raw = call_hyperclova([("system", si), ("human", human)])
        except Exception:  # noqa: BLE001 — 한 문항의 호출 실패는 그 문항 실패로 집계
            logger.warning("smoke HCX 호출 실패: %s", r.question, exc_info=True)
            continue
        body_text, marker_used = prompt_builder._strip_no_source_marker(raw)
        hit_words = [w for w in blockwords if w in body_text]
        refused = "안내가 어렵" in body_text or "범위를 벗어난" in body_text
        if hit_words:
            violations.append({"question": r.question, "words": hit_words})
        if marker_used:
            cited += 1
        # 근거가 검색된 문항이므로 정상 답변(비거절)+금칙어 0건이 통과다.
        if top and not refused and not hit_words:
            passed += 1

    return {
        "smoke": {"passed": passed, "total": SMOKE_TOTAL},
        "metrics": [
            {"label": "회귀(정상 답변)", "value": f"{passed}/{SMOKE_TOTAL}"},
            {"label": "인용([SOURCE_USED])", "value": f"{cited}/{SMOKE_TOTAL}"},
            {"label": "중대 위반(금칙어)", "value": f"{len(violations)}건"},
        ],
        "violations": violations[:5],   # 상세는 앞 5건만 — 응답이 무한히 크지 않게
        "at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/prompt/evaluate")
def evaluate_draft(body: dict, me: CurrentAdmin, db: DbSession):
    _require_editor(me, "프롬프트 평가")
    _require_request_id(body)
    row = _draft_row(db)
    if row is None:
        raise BadRequestError("평가할 초안이 없습니다. 먼저 저장해 주세요.")
    content = dict(row.content)
    evaluation = _run_smoke(db, content)
    evaluation["signature"] = content_signature(content)
    db.execute(update(prompt_drafts).where(prompt_drafts.c.id == row.id)
               .values(evaluation=evaluation))
    db.commit()
    return evaluation


# ──────────────────────────────── 게시 · 이력 · 롤백 ────────────────────────────

def _publish_content(db, request: Request, me, content: dict, evaluation: dict,
                     *, via: str) -> dict:
    """게시 공통 경로 — publish(직접)와 approve(승인)가 같은 검증·같은 기록을 거친다.

    게시본은 덮어쓰지 않는다(긴급 롤백이 직전 본문을 필요로 한다). is_current 는 부분
    유니크가 1개를 강제하므로 기존 current 를 먼저 내리고 새 행을 올린다(한 트랜잭션).
    """
    if not evaluation:
        raise PromptConflictError("평가되지 않은 내용은 게시할 수 없습니다. 먼저 평가를 실행해 주세요.")
    if evaluation.get("signature") != content_signature(content):
        raise PromptConflictError("평가 이후 내용이 수정되었습니다. 다시 평가해 주세요.")
    smoke = evaluation.get("smoke") or {}
    if not (smoke.get("total") == SMOKE_TOTAL and smoke.get("passed") == SMOKE_TOTAL):
        raise PromptConflictError(
            f"Smoke {smoke.get('passed', 0)}/{smoke.get('total', 0)} — "
            f"{SMOKE_TOTAL}문항 전건 통과해야 게시할 수 있습니다. 현행 프롬프트가 유지됩니다.")

    now = datetime.now(timezone.utc)
    new_version = (db.execute(select(func.max(prompt_versions.c.version))).scalar_one() or 0) + 1
    db.execute(update(prompt_versions).where(prompt_versions.c.is_current)
               .values(is_current=False))
    db.execute(insert(prompt_versions).values(
        version=new_version, is_current=True,
        system_instruction=content["system_instruction"],
        few_shot=content.get("few_shot"),
        no_evidence_notice=content.get("no_evidence_notice"),
        guardrails=content.get("guardrails"),
        smoke_passed=smoke["passed"], smoke_total=smoke["total"],
        published_by=me.email,
    ))
    # 게시로 초안의 역할이 끝난다 — 남겨 두면 '게시된 것과 같은 초안'이 dirty 없이 떠돈다.
    row = _draft_row(db)
    if row is not None:
        db.execute(prompt_drafts.delete().where(prompt_drafts.c.id == row.id))
    db.commit()
    runtime_config.invalidate("prompt")   # 같은 프로세스는 즉시 반영(CLI 는 TTL 60초)

    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=ACTION_PUBLISH,
        target=f"프롬프트 v{new_version}",
        detail={"version": new_version, "via": via, "smoke": smoke},
    )
    return {"version": new_version, "smoke": smoke}


@router.post("/prompt/publish")
def publish(body: dict, request: Request, me: CurrentAdmin, db: DbSession):
    """초안 직접 게시(M4). 저장된 평가를 재사용하므로 LLM 을 다시 부르지 않는다.
    재인증은 걸지 않는다(M7 미확정 — 모듈 주석)."""
    _require_editor(me, "프롬프트 게시")
    _require_request_id(body)
    row = _draft_row(db)
    if row is None:
        raise PromptConflictError("게시할 초안이 없습니다.")
    return _publish_content(db, request, me, dict(row.content), row.evaluation, via="direct")


@router.get("/prompt/versions")
def list_versions(admin: CurrentAdmin, db: DbSession):
    del admin
    rows = db.execute(
        select(prompt_versions).order_by(prompt_versions.c.version.desc())
    ).all()
    return {"items": [{
        "version": r.version, "is_current": r.is_current,
        "char_count": len(r.system_instruction or ""),
        "smoke": {"passed": r.smoke_passed, "total": r.smoke_total},
        "published_by": r.published_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows], "total": len(rows)}


def _switch_current(db, target_version: int) -> None:
    """is_current 를 target 으로 옮긴다. 새 행을 만들지 않는 이유: 게시본은 불변이고
    롤백은 '어느 게시본이 켜져 있나'의 전환이라, 파라미터 롤백(값 복사)과 성격이 다르다."""
    target = db.execute(
        select(prompt_versions).where(prompt_versions.c.version == target_version)
    ).first()
    if target is None:
        raise NotFoundError("해당 버전을 찾을 수 없습니다.")
    if target.is_current:
        raise BadRequestError("이미 적용 중인 버전입니다.")
    db.execute(update(prompt_versions).where(prompt_versions.c.is_current)
               .values(is_current=False))
    db.execute(update(prompt_versions).where(prompt_versions.c.version == target_version)
               .values(is_current=True))
    db.commit()
    runtime_config.invalidate("prompt")


@router.post("/prompt/versions/{version}/rollback")
def rollback_version(version: int, body: dict, request: Request,
                     me: CurrentAdmin, db: DbSession):
    _require_editor(me, "프롬프트 롤백")
    _require_request_id(body)
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise BadRequestError("변경 사유를 입력해 주세요.")
    before = db.execute(
        select(prompt_versions.c.version).where(prompt_versions.c.is_current)
    ).scalar()
    _switch_current(db, version)
    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=ACTION_ROLLBACK,
        target=f"프롬프트 v{before} -> v{version}", reason=reason,
        detail={"from_version": before, "to_version": version},
    )
    return {"version": version}


@router.post("/prompt/versions/emergency-rollback")
def emergency_rollback(body: dict, request: Request, me: ReauthedAdmin, db: DbSession):
    """직전 버전으로 즉시 복귀. ADMIN + **서버 독립 재인증**(M5·P5 — me 가 ReauthedAdmin
    이라 재확인 만료면 여기 닿기 전에 403). 본 요청 바디에 password 를 싣지 않는다 —
    재확인은 POST /reauth 별도 호출로 먼저 끝난 상태다."""
    if me.role != "ADMIN":
        raise ForbiddenError(f"긴급 롤백에는 ADMIN 권한이 필요합니다. 현재 권한은 {me.role}입니다.")
    _require_request_id(body)

    current = db.execute(
        select(prompt_versions.c.version).where(prompt_versions.c.is_current)
    ).scalar()
    if current is None:
        raise BadRequestError("게시된 프롬프트가 없어 되돌릴 대상이 없습니다.")
    previous = db.execute(
        select(func.max(prompt_versions.c.version))
        .where(prompt_versions.c.version < current)
    ).scalar_one()
    if previous is None:
        raise BadRequestError("직전 버전이 없습니다(첫 게시본).")
    _switch_current(db, previous)
    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=ACTION_EMERGENCY,
        target=f"프롬프트 v{current} -> v{previous}",
        reason=str(body.get("reason") or "").strip() or "긴급 롤백",
        detail={"from_version": current, "to_version": previous},
    )
    return {"version": previous, "rolled_back_from": current}


# ──────────────────────────────── 게시 요청(승인 흐름) ────────────────────────

@router.get("/prompt/publish-requests")
def list_publish_requests(admin: CurrentAdmin, db: DbSession):
    del admin
    rows = db.execute(
        select(prompt_publish_requests)
        .order_by(prompt_publish_requests.c.requested_at.desc())
    ).all()
    return {"items": [{
        "id": str(r.id), "status": r.status,
        "requested_by": r.requested_by,
        "requested_at": r.requested_at.isoformat() if r.requested_at else None,
        "decided_by": r.decided_by,
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        "reason": r.reason, "published_version": r.published_version,
    } for r in rows], "total": len(rows)}


@router.post("/prompt/publish-requests")
def create_publish_request(body: dict, request: Request, me: CurrentAdmin, db: DbSession):
    """게시 요청 생성. **요청 시점 초안 스냅샷을 함께 박는다** — draft_id 만 두면 승인자가
    본 것과 실제 게시본이 달라져 승인 절차의 의미가 없어진다(스키마 주석)."""
    _require_editor(me, "프롬프트 게시 요청")
    _require_request_id(body)
    row = _draft_row(db)
    if row is None:
        raise BadRequestError("게시를 요청할 초안이 없습니다.")
    if not row.evaluation:
        raise PromptConflictError("평가되지 않은 초안은 게시를 요청할 수 없습니다.")
    pending = db.execute(
        select(func.count()).select_from(prompt_publish_requests)
        .where(prompt_publish_requests.c.status == "PENDING")
    ).scalar_one()
    if pending:
        raise PromptConflictError("대기 중인 게시 요청이 이미 있습니다.")

    req_id = uuid.uuid4()
    # 스냅샷에 평가를 함께 넣는다 — 승인 시 이 평가로 게이트를 다시 검증한다(LLM 재호출 없음).
    snapshot = {"content": dict(row.content), "evaluation": row.evaluation}
    db.execute(insert(prompt_publish_requests).values(
        id=req_id, draft_id=row.id, content=snapshot, status="PENDING",
        requested_by=me.email))
    db.commit()
    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=ACTION_REQUEST,
        target=f"게시 요청 {req_id}", detail={"draft_signature": row.evaluation.get("signature")},
    )
    return {"id": str(req_id), "status": "PENDING"}


def _load_pending(db, request_id: str):
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise NotFoundError("게시 요청을 찾을 수 없습니다.")
    row = db.execute(
        select(prompt_publish_requests).where(prompt_publish_requests.c.id == rid)
    ).first()
    if row is None:
        raise NotFoundError("게시 요청을 찾을 수 없습니다.")
    if row.status != "PENDING":
        raise PromptConflictError(f"이미 처리된 요청입니다(현재 상태: {row.status}).")
    return row


@router.post("/prompt/publish-requests/{request_id}/approve")
def approve_publish_request(request_id: str, body: dict, request: Request,
                            me: CurrentAdmin, db: DbSession):
    """승인 = 스냅샷 게시. 재인증은 걸지 않는다(M7 미확정 — 모듈 주석)."""
    if me.role != "ADMIN":
        raise ForbiddenError(f"게시 승인에는 ADMIN 권한이 필요합니다. 현재 권한은 {me.role}입니다.")
    _require_request_id(body)
    row = _load_pending(db, request_id)
    snapshot = dict(row.content)
    result = _publish_content(db, request, me, dict(snapshot["content"]),
                              snapshot.get("evaluation"), via=f"approve:{request_id}")
    db.execute(update(prompt_publish_requests)
               .where(prompt_publish_requests.c.id == row.id)
               .values(status="APPROVED", decided_by=me.email,
                       decided_at=datetime.now(timezone.utc),
                       published_version=result["version"]))
    db.commit()
    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=ACTION_APPROVE,
        target=f"게시 요청 {request_id} -> v{result['version']}",
        detail={"request_id": request_id, "version": result["version"]},
    )
    return {**result, "request_status": "APPROVED"}


@router.post("/prompt/publish-requests/{request_id}/reject")
def reject_publish_request(request_id: str, body: dict, request: Request,
                           me: CurrentAdmin, db: DbSession):
    if me.role != "ADMIN":
        raise ForbiddenError(f"게시 반려에는 ADMIN 권한이 필요합니다. 현재 권한은 {me.role}입니다.")
    _require_request_id(body)
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise BadRequestError("반려 사유를 입력해 주세요.")
    row = _load_pending(db, request_id)
    db.execute(update(prompt_publish_requests)
               .where(prompt_publish_requests.c.id == row.id)
               .values(status="REJECTED", decided_by=me.email,
                       decided_at=datetime.now(timezone.utc), reason=reason))
    db.commit()
    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=ACTION_REJECT,
        target=f"게시 요청 {request_id}", reason=reason, detail={"request_id": request_id},
    )
    return {"id": request_id, "status": "REJECTED"}


@router.post("/prompt/publish-requests/{request_id}/cancel")
def cancel_publish_request(request_id: str, body: dict, request: Request,
                           me: CurrentAdmin, db: DbSession):
    """취소는 요청자 본인만 — 남의 요청을 지우는 건 반려(ADMIN)의 몫이다."""
    _require_editor(me, "게시 요청 취소")
    _require_request_id(body)
    row = _load_pending(db, request_id)
    if row.requested_by != me.email:
        raise ForbiddenError("본인이 올린 게시 요청만 취소할 수 있습니다.")
    db.execute(update(prompt_publish_requests)
               .where(prompt_publish_requests.c.id == row.id)
               .values(status="CANCELLED", decided_by=me.email,
                       decided_at=datetime.now(timezone.utc)))
    db.commit()
    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=ACTION_CANCEL,
        target=f"게시 요청 {request_id}", detail={"request_id": request_id},
    )
    return {"id": request_id, "status": "CANCELLED"}


# ──────────────────────────────── 가드레일 검증 ────────────────────────────────

@router.post("/guardrails/masking/validate")
def validate_masking_rule(body: dict, me: CurrentAdmin):
    """마스킹 정규식 서버 판정(M6) -> {passed, sample_count, message}.

    두 가지를 본다. ① 정규식 문법 오류 ② 과대 매칭 — 보존 표본(PROTECTED_SAMPLES:
    금액·날짜·수량·기관 연락처·page_id·URL)에 걸리면 그 규칙은 답변의 핵심 정보를
    가리므로 미통과다. api/masking.py 가 계좌번호 정규식을 만들지 않기로 한 것과 같은
    원칙이다("5,000만원"·"1332" 를 잡아먹는 패턴 금지).
    """
    _require_editor(me, "마스킹 규칙 검증")
    pattern = str(body.get("pattern") or "")
    if not pattern.strip():
        raise BadRequestError("pattern이 필요합니다.")

    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return {"passed": False, "sample_count": len(PROTECTED_SAMPLES),
                "message": f"정규식 문법 오류: {exc}"}

    over_matched = [s for s in PROTECTED_SAMPLES if compiled.search(s)]
    if over_matched:
        return {"passed": False, "sample_count": len(PROTECTED_SAMPLES),
                "message": ("과대 매칭 — 보존해야 할 값이 가려집니다: "
                            + ", ".join(over_matched[:3])
                            + (" 외" if len(over_matched) > 3 else ""))}

    matches_target = bool(compiled.search(MASKING_MUST_MATCH_HINT))
    return {"passed": True, "sample_count": len(PROTECTED_SAMPLES),
            "message": ("검증 통과."
                        + ("" if matches_target
                           else " (참고: 예시 개인 연락처 010-1234-5678 에는 걸리지 않는 패턴입니다.)"))}
