"""운영 정책(AD-009) — 요청 제한·캐시·차단·추천 질문. **엔드포인트는 B 트랙 담당자가 채운다.**

빈 라우터로 자리만 잡아 둔 파일이다(사유는 admin_dashboard.py 상단과 같다).

## 만들 것 (8종)

    GET  /api/admin/ops-policy
    PUT  /api/admin/ops-policy                     부분 패치 + 새 version 반환(O5)
    GET  /api/admin/cache/stats
    POST /api/admin/cache/purge?scope=query|all
    GET  /api/admin/blocks
    POST /api/admin/blocks/{id}/release
    PUT  /api/admin/suggested-questions            전체 교체. reason 필수(O2)
    POST /api/admin/suggested-questions/validate   금칙어 검사

경로가 /ops-policy · /cache · /blocks · /suggested-questions 로 갈려서 prefix 를
/api/admin 까지만 잡았다. 각 경로를 데코레이터에 그대로 적을 것.

## 쓸 테이블 (2026-08-12 신설, src/schema_admin.py)

    ops_policy          버전마다 새 행. 가장 큰 version 이 현재 적용본이다.
                        정책 항목이 기획서에 없어 policy JSONB 로 열어 뒀다 —
                        모양 정본은 promptops/api.ts 의 OpsPolicy.
    query_cache         cache_key(정규화 해시) PK. hit_count 로 적중률을 낸다.
    rate_limit_blocks   expires_at 필수(O4). released_at 은 수동 해제 기록.

## 확정된 팀 결정

- PUT /ops-policy 는 **부분 패치**(변경된 필드만)를 받고 응답에 새 version 을 담는다(O5).
  burst_per_10s 는 읽기 전용이다.
- 🔴 PUT /ops-policy 는 위험 작업이라 **서버가 재인증 유효성을 독립 검증**한다(P5).
  프론트 판정은 우회 가능하다. A 트랙이 만드는 재인증 헬퍼를 가져다 쓸 것.
- 차단 목록은 expires_at 이 필수다(O4). 화면이 만료된 행의 [해제]를 비활성화하고 남은
  시간을 확인 모달에 표시한다.
- ⚠️ SuggestedQuestion.click_count 를 화면은 '최근 7일 클릭'으로 렌더한다(O3). 그런데
  추천 칩 클릭 수집 경로 자체가 계약에 없다 — 7일 윈도우 집계를 줄 수 없으면 필드를
  null 로 두고 프론트에 알려라. **0 을 넣으면 '아무도 안 눌렀다'는 거짓이 된다.**
- 모든 쓰기에 api/deps.py 의 write_activity_log 를 남긴다. 본 작업 commit 뒤에 부를 것
  (그 함수가 스스로 commit 한다 — deps.py:279-284).
"""
import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete, func, insert, select, update

from api.deps import (REAUTH_WINDOW, CurrentAdmin, DbSession,
                      get_current_admin, write_activity_log)
from api.errors import BadRequestError, ForbiddenError, NotFoundError
from api.routers.admin_logs import _to_kst_iso
from schema import suggested_questions
from schema_admin import (admin_activity_logs, guardrail_rules, ops_policy,
                          query_cache, rate_limit_blocks)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-ops"],
    dependencies=[Depends(get_current_admin)],
)

ROLE_RANK = {"VIEWER": 0, "OPERATOR": 1, "EDITOR": 2, "ADMIN": 3}
REGISTERED_SUGGESTION_MAX = 15
ACTIVE_SUGGESTION_MAX = 10
READ_ONLY_POLICY_FIELDS = frozenset({"burst_per_10s", "version"})
PATCHABLE_POLICY_FIELDS = frozenset({
    "ip_per_min",
    "ip_per_day",
    "session_per_30min",
    "over_limit_message",
    "auto_purge",
})

DEFAULT_POLICY = {
    "ip_per_min": 10,
    "ip_per_day": 300,
    "session_per_30min": 30,
    "burst_per_10s": 3,
    "over_limit_message": "잠시 후 다시 시도해 주세요. 문의가 많아 잠깐 대기 중이에요.",
    "auto_purge": True,
}

