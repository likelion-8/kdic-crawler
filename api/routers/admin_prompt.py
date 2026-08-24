"""프롬프트·가드레일(AD-008) — 기준값 제공·전후 비교 평가·게시·롤백.

🔴 계약 정본은 web/src/routes/admin/settings/promptops/api.ts 다. 핸드오프 문서(M1~M7)와
다르게 확정된 지점이 둘 있다(처음 구현을 핸드오프 기준으로 했다가 화면이 통째로 빈 사고,
2026-08-12):

  1. **초안은 서버가 아니라 화면 로컬(localStorage)이다.** 서버는 GET /prompt/draft 로
     게시본 기준값만 주고, 편집은 로컬에 쌓이다가 평가·게시 때 본문으로 실려 온다.
     (PUT draft / discard 는 계약 파일에 @deprecated 로 남아 있어 호환 스텁만 둔다.)
  2. **게시 요청/승인 2단계는 없앴다(팀 결정 2026-08-04).** EDITOR 이상이 바로 게시한다.
     사전 차단은 회귀 게이트가, 사후 추적은 활동 로그(AD-011)와 긴급 롤백이 맡는다.

## 엔드포인트 (화면이 실제로 부르는 것)
    GET  /prompt/draft                      게시본 기준값 -> PromptDraft
    POST /prompt/evaluate {draft}           전후 비교 실측 -> PromptEvaluation (무상태)
    POST /prompt/publish  {draft,gate_passed}+reason -> PublishResult {version, smoke}
    GET  /prompt/versions?page&size         -> Page<PromptVersion>
    POST /prompt/versions/{v}/rollback      그 버전 내용으로 기준값 재구성 -> PromptDraft
    POST /prompt/versions/{v}/emergency-rollback  ADMIN+재인증 -> PromptVersion
    POST /guardrails/masking/validate       정규식 서버 판정 -> ValidationResult

## 프롬프트 ⇄ 원칙(principles) 변환

화면은 시스템 프롬프트를 "번호 붙은 원칙" 행들로 편집한다. 서버가 전문(SYSTEM_INSTRUCTION)
과 행 배열을 양방향 변환한다:
  - 분해: 머리말(역할 소개)과 "다음 원칙을 반드시 지키세요:" 아래 번호 항목들로 나눈다.
  - **마커 규칙([SOURCE_USED]/[NO_SOURCE])은 잠금 원칙**이다 — 출처 부착·사후 판정
    (source_check)이 전부 이 마커에 걸려 있어 화면에서 지울 수 없어야 한다. 분해 시
    편집 목록에서 빼서 locked_principle 로 주고, 조립 시 서버가 **무조건 마지막 번호로
    다시 붙인다**(클라이언트가 빼고 보내도 살아남는다).

## 평가(전후 비교)와 게시 Smoke — 실측이다

evaluate: 골든셋에서 인스코프 4문항 + 범위외 2문항을 뽑아, 같은 검색 근거로 현행(전)과
초안(후) 프롬프트 각각 실제 생성한다(HCX 12콜, 동기 ~1분). 판정 축은 화면 게이트 그대로 —
출처 부착(인스코프에서 [SOURCE_USED]) · 범위외 거절([NO_SOURCE]) · 가드레일(금칙어 0건).
전{양호}→후{불량}이 REGRESSED 다. **서버에 아무것도 저장하지 않는다**(계약: 일시 평가).

publish: 초안 프롬프트로 Smoke 30문항을 실제 생성해(HCX 30콜, 동기 ~1-2분) 전건 통과면
새 버전을 현행으로 활성화한다. Smoke 미달이어도 활성화하며 **경고로만 기록**한다(2026-08-19).
gate_passed(클라이언트가 보낸 직전 평가 결과)는 진입 조건일 뿐 최종 판정은 Smoke 다.

## 폴백

게시본이 없으면 파이프라인은 코드 상수(prompt_builder)로 동작한다(runtime_config).
게시·롤백 후 runtime_config.invalidate("prompt") 로 같은 프로세스에 즉시 반영한다.
버전 표기는 'v1.N'(N = DB 정수 버전), 코드 기본값은 v1.0 이다.
"""
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, insert, select, update

from api.deps import (CurrentAdmin, DbSession, ReauthedAdmin, get_current_admin,
                      write_activity_log)
