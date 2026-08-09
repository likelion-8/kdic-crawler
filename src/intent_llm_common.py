"""LLM 기반 intent 분류의 공유 스키마·시스템 프롬프트.

지금 이 모듈을 import하는 곳은 query_classifier.py 하나다(IntentResult·SYSTEM_PROMPT).
그리고 그 classify_intent() 자체가 쿼리 플래너(query_planner)를 끈 USE_QUERY_PLANNER=False
폴백 경로 전용이라, 평소 서비스 경로(pipeline._answer_one · api/rag/answer.prepare_sub)에서는
둘 다 `if intent is None:` 가드 안에 있어 타지 않는다.

단, 평가 스크립트 eval_pipeline_retrieval.py 는 가드 없이 classify_intent()를 직접 부른다.
그래서 아래 SYSTEM_PROMPT 를 고치면 서비스 동작은 그대로여도 그 평가 수치는 움직인다.

원래는 HCX 구현과 OpenAI 구현이 '완전히 동일한' 스키마·프롬프트를 쓰게 해서 두 모델을 공정
비교하려고 분리한 파일이다(프롬프트가 조금이라도 다르면 비교가 성립하지 않으므로).
그 비교 실험의 결과는 docs/intent_classifier_comparison.md 에 있다.
※ 예전 주석이 양쪽 구현으로 지목하던 classify_intent_hyperclova.py·classify_intent_openai.py
   두 파일은 이 저장소에 커밋된 적이 없다(git 이력 확인). 찾지 말 것.

⚠️ query_planner.py 는 이 파일을 import하지 않는다 — 분해 규칙과 intent 규칙을 한 지시로
합쳐야 해서 SYSTEM_PROMPT 를 자기 파일에 따로 갖고 있다. 라벨 정의(informational/
civil_petition)를 고칠 때는 두 곳을 같이 고쳐야 판단 기준이 갈리지 않는다.

Structured Output은 '이진분류 기능'이 아니라 'LLM 출력 형식을 제약'하는 기능이다. 실제
판단은 LLM의 언어이해가 하고(확률론적 — 같은 입력도 100% 동일 출력 보장 안 됨), 여기서는
그 출력이 반드시 두 라벨 중 하나가 되도록 Literal로 스키마를 강제한다. 기존 LogReg의
'학습된 가중치' 역할을, 아래 사람이 작성한 시스템 프롬프트(정의 + 혼동 예시)가 대신한다.
"""
from typing import Literal

from pydantic import BaseModel, Field


class IntentResult(BaseModel):
    """intent 분류 결과 — 반드시 두 값 중 하나만 나오도록 Literal로 제약."""
    intent: Literal["informational", "civil_petition"] = Field(
        description="질문의 의도. 개념·사실을 묻으면 informational, 신청·접수 등 절차를 "
                    "실행하려 하면 civil_petition."
    )


# 두 구현이 공유하는 시스템 프롬프트. LogReg의 학습 가중치를 대체하는 '사람이 쓴 규칙+예시'.
SYSTEM_PROMPT = """당신은 예금보험공사(KDIC) 챗봇의 질의 의도 분류기입니다. 사용자 질문을 읽고
두 가지 의도 중 하나로만 분류하세요. 질문에 답하지 말고, 오직 의도만 판단하세요.

[두 가지 의도]
- informational (정보성): 제도·개념·용어·사실·수치를 '알고 싶어' 하는 질문.
  예) "예금보험금이 뭐예요?", "보호 한도는 얼마인가요?", "착오송금 반환지원 제도는 무엇인가요?"
- civil_petition (민원성): 신청·접수·제출·발급 등 '절차를 실행'하려는 질문. 필요한 서류·방법·
  기한을 묻는 것도 실행 의도로 봅니다.
  예) "예금보험금 어떻게 신청해요?", "반환 신청에 필요한 서류가 뭐예요?", "위임장 어디서 받아요?"

[판단 규칙]
1. "~이/가 뭐예요", "~무엇인가요", "~얼마예요", "~어떤 게 있나요"처럼 정의·사실을 물으면 informational.
2. "~어떻게 신청해요", "~하려면", "~신청 방법", "필요한 서류"처럼 절차 실행을 물으면 civil_petition.
3. 구어체·축약·오타가 섞여도 '실행 의도'가 있으면 civil_petition으로 판단하세요.
   예) "돈 잘못 보냈는데 어케해" → 반환을 실행하려는 의도 → civil_petition
       "내 돈 받을 수 있는 거임?" → 가능 여부(사실)를 물음 → informational
4. 인사말·잡담·업무와 무관한 질문(예: "하이요", "안녕하세요", "우주여행 가고 싶어요",
   "주식 투자 어떻게 해요")은 절차 실행이 아니므로 informational로 처리하세요(안전한 기본값).
5. 애매하면 informational로 처리하세요."""