ACTION_POLICY_UPDATE = "사용량 제한 정책 변경"
ACTION_CACHE_PURGE = "질의 캐시 비우기"
ACTION_BLOCK_RELEASE = "차단 해제"
ACTION_SUGGESTIONS_REPLACE = "추천 질문 변경"

_ELLIPSIS = re.compile(r"(?:\.{3,}|…+)")
_WHITESPACE = re.compile(r"\s+")


def _require_role(admin: CurrentAdmin, minimum: str, what: str) -> None:
    if ROLE_RANK.get(admin.role, -1) < ROLE_RANK[minimum]:
        raise ForbiddenError(
            f"{what}에는 {minimum} 이상 권한이 필요합니다. 현재 권한은 {admin.role}입니다.")


def _require_write_fields(body: dict) -> tuple[str, str]:
    request_id = str(body.get("request_id") or "").strip()
    reason = str(body.get("reason") or "").strip()
    if not request_id:
        raise BadRequestError("request_id가 필요합니다.")
    if not reason:
        raise BadRequestError("변경 사유를 입력해 주세요.")
    return request_id, reason


def _require_recent_reauth(admin: CurrentAdmin) -> None:
    """A 트랙 재인증 헬퍼 병합 전 seam.

    원격 main과 모든 원격 브랜치에 아직 헬퍼가 없어 같은 정본(REAUTH_WINDOW)으로 서버 판정을
    닫아 둔다. A 트랙 함수가 들어오면 이 함수 본문을 그 import 호출로 교체한다.
    """
    last_auth = admin.last_auth_at
    if last_auth.tzinfo is None:
        last_auth = last_auth.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= last_auth + REAUTH_WINDOW:
        raise ForbiddenError("위험 작업을 계속하려면 비밀번호를 다시 확인해 주세요.")