from api.errors import BadRequestError, ForbiddenError, NotFoundError, RateLimitError
# src/ 는 flat import(api/__init__.py 가 sys.path 에 넣는다).
import prompt_builder
import runtime_config
from schema_admin import prompt_versions

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-prompt"],
    dependencies=[Depends(get_current_admin)],
)

KST = timezone(timedelta(hours=9))
ROLE_RANK = {"VIEWER": 0, "OPERATOR": 1, "EDITOR": 2, "ADMIN": 3}

ACTION_PUBLISH = "프롬프트 게시"
ACTION_ROLLBACK = "프롬프트 롤백"
ACTION_EMERGENCY = "프롬프트 긴급 롤백"

# Smoke 문항 수 — 서버가 정하는 값(화면 목도 "서버가 정한다"고 명시). 전건 통과만 활성화.
SMOKE_TOTAL = 30
# 전후 비교 평가 문항 수(인스코프/범위외). HCX 콜 수 = (IN+OOS)×2 라 작게 유지한다.
EVAL_IN_SCOPE = 4
EVAL_OUT_OF_SCOPE = 2

# 잠금 원칙의 화면 표시 라벨. 실제 규칙 전문은 서버가 조립 시 붙인다(모듈 주석).
LOCKED_LABEL = "답변 첫 줄 근거 사용 마커([SOURCE_USED]/[NO_SOURCE]) 표기 — 시스템 필수 규칙"

# 마스킹 정규식 과대 매칭 판정용 보존 표본 — 이 서비스 답변의 핵심(금액·날짜·수량·기관
# 연락처·page_id·URL)이 가려지면 안 된다. api/masking.py 의 계좌번호 제외 결정과 같은 원칙.
PROTECTED_SAMPLES = [
    "5,000만원", "50000000원", "1억원 한도",
    "2024-03-15", "2024년 3월 15일",
    "1332", "02-758-0114",
    "deposit_protection_faq#3",
    "https://www.kdic.or.kr/sp/dpstrprot/ProtSystFaq/selectScrn.do",
]
MASKING_MUST_MATCH_HINT = "010-1234-5678"


# ──────────────────────── 프롬프트 ⇄ 원칙 변환 ────────────────────────

_NUMBERED = re.compile(r"^\d+\.\s*", re.MULTILINE)


def split_instruction(full: str) -> tuple[str, list, str]:
    """전문 -> (머리말, 편집 가능 원칙들, 잠금 원칙 전문).

    번호 항목은 '^숫자. ' 로 가른다(원칙 하나가 여러 줄이어도 다음 번호 전까지 한 항목).
    마커 규칙은 '[SOURCE_USED]' 포함 여부로 식별해 편집 목록에서 뺀다.
    """
    marker_positions = [m.start() for m in _NUMBERED.finditer(full)]
    if not marker_positions:
        return full, [], ""
    header = full[:marker_positions[0]].rstrip()
    items = []
    for i, start in enumerate(marker_positions):
        end = marker_positions[i + 1] if i + 1 < len(marker_positions) else len(full)
        items.append(_NUMBERED.sub("", full[start:end].strip(), count=1))
    locked = next((it for it in items if "[SOURCE_USED]" in it), "")
    principles = [it for it in items if it != locked]
    return header, principles, locked


def assemble_instruction(header: str, principles: list, locked: str) -> str:
    """원칙들 -> 전문. **잠금(마커) 규칙을 서버가 무조건 마지막 번호로 붙인다** — 클라이언트가
    빼고 보내도, 마커 규칙이 사라져 출처 부착 전체가 무너지는 사고를 서버가 막는다."""
    rules = [p for p in principles if str(p).strip()]
    if locked:
        rules.append(locked)
    numbered = "\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1))
    # 머리말은 자체적으로 "…지키세요:" 줄로 끝난다 — 빈 줄 없이 바로 규칙이 이어져야
    # 원본(SYSTEM_INSTRUCTION)과 왕복 시 동일해진다(테스트로 고정).
    return f"{header}\n{numbered}"


def _current_row(db):
    return db.execute(select(prompt_versions).where(prompt_versions.c.is_current)).first()


def _effective(db) -> dict:
    """지금 파이프라인이 실제로 쓰는 프롬프트 구성 — 게시본이 있으면 그것, 없으면 코드 상수."""
    row = _current_row(db)
    if row is None:
        return {"version": 0, "system_instruction": prompt_builder.SYSTEM_INSTRUCTION,
                "few_shot": prompt_builder.FEW_SHOT_EXAMPLES,
                "guardrails": None, "updated_at": None}
    return {"version": row.version, "system_instruction": row.system_instruction,
            "few_shot": row.few_shot or prompt_builder.FEW_SHOT_EXAMPLES,
            "guardrails": row.guardrails, "updated_at": row.created_at}


