"""런타임 설정 — 파이프라인 상수를 DB(관리자 화면)에서 읽되, **없으면 코드 상수를 쓴다.**

AD-007(RAG 파라미터)·AD-008(프롬프트)이 값을 바꿀 수 있게 하려면 파이프라인이 상수 대신
DB 를 봐야 한다. 그런데 그냥 DB 조회로 바꾸면 **DB 가 느리거나 비면 답변 경로가 통째로
멈춘다.** 그래서 읽기를 이 모듈 하나로 모으고, 실패·부재를 전부 기본값으로 흡수한다.

## 핵심 계약

    get_param("k_candidates", K_CANDIDATES)   ->  DB 값 또는 K_CANDIDATES

- **DB 가 비어 있으면 오늘과 완전히 똑같이 동작한다.** 행이 없는 것은 오류가 아니라
  '기본값 사용'이라는 정상 상태다. 그래서 롤백은 `rag_param_versions` 의 current 행을
  지우는 것 하나로 끝난다.
- DB 가 죽어도 답변은 나온다. 예외를 삼키고 기본값으로 떨어진다.

## 호출 시점이 중요하다

모듈 최상단에서

    K_CANDIDATES = get_param("k_candidates", 20)      # ❌

처럼 쓰면 **import 시점에 값이 굳어** 관리자가 바꿔도 재시작 전까지 반영되지 않는다.
관리자 화면을 만드는 목적 자체가 사라진다. 반드시 **쓰는 자리에서** 부를 것:

    route_search_chunks(query, k=get_param("k_candidates", K_CANDIDATES))   # ✅

코드 상수는 지우지 않고 **문서화된 기본값**으로 남긴다 — 각 상수 주석에 붙은 실측 근거
(리랭커 CPU 96초 · MIN_TOP1_SCORE 0.35 도출 · 플래너 100문항 벤치마크)가 "왜 이 값인가"의
유일한 기록이라, DB 로 옮겼다고 지우면 근거가 사라진다.

## 모듈 전역 덮어쓰기가 이긴다

`src/eval/eval_pipeline_generation.py:82` 가 `pipeline.USE_RERANKER = args.rerank` 로 모듈
전역을 런타임에 바꿔 A/B 를 돌린다. 그래서 호출부는 늘 `get_param(name, 현재_모듈_전역)`
형태로 부르고, 이 모듈은 **DB 에 값이 있을 때만** 그것을 쓴다. 즉 덮어쓴 전역은 DB 에 해당
파라미터가 없으면 그대로 이긴다. 평가 스크립트를 고치지 않아도 되게 하기 위한 것이다.

⚠️ DB 에 그 파라미터가 들어간 뒤에는 DB 가 이긴다. 평가 스크립트로 A/B 를 돌릴 때는
   해당 파라미터를 DB 에서 빼거나 `override()` 를 쓸 것.

## 캐시

매 질의마다 DB 를 치면 latency 가 는다. 프로세스당 dict 하나를 TTL 로 들고 있는다.

- 같은 프로세스(FastAPI 안의 관리자 API)가 값을 바꾸면 `invalidate()` 로 즉시 반영한다.
- CLI 처럼 다른 프로세스는 TTL 이 만료될 때 따라온다(최대 CACHE_TTL_S 지연).

## 실패를 조용히 삼키지 않는다

`src/query_classifier.py` 가 예외를 조용히 삼켜 **실서버 답변이 100% informational 이었던**
사고가 있었다(2026-08-04 수정). 같은 실수를 막으려고 여기서는 반드시 경고 로그를 남긴다.
다만 질의마다 찍으면 로그가 뒤덮이므로 TTL 창당 한 번으로 줄인다.
"""
import logging
import time

logger = logging.getLogger(__name__)

# 다른 프로세스(CLI)가 관리자 변경을 따라잡는 최대 지연. 짧게 잡으면 DB 왕복이
# 늘고, 길게 잡으면 "바꿨는데 왜 그대로냐"가 된다. 파라미터 변경은 사람이 가끔 하는 일이라
# 60초면 충분하다(같은 프로세스는 invalidate() 로 즉시 반영된다).
CACHE_TTL_S = 60

# 캐시 한 벌. params/prompt 를 따로 두는 이유는 무효화 시점이 다르기 때문이다
# (파라미터 apply 와 프롬프트 publish 는 서로 다른 화면·다른 테이블이다).
_cache = {
    "params": {"value": None, "at": 0.0},
    "prompt": {"value": None, "at": 0.0},
}

# 테스트·평가용 강제 주입. None 이 아니면 DB 를 아예 안 본다(override 참고).
_forced = {"params": None, "prompt": None}

# 마지막으로 경고를 찍은 시각 — 질의마다 찍지 않기 위한 것.
_last_warned = {"params": 0.0, "prompt": 0.0}


def _warn_once(kind: str, exc: Exception) -> None:
    """TTL 창당 한 번만 경고한다. 조용히 삼키지도, 로그를 뒤덮지도 않기 위해서다."""
    now = time.monotonic()
    if now - _last_warned[kind] >= CACHE_TTL_S:
        _last_warned[kind] = now
        logger.warning(
            "런타임 설정(%s)을 읽지 못해 코드 기본값으로 동작한다 — 관리자 화면에서 바꾼 값이 "
            "반영되지 않는 상태다: %r", kind, exc)


