"""근거 사용 판정 — 답변이 검색 근거(컨텍스트)를 실제로 사용했는지 코드로 판정한다.

[SOURCE_USED]/[NO_SOURCE] 자기보고 마커의 대체다(2026-07-30). 마커는 형식 사고(띄어쓰기
변형·누락, 심지어 "[ SOURCE USED ]" 괄호 안 공백 변형까지)를 계속 만들었고, 형식을 다
잡아도 내용 오표기가 남았다 — 라벨 데이터 107건 실측에서 마커는 근거를 실제로 쓴 답변의
33/61(54%)에서 출처를 잘못 생략했다(docs/pipeline_issues.md 이슈 5). 프롬프트 수정 7종이
전부 실패해, 업계 표준(AWS Bedrock 가드레일, Google Vertex Check Grounding)과 같은 "생성
후 결정론적 판정" 구조로 바꿨다. 같은 라벨에서 이 판정기는 누락 1/61, 거절문 차단 28/46.

특징: (1) 답변 형태소 TF-IDF(거절·인사 문체는 정형적이라 문체가 1차 신호 — 고정 문구
매칭이 아니라 학습된 가중치라 표현 변형에 견딤) (2) 답변 내용어의 근거 겹침률
(3) bge-m3-ko(dragonkue/BGE-m3-ko, retrieval.DEFAULT_DENSE_MODEL 재사용) 임베딩 코사인.
전부 파이프라인이 이미 로딩한 자원(Kiwi, 검색용 임베딩 모델)만 쓰므로
새 의존성·추가 API 호출이 없다.

모델은 data/source_verifier/model.json — sklearn pickle이 아니라 JSON인 이유: 버전이
다른 sklearn에서 pickle 로드가 깨지는 문제가 intent 분류기에서 실제로 발생했다
(2026-07-30, "idf vector is not fitted"). TF-IDF 변환(스무딩 idf·L2 정규화)을 아래에서
수식으로 직접 구현하며, train_source_verifier.py가 학습 때마다 sklearn 결과와 일치하는지
assert로 검증한 뒤 저장한다. 임계값은 '근거 쓴 답변의 출처 누락 0' 우선으로 고른 값이다
— 무관한 출처가 붙는 것보다 있어야 할 출처가 빠지는 쪽이 나쁘다는 원칙(출처 표시 필수).
"""
import json
import math
from collections import Counter
from pathlib import Path

from query_classifier import tokenize_intent
from retrieval import DEFAULT_DENSE_MODEL, _encode_query, _get_model

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "data" / "source_verifier" / "model.json"

# 내용어 품사 — 겹침률 계산에서 조사·어미 같은 기능어를 빼고 '알맹이'만 근거와 대조
_CONTENT_TAGS = {"NNG", "NNP", "SN", "VV", "SL"}

_model_cache = {}


def _load_model():
    if not _model_cache:
        _model_cache.update(json.loads(MODEL_PATH.read_text(encoding="utf-8")))
    return _model_cache


def _content_overlap(answer_tokens, context):
    toks = [t for t in answer_tokens if t.split("/")[-1] in _CONTENT_TAGS]
    ctx = {t for t in tokenize_intent(context) if t.split("/")[-1] in _CONTENT_TAGS}
    return sum(1 for t in toks if t in ctx) / len(toks) if toks else 0.0


def _tfidf_score(answer_tokens, vocab):
    """sklearn TfidfVectorizer 기본 설정(smooth_idf, L2 정규화, raw tf)과 동일한 변환을
    수식으로 수행해 로지스틱 회귀의 TF-IDF 부분 점수(Σ tfidf·w)를 반환한다.
    학습 시 sklearn과의 일치가 assert로 검증된다(train_source_verifier.py)."""
    counts = Counter(t for t in answer_tokens if t in vocab)
    if not counts:
        return 0.0
    vals = {t: c * vocab[t][0] for t, c in counts.items()}  # tf * idf
    norm = math.sqrt(sum(v * v for v in vals.values()))
    return sum(v / norm * vocab[t][1] for t, v in vals.items())


def used_source(answer, context):
    """True = 답변이 근거를 사용함 → 출처를 붙인다. False = 미사용(거절·인사 등) → 생략."""
    m = _load_model()
    answer_tokens = tokenize_intent(answer)
    dense_model = _get_model(DEFAULT_DENSE_MODEL)
    cosine = float(_encode_query(dense_model, answer) @ _encode_query(dense_model, context))
    z = (m["bias"]
         + _tfidf_score(answer_tokens, m["vocab"])
         + m["w_overlap"] * _content_overlap(answer_tokens, context)
         + m["w_cosine"] * cosine)
    return 1.0 / (1.0 + math.exp(-z)) >= m["threshold"]