def _vstr(n: int) -> str:
    return f"v1.{n}"


def _parse_vstr(v: str) -> int:
    m = re.fullmatch(r"v1\.(\d+)", v.strip())
    if not m:
        raise NotFoundError("해당 버전을 찾을 수 없습니다.")
    return int(m.group(1))


def _kst(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    aware = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return aware.astimezone(KST).isoformat()


def build_draft_response(db, *, base: dict = None) -> dict:
    """화면의 PromptDraft(기준값) — 편집은 로컬에서 하므로 change_count 0·dirty false 로 준다."""
    base = base or _effective(db)
    header, principles, locked = split_instruction(base["system_instruction"])
    del header  # 화면은 원칙 행만 편집한다 — 머리말은 조립 시 서버가 유지
    guardrails = base.get("guardrails") or {}
    next_version = (db.execute(select(func.max(prompt_versions.c.version))).scalar_one() or 0) + 1
    return {
        "principles": [{"id": f"p{i+1}", "text": t, "dirty": False}
                       for i, t in enumerate(principles)],
        "fewshots": [{"id": f"fs{i+1}", "question": ex["question"], "answer": ex["answer"]}
                     for i, ex in enumerate(base["few_shot"])],
        "blocklist": guardrails.get("blocklist") or {"active": False, "items": []},
        "masking": guardrails.get("masking") or {"active": False, "items": []},
        "draft_version": _vstr(next_version),
        "base_version": _vstr(base["version"]),
        "base_updated_at": _kst(base.get("updated_at")),
        "change_count": 0,
        # 마커 규칙이 프롬프트에서 빠졌으면(2026-08-20) 잠긴 원칙이 없다 — 라벨만 남기면
        # AD-008 이 "편집 불가 원칙이 있다"고 거짓말한다. 실제로 잠긴 게 있을 때만 준다.
        "locked_principle": LOCKED_LABEL if locked else None,
        "char_count": len(base["system_instruction"]),
        "dirty": {"prompt": False, "fewshot": False, "guardrail": False},
        "evaluation": None,
    }


def _require_editor(me: CurrentAdmin, what: str) -> None:
    if ROLE_RANK.get(me.role, -1) < ROLE_RANK["EDITOR"]:
        raise ForbiddenError(
            f"{what}에는 EDITOR 이상 권한이 필요합니다. 현재 권한은 {me.role}입니다.")


def _require_request_id(body: dict) -> None:
    if not str(body.get("request_id") or "").strip():
        raise BadRequestError("request_id가 필요합니다.")


def _draft_to_content(db, draft: dict) -> dict:
    """화면이 보낸 PromptDraftContent -> 서버 내부 구성(전문 SI + few_shot + guardrails).

    머리말과 잠금 규칙은 **현행 게시본(없으면 코드 상수)에서 가져와** 유지한다 — 화면은
    원칙 행만 편집하고, 마커 규칙은 어떤 경우에도 살아남아야 한다(모듈 주석).
    """
    base = _effective(db)
    header, _base_principles, locked = split_instruction(base["system_instruction"])
    if not locked:   # 방어 — 어떤 이유로든 현행에서 마커 규칙을 못 찾으면 코드 상수에서 가져온다
        _, _, locked = split_instruction(prompt_builder.SYSTEM_INSTRUCTION)
    principles = [str(p.get("text") or "").strip()
                  for p in (draft.get("principles") or []) if str(p.get("text") or "").strip()]
    if not principles:
        raise BadRequestError("원칙이 비어 있습니다. 최소 한 줄은 있어야 합니다.")
    fewshots = [{"question": f.get("question"), "answer": f.get("answer")}
                for f in (draft.get("fewshots") or [])
                if str(f.get("question") or "").strip() and str(f.get("answer") or "").strip()]
    guardrails = {"blocklist": draft.get("blocklist") or {"active": False, "items": []},
                  "masking": draft.get("masking") or {"active": False, "items": []}}
    # 2026-08-19 정책 변경: 미통과 마스킹 규칙도 저장을 막지 않는다 — 경고 로그만 남긴다
    # (화면이 규칙별 검증 상태를 그대로 보여주므로 인지는 화면 몫).
    unvalidated = [str(item.get("pattern") or "") for item in guardrails["masking"].get("items") or []
                   if isinstance(item, dict) and item.get("validated") is False]
    if unvalidated:
        logger.warning("검증 미통과 마스킹 규칙 포함 저장: %s", ", ".join(unvalidated))
    return {"system_instruction": assemble_instruction(header, principles, locked),
            "few_shot": fewshots or base["few_shot"], "guardrails": guardrails}


def _blockwords(guardrails: dict) -> list:
    block = (guardrails or {}).get("blocklist") or {}
    if not block.get("active", True):
        return []
    words = []
    for item in block.get("items") or []:
        w = item if isinstance(item, str) else (item.get("pattern") or "")
        if str(w).strip():
            words.append(str(w).strip())
    return words


# ──────────────────────── 생성 실측 공통 ────────────────────────

# 콜 사이 최소 간격(초). 0 으로 두면 12콜이 한꺼번에 나가 한도에 걸린다.
_CALL_GAP_S = 1.5
_last_call_at = 0.0


def _pace() -> None:
    """직전 HCX 콜로부터 _CALL_GAP_S 가 지나도록 기다린다(프로세스 내 단일 워커 기준)."""
    global _last_call_at
    wait = _CALL_GAP_S - (time.monotonic() - _last_call_at)
    if wait > 0:
        time.sleep(wait)
    _last_call_at = time.monotonic()


def _is_rate_limited(exc: Exception) -> bool:
    """HCX(CLOVA Studio) 요청 한도 초과인가. SDK 예외 타입을 import 하지 않고 판별한다 —
    langchain_naver 가 openai SDK 를 통해 던지므로 타입을 붙잡으면 그 의존성에 묶인다."""
    if type(exc).__name__ == "RateLimitError":
        return True
    return getattr(exc, "status_code", None) == 429 or "429" in str(exc)


def _call_with_retry(messages: list, *, seed: int | None):
    """HCX 1콜 + 한도 초과 재시도.

    [전후 비교]는 문항마다 현행·초안 두 벌을 생성해 (4+2)×2 콜을 연달아 쏜다. 쉬지 않고
    보내면 CLOVA Studio 의 짧은 구간 한도에 걸리고, 무상태 API 라 그때까지 만든 생성이 통째로
    버려진다. 그래서 (a) 콜 사이에 간격을 두고 (b) 걸리면 쉬었다 다시 부른다.
    그래도 걸리면 429 를 그대로 올려 화면이 '잠시 후 다시' 라고 말하게 한다 — 조용히 빈
    결과를 돌려주면 관리자가 게이트 판정을 사실로 믿는다.

    ⚠ 한도 자체는 클라비가 준 키의 제공자 설정이라 여기서 알 수 없다. 간격·재시도 값은
    실측으로 정한 것이고, 평가 문항이 늘면 다시 봐야 한다.
    """
    from llm_client import call_hyperclova
    _pace()
    delays = (5, 15)
    for attempt in range(len(delays) + 1):
        try:
            return call_hyperclova(messages, deterministic=True, seed=seed)
        except Exception as exc:  # noqa: BLE001 — 한도 초과만 재시도하고 나머지는 그대로 올린다
            if not _is_rate_limited(exc) or attempt == len(delays):
                if _is_rate_limited(exc):
                    logger.warning("HCX 요청 한도 초과 — 재시도 %d회 후 포기", len(delays))
                    raise RateLimitError(
                        "답변 생성 요청 한도를 넘었습니다. 1~2분 뒤 다시 실행해 주세요."
                    ) from exc
                raise
            time.sleep(delays[attempt])


def _generate(question: str, si: str, few_shot: list, *, seed: int | None = None
              ) -> tuple[str, bool, list]:
    """실서비스와 같은 검색 근거로 1문항 생성 -> (본문, 마커 SOURCE_USED, 출처 목록).

    2026-08-13 게이트 정합 2건:
    - 결정화: temperature 0 + seed 고정(llm_client deterministic). 같은 초안 2회 평가에서
      회귀/개선 판정이 뒤집히던 비결정성 제거. seed 를 넘기면 flaky 재확인용 재생성.
    - 판정 정렬: 운영은 마커 오표기를 source_check 로 복구하는데 평가만 원시 마커를 재서
      '출처 부착 1건'이 항상 흔들렸다 — 같은 복구를 적용. 2026-08-14 팀 결정으로 운영과
      함께 단일 검증 1콜(validate_answer, 모든 답변 대상)로 정렬했다(평가=운영 원칙)."""
    from candidate_ranking import gate_low_relevance, top_k_cut
    from citation import format_all_citations
    from retrieval import route_search_chunks

    top = gate_low_relevance(top_k_cut(route_search_chunks(question, k=20), k=5))
    context = "\n\n".join(text for _, _, text in top) if top else "(근거 없음)"
    examples = "\n\n".join(f"질문: {ex['question']}\n답변: {ex['answer']}" for ex in few_shot)
    human = (f"{examples}\n\n--- 아래는 실제 질문입니다 ---\n\n"
             f"근거 자료:\n{context}\n\n질문: {question}\n답변:")
    raw = _call_with_retry([("system", si), ("human", human)], seed=seed)
    body, marker = prompt_builder.parse_marker(raw)
    # 🔴 근거가 비었으면(게이트가 걷어냄) 쓸 출처가 애초에 없다 — "근거를 썼다"가 될 수 없다.
    # 종전에는 마커 없는 응답이 True 로 들어와, 범위외 문항의 회귀 판정(not marker)이
    # 전건 실패했다(2026-08-20 수정). 마커가 실제로 있으면 그 값을 존중한다.
    marker_used = (True if marker is None else marker) if top else False
    if top:
        import pipeline as _pipeline
        import runtime_config as _rc
        if _rc.get_param("use_source_recheck", _pipeline.USE_SOURCE_RECHECK):
            # 모든 답변 검증(2026-08-14) — used_source 가 마커를 양방향 오버라이드.
            # 실패(None)는 fail-open 으로 마커 유지. 결정화(deterministic 생성)는 그대로다.
            from source_check import validate_answer
            v = validate_answer(question, body, context)
            if v is not None:
                marker_used = v.used_source
    sources = format_all_citations([cid for cid, _, _ in top]) if top else []
    return body, marker_used, sources


def _eval_questions(db):
    """전후 비교용 고정 문항 — 평가메뉴(AD-006) 현행 버전에서 인스코프 앞 N + 범위외 앞 M.
    2026-08-19 전환: 종전에는 골든셋(evaluation_dataset)을 직접 읽어 화면 편집(추가·수정)이
    반영되지 않았다. 이제 관리자가 보는 평가셋이 곧 평가 문항이다."""
    from api.routers.admin_evaluations import active_questions
    in_scope = active_questions(db, in_scope=True, limit=EVAL_IN_SCOPE)
    oos = active_questions(db, in_scope=False, limit=EVAL_OUT_OF_SCOPE)
    return in_scope, oos


# ──────────────────────── 엔드포인트 ────────────────────────

@router.get("/prompt/draft")
def get_draft(admin: CurrentAdmin, db: DbSession):
    """편집 시작점 — 게시본 기준값. 편집은 화면 로컬에 쌓인다(서버 초안 없음)."""
    del admin
    return build_draft_response(db)


@router.put("/prompt/draft")
def save_draft_deprecated(body: dict, me: CurrentAdmin, db: DbSession):
    """@deprecated — AD-008 은 로컬 초안이라 부르지 않는다(계약 파일 주석). 다른 화면과의
    계약 대조를 위해 시그니처만 유지하고, 서버 상태 없이 기준값을 돌려준다."""
    del body
    _require_editor(me, "프롬프트 초안 저장")
    return build_draft_response(db)


@router.post("/prompt/draft/discard")
def discard_draft_deprecated(body: dict, me: CurrentAdmin, db: DbSession):
    """@deprecated — 되돌리기는 화면의 [초기화](로컬 비우기)로 끝난다. 기준값만 돌려준다."""
    del body
    _require_editor(me, "프롬프트 초안 폐기")
    return build_draft_response(db)


@router.post("/prompt/evaluate")
def evaluate_prompt(body: dict, me: CurrentAdmin, db: DbSession):
    """[전후 비교] — 같은 검색 근거로 현행(전)/초안(후)을 실제 생성해 비교한다.
    서버 초안을 만들지도 바꾸지도 않는다(무상태). ⚠️ HCX (4+2)×2 콜, 동기 ~1분."""
    _require_editor(me, "프롬프트 평가")
    _require_request_id(body)
    content = _draft_to_content(db, dict(body.get("draft") or {}))
    base = _effective(db)
    blockwords = _blockwords(content["guardrails"])

    in_scope, oos = _eval_questions(db)
    if not in_scope:
        raise BadRequestError("평가 문항이 없습니다(evaluation_dataset 비어 있음).")

    items = []
    src_ok = 0
    oos_ok = 0
    guard_hits = 0
    keep = improved = regressed = 0
    for kind, questions in (("in", in_scope), ("oos", oos)):
        for q in questions:
            b_body, b_marker, b_sources = _generate(q, base["system_instruction"], base["few_shot"])
            a_body, a_marker, a_sources = _generate(q, content["system_instruction"], content["few_shot"])
            hits = [w for w in blockwords if w in a_body]
            before_ok = b_marker if kind == "in" else (not b_marker)
            after_ok = ((a_marker if kind == "in" else not a_marker) and not hits)
            if before_ok and not after_ok:
                # REGRESSED 후보만 seed 바꿔 1회 재생성 — 2연속 실패만 회귀 확정(flaky 흡수).
                # seed 고정도 best-effort 라 잔여 비결정이 남는다(2026-08-13 리서치).
                from llm_client import EVAL_SEED
                a_body, a_marker, a_sources = _generate(
                    q, content["system_instruction"], content["few_shot"], seed=EVAL_SEED + 1)
                hits = [w for w in blockwords if w in a_body]
                after_ok = ((a_marker if kind == "in" else not a_marker) and not hits)
            guard_hits += len(hits)
            if kind == "in":
                if after_ok:
                    src_ok += 1
                axis = "출처 부착"
            else:
                if after_ok:
                    oos_ok += 1
                axis = "범위외 거절"
            if before_ok and not after_ok:
                verdict, note = "REGRESSED", f"{axis} 회귀"
                regressed += 1
            elif not before_ok and after_ok:
                verdict, note = "IMPROVED", f"{axis} 개선"
                improved += 1
            else:
                verdict, note = "KEEP", (f"{axis} 유지" if after_ok else f"{axis} 전후 모두 미통과")
                keep += 1
            if hits:
                note += f" · 금칙어 {len(hits)}건"
            items.append({
                "id": f"ev{len(items)+1}", "question": q, "verdict": verdict, "note": note,
                "before": {"answer": b_body, "sources": b_sources},
                "after": {"answer": a_body, "sources": a_sources},
            })

    # 출처 부착은 1건 흔들림 허용(≥ 3/4) — 소표본 100% 요구는 p=0.9 에도 통과율 66%인
    # 동전던지기였다(2026-08-13 실측: 무변경 초안 2회 실행에서 판정 반전). 회귀 확정은
    # 위 seed 재시도(2연속 실패)로 이미 좁혔고, 범위외·금칙어 축은 역사적으로 안정이라 유지.
    src_need = max(len(in_scope) - 1, 1)
    gate = {
        "passed": (src_ok >= src_need and oos_ok == len(oos)
                   and guard_hits == 0 and regressed == 0),
        "source_attached": {"passed": src_ok >= src_need,
                            "count": src_ok, "total": len(in_scope)},
        "out_of_scope": {"passed": oos_ok == len(oos), "count": oos_ok, "total": len(oos)},
        "guardrail": {"passed": guard_hits == 0},
    }
    return {"ran_at": _kst(datetime.now(timezone.utc)),
            "summary": {"total": len(items), "keep": keep,
                        "improved": improved, "regressed": regressed},
            "items": items, "gate": gate}


@router.post("/prompt/publish")
def publish(body: dict, request: Request, me: CurrentAdmin, db: DbSession):
    """[게시] — 이 시점에 비로소 초안이 서버에 저장된다. Smoke 30문항을 새 프롬프트로 실측해
    결과와 무관하게 현행으로 활성화한다(2026-08-19 정책 변경 — 게이트·Smoke 는 경고로만
    남긴다. 종전에는 미달 시 '실패' 버전으로 기록하고 현행을 유지했다).
    ⚠️ HCX 30콜, 동기 ~1-2분."""
    _require_editor(me, "프롬프트 게시")
    _require_request_id(body)
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise BadRequestError("게시 사유를 입력해 주세요.")
    # 2026-08-19 정책 변경: 회귀 게이트는 게시를 막지 않는다 — 경고로만 남긴다(활동 로그 detail).
    gate_warning = None if body.get("gate_passed") else "회귀 게이트 미통과(또는 미평가) 상태로 게시"
    if gate_warning:
        logger.warning("프롬프트 게시: %s", gate_warning)
    content = _draft_to_content(db, dict(body.get("draft") or {}))

    # Smoke 문항도 평가메뉴 현행 버전에서 뽑는다(2026-08-19 전환 — _eval_questions 와 동일).
    from api.routers.admin_evaluations import active_questions
    questions = active_questions(db, in_scope=True, limit=SMOKE_TOTAL)
    if len(questions) < SMOKE_TOTAL:
        raise BadRequestError(f"Smoke 문항이 부족합니다({len(questions)}/{SMOKE_TOTAL}).")

    blockwords = _blockwords(content["guardrails"])

    def _smoke_ok(q: str, *, seed: int | None = None) -> bool:
        try:
            a_body, marker, _src = _generate(
                q, content["system_instruction"], content["few_shot"], seed=seed)
        except Exception:  # noqa: BLE001 — 한 문항 호출 실패 = 그 문항 실패
            logger.warning("smoke 호출 실패: %s", q, exc_info=True)
            return False
        return bool(marker) and not any(w in a_body for w in blockwords)

    from llm_client import EVAL_SEED
    passed = 0
    for q in questions:
        # 실패 문항만 seed 바꿔 1회 재시도(2연속 실패만 실패) — 문항당 p=0.97 이어도
        # 30연속 통과율이 ~40%로 떨어지는 이항 함정을 흡수한다. 전건 통과 의미는 유지.
        if _smoke_ok(q) or _smoke_ok(q, seed=EVAL_SEED + 1):
            passed += 1

    smoke_ok = passed == SMOKE_TOTAL
    # 2026-08-19 정책 변경: Smoke 미달도 게시를 막지 않는다 — 항상 현행으로 활성화하고
    # 미달 여부는 경고(활동 로그·응답 smoke 수치)로만 남긴다. 종전에는 미달 시 현행 유지였다.
    activate = True
    new_version = (db.execute(select(func.max(prompt_versions.c.version))).scalar_one() or 0) + 1
    db.execute(update(prompt_versions).where(prompt_versions.c.is_current)
               .values(is_current=False))
    db.execute(insert(prompt_versions).values(
        version=new_version, is_current=activate,
        system_instruction=content["system_instruction"],
        few_shot=content["few_shot"],
        no_evidence_notice=prompt_builder.NO_EVIDENCE_NOTICE,
        guardrails=content["guardrails"],
        smoke_passed=passed, smoke_total=SMOKE_TOTAL,
        published_by=me.email, reason=reason,
    ))
    db.commit()
    if activate:
        runtime_config.invalidate("prompt")

    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=ACTION_PUBLISH,
        target=f"프롬프트 {_vstr(new_version)}" + ("" if smoke_ok else " (Smoke 미달 — 경고, 활성화됨)"),
        reason=reason,
        detail={"version": new_version, "smoke": {"passed": passed, "total": SMOKE_TOTAL},
                "activated": activate,
                **({"gate_warnings": [w for w in [gate_warning,
                    None if smoke_ok else f"Smoke {passed}/{SMOKE_TOTAL} 미달 상태로 활성화"] if w]}
                   if (gate_warning or not smoke_ok) else {})},
    )
    return {"version": _vstr(new_version), "smoke": {"passed": passed, "total": SMOKE_TOTAL}}


