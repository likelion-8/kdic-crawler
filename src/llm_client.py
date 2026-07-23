"""HyperCLOVA X 호출 — prompt_builder.py가 만든 메시지를 실제 LLM 응답으로 변환.

langchain-naver의 ChatClovaX는 CLOVASTUDIO_API_KEY 환경변수를 자동으로 찾지만,
src/.env의 키 이름은 CLOVA_STUDIO_API_KEY(언더스코어 위치가 다름)라 자동 인식에
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
