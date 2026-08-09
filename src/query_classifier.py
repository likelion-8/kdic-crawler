"""질문 분류 — 유형(question_type: table_lookup 여부)과 업무(business_function) 판별.

둘 다 같은 메커니즘(테스트셋 라벨링 질문과의 코사인 유사도 1-최근접)을 쓴다.
retrieval.py의 라우팅/검색 실행과 분리해, "무엇으로 라우팅할지 판단"과 "그 판단으로
검색을 실행"하는 책임을 나눈다. RoutedRetriever(retrieval.py)가 이 분류기들을 받아
qtype/business_function을 자동으로 채워 넣는다.
"""
import os

from dotenv import load_dotenv

from retrieval import DEFAULT_DENSE_MODEL, ROOT, _encode_query, _get_model

load_dotenv(ROOT / ".env")  # OPENAI_API_KEY 등 로드(intent 분류 OpenAI 호출용)

_LABEL_FIELDS = ("question_type", "business_function")


class QuestionTypeClassifier:
    """새 질문의 유형(qtype)을 예시 질문과의 코사인 유사도로 분류(1-최근접).

    예시는 Supabase evaluation_dataset의 (question, question_type, embedding)을 그대로
    쓴다(expected_sources 빈 값=out_of_scope 제외). evaluation_dataset.embedding은
    index_evaluation_sets.py가 미리 계산해 저장해둔 값이라, 프로세스 시작 시 한 번만
    통째로 읽어 메모리에 올려두고(2026-08-03 로컬 JSONL+npy 캐시에서 이관) 그 뒤로는
    Supabase에 다시 안 물어본다 — 질문 하나 처리할 때마다 재계산되는 게 아니라, 질의
    임베딩 1건 + 메모리의 참조 벡터들과의 내적 비교만 매번 일어난다(수 ms 수준).

    table_lookup이 페이지 구조가 아니라 질문 자체의 형태(엔티티+조회 의도)에서
    나온다는 게 확인돼서(2026-07-21), 코퍼스(본문) 대신 라벨링된 질문을 예시로 쓴다.
    """
    def __init__(self, model=DEFAULT_DENSE_MODEL, label_field="question_type"):
        # label_field로 라벨을 바꿔 재사용 — question_type(유형 라우팅) 또는
        # business_function(업무 필터) 분류에 같은 1-NN·같은 evaluation_dataset 임베딩을 쓴다.
        assert label_field in _LABEL_FIELDS, f"알 수 없는 label_field: {label_field}"
        import numpy as np
        from sqlalchemy import func, select

        from db import get_engine
        from schema import evaluation_dataset

        c = evaluation_dataset.c
        stmt = (select(c.question, c[label_field], c.embedding)
                .where(func.cardinality(c.expected_sources) > 0))
        with get_engine().connect() as conn:
            rows = conn.execute(stmt).all()

        self.types = [r[1] for r in rows]
        self.emb = np.array([r[2] for r in rows])
        self.model = _get_model(model)

    def classify(self, query):
        import numpy as np
        q = _encode_query(self.model, query)
        best = int(np.argmax(self.emb @ q))
        return self.types[best]


# 2026-07-29 팀 결정: 업무(business_function) 분류는 검색에 쓰지 않기로 하여 비활성화.
# (retrieval._build_engines가 bf_classifier를 넘기지 않아 이미 무필터였고, 이 클래스는
#  아무도 인스턴스화하지 않던 죽은 코드였음.) 재도입 시 아래 주석을 되살리고, retrieval.py의
#  import·RoutedRetriever 인자, app.py 워밍업도 함께 복원할 것.
# class BusinessFunctionClassifier(QuestionTypeClassifier):
#     """질의 → 6개 업무(business_function) 분류. QuestionTypeClassifier와 같은 1-NN·같은
#     질문 임베딩 캐시를 쓰되 라벨만 business_function으로 바꾼다. 결과값을 RoutedRetriever
#     (또는 leaf)의 search(..., business_function=...)에 넣어 업무 범위를 좁힌다."""
#     def __init__(self, model=DEFAULT_DENSE_MODEL):
#         super().__init__(model=model, label_field="business_function")


# 함수형 인터페이스 — label_field별로 분류기 인스턴스를 한 번만 만들어 재사용(임베딩
# 재계산 방지). 프로세스당 1회 로딩되고, 예시 벡터 캐시는 DenseRetriever와 동일한
# (모델+텍스트) 해시라 테스트셋 내용이 실제로 바뀔 때만 재계산된다.
_classifiers = {}


def _get_classifier(label_field):
    if label_field not in _classifiers:
        _classifiers[label_field] = QuestionTypeClassifier(label_field=label_field)
    return _classifiers[label_field]


def classify_query_type(query):
    """table_lookup 여부만 판단(이진). RoutedRetriever가 Dense/Hybrid 중 뭘 쓸지
    고르는 데 이 결과만 쓰므로, 5개 유형 중 table_lookup만 구분하고 나머진 general로 접는다."""
    qtype = _get_classifier("question_type").classify(query)
    return "table_lookup" if qtype == "table_lookup" else "general"