@router.get("/prompt/versions")
def list_versions(admin: CurrentAdmin, db: DbSession, page: int = 1, size: int = 20):
    del admin
    rows = db.execute(
        select(prompt_versions).order_by(prompt_versions.c.version.desc())
    ).all()
    # 긴급 롤백 후보 = 현행이 아닌 것 중 Smoke 를 통과했던 가장 최신 버전(직전 정상본).
    candidate = next((r.version for r in rows
                      if not r.is_current and (r.smoke_passed or 0) >= (r.smoke_total or 0)
                      and r.smoke_total), None)
    items = [{
        "version": _vstr(r.version),
        "created_at": _kst(r.created_at),
        "author": r.published_by or "",
        "reason": r.reason or "",
        "status": ("현행" if r.is_current
                   else "실패" if (r.smoke_passed or 0) < (r.smoke_total or 0) else "보관"),
        "emergency_candidate": r.version == candidate,
    } for r in rows]
    start = (page - 1) * size
    return {"items": items[start:start + size], "total": len(items), "page": page, "size": size}


@router.post("/prompt/versions/{version}/rollback")
def rollback_version(version: str, body: dict, request: Request,
                     me: CurrentAdmin, db: DbSession):
    """[이 버전으로 롤백] — 그 버전 내용을 기준값(PromptDraft)으로 돌려준다. 화면이 이걸
    로컬 초안으로 얹어 검토·재게시한다 — 현행 전환은 게시(Smoke)를 다시 거쳐야 한다."""
    _require_editor(me, "프롬프트 롤백")
    _require_request_id(body)
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise BadRequestError("사유를 입력해 주세요.")
    n = _parse_vstr(version)
    row = db.execute(select(prompt_versions).where(prompt_versions.c.version == n)).first()
    if row is None:
        raise NotFoundError("해당 버전을 찾을 수 없습니다.")
    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=ACTION_ROLLBACK,
        target=f"프롬프트 {version} 내용을 초안으로 복원", reason=reason,
        detail={"version": n},
    )
    return build_draft_response(db, base={
        "version": row.version, "system_instruction": row.system_instruction,
        "few_shot": row.few_shot or prompt_builder.FEW_SHOT_EXAMPLES,
        "guardrails": row.guardrails, "updated_at": row.created_at,
    })


