"""HyperCLOVA X 호출 — prompt_builder.py가 만든 메시지를 실제 LLM 응답으로 변환.

langchain-naver의 ChatClovaX는 CLOVASTUDIO_API_KEY 환경변수를 자동으로 찾지만,
.env의 키 이름은 CLOVA_STUDIO_API_KEY(언더스코어 위치가 다름)라 자동 인식에
맡기지 않고 api_key를 직접 넘긴다.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

_client = {}


def _get_client():
    if "model" not in _client:
        from langchain_naver import ChatClovaX
        # temperature는 0.2다(아래 코드가 정본). 이 값은 HCX를 쓰는 경로가 전부 공유한다 —
        # llm_client 를 import 하는 곳은 넷뿐이다 — 답변 생성 pipeline.py(invoke)와
        # api/rag/sse.py(stream), 출처 재확인 판정 source_check.py, 폴백 경로의 분해기
        # query_decomposer.py.
        # 쿼리 플래너(query_planner)는 HCX가 아니라 OpenAI를 쓰므로 이 설정과 무관하다.
        #
        # 2026-08-03에 "근거가 있는데도 모델이 사전학습 지식을 섞어 넣는 사례(코퍼스에 없는
        # 주소 문자열을 답변에 넣음)를 줄이려 0.2 -> 0.1로 낮춘다"는 안이 있었으나 코드에는
        # 반영되지 않았다(파일 생성 이후 줄곧 0.2). 아래 실측·측정치는 전부 0.2 기준이다.
        #
        # 주의: 분해 판단(쪼갤지 말지)은 온도를 낮춰도 안 고쳐진다. 0.2/0.1 각 5회 실측에서
        # 문제 케이스("명동에 있는 은행 알려줘 착오송금 서류 제출해야하거든")는 양쪽 모두
        # 0/5로 동일하게 안 쪼갰다 — 비결정성이 아니라 분해기의 일관된 오판이라 프롬프트·
        # 라벨셋 쪽 과제다(docs/multiquery_decomposition.md 9절).
        #
        # 온도를 실제로 바꾸게 되면, 기존 문서의 측정치(응답시간·분해 안정성·마커 관련 수치)는
        # 전부 0.2 기준이므로 같은 온도에서 재측정해야 비교가 성립한다.
        _client["model"] = ChatClovaX(
            model_name=os.environ["CLOVA_MODEL"],
            api_key=os.environ["CLOVA_STUDIO_API_KEY"],
            temperature=0.2,
            max_tokens=2048,
        )
    return _client["model"]


def call_hyperclova(messages):
    """messages: prompt_builder.build_informational_prompt()/build_civil_petition_prompt()가
    반환한 [(role, content), ...] 튜플 리스트. 응답 텍스트(str)만 반환한다."""
    response = _get_client().invoke(messages)
    return response.content


def stream_hyperclova(messages):
    """call_hyperclova와 같은 클라이언트·설정을 쓰되 응답을 토큰 조각(str)으로 순차 yield한다.
    SSE 스트리밍(api/rag/sse.py)이 이 제너레이터를 소비한다 — .invoke() 대신 .stream()을 쓴다.
    각 청크의 content만 흘리고 빈 조각은 건너뛴다. 호출부가 조각을 이어붙이면 call_hyperclova의
    반환 문자열과 동일해야 한다(동일 모델·프롬프트 기준)."""
    for chunk in _get_client().stream(messages):
        text = getattr(chunk, "content", "") or ""
        if text:
            yield text
