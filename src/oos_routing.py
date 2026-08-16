"""OOS 라우팅 게이트와 Context Supervisor.

검색·생성 경로가 CLI(`pipeline.py`)와 웹 SSE(`api/rag/answer.py`)로 나뉘어
있기 때문에, 범위 판정의 계약은 이 모듈에 둔다.

게이트는 확실한 경우만 앞에서 종료한다. 임계값을 넘지 못한 애매한 질의는
항상 다음 단계로 흘려보내고, 검색 근거가 준비된 뒤 Context Supervisor가
최종적으로 ANSWERABLE / OOS / INSUFFICIENT_EVIDENCE를 판단한다.
"""
from dataclasses import dataclass
import logging
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field
from observability import observe

logger = logging.getLogger(__name__)

Decision = Literal["ANSWERABLE", "OOS", "INSUFFICIENT_EVIDENCE"]

# 기준선 비교를 위한 런타임 스위치. 운영 기본값은 켜짐이며, 평가에서만
# get_param/override로 꺼서 supervisor 도입 전후를 짝지어 비교할 수 있다.
USE_CONTEXT_SUPERVISOR = True

# 실측 전에는 코사인 게이트를 사실상 끈다. 821개 인스코프 문항에서 오차단 0인
# 임계값을 측정한 뒤 관리자 파라미터로 올린다. 기본값을 공격적으로 잡지 않는 것은
# 새 게이트가 정상 질문을 조용히 거절하는 회귀를 막기 위해서다.
MIN_ROUTE_COSINE_SCORE = 0.0

# 리랭커는 현재 기본 Off이고, 모델 로짓의 운영 분포도 아직 확정하지 않았다.
# -100은 실제 임계값이 측정될 때까지의 안전한 비활성 기본값이다.
MIN_RERANK_TOP1_SCORE = -100.0

OUT_OF_SCOPE_MESSAGE = (
    "문의하신 내용은 예금보험공사가 제공하는 정보의 범위를 벗어난 질문이라 정확한 안내가 "
    "어렵습니다. 예금자보호제도나 착오송금 반환지원 등 공사 업무에 대해 궁금하신 점을 물어봐 주세요."
)
INSUFFICIENT_EVIDENCE_MESSAGE = (
    "질문에 답할 수 있는 충분한 근거를 제공된 자료에서 찾지 못했습니다. "
    "예금자보호제도나 착오송금 반환지원 등 공사 업무에 관해 조금 더 구체적으로 물어봐 주세요."
)

# 문서 전체를 supervisor에 넣지 않고, 현재 코퍼스가 다루는 업무 축과 명백한
# 비대상 예시만 고정한다. 세부 사실은 반드시 Top5 근거에서 확인하게 한다.
SCOPE_KB = """예금보험공사(KDIC) 상담 범위:
- 예금자보호제도: 보호한도, 보호·비보호 금융상품과 금융회사, 제도·표시·설명·확인
- 예금보험금: 보험금의 정의, 지급·신청 절차, 지급 대상 금융회사, 구비서류
- 고객 미수령금: 미수령금 조회·신청, 상속인 금융거래조회, 관련 문의 안내
- 착오송금 반환지원: 신청대상·기한·금액, 신청·반환 절차, 송금인·수취인 구비서류와 유의사항
- 채무조정: 파산 금융회사 채무조정, 이자율 조정, 신청 자격·서류·절차
- 은닉재산 신고: 신고 대상·방법·처리 및 포상금 안내

예금보험공사 업무와 무관한 타 기관의 민원·법률·투자·대출·의료·여행·일상 잡담은
업무 범위 밖으로 본다. 다만 질문이 KDIC 업무와 연결되는지는 질문과 근거를 함께 보고 판단한다.
"""


@dataclass(frozen=True)
class GateResult:
    """앞단 게이트의 결과. decision=None이면 다음 단계로 통과한다."""

    stage: str
    decision: Optional[Decision] = None
    response: Optional[str] = None
    route_type: Optional[str] = None
    route_score: Optional[float] = None
    reason: Optional[str] = None

    @property
    def is_terminal(self) -> bool:
        return self.decision is not None