@router.post("/prompt/versions/{version}/emergency-rollback")
def emergency_rollback(version: str, body: dict, request: Request,
                       me: ReauthedAdmin, db: DbSession):
    """긴급 롤백 — 지정 버전을 **즉시 현행으로 전환**한다(Smoke 재실행 없음 — 이미 통과한
    게시본만 후보다). ADMIN + 서버 독립 재인증(me: ReauthedAdmin — 만료면 진입 전 403)."""
    if me.role != "ADMIN":
        raise ForbiddenError(f"긴급 롤백에는 ADMIN 권한이 필요합니다. 현재 권한은 {me.role}입니다.")
    _require_request_id(body)
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise BadRequestError("사유를 입력해 주세요.")
    n = _parse_vstr(version)
    row = db.execute(select(prompt_versions).where(prompt_versions.c.version == n)).first()
    if row is None:
        raise NotFoundError("해당 버전을 찾을 수 없습니다.")
    if row.is_current:
        raise BadRequestError("이미 현행 버전입니다.")
    if (row.smoke_passed or 0) < (row.smoke_total or 0):
        # 2026-08-19 정책 변경: Smoke 미달 버전도 롤백을 막지 않는다 — 경고만 남긴다.
        logger.warning("Smoke 미달 버전으로 긴급 롤백: %s", _vstr(n))

    before = db.execute(
        select(prompt_versions.c.version).where(prompt_versions.c.is_current)
    ).scalar()
    db.execute(update(prompt_versions).where(prompt_versions.c.is_current)
               .values(is_current=False))
    db.execute(update(prompt_versions).where(prompt_versions.c.version == n)
               .values(is_current=True))
    db.commit()
    runtime_config.invalidate("prompt")

    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=ACTION_EMERGENCY,
        target=f"프롬프트 v1.{before} -> {version}", reason=reason,
        detail={"from_version": before, "to_version": n},
    )
    return {"version": _vstr(n), "created_at": _kst(row.created_at),
            "author": row.published_by or "", "reason": row.reason or "",
            "status": "현행", "emergency_candidate": False}


