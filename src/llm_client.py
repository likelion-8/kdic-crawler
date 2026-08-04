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
        # 2026-08-03: temperature 0.2 -> 0.1. 근거가 있는데도 모델이 사전학습 지식을 섞어
        # 넣는 사례(코퍼스에 없는 주소 문자열을 답변에 넣음)를 줄이기 위함. 이 값은 파이프라인
        # 전체가 공유한다 — 분해기(query_decomposer), 답변 생성(prompt_builder), 출처 재확인
        # 판정(source_check)이 모두 이 클라이언트를 쓴다.
        #
        # 주의: 분해 판단(쪼갤지 말지)은 이 변경으로 안 고쳐진다. 0.2/0.1 각 5회 실측에서
        # 문제 케이스("명동에 있는 은행 알려줘 착오송금 서류 제출해야하거든")는 양쪽 모두
        # 0/5로 동일하게 안 쪼갰다 — 비결정성이 아니라 분해기의 일관된 오판이라 프롬프트·
        # 라벨셋 쪽 과제다(docs/multiquery_decomposition.md 9절).
        #
        # 기존 문서의 측정치(응답시간·분해 안정성·마커 관련 수치)는 전부 0.2 기준이므로,
        # 다시 비교할 때는 같은 온도에서 재측정할 것.
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