def classify_question_type(query):
    """question_type 원본 라벨(fact/faq/table_lookup/link_guide/file_download 등)을 그대로
    반환한다. classify_query_type()과 같은 분류기(같은 캐시된 인스턴스)를 재사용하되, 라우팅용
    이진 접기 없이 원본 라벨이 필요한 곳(rag_runs 로깅 등)에서 쓴다."""
    return _get_classifier("question_type").classify(query)


# ── intent 분류: OpenAI Structured Output (2026-08-03, 기존 Kiwi+TF-IDF+LogReg에서 교체) ──
# 채택 근거: held-out(testset_pipeline) 4자 비교에서 gpt-5.4-mini가 전체 92.1%·구어체 93.8%로
# 최고이면서 응답 ~0.85초로 빠르고, native structured output으로 출력이 두 라벨 중 하나로 보장됨
# (기존 TF-IDF baseline 77.2% 대비 큰 개선, HCX-007 91.0%보다 빠름).
# 상세: docs/intent_classifier_comparison.md. 스키마·프롬프트는 intent_llm_common.py 재사용.
# question_type 분류(위 QuestionTypeClassifier)는 코사인 방식 그대로 유지 — 이번 교체 대상 아님.
#
# 2026-08-09: 멀티쿼리 분해 + intent를 한 콜로 처리하는 query_planner.plan_query()를 도입하면서
# classify_intent()는 그 플래너를 끈(USE_QUERY_PLANNER=False) 경우의 폴백 경로가 됐다. 모델
# 환경변수는 플래너와 공유한다(OPENAI_PLANNER_MODEL) — 같은 OpenAI 모델(gpt-5.6-luna)을 쓰므로
# 하나로 통일. 이름이 OPENAI_INTENT_MODEL에서 바뀐 이유는 이 모델이 이제 intent만 하지 않기 때문.
_OPENAI_INTENT_MODEL = os.environ.get("OPENAI_PLANNER_MODEL") or "gpt-5.6-luna"
_openai = {}

# 2026-08-04: 모델마다 temperature 지원 여부가 다르다(gpt-5.4-mini는 0 허용, gpt-5.6-luna
# 같은 일부 모델은 기본값 1만 허용하고 0을 주면 즉시 BadRequestError). 이 프로젝트는 지금까지
# HCX-007 -> gpt-4o-mini -> gpt-5.4-mini -> gpt-5.6-luna로 모델을 계속 바꿔왔으므로(교체 근거
# docs/intent_classifier_comparison.md), "이 모델은 temperature 됨/안 됨" 목록을 코드에
# 박아두면 모델 바꿀 때마다 또 손봐야 한다. 대신 일단 temperature=0으로 시도하고, 그 모델이
# 거부하면(BadRequestError, 메시지에 "temperature" 포함) 이후로는 그 모델에 한해 파라미터 없이
# (모델 기본값으로) 호출한다 — 새 모델로 바꿔도 코드 수정 불필요, 매 호출마다 재시도하지도 않음.
_temperature_unsupported = set()


def _get_openai_client():
    """OpenAI 클라이언트를 프로세스당 1회만 생성(OPENAI_API_KEY 환경변수 사용)."""
    if "c" not in _openai:
        from openai import OpenAI
        _openai["c"] = OpenAI()
    return _openai["c"]


def _parse_intent(client, model, messages):
    """IntentResult로 파싱된 completion을 반환 — temperature=0을 모델이 거부하면
    (BadRequestError, 메시지에 temperature 포함) 그 모델을 _temperature_unsupported에
    기록하고 파라미터 없이 재시도한다. temperature와 무관한 에러는 그대로 올린다(호출부
    classify_intent의 바깥 try/except가 처리)."""
    from intent_llm_common import IntentResult

    if model not in _temperature_unsupported:
        try:
            return client.beta.chat.completions.parse(
                model=model, messages=messages, response_format=IntentResult, temperature=0)
        except Exception as e:
            if "temperature" not in str(e).lower():
                raise
            _temperature_unsupported.add(model)

    return client.beta.chat.completions.parse(
        model=model, messages=messages, response_format=IntentResult)


def classify_intent(query):
    """질의 의도를 informational/civil_petition 중 하나로 판단(OpenAI structured output).
    입출력 계약은 기존과 동일(query 문자열 → 두 라벨 중 하나)이라 호출부(pipeline.py 등)는
    수정 없이 그대로 작동한다. API 실패 시 안전 기본값 informational로 폴백해 전체 파이프라인이
    멈추지 않게 한다(프롬프트 규칙 5 — 애매하면 informational)."""
    from intent_llm_common import SYSTEM_PROMPT
    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": query}]
        completion = _parse_intent(_get_openai_client(), _OPENAI_INTENT_MODEL, messages)
        return completion.choices[0].message.parsed.intent
    except Exception:
        return "informational"