# ──────────────────────── 가드레일 검증 ────────────────────────

@router.post("/guardrails/masking/validate")
def validate_masking_rule(body: dict, me: CurrentAdmin):
    """마스킹 정규식 서버 판정 -> {passed, sample_count, message}.

    ① 문법 오류 ② 과대 매칭(보존 표본이 가려지면 미통과 — 이 서비스 답변의 핵심이 숫자라서
    숫자를 통째로 잡는 패턴이 들어오면 정답이 가려진다)."""
    _require_editor(me, "마스킹 규칙 검증")
    pattern = str(body.get("pattern") or "")
    if not pattern.strip():
        raise BadRequestError("pattern이 필요합니다.")
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return {"passed": False, "sample_count": len(PROTECTED_SAMPLES),
                "message": f"정규식 문법 오류: {exc}"}
    over = [s for s in PROTECTED_SAMPLES if compiled.search(s)]
    if over:
        return {"passed": False, "sample_count": len(PROTECTED_SAMPLES),
                "message": ("과대 매칭 — 보존해야 할 값이 가려집니다: "
                            + ", ".join(over[:3]) + (" 외" if len(over) > 3 else ""))}
    hint = "" if compiled.search(MASKING_MUST_MATCH_HINT) else \
        " (참고: 예시 개인 연락처 010-1234-5678 에는 걸리지 않는 패턴입니다.)"
    return {"passed": True, "sample_count": len(PROTECTED_SAMPLES),
            "message": "검증 통과." + hint}