def _load_params() -> dict:
    """rag_param_versions 의 current 행 -> {이름: 값}. 없거나 실패하면 빈 dict.

    빈 dict 는 오류가 아니다 — get_param 이 전부 기본값으로 떨어지고, 그게 '오늘과 같은
    동작'이다. 그래서 반환 타입에 None 을 두지 않는다(호출부가 분기할 필요가 없게).
    """
    try:
        from db import get_session
        from schema_admin import rag_param_versions
        from sqlalchemy import select

        with get_session() as session:
            row = session.execute(
                select(rag_param_versions.c.params)
                .where(rag_param_versions.c.status == "current")
            ).first()
        return dict(row.params) if row and row.params else {}
    except Exception as exc:  # noqa: BLE001 — 설정 조회가 답변을 막으면 안 된다
        _warn_once("params", exc)
        return {}


def _load_prompt() -> dict:
    """prompt_versions 의 is_current 행 -> {필드: 값}. 없거나 실패하면 빈 dict."""
    try:
        from db import get_session
        from schema_admin import prompt_versions
        from sqlalchemy import select

        with get_session() as session:
            row = session.execute(
                select(prompt_versions.c.system_instruction,
                       prompt_versions.c.few_shot,
                       prompt_versions.c.no_evidence_notice,
                       prompt_versions.c.guardrails,
                       prompt_versions.c.version)
                .where(prompt_versions.c.is_current)
            ).first()
        if row is None:
            return {}
        return {
            "system_instruction": row.system_instruction,
            "few_shot": row.few_shot,
            "no_evidence_notice": row.no_evidence_notice,
            # AD-008 이 게시한 금칙어·마스킹 규칙. 챗 경로(api/rag/answer.py guardrail_hit)가
            # 읽는다 — 종전에는 게시해도 어디에도 적용되지 않았다(2026-08-13 F-3).
            "guardrails": row.guardrails,
            "version": row.version,
        }
    except Exception as exc:  # noqa: BLE001
        _warn_once("prompt", exc)
        return {}


_LOADERS = {"params": _load_params, "prompt": _load_prompt}


def _get(kind: str) -> dict:
    """TTL 캐시를 거쳐 한 벌을 돌려준다."""
    if _forced[kind] is not None:
        return _forced[kind]
    slot = _cache[kind]
    now = time.monotonic()
    if slot["value"] is None or now - slot["at"] >= CACHE_TTL_S:
        slot["value"] = _LOADERS[kind]()
        slot["at"] = now
    return slot["value"]


def get_param(name: str, default):
    """활성 파라미터 값. DB 에 그 이름이 없으면 default 를 그대로 돌려준다.

    default 에는 **호출 시점의 모듈 전역**을 넘길 것(예: `pipeline.USE_RERANKER`). 그래야
    평가 스크립트의 전역 덮어쓰기가 DB 에 값이 없는 동안 계속 이긴다(모듈 주석 참고).

    ⚠️ 반환값의 타입 검사는 하지 않는다. DB(JSONB)에 잘못된 타입이 들어가면 그대로 나온다 —
    쓰기 쪽(AD-007 apply)이 파라미터 메타의 min/max/step 으로 검증하는 것이 정본이다.
    """
    value = _get("params").get(name)
    return default if value is None else value


def get_prompt(name: str, default):
    """활성 프롬프트 구성요소(system_instruction / few_shot / no_evidence_notice).

    게시본이 없으면 default(= prompt_builder 의 코드 상수)를 그대로 쓴다.
    """
    value = _get("prompt").get(name)
    return default if value is None else value


def current_versions() -> dict:
    """지금 적용 중인 버전 표시용 -> {"prompt": int|None}.

    파라미터 쪽은 params JSONB 안에 버전을 담지 않으므로(행의 version 컬럼이 정본) 여기서는
    프롬프트만 돌려준다. 관리자 화면이 '현재 적용본'을 보여줄 때 쓴다.
    """
    return {"prompt": _get("prompt").get("version")}


def invalidate(kind: str = None) -> None:
    """캐시를 버린다. 관리자 API 가 값을 바꾼 **직후** 부를 것.

    같은 프로세스(FastAPI)는 이걸로 즉시 반영되고, 다른 프로세스(CLI)는 TTL 이
    만료될 때 따라온다. kind 를 안 주면 둘 다 버린다.
    """
    for key in ([kind] if kind else list(_cache)):
        _cache[key]["value"] = None
        _cache[key]["at"] = 0.0


def override(kind: str, value: dict) -> None:
    """DB 를 보지 않고 한 벌을 강제한다 — **테스트·평가 전용.**

    value 에 {} 를 주면 "DB 가 빈 상태"를 재현한다(= 전부 코드 기본값). None 을 주면 강제를
    풀고 다시 DB 를 본다. 운영 코드에서는 쓰지 마라.
    """
    _forced[kind] = value
