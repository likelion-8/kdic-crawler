"""질문 분류 — 유형(question_type: table_lookup 여부)과 업무(business_function) 판별.

둘 다 같은 메커니즘(테스트셋 라벨링 질문 579개와의 코사인 유사도 1-최근접)을 쓴다.
retrieval.py의 라우팅/검색 실행과 분리해, "무엇으로 라우팅할지 판단"과 "그 판단으로
검색을 실행"하는 책임을 나눈다. RoutedRetriever(retrieval.py)가 이 분류기들을 받아
qtype/business_function을 자동으로 채워 넣는다.
"""
from retrieval import DEFAULT_DENSE_MODEL, ROOT, DenseRetriever, _encode_query, _get_model


class QuestionTypeClassifier:
    """새 질문의 유형(qtype)을 예시 질문과의 코사인 유사도로 분류(1-최근접).

    예시는 data/testset/testset_all.jsonl의 (question, question_type)을 그대로 쓴다
    (out_of_scope 제외, 579문항). 테스트셋을 그대로 참조하지만 "매번 재계산"되는 건
    아니다 — DenseRetriever와 동일한 (모델+텍스트) 해시 캐싱이라, 테스트셋 내용이
    실제로 안 바뀌면 캐시를 그대로 재사용하고, 바뀔 때만(그 파일이 수정될 때만) 579개
    질문을 다시 인코딩한다. 질문 하나 처리할 때마다 재계산되는 게 아니라, 질의 임베딩
    1건 + 캐시된 579개 벡터와의 내적 비교만 매번 일어난다(수 ms 수준).

    table_lookup이 페이지 구조가 아니라 질문 자체의 형태(엔티티+조회 의도)에서
    나온다는 게 확인돼서(2026-07-21), 코퍼스(본문) 대신 라벨링된 질문을 예시로 쓴다.
    """
    def __init__(self, model=DEFAULT_DENSE_MODEL, label_field="question_type"):
        # label_field로 라벨을 바꿔 재사용 — question_type(유형 라우팅) 또는
        # business_function(업무 필터) 분류에 같은 1-NN·같은 질문 임베딩 캐시를 쓴다.
        import json
        import numpy as np

        questions, types = [], []
        path = ROOT / "data" / "testset" / "testset_all.jsonl"
        with open(path, encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if d["expected_sources"]:  # out_of_scope 제외 — 라우팅 대상이 아님
                    questions.append(d["question"])
                    types.append(d[label_field])
        self.types = types

        self.model = _get_model(model)
        cache = DenseRetriever._cache_path(questions, model)
        if cache.exists():
            self.emb = np.load(cache)
        else:
            self.emb = self.model.encode(
                questions, normalize_embeddings=True, show_progress_bar=True, batch_size=8)
            cache.parent.mkdir(exist_ok=True)
            np.save(cache, self.emb)

    def classify(self, query):
        import numpy as np
        q = _encode_query(self.model, query)
        best = int(np.argmax(self.emb @ q))
        return self.types[best]


class BusinessFunctionClassifier(QuestionTypeClassifier):
    """질의 → 6개 업무(business_function) 분류. QuestionTypeClassifier와 같은 1-NN·같은
    질문 임베딩 캐시를 쓰되 라벨만 business_function으로 바꾼다. 결과값을 RoutedRetriever
    (또는 leaf)의 search(..., business_function=...)에 넣어 업무 범위를 좁힌다."""
    def __init__(self, model=DEFAULT_DENSE_MODEL):
        super().__init__(model=model, label_field="business_function")


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


def classify_intent(query):
    """질의 의도를 informational/civil_petition 중 하나로 판단.

    라벨은 data/testset/testset_all.jsonl의 intent 필드(2026-07-22, src/project1_src/
    label_intent.py로 규칙 기반 1차 라벨링 — file_download/link_guide 유형은 전부
    civil_petition, 나머지는 "신청/접수/제출/구비서류/위임장/철회/취소/이의제기/지급명령/청구"
    등 절차 실행 표현 포함 여부로 판단). 사람이 한 땀 한 땀 검수한 정답은 아니므로,
    leave-one-out 등으로 정확도를 실측하기 전까지는 잠정 라벨로 취급할 것.
    """
    return _get_classifier("intent").classify(query)