class ContextSupervisorResult(BaseModel):
    """검색 근거를 본 뒤의 3-way 판정."""

    decision: Literal["ANSWERABLE", "OOS", "INSUFFICIENT_EVIDENCE"] = Field(
        description="질문과 Top5 근거의 관계에 대한 최종 판정"
    )
    rationale: str = Field(
        description="판정의 짧은 이유. 답변 본문으로 사용자에게 노출하지 않는다.",
    )


_RULE_PHRASES = {
    "안녕", "안녕하세요", "안녕하십니까", "하이", "하이요", "헬로", "반가워", "반가워요",
    "반갑습니다", "감사합니다", "감사해요", "고마워", "고마워요", "잘지내",
    "너는누구야", "넌누구야", "너는누구야hyperclovaxy", "무슨ai야", "무슨인공지능이야", "어떤ai야",
    "뭘할수있어", "뭐할수있어", "무엇을할수있어", "무엇을할수있나요", "무슨일을할수있어", "오늘날씨어때",
    "우주여행가고싶어요", "주식투자어떻게해",
}
_IDENTITY_PHRASES = {
    "너는누구야", "넌누구야", "너는누구야hyperclovaxy", "무슨ai야", "무슨인공지능이야", "어떤ai야",
    "뭘할수있어", "뭐할수있어", "무엇을할수있어", "무엇을할수있나요", "무슨일을할수있어",
}


def _compact(text: str) -> str:
    """규칙 게이트용 정규화. 단어 내부 공백·종결부호 차이만 흡수한다."""
    return re.sub(r"[^0-9a-z가-힣]+", "", str(text or "").casefold())


def rule_gate(query: str) -> Optional[GateResult]:
    """명백한 인사·정체성·잡담만 판정한다.

    전체 문장이 알려진 짧은 표현과 일치할 때만 종료한다. 예를 들어
    ``안녕하세요, 보호한도는 얼마인가요?``는 검색 경로로 통과한다.
    """
    compact = _compact(query)
    if not compact or compact not in _RULE_PHRASES:
        return None
    if compact in _IDENTITY_PHRASES:
        body = "안녕하세요! 저는 예금보험공사의 AI 상담 챗봇 예솜입니다. 예금자보호제도나 착오송금 반환지원처럼 궁금하신 점을 편하게 물어봐 주세요."
    elif compact in {"감사합니다", "감사해요", "고마워", "고마워요"}:
        body = "도움이 되어 기쁩니다. 예금보험공사 업무에 관해 궁금한 점이 있으면 언제든지 물어봐 주세요."
    else:
        body = "안녕하세요! 예금보험공사와 관련해 궁금하신 점이 있으시면 말씀해주세요."
    return GateResult(
        stage="rule",
        decision="OOS",
        response=body,
        reason="obvious_smalltalk",
    )


def pre_route(query: str, route_signal=None) -> GateResult:
    """룰 게이트와 코사인 극단값 게이트를 순서대로 적용한다.

    ``route_signal``은 ``(question_type, top1_similarity)`` 튜플이다. 없으면
    운영과 같은 1-NN 분류기를 사용한다. 분류기/DB가 일시적으로 실패하면
    게이트를 적용하지 않고 통과시켜 검색 서비스가 막히지 않게 한다.
    """
    ruled = rule_gate(query)
    if ruled is not None:
        return ruled

    try:
        from runtime_config import get_param
        threshold = get_param("min_route_cosine_score", MIN_ROUTE_COSINE_SCORE)
        # 임계값 0.0은 실측 전 비활성 상태다. 이때는 검색 라우터가 원래 하던
        # 1-NN 계산만 수행하게 두어 게이트 때문에 임베딩을 한 번 더 만들지 않는다.
        if float(threshold) <= MIN_ROUTE_COSINE_SCORE and route_signal is None:
            return GateResult(stage="pre_route")
        if route_signal is None:
            from query_classifier import classify_question_type_with_score
            route_signal = classify_question_type_with_score(query)
        route_type, route_score = route_signal
        if float(route_score) < float(threshold):
            return GateResult(
                stage="cosine",
                decision="OOS",
                response=OUT_OF_SCOPE_MESSAGE,
                route_type=route_type,
                route_score=float(route_score),
                reason="extreme_low_route_similarity",
            )
        return GateResult(
            stage="pre_route",
            route_type=route_type,
            route_score=float(route_score),
        )
    except Exception:  # noqa: BLE001 — 라우팅 보조 신호 실패는 검색을 막지 않는다
        logger.warning("OOS 사전 라우팅 신호를 계산하지 못해 게이트를 통과시킵니다", exc_info=True)
        return GateResult(stage="pre_route", reason="route_signal_unavailable")


