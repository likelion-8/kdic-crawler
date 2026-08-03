"""질문 분류 — 유형(question_type: table_lookup 여부)과 업무(business_function) 판별.

둘 다 같은 메커니즘(테스트셋 라벨링 질문과의 코사인 유사도 1-최근접)을 쓴다.
retrieval.py의 라우팅/검색 실행과 분리해, "무엇으로 라우팅할지 판단"과 "그 판단으로
검색을 실행"하는 책임을 나눈다. RoutedRetriever(retrieval.py)가 이 분류기들을 받아
qtype/business_function을 자동으로 채워 넣는다.
"""
from retrieval import DEFAULT_DENSE_MODEL, ROOT, _encode_query, _get_model

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


# ── intent 분류: Kiwi 형태소 + TF-IDF + LogisticRegression (2026-07-29 코사인 1-NN에서 교체) ──
# question_type 분류(위)는 코사인 방식 유지. intent만 형태소 방식으로 바꾼다.
# Leave-Page-Out 검증: 형태소 89.6% > 코사인 1-NN 80.5%. 학습 산출물은
# train_intent_morpheme.py가 data/intent_classifier/ 에 pickle로 만든다(파이프라인은 로드만).
_INTENT_DIR = ROOT / "data" / "intent_classifier"
_intent_artifacts = {}
_kiwi_intent = {}


def tokenize_intent(text):
    """Kiwi 형태소+품사 태그 토큰(예: "신청/NNG", "어요/EF"). 학습(train_intent_morpheme.py)과
    추론이 반드시 같은 토큰화를 써야 하므로 이 함수 하나를 양쪽이 공유한다(train이 여기서 import).
    TF-IDF 벡터라이저는 공백 분리(token_pattern)만 쓰므로, 여기서 토큰을 만들어 공백으로 이어
    넘긴다 — 커스텀 tokenizer를 pickle에 넣지 않아 저장/로드가 깨지지 않는다."""
    if "kiwi" not in _kiwi_intent:
        from kiwipiepy import Kiwi
        _kiwi_intent["kiwi"] = Kiwi()
    return [f"{t.form}/{t.tag}" for t in _kiwi_intent["kiwi"].tokenize(text)]


def _load_intent_model():
    """vectorizer/model pickle을 프로세스당 1회만 로드(함수 호출마다 다시 읽지 않게)."""
    if not _intent_artifacts:
        import pickle
        with open(_INTENT_DIR / "tfidf_vectorizer.pkl", "rb") as f:
            _intent_artifacts["vec"] = pickle.load(f)
        with open(_INTENT_DIR / "logreg_model.pkl", "rb") as f:
            _intent_artifacts["model"] = pickle.load(f)
    return _intent_artifacts["vec"], _intent_artifacts["model"]


def classify_intent(query):
    """질의 의도를 informational/civil_petition 중 하나로 판단(형태소 TF-IDF + LogReg).
    입출력 계약은 기존과 동일(query 문자열 → 두 라벨 중 하나)이라 호출부(pipeline.py 등)는
    수정이 필요 없다. 모델 산출물이 없으면 train_intent_morpheme.py를 먼저 실행해야 한다."""
    vec, model = _load_intent_model()
    joined = " ".join(tokenize_intent(query))
    return str(model.predict(vec.transform([joined]))[0])