def _utc_aware(value: datetime) -> datetime:
    """DB 드라이버가 naive datetime을 돌려줘도 UTC 비교를 안전하게 한다."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def normalize_cache_question(question: str) -> str:
    """NFKC → 말줄임 제거 → 모든 공백 한 칸 → 소문자.

    공백·`...`·`…`만 다른 질문은 같은 캐시 키가 된다. 영문 대소문자도 질의 의미를
    바꾸지 않으므로 casefold 한다. 다른 문장부호는 의미를 바꿀 수 있어 보존한다.
    """
    normalized = unicodedata.normalize("NFKC", question)
    normalized = _ELLIPSIS.sub("", normalized)
    normalized = _WHITESPACE.sub(" ", normalized).strip().casefold()
    return normalized


def cache_key_for_question(question: str) -> str:
    return hashlib.sha256(normalize_cache_question(question).encode("utf-8")).hexdigest()


def _policy_response(version: int, policy: dict) -> dict:
    return {"version": f"v{version}.0", **DEFAULT_POLICY, **policy,
            "burst_per_10s": DEFAULT_POLICY["burst_per_10s"]}


def _load_policy(db, *, lock: bool = False):
    query = select(ops_policy).order_by(ops_policy.c.version.desc()).limit(1)
    if lock:
        query = query.with_for_update()
    return db.execute(query).first()


def _validate_policy(policy: dict) -> None:
    numeric = ("ip_per_min", "ip_per_day", "session_per_30min")
    for field in numeric:
        value = policy.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise BadRequestError(f"{field} 값은 1 이상의 정수여야 합니다.")
    if policy["ip_per_day"] < policy["ip_per_min"]:
        raise BadRequestError("일일 요청은 분당 요청보다 크거나 같아야 합니다.")
    if not isinstance(policy.get("auto_purge"), bool):
        raise BadRequestError("auto_purge 값은 true 또는 false여야 합니다.")
    if not str(policy.get("over_limit_message") or "").strip():
        raise BadRequestError("초과 안내 문구를 입력해 주세요.")


@router.get("/ops-policy")
def get_ops_policy(admin: CurrentAdmin, db: DbSession):
    del admin
    row = _load_policy(db)
    return _policy_response(row.version, row.policy) if row else _policy_response(0, {})


@router.put("/ops-policy")
def update_ops_policy(body: dict, request: Request, admin: CurrentAdmin, db: DbSession):
    _require_role(admin, "ADMIN", "운영 정책 변경")
    _require_recent_reauth(admin)
    _, reason = _require_write_fields(body)

    supplied_read_only = READ_ONLY_POLICY_FIELDS.intersection(body)
    if supplied_read_only:
        raise BadRequestError(
            f"읽기 전용 필드는 변경할 수 없습니다: {', '.join(sorted(supplied_read_only))}")
    unknown = set(body) - PATCHABLE_POLICY_FIELDS - {"request_id", "reason"}
    if unknown:
        raise BadRequestError(f"지원하지 않는 정책 필드입니다: {', '.join(sorted(unknown))}")
    patch = {key: body[key] for key in PATCHABLE_POLICY_FIELDS if key in body}
    if not patch:
        raise BadRequestError("변경할 정책 값을 하나 이상 보내 주세요.")

    current = _load_policy(db, lock=True)
    current_version = current.version if current else 0
    before = {**DEFAULT_POLICY, **(current.policy if current else {})}
    after = {**before, **patch, "burst_per_10s": DEFAULT_POLICY["burst_per_10s"]}
    _validate_policy(after)
    new_version = current_version + 1
    db.execute(insert(ops_policy).values(
        version=new_version,
        policy={key: after[key] for key in DEFAULT_POLICY if key != "version"},
        reason=reason,
        updated_by=admin.email,
    ))
    db.commit()

    # write_activity_log가 스스로 commit 하므로 정책 버전 INSERT를 먼저 확정한다.
    write_activity_log(
        db, request,
        actor=admin.email,
        actor_role=admin.role,
        action=ACTION_POLICY_UPDATE,
        target=f"운영 정책 v{new_version}.0",
        reason=reason,
        before_value=json.dumps(before, ensure_ascii=False, sort_keys=True),
        after_value=json.dumps(after, ensure_ascii=False, sort_keys=True),
        detail={"version": new_version, "changed_fields": sorted(patch)},
    )
    return _policy_response(new_version, after)


def _cache_stats(db) -> dict:
    now = datetime.now(timezone.utc)
    active = (query_cache.c.expires_at.is_(None) | (query_cache.c.expires_at > now))
    aggregate = db.execute(
        select(func.count().label("entries"),
               func.coalesce(func.sum(query_cache.c.hit_count), 0).label("hits"))
        .where(active)
    ).first()
    entries = int(aggregate.entries or 0)
    hits = int(aggregate.hits or 0)
    denominator = entries + hits  # 최초 생성 1회 + 이후 적중 횟수

    latest_purge = db.execute(
        select(admin_activity_logs.c.occurred_at,
               admin_activity_logs.c.reason,
               admin_activity_logs.c.target)
        .where(admin_activity_logs.c.action == ACTION_CACHE_PURGE)
        .order_by(admin_activity_logs.c.occurred_at.desc()).limit(1)
    ).first()
    return {
        "hit_rate": round(hits / denominator, 4) if denominator else 0.0,
        "saved_generations": hits,
        "entries": entries,
        "extension": "시맨틱 캐시",
        "extension_applied": False,
        "last_purged_at": _to_kst_iso(latest_purge.occurred_at) if latest_purge else "",
        "last_purge_reason": (
            "" if latest_purge is None else (latest_purge.reason or latest_purge.target or "")
        ),
    }


@router.get("/cache/stats")
def get_cache_stats(admin: CurrentAdmin, db: DbSession):
    del admin
    return _cache_stats(db)


@router.post("/cache/purge")
def purge_cache(
    body: dict,
    request: Request,
    admin: CurrentAdmin,
    db: DbSession,
    scope_query: str | None = Query(default=None, alias="scope"),
):
    _, reason = _require_write_fields(body)
    scope = str(scope_query or body.get("scope") or "").strip()
    if scope not in {"query", "all"}:
        raise BadRequestError("scope는 query 또는 all이어야 합니다.")

    _require_role(admin, "ADMIN" if scope == "all" else "OPERATOR", "질의 캐시 비우기")
    if scope == "all":
        _require_recent_reauth(admin)
        statement = delete(query_cache)
        target = "전체 캐시"
    else:
        question = str(body.get("query") or "").strip()
        if not normalize_cache_question(question):
            raise BadRequestError("비울 질의를 입력해 주세요.")
        statement = delete(query_cache).where(
            query_cache.c.cache_key == cache_key_for_question(question))
        target = question

    removed = db.execute(statement).rowcount or 0
    db.commit()
    write_activity_log(
        db, request,
        actor=admin.email,
        actor_role=admin.role,
        action=ACTION_CACHE_PURGE,
        target=target,
        reason=reason,
        detail={"scope": scope, "removed": removed},
    )
    return {"removed": removed, **_cache_stats(db)}


def _block_page_query():
    counts = (
        select(rate_limit_blocks.c.target,
               func.count().label("block_count"))
        .group_by(rate_limit_blocks.c.target).subquery()
    )
    return (
        select(rate_limit_blocks, counts.c.block_count)
        .join(counts, counts.c.target == rate_limit_blocks.c.target)
        .where(rate_limit_blocks.c.released_at.is_(None))
        .order_by(rate_limit_blocks.c.blocked_at.desc())
    )


def _block_out(row) -> dict:
    return {
        "id": str(row.id),
        "subject": row.target,
        "kind": "IP" if row.target_kind == "ip" else "세션",
        "reason": row.reason or "",
        "blocked_at": _to_kst_iso(row.blocked_at) or "",
        "expires_at": _to_kst_iso(row.expires_at) or "",
        "count": row.block_count,
    }


@router.get("/blocks")
def list_blocks(
    admin: CurrentAdmin,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
):
    del admin
    total = db.execute(
        select(func.count()).select_from(rate_limit_blocks)
        .where(rate_limit_blocks.c.released_at.is_(None))
    ).scalar_one()
    rows = db.execute(_block_page_query().offset((page - 1) * size).limit(size)).all()
    return {"items": [_block_out(row) for row in rows], "total": total, "page": page, "size": size}


@router.post("/blocks/{block_id}/release", status_code=204)
def release_block(
    block_id: str,
    body: dict,
    request: Request,
    admin: CurrentAdmin,
    db: DbSession,
):
    _require_role(admin, "OPERATOR", "차단 해제")
    _, reason = _require_write_fields(body)
    try:
        uuid.UUID(block_id)
    except ValueError as exc:
        raise NotFoundError("차단 항목을 찾을 수 없습니다.") from exc

    existing = db.execute(
        select(rate_limit_blocks).where(rate_limit_blocks.c.id == block_id)
    ).first()
    if existing is None:
        raise NotFoundError("차단 항목을 찾을 수 없습니다.")
    now = datetime.now(timezone.utc)
    if existing.released_at is not None:
        raise BadRequestError("이미 수동 해제된 차단입니다.")
    if _utc_aware(existing.expires_at) <= now:
        raise BadRequestError("이미 만료된 차단입니다.")

    released = db.execute(
        update(rate_limit_blocks)
        .where(rate_limit_blocks.c.id == block_id,
               rate_limit_blocks.c.released_at.is_(None),
               rate_limit_blocks.c.expires_at > now)
        .values(released_at=now, released_by=admin.email)
        .returning(*rate_limit_blocks.c)
    ).first()
    if released is None:
        db.rollback()
        raise BadRequestError("차단 상태가 이미 변경되었습니다.")
    db.commit()
    write_activity_log(
        db, request,
        actor=admin.email,
        actor_role=admin.role,
        action=ACTION_BLOCK_RELEASE,
        target=f"{'IP' if released.target_kind == 'ip' else '세션'} {released.target} ({block_id})",
        reason=reason,
        detail={"expires_at": released.expires_at.isoformat()},
    )
    return Response(status_code=204)


def _suggestion_out(item: dict) -> dict:
    return {
        "id": item["id"],
        "text": item["text"],
        "business_function": item["business_function"],
        "active": item["active"],
        "order": item["order"],
        # O3: 7일 클릭 수집 경로가 없으므로 누적 click_count를 최근 7일 값처럼 내보내지 않는다.
        "click_count": None,
    }


def _validate_suggestions(raw_items) -> list[dict]:
    if not isinstance(raw_items, list):
        raise BadRequestError("items는 추천 질문 배열이어야 합니다.")
    if len(raw_items) > REGISTERED_SUGGESTION_MAX:
        raise BadRequestError(f"추천 질문은 최대 {REGISTERED_SUGGESTION_MAX}개까지 등록할 수 있습니다.")
    items = []
    seen_ids = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise BadRequestError("추천 질문 항목 형식이 올바르지 않습니다.")
        item_id = str(raw.get("id") or "").strip()
        text_value = str(raw.get("text") or "").strip()
        business = str(raw.get("business_function") or "").strip()
        active = raw.get("active")
        order = raw.get("order")
        if not item_id or item_id in seen_ids:
            raise BadRequestError("추천 질문 id는 비어 있지 않은 고유값이어야 합니다.")
        if not text_value or len(text_value) > 40:
            raise BadRequestError("추천 질문 문구는 1자 이상 40자 이하여야 합니다.")
        if not business:
            raise BadRequestError("추천 질문의 업무 구분이 필요합니다.")
        if not isinstance(active, bool):
            raise BadRequestError("추천 질문 active 값은 true 또는 false여야 합니다.")
        if isinstance(order, bool) or not isinstance(order, int) or order < 1:
            raise BadRequestError("추천 질문 order 값은 1 이상의 정수여야 합니다.")
        seen_ids.add(item_id)
        items.append({"id": item_id, "text": text_value, "business_function": business,
                      "active": active, "order": order})
    if sum(1 for item in items if item["active"]) > ACTIVE_SUGGESTION_MAX:
        raise BadRequestError(f"활성 추천 질문은 최대 {ACTIVE_SUGGESTION_MAX}개까지입니다.")
    return items


@router.put("/suggested-questions")
def replace_suggested_questions(
    body: dict,
    request: Request,
    admin: CurrentAdmin,
    db: DbSession,
):
    _require_role(admin, "EDITOR", "추천 질문 변경")
    _, reason = _require_write_fields(body)
    items = _validate_suggestions(body.get("items"))

    old_rows = db.execute(
        select(suggested_questions).order_by(suggested_questions.c.display_order)
    ).all()
    before = [
        {"id": row.id, "text": row.text, "business_function": row.business_function,
         "active": row.active, "order": row.display_order}
        for row in old_rows
    ]
    old_clicks = {row.id: row.click_count for row in old_rows}
    db.execute(delete(suggested_questions))
    if items:
        db.execute(insert(suggested_questions), [
            {"id": item["id"], "text": item["text"],
             "business_function": item["business_function"], "active": item["active"],
             "display_order": item["order"], "click_count": old_clicks.get(item["id"], 0)}
            for item in items
        ])
    db.commit()
    write_activity_log(
        db, request,
        actor=admin.email,
        actor_role=admin.role,
        action=ACTION_SUGGESTIONS_REPLACE,
        target=f"추천 질문 {len(items)}건",
        reason=reason,
        before_value=json.dumps(before, ensure_ascii=False),
        after_value=json.dumps(items, ensure_ascii=False),
        detail={"total": len(items), "active": sum(1 for item in items if item["active"])},
    )
    response_items = [_suggestion_out(item) for item in sorted(items, key=lambda value: value["order"])]
    return {"items": response_items, "total": len(response_items),
            "page": 1, "size": len(response_items)}


@router.post("/suggested-questions/validate")
def validate_suggested_question(body: dict, admin: CurrentAdmin, db: DbSession):
    del admin
    text_value = str(body.get("text") or "").strip()
    if not text_value:
        return {"passed": False, "message": "추천 질문 문구를 입력해 주세요."}
    patterns = db.execute(
        select(guardrail_rules.c.pattern)
        .where(guardrail_rules.c.kind == "blocklist",
               guardrail_rules.c.active.is_(True))
    ).scalars().all()
    folded = unicodedata.normalize("NFKC", text_value).casefold()
    for pattern in patterns:
        if unicodedata.normalize("NFKC", pattern).casefold() in folded:
            return {"passed": False,
                    "message": f"금칙어 '{pattern}'가 포함되어 저장할 수 없습니다."}
    return {"passed": True, "message": ""}