def _supervisor_messages(query: str, top: list, scope_kb: str) -> list:
    context = "\n\n".join(
        f"[근거 {i}] score={float(score):.4f}\n{text}"
        for i, (_cid, score, text) in enumerate(top[:5], 1)
    )
    system = f"""당신은 KDIC RAG의 Context Supervisor입니다. 질문과 검색 근거를 보고 답변 가능성을 3가지 중 하나로만 판정하세요.

[판정]
- ANSWERABLE: 질문이 KDIC 범위에 속하고, Top5 근거에 질문에 답할 핵심 내용이 있다.
- OOS: 질문 자체가 KDIC 업무 범위 밖이다. 근거가 비슷해 보여도 다른 기관·다른 업무를 묻는다면 OOS다.
- INSUFFICIENT_EVIDENCE: 질문은 KDIC 범위일 수 있지만 Top5 근거만으로 답을 뒷받침하기 부족하거나 서로 맞지 않는다.

점수가 높다는 이유만으로 ANSWERABLE로 판정하지 말고, 질문의 실제 요구와 근거 내용을 확인하세요.
애매하면 OOS가 아니라 INSUFFICIENT_EVIDENCE를 우선하세요. 오직 JSON 구조화 출력으로 판정합니다.

[Scope KB]
{scope_kb}

[검색 근거 Top5]
{context}
"""
    return [{"role": "system", "content": system}, {"role": "user", "content": query}]


_openai = {}
_temperature_unsupported = set()


def _get_client():
    if "client" not in _openai:
        from openai import OpenAI
        _openai["client"] = OpenAI()
    return _openai["client"]


def _parse(client, model, messages):
    if model not in _temperature_unsupported:
        try:
            return client.beta.chat.completions.parse(
                model=model, messages=messages,
                response_format=ContextSupervisorResult, temperature=0,
            )
        except Exception as exc:
            if "temperature" not in str(exc).lower():
                raise
            _temperature_unsupported.add(model)
    return client.beta.chat.completions.parse(
        model=model, messages=messages, response_format=ContextSupervisorResult,
    )


@observe()
def supervise_context(query: str, top: list, scope_kb: str = SCOPE_KB) -> ContextSupervisorResult:
    """질문 + Top5 + Scope KB의 3-way 판정.

    supervisor 장애 시 ANSWERABLE로 fail-open한다. 이 호출은 OOS를 줄이는
    보조 판정기이지, 외부 모델 장애로 기존 답변 경로를 중단시키는 단일 장애점이
    아니어야 한다.
    """
    try:
        import os
        if not os.environ.get("OPENAI_API_KEY"):
            return ContextSupervisorResult(
                decision="ANSWERABLE", rationale="supervisor_api_key_unavailable",
            )
        model = (os.environ.get("OPENAI_SUPERVISOR_MODEL")
                 or os.environ.get("OPENAI_PLANNER_MODEL")
                 or "gpt-5.6-luna")
        completion = _parse(_get_client(), model, _supervisor_messages(query, top, scope_kb))
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError("supervisor structured output이 비어 있습니다")
        return parsed
    except Exception:  # noqa: BLE001 — supervisor 장애는 기존 생성 경로를 보존
        logger.warning("Context Supervisor 실패 — ANSWERABLE로 fail-open", exc_info=True)
        return ContextSupervisorResult(
            decision="ANSWERABLE", rationale="supervisor_unavailable",
        )
